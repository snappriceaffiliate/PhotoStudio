// @vitest-environment jsdom
/** The API client: error shapes, the CSRF token and file uploads. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { api, ApiError, apiUpload } from './client';

function respond(status: number, body?: unknown) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

let fetchMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
  document.cookie = 'csrftoken=abc%20123';
  fetchMock = vi.fn(async () => respond(200, { ok: true }));
  vi.stubGlobal('fetch', fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
});

describe('ApiError', () => {
  it('uses the detail message when there is one', () => {
    expect(new ApiError(400, { detail: 'Nope.' }).message).toBe('Nope.');
  });

  it('collects field errors as lists of text', () => {
    const error = new ApiError(400, { email: ['Taken.'], password: ['Too short.', 'Too common.'], detail: undefined });
    expect(error.fields).toEqual({ email: ['Taken.'], password: ['Too short.', 'Too common.'] });
  });

  it('turns non-field errors into the message', () => {
    const error = new ApiError(400, { non_field_errors: ['Something is off.', 'Try again.'] });
    expect(error.message).toBe('Something is off. Try again.');
  });

  it('has a plain message for rate limits and a generic one otherwise', () => {
    expect(new ApiError(429, {}).message).toContain('Too many attempts');
    expect(new ApiError(500, null).message).toBe('Request failed (500)');
  });

  it('keeps the status', () => {
    expect(new ApiError(402, { detail: 'Pay.' }).status).toBe(402);
  });
});

describe('api()', () => {
  it('sends GET requests without a body or CSRF header', async () => {
    await api('/events');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/events');
    expect(init.method).toBe('GET');
    expect(init.headers['X-CSRFToken']).toBeUndefined();
    expect(init.body).toBeUndefined();
    expect(init.credentials).toBe('same-origin');
  });

  it('sends the CSRF token and JSON on changes', async () => {
    await api('/events', { method: 'POST', body: { title: 'Wedding' } });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers['X-CSRFToken']).toBe('abc 123');
    expect(init.headers['Content-Type']).toBe('application/json');
    expect(JSON.parse(init.body)).toEqual({ title: 'Wedding' });
  });

  it('fetches a CSRF cookie first when there is none', async () => {
    document.cookie = 'csrftoken=; expires=Thu, 01 Jan 1970 00:00:00 GMT';
    fetchMock.mockImplementationOnce(async () => {
      document.cookie = 'csrftoken=fresh';
      return respond(204);
    });
    await api('/events', { method: 'POST', body: {} });
    expect(fetchMock.mock.calls[0][0]).toBe('/api/v1/auth/csrf');
    expect(fetchMock.mock.calls[1][1].headers['X-CSRFToken']).toBe('fresh');
  });

  it('returns nothing for 204', async () => {
    fetchMock.mockResolvedValueOnce(respond(204));
    expect(await api('/auth/logout', { method: 'POST' })).toBeUndefined();
  });

  it('throws an ApiError carrying the server message and fields', async () => {
    fetchMock.mockResolvedValueOnce(respond(400, { email: ['Taken.'] }));
    await expect(api('/auth/signup', { method: 'POST', body: {} })).rejects.toMatchObject({
      status: 400,
      fields: { email: ['Taken.'] },
    });
  });

  it('copes with an error that is not JSON', async () => {
    fetchMock.mockResolvedValueOnce(new Response('<html>Bad gateway</html>', { status: 502 }));
    await expect(api('/events')).rejects.toMatchObject({ status: 502, message: 'Request failed (502)' });
  });
});

describe('apiUpload()', () => {
  it('posts the file as form data with the CSRF token', async () => {
    const blob = new Blob(['RIFF'], { type: 'image/webp' });
    await apiUpload('/studio/branding/logo', 'logo', blob, 'logo.webp');
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('/api/v1/studio/branding/logo');
    expect(init.method).toBe('POST');
    expect(init.headers['X-CSRFToken']).toBe('abc 123');
    expect(init.headers['Content-Type']).toBeUndefined(); // the browser adds the boundary
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get('logo')).toBeInstanceOf(Blob);
    expect(((init.body as FormData).get('logo') as File).name).toBe('logo.webp');
  });

  it('throws the server message on failure', async () => {
    fetchMock.mockResolvedValueOnce(respond(400, { logo: ['The logo must be a WebP image.'] }));
    await expect(apiUpload('/x', 'logo', new Blob(['x']), 'x.webp')).rejects.toMatchObject({
      fields: { logo: ['The logo must be a WebP image.'] },
    });
  });
});

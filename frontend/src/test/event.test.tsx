// @vitest-environment jsdom
/** An event's settings, albums, photo grid and the upload screen. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { callsTo, installBrowserMocks, mockApi, owner, press, renderApp, reply, session, typeInto } from './harness';

installBrowserMocks();

vi.mock('../compression/pool', () => ({
  defaultPoolSize: () => 1,
  CompressionPool: class {
    compress(file: File, path: string) {
      return Promise.resolve({
        ok: true, file, path,
        result: { source: 'jpeg', preview: { blob: new Blob(['p']), width: 10, height: 10 }, thumb: { blob: new Blob(['t']), width: 5, height: 5 } },
      });
    }
    terminate() {}
  },
}));

const detail = {
  id: 'e1', title: 'Priya and Arun Wedding', event_date: null, status: 'draft', selection_limit: 3,
  expires_at: null, watermark_enabled: false, watermark_text: '', photo_count: 0,
};

const photo = (n: number) => ({
  id: `p${n}`, relative_path: `Day/IMG_${n}.jpg`, original_filename: `IMG_${n}.jpg`, thumb_url: 'data:,', preview_url: 'data:,',
});

function eventRoutes(extra: Record<string, unknown> = {}) {
  return {
    ...session(owner).routes,
    'GET /api/v1/events/e1': detail,
    'GET /api/v1/events/e1/albums': [],
    'GET /api/v1/events/e1/photos': { count: 0, next_page: null, results: [] },
    'GET /api/v1/events/e1/selection': { count: 0, results: [], duplicate_filenames: [] },
    'GET /api/v1/events/e1/clients': [],
    'GET /api/v1/events/e1/progress': { status: 'draft', selection_limit: 3, selected: 0, submitted_at: null, last_client_login: null },
    ...extra,
  };
}

const settingsSave = () => screen.getByRole('button', { name: 'Save settings' });

describe('event settings', () => {
  it('shows the current values and saves changes', async () => {
    const calls = mockApi(eventRoutes({
      'PATCH /api/v1/events/e1': (call: { body: object }) => ({ ...detail, ...call.body }),
    }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Event settings' });
    const fields = screen.getAllByLabelText('Photos the client may select');
    expect((fields[fields.length - 1] as HTMLInputElement).value).toBe('3');
    typeInto('Client link expires on', '2027-01-31');
    fireEvent.change(fields[fields.length - 1], { target: { value: '150' } });
    fireEvent.click(settingsSave());
    expect((await screen.findByText('Settings saved.'))).toBeTruthy();
    const body = callsTo(calls, 'PATCH', '/api/v1/events/e1')[0].body as Record<string, unknown>;
    expect(body).toMatchObject({ selection_limit: 150, expires_at: '2027-01-31', event_date: null, title: 'Priya and Arun Wedding' });
  });

  it('turns the watermark on and sends its text', async () => {
    const calls = mockApi(eventRoutes({ 'PATCH /api/v1/events/e1': (c: { body: object }) => ({ ...detail, ...c.body }) }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Event settings' });
    expect(screen.queryByLabelText('Watermark text')).toBeNull();
    fireEvent.click(screen.getByLabelText('Add a watermark to previews'));
    typeInto('Watermark text', 'Lens and Light');
    fireEvent.click(settingsSave());
    await screen.findByText('Settings saved.');
    expect(callsTo(calls, 'PATCH', '/api/v1/events/e1')[0].body).toMatchObject({
      watermark_enabled: true, watermark_text: 'Lens and Light',
    });
  });

  it('clearing the limit means no limit', async () => {
    const calls = mockApi(eventRoutes({ 'PATCH /api/v1/events/e1': detail }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Event settings' });
    const fields = screen.getAllByLabelText('Photos the client may select');
    fireEvent.change(fields[fields.length - 1], { target: { value: '' } });
    fireEvent.click(settingsSave());
    await waitFor(() => expect(callsTo(calls, 'PATCH', '/api/v1/events/e1')).toHaveLength(1));
    expect((callsTo(calls, 'PATCH', '/api/v1/events/e1')[0].body as { selection_limit: unknown }).selection_limit).toBeNull();
  });

  it('shows field errors from the server', async () => {
    mockApi(eventRoutes({ 'PATCH /api/v1/events/e1': reply(400, { title: ['This field may not be blank.'] }) }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Event settings' });
    const names = screen.getAllByLabelText('Event name');
    fireEvent.change(names[names.length - 1], { target: { value: '' } });
    fireEvent.click(settingsSave());
    expect(await screen.findByText('This field may not be blank.')).toBeTruthy();
  });
});

describe('albums', () => {
  it('lists albums with their photo counts', async () => {
    mockApi(eventRoutes({ 'GET /api/v1/events/e1/albums': [{ id: 'a1', name: 'Reception', photo_count: 40 }] }));
    renderApp('/events/e1');
    expect(await screen.findByText('Reception', { selector: 'li' })).toBeTruthy();
    expect(screen.getByText('· 40 photos')).toBeTruthy();
  });

  it('adds an album, and the button waits for a name', async () => {
    let albums: { id: string; name: string; photo_count: number }[] = [];
    const calls = mockApi(eventRoutes({
      'GET /api/v1/events/e1/albums': () => albums,
      'POST /api/v1/events/e1/albums': () => {
        albums = [{ id: 'a1', name: 'Engagement', photo_count: 0 }];
        return reply(201, albums[0]);
      },
    }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Albums' });
    expect((screen.getByRole('button', { name: 'Add album' }) as HTMLButtonElement).disabled).toBe(true);
    typeInto('New album', 'Engagement');
    press('Add album');
    expect(await screen.findByText('Engagement', { selector: 'li' })).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/events/e1/albums')[0].body).toEqual({ name: 'Engagement' });
    expect((screen.getByLabelText('New album') as HTMLInputElement).value).toBe(''); // cleared
  });
});

describe('the photo grid', () => {
  it('says there are no photos yet', async () => {
    mockApi(eventRoutes());
    renderApp('/events/e1');
    expect(await screen.findByText('No photos yet. Upload the event folder above.')).toBeTruthy();
  });

  it('shows photos with a count, opens one large and closes it', async () => {
    mockApi(eventRoutes({
      'GET /api/v1/events/e1/photos': { count: 2, next_page: null, results: [photo(1), photo(2)] },
    }));
    renderApp('/events/e1');
    expect(await screen.findByText('(2)')).toBeTruthy();
    fireEvent.click(screen.getByAltText('IMG_1.jpg').closest('button')!);
    expect(await screen.findByText('Day/IMG_1.jpg · click to close')).toBeTruthy();
    fireEvent.click(screen.getByText('Day/IMG_1.jpg · click to close'));
    expect(screen.queryByText('Day/IMG_1.jpg · click to close')).toBeNull();
  });

  it('shows only the first 10 photos and links to all of them', async () => {
    const calls = mockApi(eventRoutes({
      'GET /api/v1/events/e1/photos': { count: 25, next_page: 2, results: Array.from({ length: 10 }, (_, i) => photo(i + 1)) },
    }));
    renderApp('/events/e1');
    expect(await screen.findByAltText('IMG_10.jpg')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Load more' })).toBeNull();
    expect(calls.some((c) => c.path === '/api/v1/events/e1/photos' && c.query.includes('page_size=10'))).toBe(true);
    expect(screen.getByRole('link', { name: 'View all 25 photos' }).getAttribute('href')).toBe('/events/e1/photos');
    expect(screen.getByText(/Showing 10 of 25/)).toBeTruthy();
  });
});

describe('all photos page', () => {
  const listed = (n: number, chosen = false) => ({ ...photo(n), chosen, created_at: `2026-11-0${n}T10:00:00Z` });

  it('sorts, filters by album and loads more', async () => {
    const calls = mockApi(eventRoutes({
      'GET /api/v1/events/e1/albums': [{ id: 'a1', name: 'Reception', photo_count: 1 }],
      'GET /api/v1/events/e1/photos': (call: { query: string }) =>
        call.query.startsWith('page=2')
          ? { count: 3, next_page: null, results: [listed(3)] }
          : { count: 3, next_page: 2, results: [listed(1), listed(2, true)] },
    }));
    renderApp('/events/e1/photos');
    expect(await screen.findByAltText('IMG_2.jpg')).toBeTruthy();
    expect(screen.getByText('Chosen')).toBeTruthy();
    press('Load more');
    expect(await screen.findByAltText('IMG_3.jpg')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: '-name' } });
    await waitFor(() => expect(calls.some((c) => c.query.includes('sort=-name'))).toBe(true));
    fireEvent.change(screen.getByLabelText('Album'), { target: { value: 'a1' } });
    await waitFor(() => expect(calls.some((c) => c.query.includes('album=a1'))).toBe(true));
  });

  it('deletes the ticked photos after a warning about chosen ones', async () => {
    let gone = false;
    const calls = mockApi(eventRoutes({
      'GET /api/v1/events/e1/photos': () => ({ count: gone ? 1 : 2, next_page: null, results: gone ? [listed(2)] : [listed(1, true), listed(2)] }),
      'POST /api/v1/events/e1/photos/delete': () => {
        gone = true;
        return { deleted: 1, removed_from_selection: 1 };
      },
    }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderApp('/events/e1/photos');
    fireEvent.click(await screen.findByLabelText('Select IMG_1.jpg'));
    press('Delete 1 photo');
    expect(confirm.mock.calls[0][0]).toContain('chosen by the client');
    expect(await screen.findByText(/Deleted 1 photo\. 1 was removed from the client’s selection/)).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/events/e1/photos/delete')[0].body).toEqual({ photo_ids: ['p1'] });
    await waitFor(() => expect(screen.queryByAltText('IMG_1.jpg')).toBeNull());
    confirm.mockRestore();
  });

  it('does nothing when the warning is cancelled, and shows a refusal', async () => {
    const calls = mockApi(eventRoutes({
      'GET /api/v1/events/e1/photos': { count: 1, next_page: null, results: [listed(1, true)] },
      'POST /api/v1/events/e1/photos/delete': reply(409, { detail: 'The client has sent their selection. Let the client make changes (reopen the selection) before deleting them.' }),
    }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false);
    renderApp('/events/e1/photos');
    press(await screen.findByRole('button', { name: 'Select all 1 shown' }).then((b) => b.textContent!));
    press('Delete 1 photo');
    expect(callsTo(calls, 'POST', '/api/v1/events/e1/photos/delete')).toHaveLength(0);
    confirm.mockReturnValue(true);
    press('Delete 1 photo');
    expect((await screen.findByRole('alert')).textContent).toContain('reopen the selection');
    confirm.mockRestore();
  });

  it('shows the photos the client chose, sorted by name', async () => {
    const chosen = (n: number, note = '') => ({
      photo_id: `p${n}`, relative_path: `Day/IMG_${n}.jpg`, filename: `IMG_${n}.jpg`, note, selected_at: `2026-11-0${n}T10:00:00Z`,
      thumb_url: 'data:,', preview_url: 'data:,',
    });
    mockApi(eventRoutes({
      'GET /api/v1/events/e1/selection': { count: 2, results: [chosen(2), chosen(1, 'Album cover')], duplicate_filenames: [] },
    }));
    renderApp('/events/e1/photos?tab=chosen');
    expect(await screen.findByRole('tab', { name: 'Chosen by client (2)' })).toBeTruthy();
    await screen.findByAltText('IMG_1.jpg');
    fireEvent.change(screen.getByLabelText('Sort'), { target: { value: 'name' } });
    await waitFor(() => {
      const names = screen.getAllByRole('img').map((i) => i.getAttribute('alt'));
      expect(names).toEqual(['IMG_1.jpg', 'IMG_2.jpg']);
    });
    expect(screen.getByText('IMG_1.jpg · Album cover')).toBeTruthy();
  });
});

describe('uploading', () => {
  function chooseFiles(names: string[]) {
    const input = document.querySelectorAll('input[type="file"]')[1] as HTMLInputElement;
    const list = names.map((n) => new File(['x'], n));
    fireEvent.change(input, { target: { files: list } });
  }

  /** Press Start upload, then keep the watermark as it is in the dialog. */
  async function startUpload() {
    press(await screen.findByRole('button', { name: 'Start upload' }).then((b) => b.textContent!));
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Start upload' }));
  }

  function uploadRoutes() {
    return eventRoutes({
      'POST /api/v1/events/e1/uploads': { id: 'u1' },
      'POST /api/v1/uploads/u1/files': (call: { body: { files: { relative_path: string }[] } }) => ({
        files: call.body.files.map((f) => ({ id: `id:${f.relative_path}`, relative_path: f.relative_path, status: 'pending' })),
      }),
      'POST /api/v1/uploads/u1/urls': (call: { body: { photo_ids: string[] } }) => ({
        urls: call.body.photo_ids.map((id) => ({ id, preview_url: `https://r2.test/${id}/p`, thumb_url: `https://r2.test/${id}/t` })),
      }),
      'POST /api/v1/uploads/u1/confirm': (call: { body: { photos: { id: string }[] } }) => ({
        results: call.body.photos.map((p) => ({ id: p.id, relative_path: p.id.replace('id:', ''), status: 'ready', failure_reason: '' })),
      }),
      'POST /api/v1/uploads/u1/complete': reply(204),
    });
  }

  it('counts the photos ready, ignoring other kinds of file', async () => {
    mockApi(eventRoutes());
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Upload photos' });
    chooseFiles(['IMG_1.jpg', 'IMG_2.JPG', 'notes.txt', 'movie.mp4']);
    expect((await screen.findByText('photos ready to upload.', { exact: false })).textContent).toContain('2');
    expect(screen.getByRole('button', { name: 'Start upload' })).toBeTruthy();
  });

  it('warns when the same filename is used in two folders', async () => {
    mockApi(eventRoutes());
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Upload photos' });
    const input = document.querySelectorAll('input[type="file"]')[0] as HTMLInputElement;
    const make = (path: string) => {
      const f = new File(['x'], path.split('/').pop()!);
      Object.defineProperty(f, 'webkitRelativePath', { value: path });
      return f;
    };
    fireEvent.change(input, { target: { files: [make('W/A/IMG_1.jpg'), make('W/B/IMG_1.jpg')] } });
    expect(await screen.findByText(/appears in more than one folder/)).toBeTruthy();
  });

  it('offers albums, and asks about a watermark before starting', async () => {
    const calls = mockApi(eventRoutes({
      'GET /api/v1/events/e1': { ...detail, watermark_enabled: true, watermark_text: 'Lens and Light' },
      'GET /api/v1/events/e1/albums': [{ id: 'a1', name: 'Reception', photo_count: 0 }],
      'PATCH /api/v1/events/e1': (call: { body: object }) => ({ ...detail, ...call.body }),
      'POST /api/v1/events/e1/uploads': reply(402, { detail: 'Stop here.' }),
    }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Upload photos' });
    chooseFiles(['IMG_1.jpg']);
    expect(await screen.findByLabelText('Add to album')).toBeTruthy();
    press('Start upload');
    const dialog = await screen.findByRole('dialog');
    expect((within(dialog).getByLabelText('Add a watermark') as HTMLInputElement).checked).toBe(true);
    expect((within(dialog).getByLabelText('Watermark text') as HTMLInputElement).value).toBe('Lens and Light');
    // Cancel leaves everything as it was.
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    // Turning it off is saved on the event before the upload starts.
    press('Start upload');
    fireEvent.click(within(await screen.findByRole('dialog')).getByLabelText('No watermark'));
    fireEvent.click(within(screen.getByRole('dialog')).getByRole('button', { name: 'Start upload' }));
    expect(await screen.findByText(/Upload stopped: Stop here\./)).toBeTruthy();
    expect(callsTo(calls, 'PATCH', '/api/v1/events/e1')[0].body).toEqual({ watermark_enabled: false });
  });

  it('defaults the watermark to the studio name when the event has none', async () => {
    const calls = mockApi(eventRoutes({
      'PATCH /api/v1/events/e1': (call: { body: object }) => ({ ...detail, ...call.body }),
      'POST /api/v1/events/e1/uploads': reply(402, { detail: 'Stop here.' }),
    }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Upload photos' });
    chooseFiles(['IMG_1.jpg']);
    press(await screen.findByRole('button', { name: 'Start upload' }).then((b) => b.textContent!));
    const dialog = await screen.findByRole('dialog');
    expect((within(dialog).getByLabelText('No watermark') as HTMLInputElement).checked).toBe(true);
    fireEvent.click(within(dialog).getByLabelText('Add a watermark'));
    const text = within(dialog).getByLabelText('Watermark text') as HTMLInputElement;
    expect(text.value).not.toBe('');
    fireEvent.change(text, { target: { value: 'Lens and Light' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Start upload' }));
    expect(await screen.findByText(/Upload stopped/)).toBeTruthy();
    expect(callsTo(calls, 'PATCH', '/api/v1/events/e1')[0].body).toEqual({ watermark_enabled: true, watermark_text: 'Lens and Light' });
  });

  it('uploads the chosen photos and says when it is done', async () => {
    const routes = uploadRoutes();
    const calls = mockApi(routes);
    // Storage accepts every PUT.
    const base = globalThis.fetch as unknown as (i: RequestInfo, init?: RequestInit) => Promise<Response>;
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo, init?: RequestInit) =>
      init?.method === 'PUT' ? Promise.resolve(new Response(null, { status: 200 })) : base(input, init)));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Upload photos' });
    chooseFiles(['IMG_1.jpg', 'IMG_2.jpg']);
    await startUpload();
    expect(await screen.findByText(/Done: 2 uploaded/)).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/uploads/u1/complete')).toHaveLength(1);
    expect(callsTo(calls, 'POST', '/api/v1/uploads/u1/files')[0].body).toEqual({
      files: [{ relative_path: 'IMG_1.jpg', album_id: null }, { relative_path: 'IMG_2.jpg', album_id: null }],
    });
  });

  it('shows why an upload stopped', async () => {
    mockApi(eventRoutes({ 'POST /api/v1/events/e1/uploads': reply(402, { detail: 'Your plan has ended.' }) }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Upload photos' });
    chooseFiles(['IMG_1.jpg']);
    await startUpload();
    expect(await screen.findByText(/Upload stopped: Your plan has ended\./)).toBeTruthy();
  });

  it('archived events cannot take new photos', async () => {
    mockApi(eventRoutes({ 'GET /api/v1/events/e1': { ...detail, status: 'archived' } }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Priya and Arun Wedding' });
    expect(screen.queryByRole('heading', { name: 'Upload photos' })).toBeNull();
  });
});

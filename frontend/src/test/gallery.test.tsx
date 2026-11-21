// @vitest-environment jsdom
/** The client's side: logging in to a gallery, choosing photos, the viewer and sending the selection. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { callsTo, mockApi, press, renderApp, reply, typeInto, installBrowserMocks } from './harness';

installBrowserMocks();

const photo = (n: number, selected = false, note = '') => ({
  id: `p${n}`, width: 1600, height: 1067, thumb_url: 'data:,', preview_url: 'data:,', selected, note,
});

function gallery(overrides: Record<string, unknown> = {}, eventOverrides: Record<string, unknown> = {}) {
  const state = {
    selected: 1,
    photos: [photo(1, true, 'Cover'), photo(2), photo(3)],
    submittedAt: null as string | null,
  };
  const calls = mockApi({
    'GET /api/v1/client/me': () => ({
      client_name: 'Priya', studio_name: 'Lens and Light',
      event: { title: 'Wedding', selection_limit: 2, expires_at: null, submitted_at: state.submittedAt, ...eventOverrides },
      photo_count: state.photos.length, selected: state.selected, albums: [{ id: 'a1', name: 'Reception' }],
      cover_url: null, branding: null, ...overrides,
    }),
    'GET /api/v1/client/photos': (call: { query: string }) => {
      const results = call.query.includes('selected=1') ? state.photos.filter((p) => p.selected) : state.photos;
      return { count: results.length, next_page: null, results };
    },
    'PUT /api/v1/client/selections/p2': () => {
      state.selected = 2;
      return { selected_count: 2 };
    },
    'PUT /api/v1/client/selections/p3': reply(409, { detail: 'You can choose up to 2 photos.' }),
    'DELETE /api/v1/client/selections/p1': () => {
      state.selected = 0;
      return { selected_count: 0 };
    },
    'POST /api/v1/client/submit': () => {
      state.submittedAt = '2026-12-02T10:00:00Z';
      return { photo_count: state.selected };
    },
    'POST /api/v1/client/logout': reply(204),
  });
  return { calls, state };
}

describe('gallery login', () => {
  it('prefills the username from the link and opens the gallery', async () => {
    const calls = mockApi({
      'POST /api/v1/client/login': {},
      'GET /api/v1/client/me': reply(403, {}),
      'GET /api/v1/client/photos': reply(403, {}),
    });
    renderApp('/gallery/login?u=priya-5685');
    await screen.findByRole('heading', { name: 'Open your photo gallery' });
    expect((screen.getByLabelText('Username') as HTMLInputElement).value).toBe('priya-5685');
    typeInto('Password', ' Abcd-Efgh-1234');
    press('Open gallery');
    await waitFor(() => expect(callsTo(calls, 'POST', '/api/v1/client/login')).toHaveLength(1));
    expect(callsTo(calls, 'POST', '/api/v1/client/login')[0].body).toEqual({
      username: 'priya-5685', password: ' Abcd-Efgh-1234',
    });
  });

  it('trims spaces from a pasted username', async () => {
    const calls = mockApi({ 'POST /api/v1/client/login': {}, 'GET /api/v1/client/me': reply(403, {}), 'GET /api/v1/client/photos': reply(403, {}) });
    renderApp('/gallery/login');
    await screen.findByRole('heading', { name: 'Open your photo gallery' });
    typeInto('Username', '  priya-5685  ');
    typeInto('Password', 'x');
    press('Open gallery');
    await waitFor(() => expect(callsTo(calls, 'POST', '/api/v1/client/login')).toHaveLength(1));
    expect((callsTo(calls, 'POST', '/api/v1/client/login')[0].body as { username: string }).username).toBe('priya-5685');
  });

  it('gives the same plain message for a wrong or locked login', async () => {
    mockApi({ 'POST /api/v1/client/login': reply(400, { detail: 'That username and password do not match.' }) });
    renderApp('/gallery/login');
    await screen.findByRole('heading', { name: 'Open your photo gallery' });
    typeInto('Username', 'priya-5685');
    typeInto('Password', 'wrong');
    press('Open gallery');
    expect((await screen.findByRole('alert')).textContent).toBe('That username and password do not match.');
  });

  it('sends people without a session back to the login', async () => {
    mockApi({ 'GET /api/v1/client/me': reply(403, {}), 'GET /api/v1/client/photos': reply(403, {}) });
    renderApp('/gallery');
    expect(await screen.findByRole('heading', { name: 'Open your photo gallery' })).toBeTruthy();
  });
});

describe('studio contact', () => {
  it('shows how to reach the studio when it filled in its profile', async () => {
    gallery({ studio_contact: { phone: '919876543210', email: null, city: 'Chennai', website: 'https://lens.in', instagram: 'lens' } });
    renderApp('/gallery');
    const list = await screen.findByRole('list', { name: 'Contact Lens and Light' });
    expect(within(list).getByRole('link', { name: 'WhatsApp' }).getAttribute('href')).toBe('https://wa.me/919876543210');
    expect(within(list).getByRole('link', { name: '@lens' }).getAttribute('href')).toBe('https://instagram.com/lens');
    expect(within(list).getByRole('link', { name: 'lens.in' })).toBeTruthy();
    expect(within(list).getByText('Chennai')).toBeTruthy();
  });

  it('shows nothing when the studio added no details', async () => {
    gallery();
    renderApp('/gallery');
    await screen.findByRole('heading', { name: 'Wedding' });
    expect(screen.queryByRole('list', { name: /Contact/ })).toBeNull();
  });
});

describe('choosing photos', () => {
  it('shows the studio, the count and what is left', async () => {
    gallery();
    renderApp('/gallery');
    expect(await screen.findByRole('heading', { name: 'Wedding' })).toBeTruthy();
    expect(screen.getByText('Lens and Light')).toBeTruthy();
    expect(screen.getByText('All 3')).toBeTruthy();
    expect(screen.getByText('Selected 1')).toBeTruthy();
    expect(document.querySelector('.submit-count')!.textContent).toBe('1 of 2 chosen · 1 left');
    expect(document.querySelectorAll('.gallery-grid li')).toHaveLength(3);
  });

  it('choosing a photo saves it straight away and updates the count', async () => {
    const { calls } = gallery();
    renderApp('/gallery');
    await waitFor(() => expect(document.querySelectorAll('.gallery-grid li')).toHaveLength(3));
    const hearts = screen.getAllByRole('button', { name: 'Add to selection' });
    fireEvent.click(hearts[0]);
    await waitFor(() => expect(document.querySelector('.submit-count')!.textContent).toContain('2 of 2 chosen'));
    expect(document.querySelector('.submit-count')!.textContent).toContain('limit reached');
    expect(callsTo(calls, 'PUT', '/api/v1/client/selections/p2')).toHaveLength(1);
  });

  it('un-choosing removes it', async () => {
    const { calls } = gallery();
    renderApp('/gallery');
    await waitFor(() => expect(document.querySelectorAll('.gallery-grid li')).toHaveLength(3));
    fireEvent.click(screen.getByRole('button', { name: 'Remove from selection' }));
    await waitFor(() => expect(callsTo(calls, 'DELETE', '/api/v1/client/selections/p1')).toHaveLength(1));
    await waitFor(() => expect(document.querySelector('.submit-count')!.textContent).toContain('0 of 2'));
  });

  it('puts the heart back and explains when the limit refuses a photo', async () => {
    gallery();
    renderApp('/gallery');
    await waitFor(() => expect(document.querySelectorAll('.gallery-grid li')).toHaveLength(3));
    const hearts = screen.getAllByRole('button', { name: 'Add to selection' });
    fireEvent.click(hearts[1]); // p3, which the server refuses
    expect((await screen.findByRole('alert')).textContent).toBe('You can choose up to 2 photos.');
    expect(screen.getAllByRole('button', { name: 'Add to selection' })).toHaveLength(2);
  });

  it('the Selected tab asks only for chosen photos and has a friendly empty state', async () => {
    const { calls, state } = gallery();
    state.photos = [photo(1), photo(2), photo(3)];
    state.selected = 0;
    renderApp('/gallery');
    await screen.findByRole('heading', { name: 'Wedding' });
    fireEvent.click(screen.getByRole('tab', { name: /Selected/ }));
    expect(await screen.findByRole('heading', { name: 'Nothing chosen yet' })).toBeTruthy();
    expect(calls.some((c) => c.path === '/api/v1/client/photos' && c.query.includes('selected=1'))).toBe(true);
    press('See all photos');
    await waitFor(() => expect(screen.queryByRole('heading', { name: 'Nothing chosen yet' })).toBeNull());
  });

  it('filters by album', async () => {
    const { calls } = gallery();
    renderApp('/gallery');
    await screen.findByRole('heading', { name: 'Wedding' });
    fireEvent.change(screen.getByLabelText('Album'), { target: { value: 'a1' } });
    await waitFor(() => expect(calls.some((c) => c.query.includes('album=a1'))).toBe(true));
  });

  it('shows the studio logo, an accent colour and the PickSnap footer when the studio is branded', async () => {
    gallery({ branding: { logo_url: 'data:image/webp;base64,AAAA', accent_color: '#8A1C3B' }, cover_url: 'data:,' });
    renderApp('/gallery');
    const logo = await screen.findByAltText('Lens and Light');
    expect(logo.className).toBe('studio-logo');
    const root = document.querySelector('.gallery') as HTMLElement;
    expect(root.className).toContain('branded');
    expect(root.style.getPropertyValue('--brand-accent')).toBe('#8A1C3B');
    expect(screen.getByRole('link', { name: 'PickSnap' })).toBeTruthy();
  });

  it('uses the standard look when the studio has no branding', async () => {
    gallery();
    renderApp('/gallery');
    await screen.findByRole('heading', { name: 'Wedding' });
    const root = document.querySelector('.gallery') as HTMLElement;
    expect(root.className).not.toContain('branded');
    expect(screen.queryByAltText('Lens and Light')).toBeNull();
  });

  it('a cover photo turns the top into the opening screen', async () => {
    gallery({ cover_url: 'data:,' });
    renderApp('/gallery');
    const start = await screen.findByRole('button', { name: 'Continue choosing' });
    fireEvent.click(start);
    expect(Element.prototype.scrollIntoView).toHaveBeenCalled();
    expect(document.querySelector('.gallery-cover')).not.toBeNull();
  });

  it('logs out', async () => {
    const { calls } = gallery();
    renderApp('/gallery');
    await screen.findByRole('heading', { name: 'Wedding' });
    press('Log out');
    expect(await screen.findByRole('heading', { name: 'Open your photo gallery' })).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/client/logout')).toHaveLength(1);
  });
});

describe('the photo viewer', () => {
  async function openViewer() {
    const g = gallery();
    renderApp('/gallery');
    await waitFor(() => expect(document.querySelectorAll('.gallery-grid li')).toHaveLength(3));
    fireEvent.click(screen.getAllByRole('button', { name: 'View photo large' })[1]);
    return { ...g, viewer: await screen.findByRole('dialog', { name: 'Photo viewer' }) };
  }

  it('opens on the tapped photo and moves with the buttons and arrow keys', async () => {
    const { viewer } = await openViewer();
    expect(within(viewer).getByText('2 / 3')).toBeTruthy();
    fireEvent.click(within(viewer).getByRole('button', { name: 'Next photo' }));
    expect(within(viewer).getByText('3 / 3')).toBeTruthy();
    expect((within(viewer).getByRole('button', { name: 'Next photo' }) as HTMLButtonElement).disabled).toBe(true);
    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    expect(within(viewer).getByText('1 / 3')).toBeTruthy();
    expect((within(viewer).getByRole('button', { name: 'Previous photo' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('swiping moves to the next photo', async () => {
    const { viewer } = await openViewer();
    const stage = viewer.querySelector('.viewer-stage')!;
    fireEvent.touchStart(stage, { touches: [{ clientX: 300 }] });
    fireEvent.touchEnd(stage, { changedTouches: [{ clientX: 100 }] });
    expect(within(viewer).getByText('3 / 3')).toBeTruthy();
    fireEvent.touchStart(stage, { touches: [{ clientX: 100 }] });
    fireEvent.touchEnd(stage, { changedTouches: [{ clientX: 120 }] }); // too short to count
    expect(within(viewer).getByText('3 / 3')).toBeTruthy();
  });

  it('Escape and the close button leave the viewer', async () => {
    await openViewer();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByRole('dialog', { name: 'Photo viewer' })).toBeNull();
  });

  it('chooses the photo from the viewer, then saves a note', async () => {
    const { calls, viewer } = await openViewer();
    fireEvent.click(within(viewer).getByRole('button', { name: 'Choose this photo' }));
    expect(await within(viewer).findByRole('button', { name: 'Chosen' })).toBeTruthy();
    expect(callsTo(calls, 'PUT', '/api/v1/client/selections/p2')[0].body).toEqual({ note: '' });
    fireEvent.change(within(viewer).getByLabelText('Note for the studio'), { target: { value: 'Album cover' } });
    fireEvent.click(within(viewer).getByRole('button', { name: 'Save note' }));
    await waitFor(() => expect(callsTo(calls, 'PUT', '/api/v1/client/selections/p2')).toHaveLength(2));
    expect(callsTo(calls, 'PUT', '/api/v1/client/selections/p2')[1].body).toEqual({ note: 'Album cover' });
  });
});

describe('sending the selection', () => {
  it('asks first, says what happens, and lets people keep choosing', async () => {
    const { calls } = gallery();
    renderApp('/gallery');
    await screen.findByRole('heading', { name: 'Wedding' });
    press('Send selection');
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByRole('heading').textContent).toBe('Send 1 photos to Lens and Light?');
    expect(within(dialog).getByText(/selection is locked/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Keep choosing' }));
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(callsTo(calls, 'POST', '/api/v1/client/submit')).toHaveLength(0);
  });

  it('sends it, locks the gallery and thanks the client', async () => {
    const { calls } = gallery();
    renderApp('/gallery');
    await screen.findByRole('heading', { name: 'Wedding' });
    press('Send selection');
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Send selection' }));
    expect(await screen.findByText(/You submitted 1 photos. Lens and Light has been told. Thank you!/)).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/client/submit')).toHaveLength(1);
    expect(screen.queryByText('Send selection')).toBeNull(); // the bar is gone
    // Hearts no longer change anything.
    const before = calls.length;
    fireEvent.click(screen.getAllByRole('button', { name: /selection/ })[0]);
    expect(calls.length).toBe(before);
  });

  it('the Send button is off until something is chosen', async () => {
    const { state } = gallery();
    state.photos = [photo(1), photo(2), photo(3)];
    state.selected = 0;
    renderApp('/gallery');
    await screen.findByRole('heading', { name: 'Wedding' });
    expect((screen.getByRole('button', { name: 'Send selection' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows the reason when sending is refused', async () => {
    mockApi({
      'GET /api/v1/client/me': {
        client_name: 'Priya', studio_name: 'Lens and Light', cover_url: null, branding: null,
        event: { title: 'Wedding', selection_limit: null, expires_at: null, submitted_at: null },
        photo_count: 1, selected: 1, albums: [],
      },
      'GET /api/v1/client/photos': { count: 1, next_page: null, results: [photo(1, true)] },
      'POST /api/v1/client/submit': reply(409, { detail: 'Your selection is already submitted.' }),
    });
    renderApp('/gallery');
    await screen.findByRole('heading', { name: 'Wedding' });
    expect(document.querySelector('.submit-count')!.textContent).toBe('1 chosen'); // no limit set
    press('Send selection');
    fireEvent.click(within(await screen.findByRole('dialog')).getByRole('button', { name: 'Send selection' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Your selection is already submitted.');
  });

  it('an already submitted gallery is read-only', async () => {
    gallery({}, { submitted_at: '2026-12-02T10:00:00Z' });
    renderApp('/gallery');
    expect(await screen.findByText(/You submitted 1 photos/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Send selection' })).toBeNull();
    for (const heart of screen.getAllByRole('button', { name: /selection$/ })) {
      expect((heart as HTMLButtonElement).disabled).toBe(true);
    }
  });
});

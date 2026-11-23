// @vitest-environment jsdom
/** The studio's screens: events, staff, an event's sharing and selection, and billing. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { billing, callsTo, mockApi, owner, press, renderApp, reply, session, staff, typeInto, installBrowserMocks } from './harness';

installBrowserMocks();

const eventRow = {
  id: 'e1', title: 'Priya and Arun Wedding', event_date: '2026-12-01', status: 'shared', selection_limit: 200,
  photo_count: 1240, selected_count: 50, cover_url: 'data:,', created_at: '',
};

describe('events', () => {
  it('lists events with progress, and links to each one', async () => {
    mockApi({ ...session(owner).routes, 'GET /api/v1/events': [eventRow, { ...eventRow, id: 'e2', title: 'Baby Shower', selected_count: 0, photo_count: 3, status: 'draft' }] });
    renderApp('/events');
    const link = await screen.findByRole('link', { name: 'Priya and Arun Wedding' });
    expect(link.getAttribute('href')).toBe('/events/e1');
    expect(screen.getByText('50 of 200 chosen by the client')).toBeTruthy();
    expect(screen.getByText('1240 photos', { exact: false })).toBeTruthy();
    expect(screen.getByText('Shared with client')).toBeTruthy();
    expect(screen.getAllByText('Draft').length).toBeGreaterThan(0);
    // No progress line for an event nobody has chosen from.
    expect(screen.getAllByText(/chosen by the client/)).toHaveLength(1);
  });

  it('filters events into active, draft and archived', async () => {
    mockApi({ ...session(owner).routes, 'GET /api/v1/events': [
      eventRow,
      { ...eventRow, id: 'e2', title: 'Baby Shower', status: 'draft' },
      { ...eventRow, id: 'e3', title: 'Old Birthday', status: 'archived' },
    ] });
    renderApp('/events');
    await screen.findByRole('link', { name: 'Baby Shower' });
    const tab = (name: RegExp) => screen.getByRole('tab', { name });
    expect(tab(/^All/).getAttribute('aria-selected')).toBe('true');
    fireEvent.click(tab(/^Active/));
    expect(screen.getByRole('link', { name: 'Priya and Arun Wedding' })).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Baby Shower' })).toBeNull();
    fireEvent.click(tab(/^Draft/));
    expect(screen.getByRole('link', { name: 'Baby Shower' })).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Old Birthday' })).toBeNull();
    fireEvent.click(tab(/^Archived/));
    expect(screen.getByRole('link', { name: 'Old Birthday' })).toBeTruthy();
    expect(screen.queryByRole('link', { name: 'Priya and Arun Wedding' })).toBeNull();
  });

  it('deletes an event only when its name is typed', async () => {
    let gone = false;
    const calls = mockApi({
      ...session(owner).routes,
      'GET /api/v1/events': () => (gone ? [] : [eventRow]),
      'DELETE /api/v1/events/e1': () => {
        gone = true;
        return reply(204);
      },
    });
    const prompt = vi.spyOn(window, 'prompt').mockReturnValueOnce('wrong name').mockReturnValueOnce('Priya and Arun Wedding');
    const alert = vi.spyOn(window, 'alert').mockImplementation(() => undefined);
    renderApp('/events');
    const del = await screen.findByRole('button', { name: 'Delete Priya and Arun Wedding' });
    fireEvent.click(del);
    expect(alert).toHaveBeenCalled();
    expect(callsTo(calls, 'DELETE', '/api/v1/events/e1')).toHaveLength(0);
    fireEvent.click(del);
    expect(await screen.findByRole('heading', { name: 'No events yet' })).toBeTruthy();
    expect(callsTo(calls, 'DELETE', '/api/v1/events/e1')).toHaveLength(1);
    prompt.mockRestore();
    alert.mockRestore();
  });

  it('does not offer delete to staff', async () => {
    mockApi({ ...session(staff).routes, 'GET /api/v1/events': [eventRow] });
    renderApp('/events');
    await screen.findByRole('link', { name: 'Priya and Arun Wedding' });
    expect(screen.queryByRole('button', { name: /^Delete/ })).toBeNull();
  });

  it('shows a welcoming empty state', async () => {
    mockApi({ ...session(owner).routes, 'GET /api/v1/events': [] });
    renderApp('/events');
    expect(await screen.findByRole('heading', { name: 'No events yet' })).toBeTruthy();
  });

  it('says so when the list cannot load', async () => {
    mockApi({ ...session(owner).routes, 'GET /api/v1/events': reply(500, {}) });
    renderApp('/events');
    expect((await screen.findByRole('alert')).textContent).toContain('Could not load this list');
  });

  it('creates an event with a date and a limit, then reloads the list', async () => {
    let created = false;
    const calls = mockApi({
      ...session(owner).routes,
      'GET /api/v1/events': () => (created ? [eventRow] : []),
      'POST /api/v1/events': () => {
        created = true;
        return reply(201, eventRow);
      },
    });
    renderApp('/events');
    await screen.findByRole('heading', { name: 'No events yet' });
    press('New event');
    typeInto('Event name', 'Priya and Arun Wedding');
    typeInto('Event date', '2026-12-01');
    typeInto('Photos the client may select', '200');
    press('Create event');
    expect(await screen.findByRole('link', { name: 'Priya and Arun Wedding' })).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/events')[0].body).toEqual({
      title: 'Priya and Arun Wedding', event_date: '2026-12-01', selection_limit: 200,
    });
    expect(screen.queryByRole('heading', { name: 'New event' })).toBeNull(); // the form closed
  });

  it('leaves date and limit empty when they are not given', async () => {
    const calls = mockApi({
      ...session(owner).routes, 'GET /api/v1/events': [], 'POST /api/v1/events': reply(201, eventRow),
    });
    renderApp('/events');
    await screen.findByRole('heading', { name: 'No events yet' });
    press('New event');
    typeInto('Event name', 'Quick shoot');
    press('Create event');
    await waitFor(() => expect(callsTo(calls, 'POST', '/api/v1/events')).toHaveLength(1));
    expect(callsTo(calls, 'POST', '/api/v1/events')[0].body).toEqual({ title: 'Quick shoot', event_date: null, selection_limit: null });
  });

  it('shows the plan limit when a new event is refused', async () => {
    mockApi({
      ...session(owner).routes, 'GET /api/v1/events': [],
      'POST /api/v1/events': reply(402, { detail: 'Your Free trial plan allows 1 active event.' }),
    });
    renderApp('/events');
    await screen.findByRole('heading', { name: 'No events yet' });
    press('New event');
    typeInto('Event name', 'Second event');
    press('Create event');
    expect((await screen.findByRole('alert')).textContent).toContain('allows 1 active event');
  });

  it('cancelling closes the form without sending anything', async () => {
    const calls = mockApi({ ...session(owner).routes, 'GET /api/v1/events': [] });
    renderApp('/events');
    await screen.findByRole('heading', { name: 'No events yet' });
    press('New event');
    press('Cancel');
    expect(screen.getByRole('button', { name: 'New event' })).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/events')).toHaveLength(0);
  });
});

describe('staff', () => {
  const member = { id: 'm1', email: 'ravi@example.com', full_name: 'Ravi', role: 'staff', is_active: true, has_password: false };

  it('lets the owner invite someone and shows the confirmation', async () => {
    const calls = mockApi({
      ...session(owner).routes,
      'GET /api/v1/staff': [member],
      'POST /api/v1/staff': reply(201, member),
    });
    renderApp('/staff');
    await screen.findByRole('heading', { name: 'Staff' });
    typeInto('Name', 'Meera');
    typeInto('Email', 'meera@example.com');
    press('Send invitation');
    expect((await screen.findByRole('status')).textContent).toBe('Invitation sent to meera@example.com.');
    expect(callsTo(calls, 'POST', '/api/v1/staff')[0].body).toEqual({ full_name: 'Meera', email: 'meera@example.com' });
  });

  it('removes a member only after confirming', async () => {
    const calls = mockApi({
      ...session(owner).routes,
      'GET /api/v1/staff': [member],
      'DELETE /api/v1/staff/m1': reply(204),
    });
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderApp('/staff');
    await screen.findByText('Ravi');
    const remove = screen.getAllByRole('button', { name: /remove/i })[0];
    fireEvent.click(remove);
    expect(callsTo(calls, 'DELETE', '/api/v1/staff/m1')).toHaveLength(0); // said no
    fireEvent.click(remove);
    await waitFor(() => expect(callsTo(calls, 'DELETE', '/api/v1/staff/m1')).toHaveLength(1));
    expect(confirm).toHaveBeenCalledTimes(2);
    expect(await screen.findByText('Ravi no longer has access.')).toBeTruthy();
  });

  it('is closed to staff members', async () => {
    mockApi({ ...session(staff).routes, 'GET /api/v1/staff': reply(403, {}) });
    renderApp('/staff');
    expect((await screen.findByRole('alert')).textContent).toBe('Only the studio owner can manage staff.');
  });
});

describe('an event', () => {
  const detail = {
    id: 'e1', title: 'Priya and Arun Wedding', event_date: null, status: 'shared', selection_limit: 3,
    expires_at: null, watermark_enabled: false, watermark_text: '', photo_count: 5,
  };
  const client = {
    id: 'c1', client_name: 'Priya Rao', email: '', phone: '919876543210', username: 'priya-5685', is_active: true, last_login_at: null,
  };
  const eventRoutes = (extra: Record<string, unknown> = {}) => ({
    ...session(owner).routes,
    'GET /api/v1/events/e1': detail,
    'GET /api/v1/events/e1/albums': [],
    'GET /api/v1/events/e1/photos': { count: 0, next_page: null, results: [] },
    'GET /api/v1/events/e1/selection': { count: 0, results: [], duplicate_filenames: [] },
    'GET /api/v1/events/e1/clients': [],
    'GET /api/v1/events/e1/progress': { status: 'shared', selection_limit: 3, selected: 0, submitted_at: null, last_client_login: null },
    'GET /api/v1/events/e1/drive-imports': { enabled: false, imports: [] },
    ...extra,
  });

  it('shows the stepper at the right step', async () => {
    mockApi(eventRoutes());
    renderApp('/events/e1');
    const steps = await screen.findByRole('list', { name: 'Event progress' });
    expect(within(steps).getByText('Shared with client').getAttribute('aria-current')).toBe('step');
    expect(within(steps).getByText('Created').className).toBe('done');
    expect(within(steps).getByText('Archived').className).toBe('');
  });

  it('says so for an event that does not exist', async () => {
    mockApi({ ...session(owner).routes, 'GET /api/v1/events/e1': reply(404, {}), 'GET /api/v1/events/e1/albums': reply(404, {}) });
    renderApp('/events/e1');
    expect((await screen.findByRole('alert')).textContent).toBe('This event could not be found.');
  });

  it('shares with a client and offers the login on WhatsApp, shown once', async () => {
    const calls = mockApi(eventRoutes({
      'POST /api/v1/events/e1/clients': reply(201, { ...client, password: 'Abcd-Efgh-1234' }),
    }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Client' });
    typeInto('Client name', 'Priya Rao');
    typeInto('Client WhatsApp number', '98765 43210');
    press('Share with client');
    expect(await screen.findByText('Abcd-Efgh-1234')).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/events/e1/clients')[0].body).toEqual({
      client_name: 'Priya Rao', email: '', phone: '98765 43210', role: 'main',
    });
    const link = screen.getByRole('link', { name: 'Send on WhatsApp' });
    expect(link.getAttribute('href')).toContain('https://wa.me/919876543210?text=');
    expect(decodeURIComponent(link.getAttribute('href')!)).toContain('priya-5685');
    expect(screen.getByText(/shown only now/)).toBeTruthy();
    press('Hide');
    expect(screen.queryByText('Abcd-Efgh-1234')).toBeNull();
  });

  it('shares by WhatsApp only when the server has no client email', async () => {
    const whatsappOnly = { ...owner, sharing: { client_email: false, confirm_email_first: false } };
    const calls = mockApi({
      ...eventRoutes(),
      ...session(whatsappOnly).routes,
      'POST /api/v1/events/e1/clients': reply(201, { ...client, password: 'Abcd-Efgh-1234' }),
    });
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Client' });
    expect(screen.queryByLabelText('Client email (optional)')).toBeNull();
    expect(screen.getByText(/You send it on WhatsApp/)).toBeTruthy();
    expect(screen.getByLabelText('Client WhatsApp number').hasAttribute('required')).toBe(true);
    typeInto('Client name', 'Priya Rao');
    typeInto('Client WhatsApp number', '98765 43210');
    press('Share with client');
    expect(await screen.findByRole('link', { name: 'Send on WhatsApp' })).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/events/e1/clients')[0].body).toMatchObject({ client_name: 'Priya Rao', phone: '98765 43210' });
  });

  it('asks for a contact before sharing and shows the server message', async () => {
    mockApi(eventRoutes({
      'POST /api/v1/events/e1/clients': reply(400, { email: ["Enter the client's email, WhatsApp number, or both."] }),
    }));
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Client' });
    typeInto('Client name', 'No Contact');
    press('Share with client');
    expect(await screen.findByText(/Enter the client's email, WhatsApp number, or both/)).toBeTruthy();
  });

  it('does not offer sharing until photos are uploaded', async () => {
    mockApi(eventRoutes({ 'GET /api/v1/events/e1': { ...detail, photo_count: 0, status: 'draft' } }));
    renderApp('/events/e1');
    expect(await screen.findByText('Upload photos before sharing this event.')).toBeTruthy();
  });

  it('shows progress, resets a password and turns access off, each after a confirmation', async () => {
    const calls = mockApi(eventRoutes({
      'GET /api/v1/events/e1/clients': [client],
      'GET /api/v1/events/e1/progress': { status: 'shared', selection_limit: 3, selected: 2, submitted_at: null, last_client_login: null },
      'POST /api/v1/client-access/c1/reset-password': { ...client, password: 'New-Pass-9999' },
      'POST /api/v1/client-access/c1/revoke': { ...client, is_active: false },
    }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderApp('/events/e1');
    expect(await screen.findByText(/Not submitted yet/)).toBeTruthy();
    expect(screen.getByText('selected', { exact: false }).textContent).toContain('2');
    press('New password');
    expect(await screen.findByText('New-Pass-9999')).toBeTruthy();
    press('Turn off access');
    await waitFor(() => expect(callsTo(calls, 'POST', '/api/v1/client-access/c1/revoke')).toHaveLength(1));
    expect(confirm).toHaveBeenCalledTimes(2);
  });

  it('lets the studio reopen a submitted selection', async () => {
    const calls = mockApi(eventRoutes({
      'GET /api/v1/events/e1': { ...detail, status: 'submitted' },
      'GET /api/v1/events/e1/clients': [client],
      'GET /api/v1/events/e1/progress': {
        status: 'submitted', selection_limit: 3, selected: 3, submitted_at: '2026-12-02T10:00:00Z', last_client_login: null,
      },
      'POST /api/v1/events/e1/reopen': { ...detail, status: 'shared' },
    }));
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderApp('/events/e1');
    press(await screen.findByRole('button', { name: 'Let the client make changes' }).then((b) => b.textContent!));
    await waitFor(() => expect(callsTo(calls, 'POST', '/api/v1/events/e1/reopen')).toHaveLength(1));
  });

  it("lists the client's selection with every download and their notes", async () => {
    mockApi(eventRoutes({
      'GET /api/v1/events/e1': { ...detail, status: 'submitted' },
      'GET /api/v1/events/e1/selection': {
        count: 2,
        duplicate_filenames: ['IMG_001.jpg'],
        results: [
          { photo_id: 'p1', relative_path: 'Wedding/IMG_001.jpg', filename: 'IMG_001.jpg', note: 'Album cover', thumb_url: 'data:,', preview_url: 'data:,' },
          { photo_id: 'p2', relative_path: 'Wedding/IMG_002.jpg', filename: 'IMG_002.jpg', note: '', thumb_url: 'data:,', preview_url: 'data:,' },
        ],
      },
    }));
    renderApp('/events/e1');
    expect(await screen.findByText('(2 photos)')).toBeTruthy();
    const types = ['script-windows', 'script-mac', 'lightroom', 'csv', 'txt'];
    for (const type of types) {
      const link = document.querySelector(`a[href="/api/v1/events/e1/export?type=${type}"]`);
      expect(link, type).not.toBeNull();
    }
    expect(screen.getByText('Album cover', { exact: false })).toBeTruthy();
    expect(screen.getByText(/also\s+used in another folder/)).toBeTruthy();
  });

  it('at stage 4 offers to copy the chosen files to the studio’s computer', async () => {
    mockApi(eventRoutes({
      'GET /api/v1/events/e1': { ...detail, status: 'submitted' },
      'GET /api/v1/events/e1/selection': {
        count: 2, duplicate_filenames: [],
        results: [
          { photo_id: 'p1', relative_path: 'A/IMG_1.jpg', filename: 'IMG_1.jpg', note: '', thumb_url: 'data:,', preview_url: 'data:,' },
          { photo_id: 'p2', relative_path: 'A/IMG_2.jpg', filename: 'IMG_2.jpg', note: '', thumb_url: 'data:,', preview_url: 'data:,' },
        ],
      },
    }));
    renderApp('/events/e1');
    const link = await screen.findByRole('link', { name: 'Copy selected files to local' });
    expect(link.getAttribute('href')).toBe('/copy/?event=e1');
    expect(link.getAttribute('target')).toBe('_blank'); // the studio page stays open
    expect(link.getAttribute('rel')).toContain('noopener');
    expect(screen.getByText(/Ready to copy the 2 chosen photos/)).toBeTruthy();
    expect(screen.getByText(/Nothing is\s+uploaded/)).toBeTruthy();
  });

  it('does not offer the copy button before the client has sent the selection', async () => {
    mockApi(eventRoutes({
      'GET /api/v1/events/e1': { ...detail, status: 'shared' },
      'GET /api/v1/events/e1/selection': {
        count: 1, duplicate_filenames: [],
        results: [{ photo_id: 'p1', relative_path: 'A/IMG_1.jpg', filename: 'IMG_1.jpg', note: '', thumb_url: 'data:,', preview_url: 'data:,' }],
      },
    }));
    renderApp('/events/e1');
    await screen.findByText('(1 photos)');
    expect(screen.queryByRole('link', { name: 'Copy selected files to local' })).toBeNull();
  });

  it('shows the first 10 chosen photos and links to all of them', async () => {
    const results = Array.from({ length: 12 }, (_, i) => ({
      photo_id: `p${i}`, relative_path: `W/IMG_${i}.jpg`, filename: `IMG_${i}.jpg`, note: '', thumb_url: 'data:,', preview_url: 'data:,',
    }));
    mockApi(eventRoutes({
      'GET /api/v1/events/e1': { ...detail, status: 'submitted' },
      'GET /api/v1/events/e1/selection': { count: 12, duplicate_filenames: [], results },
    }));
    renderApp('/events/e1');
    expect(await screen.findByAltText('IMG_9.jpg')).toBeTruthy();
    expect(screen.queryByAltText('IMG_10.jpg')).toBeNull();
    expect(screen.getByRole('link', { name: /View all 12 chosen photos/ }).getAttribute('href')).toBe('/events/e1/photos?tab=chosen');
  });

  it('the owner can delete the event from its page, after typing its name', async () => {
    const calls = mockApi(eventRoutes({ 'DELETE /api/v1/events/e1': reply(204), 'GET /api/v1/events': [] }));
    const prompt = vi.spyOn(window, 'prompt').mockReturnValue('Priya and Arun Wedding');
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Priya and Arun Wedding' });
    fireEvent.click(screen.getByRole('button', { name: 'Delete event' }));
    expect(await screen.findByRole('heading', { name: 'No events yet' })).toBeTruthy();
    expect(callsTo(calls, 'DELETE', '/api/v1/events/e1')).toHaveLength(1);
    prompt.mockRestore();
  });

  it('archives only after confirmation', async () => {
    const calls = mockApi(eventRoutes({ 'POST /api/v1/events/e1/archive': { ...detail, status: 'archived' } }));
    const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderApp('/events/e1');
    await screen.findByRole('heading', { name: 'Priya and Arun Wedding' });
    const archive = screen.getByRole('button', { name: /archive/i });
    fireEvent.click(archive);
    expect(callsTo(calls, 'POST', '/api/v1/events/e1/archive')).toHaveLength(0);
    fireEvent.click(archive);
    await waitFor(() => expect(callsTo(calls, 'POST', '/api/v1/events/e1/archive')).toHaveLength(1));
    expect(confirm.mock.calls[0][0]).toContain('90 days');
  });
});

describe('billing', () => {
  const plans = [
    { code: 'studio', name: 'Studio', price_inr: 2499, max_active_events: 20, max_photos_per_event: 8000, max_staff: 3, available: true },
    { code: 'pro', name: 'Pro', price_inr: 4999, max_active_events: null, max_photos_per_event: 20000, max_staff: 10, available: false },
  ];
  const info = {
    ...billing, state: 'trial', plan: 'Free trial', status: 'trialing', plan_code: null, cancel_at_period_end: false,
    until: '2026-12-14T00:00:00Z',
    limits: { max_active_events: 1, max_photos_per_event: 5000, max_staff: 2 },
    usage: { active_events: 1, staff: 1 }, plans, payments_configured: true,
  };

  it('shows usage against limits and each plan with its price', async () => {
    mockApi({ ...session(owner).routes, 'GET /api/v1/billing': info });
    renderApp('/billing');
    expect(await screen.findByText(/Free trial · ends/)).toBeTruthy();
    expect(screen.getByText('1 / 1')).toBeTruthy();
    expect(screen.getByText('₹2,499', { exact: false })).toBeTruthy();
    expect(screen.getByText('Unlimited active events')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Choose Studio' })).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Not available yet' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('warns when online payments are not set up', async () => {
    mockApi({ ...session(owner).routes, 'GET /api/v1/billing': { ...info, payments_configured: false } });
    renderApp('/billing');
    expect(await screen.findByText(/Online payments are not set up yet/)).toBeTruthy();
  });

  it('hides the plan buttons from staff', async () => {
    mockApi({ ...session(staff).routes, 'GET /api/v1/billing': info });
    renderApp('/billing');
    expect(await screen.findByText('Only the studio owner can change the plan.')).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Choose/ })).toBeNull();
  });

  it('marks the current plan and offers cancel only for an active one', async () => {
    mockApi({
      ...session(owner).routes,
      'GET /api/v1/billing': { ...info, state: 'active', plan: 'Studio', status: 'active', plan_code: 'studio' },
    });
    renderApp('/billing');
    expect(await screen.findByText('Current plan')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Cancel plan' })).toBeTruthy();
  });

  it('cancels at the end of the period after confirmation', async () => {
    let cancelled = false;
    const calls = mockApi({
      ...session(owner).routes,
      'GET /api/v1/billing': () => ({
        ...info, state: cancelled ? 'ending' : 'active', plan: 'Studio', status: 'active', plan_code: 'studio', cancel_at_period_end: cancelled,
      }),
      'POST /api/v1/billing/cancel': () => {
        cancelled = true;
        return {};
      },
    });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    renderApp('/billing');
    press(await screen.findByRole('button', { name: 'Cancel plan' }).then((b) => b.textContent!));
    expect(await screen.findByText(/Your plan is cancelled/)).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/billing/cancel')).toHaveLength(1);
    expect(screen.queryByRole('button', { name: 'Cancel plan' })).toBeNull();
  });

  it('opens Razorpay Checkout and confirms the payment with the server', async () => {
    const calls = mockApi({
      ...session(owner).routes,
      'GET /api/v1/billing': info,
      'POST /api/v1/billing/subscribe': {
        subscription_id: 'sub_1', key_id: 'rzp_test_1', plan: plans[0], prefill: { name: 'Owner', email: 'o@x.com' }, studio_name: 'Lens',
      },
      'POST /api/v1/billing/verify': { state: 'active' },
    });
    let options: Record<string, unknown> = {};
    const open = vi.fn();
    vi.stubGlobal('Razorpay', class {
      constructor(o: Record<string, unknown>) { options = o; }
      open = open;
      on() {}
    });
    renderApp('/billing');
    press(await screen.findByRole('button', { name: 'Choose Studio' }).then((b) => b.textContent!));
    await waitFor(() => expect(open).toHaveBeenCalled());
    expect(options).toMatchObject({ key: 'rzp_test_1', subscription_id: 'sub_1', name: 'PickSnap' });
    const done = { razorpay_payment_id: 'pay_1', razorpay_subscription_id: 'sub_1', razorpay_signature: 'sig' };
    await (options.handler as (r: unknown) => Promise<void>)(done);
    expect(callsTo(calls, 'POST', '/api/v1/billing/verify')[0].body).toEqual(done);
    expect(await screen.findByText('Payment received. You are on the Studio plan.')).toBeTruthy();
  });

  describe('changing plan while paying', () => {
    const three = [
      { code: 'starter', name: 'Starter', price_inr: 999, max_active_events: 5, max_photos_per_event: 2000, max_staff: 1, available: true },
      { ...plans[0] },
      { ...plans[1], available: true },
    ];
    const paying = {
      ...info, state: 'active', plan: 'Studio', status: 'active', plan_code: 'studio', plans: three, until: '2026-12-21T00:00:00Z',
    };

    it('labels upgrades and switches, and shows the prorated price before Razorpay opens', async () => {
      const calls = mockApi({
        ...session(owner).routes,
        'GET /api/v1/billing': paying,
        'GET /api/v1/billing/quote': {
          kind: 'upgrade', plan: three[2], charge_now_inr: 250, days_left: 3, starts_at: '2026-12-21T00:00:00Z',
        },
        'POST /api/v1/billing/subscribe': {
          subscription_id: 'sub_2', key_id: 'rzp_test_1', plan: three[2], prefill: { name: 'Owner', email: 'o@x.com' }, studio_name: 'Lens',
        },
        'POST /api/v1/billing/verify': { state: 'active' },
      });
      let options: Record<string, unknown> = {};
      const open = vi.fn();
      vi.stubGlobal('Razorpay', class {
        constructor(o: Record<string, unknown>) { options = o; }
        open = open;
        on() {}
      });
      renderApp('/billing');
      expect(await screen.findByRole('button', { name: 'Switch to Starter' })).toBeTruthy();
      press('Upgrade to Pro');
      const dialog = await screen.findByRole('dialog', { name: 'Upgrade to Pro' });
      expect(dialog.textContent).toContain('Pay ₹250 today');
      expect(dialog.textContent).toContain('for the 3 days left this month');
      expect(dialog.textContent).toContain('₹4,999 every month, instead of ₹2,499');
      expect(callsTo(calls, 'POST', '/api/v1/billing/subscribe')).toHaveLength(0);
      press('Pay ₹250');
      await waitFor(() => expect(open).toHaveBeenCalled());
      expect(options).toMatchObject({ subscription_id: 'sub_2', description: 'Change to Pro for Lens' });
      await (options.handler as (r: unknown) => Promise<void>)({ razorpay_payment_id: 'p', razorpay_subscription_id: 'sub_2', razorpay_signature: 's' });
      expect(await screen.findByText(/You are on the Pro plan now\. Full billing starts/)).toBeTruthy();
    });

    it('explains a downgrade waits for the renewal date', async () => {
      mockApi({
        ...session(owner).routes,
        'GET /api/v1/billing': paying,
        'GET /api/v1/billing/quote': {
          kind: 'scheduled', plan: three[0], charge_now_inr: 0, days_left: 0, starts_at: '2026-12-21T00:00:00Z',
        },
      });
      renderApp('/billing');
      press(await screen.findByRole('button', { name: 'Switch to Starter' }).then((b) => b.textContent!));
      const dialog = await screen.findByRole('dialog', { name: /Switch to Starter on/ });
      expect(dialog.textContent).toContain('You keep the Studio plan until');
      expect(dialog.textContent).toContain('Starter allows 5 active events. Nothing is deleted');
      expect(within(dialog).getByRole('button', { name: 'Continue to Razorpay' })).toBeTruthy();
      press('Not now');
      await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    });

    it('shows a waiting switch on the plan it starts', async () => {
      mockApi({ ...session(owner).routes, 'GET /api/v1/billing': { ...paying, scheduled_plan_code: 'starter' } });
      renderApp('/billing');
      expect(await screen.findByText(/Switching to the Starter plan on/)).toBeTruthy();
      expect(screen.getByText(/^From /)).toBeTruthy();
      expect(screen.getByRole('button', { name: 'Keep Studio' })).toBeTruthy();
    });
  });

  it('shows the server message when checkout cannot start', async () => {
    mockApi({
      ...session(owner).routes,
      'GET /api/v1/billing': info,
      'POST /api/v1/billing/subscribe': reply(502, { detail: 'Could not reach Razorpay. Try again in a minute.' }),
    });
    renderApp('/billing');
    press(await screen.findByRole('button', { name: 'Choose Studio' }).then((b) => b.textContent!));
    expect((await screen.findByRole('alert')).textContent).toContain('Could not reach Razorpay');
  });
});

// @vitest-environment jsdom
/** Family helpers: the main client invites relatives, helpers choose but cannot submit,
 * and the studio can add family members too. */
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { familyInvitationText, invitationText } from '../share/whatsapp';
import { callsTo, mockApi, owner, press, renderApp, reply, session, typeInto, installBrowserMocks } from './harness';

installBrowserMocks();

const photo = (n: number, chosenBy: string | null = null, mine = false) => ({
  id: `p${n}`, width: 1600, height: 1067, thumb_url: 'data:,', preview_url: 'data:,', selected: Boolean(chosenBy), note: '',
  chosen_by: chosenBy, chosen_by_me: mine,
});

function gallery(role: 'main' | 'helper', extra: Record<string, unknown> = {}) {
  return mockApi({
    'GET /api/v1/client/me': {
      client_name: role === 'main' ? 'Priya Rao' : 'Ravi Uncle', role, main_name: 'Priya Rao', studio_name: 'Lens and Light',
      event: { title: 'Wedding', selection_limit: 200, expires_at: null, submitted_at: null },
      photo_count: 3, selected: 2, albums: [], cover_url: null, branding: null,
    },
    'GET /api/v1/client/photos': {
      count: 3, next_page: null,
      results: role === 'main'
        ? [photo(1, 'Priya Rao', true), photo(2, 'Ravi Uncle'), photo(3)]
        : [photo(1, 'Priya Rao'), photo(2, 'Ravi Uncle', true), photo(3)],
    },
    ...extra,
  });
}

describe('messages', () => {
  it('the main invitation asks not to forward it, and a family invitation names who asked', () => {
    const base = { clientName: 'Priya Rao', studioName: 'Lens', eventTitle: 'Wedding', galleryUrl: 'u', username: 'p', password: 'x' };
    expect(invitationText(base)).toContain('Tap “Invite family” in the gallery instead of forwarding this message.');
    const text = familyInvitationText({
      helperName: 'Ravi Uncle', mainName: 'Priya Rao', eventTitle: 'Wedding', galleryUrl: 'https://picksnap.in/gallery/login?u=ravi-1',
      username: 'ravi-1', password: 'Abcd-1234', studioName: 'Lens',
    });
    expect(text).toContain('Hello Ravi, Priya would like your help choosing photos from Wedding.');
    expect(text).toContain('Priya will see your picks and send the final selection.');
    expect(text).toContain('Password: Abcd-1234');
  });
});

describe('the main client', () => {
  it('sees who chose what and invites a relative with their own login', async () => {
    let helpers: unknown[] = [];
    const calls = gallery('main', {
      'GET /api/v1/client/family': () => ({ you: { client_name: 'Priya Rao', chosen: 1 }, helpers, max_helpers: 10 }),
      'POST /api/v1/client/family': () => {
        const created = { id: 'h1', client_name: 'Ravi Uncle', phone: '919876543210', username: 'ravi-abc123', is_active: true, last_login_at: null, chosen: 0 };
        helpers = [created];
        return reply(201, { ...created, password: 'Abcd-Efgh-1234' });
      },
      'POST /api/v1/client/family/h1/turn-off': () => {
        helpers = [{ ...(helpers[0] as object), is_active: false }];
        return reply(204);
      },
    });
    renderApp('/gallery');
    expect(await screen.findByText('Ravi', { selector: '.chosen-by' })).toBeTruthy();
    expect(document.querySelectorAll('.chosen-by')).toHaveLength(1); // not on the main client's own pick

    press('Invite family');
    const dialog = await screen.findByRole('dialog', { name: 'Invite family to help' });
    typeInto('Name', 'Ravi Uncle');
    typeInto('WhatsApp number (optional)', '98765 43210');
    press('Create their login');
    const send = await within(dialog).findByRole('link', { name: 'Send on WhatsApp to +91 98765 43210' });
    const href = decodeURIComponent(send.getAttribute('href')!);
    expect(href).toContain('ravi-abc123');
    expect(href).toContain('Abcd-Efgh-1234');
    expect(callsTo(calls, 'POST', '/api/v1/client/family')[0].body).toEqual({ client_name: 'Ravi Uncle', phone: '98765 43210' });
    expect(await within(dialog).findByText('Helping you')).toBeTruthy();

    window.confirm = () => true;
    press('Turn off');
    await waitFor(() => expect(callsTo(calls, 'POST', '/api/v1/client/family/h1/turn-off')).toHaveLength(1));
    expect(await within(dialog).findByText('· turned off')).toBeTruthy();
  });

  it('sees how many each person chose before sending', async () => {
    gallery('main', {
      'GET /api/v1/client/family': {
        you: { client_name: 'Priya Rao', chosen: 1 },
        helpers: [{ id: 'h1', client_name: 'Ravi Uncle', phone: '', username: 'r', is_active: true, last_login_at: null, chosen: 1 }],
        max_helpers: 10,
      },
    });
    renderApp('/gallery');
    await screen.findByText('Ravi', { selector: '.chosen-by' });
    fireEvent.click(screen.getByRole('button', { name: 'Send selection' }));
    const dialog = await screen.findByRole('dialog', { name: /Send 2 photos/ });
    expect(await within(dialog).findByText(/You chose 1 · Ravi chose 1\./)).toBeTruthy();
  });
});

describe('a family helper', () => {
  it('is told who sends, cannot submit or remove other people’s picks', async () => {
    gallery('helper');
    renderApp('/gallery');
    expect(await screen.findByText(/You are helping Priya choose/)).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Send selection' })).toBeNull();
    expect(screen.getByText('Priya will send the final selection')).toBeTruthy();
    expect(screen.queryByRole('button', { name: 'Invite family' })).toBeNull();
    const others = screen.getByRole('button', { name: 'Chosen by Priya Rao' }) as HTMLButtonElement;
    expect(others.disabled).toBe(true);
    const own = screen.getByRole('button', { name: 'Remove from selection' }) as HTMLButtonElement;
    expect(own.disabled).toBe(false);
  });
});

describe('the studio', () => {
  const detail = {
    id: 'e1', title: 'Wedding', event_date: null, status: 'shared', selection_limit: 3,
    expires_at: null, watermark_enabled: false, watermark_text: '', photo_count: 5,
  };
  const main = { id: 'c1', client_name: 'Priya Rao', email: '', phone: '919876543210', username: 'priya-1', is_active: true, last_login_at: null, role: 'main', invited_by: null };

  it('adds a family member once the main client has a login', async () => {
    const calls = mockApi({
      ...session(owner).routes,
      'GET /api/v1/events/e1': detail,
      'GET /api/v1/events/e1/albums': [],
      'GET /api/v1/events/e1/photos': { count: 0, next_page: null, results: [] },
      'GET /api/v1/events/e1/selection': { count: 0, results: [], duplicate_filenames: [] },
      'GET /api/v1/events/e1/clients': [main, { ...main, id: 'c2', client_name: 'Anu', username: 'anu-1', role: 'helper', invited_by: 'Priya Rao' }],
      'GET /api/v1/events/e1/progress': { status: 'shared', selection_limit: 3, selected: 0, submitted_at: null, last_client_login: null },
      'GET /api/v1/events/e1/drive-imports': { enabled: false, imports: [] },
      'POST /api/v1/events/e1/clients': reply(201, { ...main, id: 'c3', client_name: 'Ravi', username: 'ravi-1', role: 'helper', invited_by: 'Priya Rao', password: 'Pass-1234' }),
    });
    renderApp('/events/e1');
    expect(await screen.findByText(/Family, helping Priya Rao/)).toBeTruthy();
    expect(screen.getByText(/Main client/)).toBeTruthy();
    typeInto('Family member name', 'Ravi');
    typeInto('Their WhatsApp number', '98765 43210');
    press('Add family member');
    await waitFor(() => expect(callsTo(calls, 'POST', '/api/v1/events/e1/clients')).toHaveLength(1));
    expect(callsTo(calls, 'POST', '/api/v1/events/e1/clients')[0].body).toMatchObject({ client_name: 'Ravi', role: 'helper' });
    const link = await screen.findByRole('link', { name: 'Send on WhatsApp' });
    expect(decodeURIComponent(link.getAttribute('href')!)).toContain('Priya would like your help');
  });
});

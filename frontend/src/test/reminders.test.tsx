// @vitest-environment jsdom
/** Reminders for clients who have not submitted: the Events banner and the Reminders page. */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { reminderText } from '../share/whatsapp';
import { callsTo, mockApi, owner, renderApp, reply, session, installBrowserMocks } from './harness';

installBrowserMocks();

const due = (overrides: Record<string, unknown> = {}) => ({
  id: 'a1', client_name: 'Priya Rao', phone: '919876543210', username: 'priya-abc123', reason: 'first',
  shared_at: new Date(Date.now() - 3 * 86400000).toISOString(), reminder_count: 0, last_reminded_at: null, selected: 12,
  event: { id: 'e1', title: 'Priya and Arun Wedding', selection_limit: 200, expires_at: null },
  ...overrides,
});

describe('the reminder message', () => {
  it('says what was chosen, points to the first message for the password, and mentions closing', () => {
    const text = reminderText({
      clientName: 'Priya Rao', studioName: 'Lens and Light', eventTitle: 'Wedding', galleryUrl: 'https://picksnap.in/gallery/login?u=p',
      username: 'p', selected: 12, selectionLimit: 200, closesOn: '2026-12-05',
    });
    expect(text).toContain('Hello Priya, a gentle reminder to choose your photos from Wedding.');
    expect(text).toContain('You have chosen 12 of 200 so far');
    expect(text).toContain('closes after 5 December');
    expect(text).toContain('Username: p');
    expect(text).toContain('password from our earlier message');
    expect(text).not.toMatch(/Password:/);
  });
});

describe('reminders', () => {
  it('the Events screen says when clients are due and links to the reminders', async () => {
    mockApi({ ...session(owner).routes, 'GET /api/v1/events': [], 'GET /api/v1/reminders': { count: 2, max_reminders: 3, results: [] } });
    renderApp('/events');
    expect(await screen.findByText('2 clients have not chosen their photos yet.')).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Send reminders' }).getAttribute('href')).toBe('/reminders');
  });

  it('no banner when nobody is due', async () => {
    mockApi({ ...session(owner).routes, 'GET /api/v1/events': [], 'GET /api/v1/reminders': { count: 0, max_reminders: 3, results: [] } });
    renderApp('/events');
    await screen.findByRole('heading', { name: 'Events' });
    expect(screen.queryByText(/not chosen their photos/)).toBeNull();
  });

  it('opens WhatsApp with the reminder written and records it as sent', async () => {
    let list = [due()];
    const calls = mockApi({
      ...session(owner).routes,
      'GET /api/v1/reminders': () => ({ count: list.length, max_reminders: 3, results: list }),
      'POST /api/v1/reminders/a1/sent': () => {
        list = [];
        return { reminder_count: 1 };
      },
    });
    renderApp('/reminders');
    expect(await screen.findByRole('heading', { name: 'Priya Rao' })).toBeTruthy();
    expect(screen.getByText(/Shared 3 days ago/)).toBeTruthy();
    expect(screen.getByText(/12 of 200 chosen so far/)).toBeTruthy();
    const send = screen.getByRole('link', { name: 'Send on WhatsApp to +91 98765 43210' });
    const href = decodeURIComponent(send.getAttribute('href')!);
    expect(href.startsWith('https://wa.me/919876543210?text=')).toBe(true);
    expect(href).toContain('priya-abc123');
    expect(href).toContain('/gallery/login?u=priya-abc123');
    fireEvent.click(send);
    expect(await screen.findByText('Reminder for Priya Rao marked as sent.')).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/reminders/a1/sent')).toHaveLength(1);
    expect(await screen.findByRole('heading', { name: 'No reminders due' })).toBeTruthy();
  });

  it('shows why each client is due and can skip one', async () => {
    const calls = mockApi({
      ...session(owner).routes,
      'GET /api/v1/reminders': {
        count: 2, max_reminders: 3,
        results: [
          due({ id: 'a2', client_name: 'Arun', phone: '', reason: 'again', reminder_count: 1, last_reminded_at: new Date(Date.now() - 4 * 86400000).toISOString(), selected: 0 }),
          due({ id: 'a3', client_name: 'Meera', reason: 'expiring', event: { id: 'e2', title: 'Shower', selection_limit: null, expires_at: '2026-12-05' } }),
        ],
      },
      'POST /api/v1/reminders/a2/sent': reply(200, { reminder_count: 2 }),
    });
    renderApp('/reminders');
    expect(await screen.findByText(/Reminder 2 of 3 · last one 4 days ago/)).toBeTruthy();
    expect(screen.getByText(/nothing chosen yet/)).toBeTruthy();
    expect(screen.getByText(/Gallery closes tomorrow/)).toBeTruthy();
    // No number saved: WhatsApp opens and the studio picks the contact.
    expect(screen.getAllByRole('link', { name: 'Send on WhatsApp' })[0].getAttribute('href')).toMatch(/^https:\/\/wa\.me\/\?text=/);
    fireEvent.click(screen.getAllByRole('button', { name: 'Skip this one' })[0]);
    await waitFor(() => expect(callsTo(calls, 'POST', '/api/v1/reminders/a2/sent')).toHaveLength(1));
  });
});

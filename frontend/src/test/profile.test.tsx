// @vitest-environment jsdom
/** The Profile screen: studio details, the person's own name, and changing the password. */
import { screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { callsTo, mockApi, owner, press, renderApp, reply, session, staff, typeInto, installBrowserMocks } from './harness';

installBrowserMocks();

const stored = {
  name: 'Lens and Light', phone: '919876543210', contact_email: '', address: '', city: 'Chennai', website: '', instagram: 'lens',
};

describe('studio profile', () => {
  it('shows the profile and saves changes', async () => {
    const s = session(owner);
    const calls = mockApi({
      ...s.routes,
      'GET /api/v1/studio/profile': stored,
      'PATCH /api/v1/studio/profile': (call: { body: unknown }) => ({ ...(call.body as object), phone: '919876543210', website: 'https://lens.in' }),
    });
    renderApp('/profile');
    expect(await screen.findByRole('heading', { name: 'Profile' })).toBeTruthy();
    await waitFor(() => expect((screen.getByLabelText('WhatsApp number') as HTMLInputElement).value).toBe('+91 98765 43210'));
    expect(screen.getByRole('link', { name: 'Profile' })).toBeTruthy();

    typeInto('Studio name', 'Lens & Light Studio');
    typeInto('Website', 'lens.in');
    press('Save studio profile');
    expect(await screen.findByText('Studio profile saved.')).toBeTruthy();
    const [patch] = callsTo(calls, 'PATCH', '/api/v1/studio/profile');
    expect(patch.body).toMatchObject({ name: 'Lens & Light Studio', website: 'lens.in', city: 'Chennai' });
    expect((screen.getByLabelText('Website') as HTMLInputElement).value).toBe('https://lens.in');
    // The top bar picks up the new studio name.
    await waitFor(() => expect(callsTo(calls, 'GET', '/api/v1/auth/me').length).toBeGreaterThan(1));
  });

  it('shows a wrong value next to its field', async () => {
    mockApi({
      ...session(owner).routes,
      'GET /api/v1/studio/profile': stored,
      'PATCH /api/v1/studio/profile': reply(400, { phone: ['Enter a 10-digit Indian mobile number.'] }),
    });
    renderApp('/profile');
    await screen.findByDisplayValue('Chennai');
    typeInto('WhatsApp number', '123');
    press('Save studio profile');
    expect(await screen.findByText('Enter a 10-digit Indian mobile number.')).toBeTruthy();
  });

  it('staff can see the details but not change them', async () => {
    mockApi({ ...session(staff).routes, 'GET /api/v1/studio/profile': stored });
    renderApp('/profile');
    expect(await screen.findByText('Only the studio owner can change these details.')).toBeTruthy();
    expect(screen.getByLabelText('Studio name').matches(':disabled')).toBe(true);
    expect(screen.queryByRole('button', { name: 'Save studio profile' })).toBeNull();
  });
});

describe('your account', () => {
  it('saves your name', async () => {
    const calls = mockApi({ ...session(owner).routes, 'GET /api/v1/studio/profile': stored, 'PATCH /api/v1/auth/account': { user: owner } });
    renderApp('/profile');
    await screen.findByDisplayValue('Owner One');
    typeInto('Your name', 'Priya R');
    press('Save name');
    expect(await screen.findByText('Your name is saved.')).toBeTruthy();
    expect(callsTo(calls, 'PATCH', '/api/v1/auth/account')[0].body).toEqual({ full_name: 'Priya R' });
  });

  it('changes the password and explains a wrong current password', async () => {
    let attempts = 0;
    mockApi({
      ...session(owner).routes,
      'GET /api/v1/studio/profile': stored,
      'POST /api/v1/auth/password-change': () =>
        ++attempts === 1 ? reply(400, { current_password: ['This is not your current password.'] }) : { detail: 'Password changed.' },
    });
    renderApp('/profile');
    await screen.findByRole('heading', { name: 'Change password' });
    typeInto('Current password', 'wrong');
    typeInto('New password', 'a-new-strong-pass-77');
    press('Change password');
    expect(await screen.findByText('This is not your current password.')).toBeTruthy();
    typeInto('Current password', 'right-one');
    press('Change password');
    expect(await screen.findByText(/Password changed/)).toBeTruthy();
    expect((screen.getByLabelText('New password') as HTMLInputElement).value).toBe('');
  });
});

// @vitest-environment jsdom
/** Sign-in, sign-up, password links, email confirmation, the studio top bar and its banners. */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { billing, callsTo, mockApi, owner, press, renderApp, reply, session, staff, typeInto, installBrowserMocks } from './harness';

installBrowserMocks();

const events = { 'GET /api/v1/events': [] };

function fillLogin() {
  typeInto('Email', 'owner@lens.test');
  typeInto('Password', 'a-strong-pass-91');
  press('Log in');
}

describe('logging in', () => {
  it('sends logged-out visitors to the login screen', async () => {
    const { routes } = session();
    mockApi({ ...routes, ...events });
    renderApp('/events');
    expect(await screen.findByRole('heading', { name: 'Log in to your studio' })).toBeTruthy();
  });

  it('logs in and lands on the events screen', async () => {
    const s = session();
    const calls = mockApi({
      ...s.routes, ...events,
      'POST /api/v1/auth/login': () => {
        s.state.user = owner;
        return { user: owner };
      },
    });
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Log in to your studio' });
    fillLogin();
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/auth/login')[0].body).toEqual({
      email: 'owner@lens.test', password: 'a-strong-pass-91',
    });
  });

  it('shows the server message when the login is wrong and stays on the screen', async () => {
    const s = session();
    mockApi({ ...s.routes, 'POST /api/v1/auth/login': reply(400, { detail: 'Wrong email or password.' }) });
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Log in to your studio' });
    fillLogin();
    expect((await screen.findByRole('alert')).textContent).toBe('Wrong email or password.');
    expect(screen.getByRole('heading', { name: 'Log in to your studio' })).toBeTruthy();
  });

  it('tells people when they are being rate limited', async () => {
    const s = session();
    mockApi({ ...s.routes, 'POST /api/v1/auth/login': reply(429, {}) });
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Log in to your studio' });
    fillLogin();
    expect((await screen.findByRole('alert')).textContent).toContain('Too many attempts');
  });

  it('explains a network failure', async () => {
    const s = session();
    mockApi({ ...s.routes, 'POST /api/v1/auth/login': () => { throw new TypeError('offline'); } });
    renderApp('/login');
    await screen.findByRole('heading', { name: 'Log in to your studio' });
    fillLogin();
    expect((await screen.findByRole('alert')).textContent).toContain('Check your connection');
  });

  it('keeps logged-in people away from the login screen', async () => {
    const s = session(owner);
    mockApi({ ...s.routes, ...events });
    renderApp('/login');
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeTruthy();
  });
});

describe('signing up', () => {
  it('shows errors under the field they belong to', async () => {
    const s = session();
    mockApi({ ...s.routes, 'POST /api/v1/auth/signup': reply(400, { email: ['A studio with this email already exists.'] }) });
    renderApp('/signup');
    await screen.findByRole('heading', { name: 'Create your studio account' });
    typeInto('Studio name', 'Lens');
    typeInto('Your name', 'Asha');
    typeInto('Email', 'asha@example.com');
    typeInto('Password', 'a-strong-pass-91');
    press('Create account');
    const message = await screen.findByText('A studio with this email already exists.');
    expect(screen.getByLabelText('Email').getAttribute('aria-invalid')).toBe('true');
    expect(message.id).toBe('field-email-error');
    expect(screen.queryByRole('alert')).toBeNull();
  });

  it('creates the account and opens the studio', async () => {
    const s = session();
    const calls = mockApi({
      ...s.routes, ...events,
      'POST /api/v1/auth/signup': () => {
        s.state.user = owner;
        return reply(201, { user: owner });
      },
    });
    renderApp('/signup');
    await screen.findByRole('heading', { name: 'Create your studio account' });
    typeInto('Studio name', 'Lens and Light');
    typeInto('Your name', 'Owner One');
    typeInto('Email', 'owner@lens.test');
    typeInto('Password', 'a-strong-pass-91');
    press('Create account');
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/auth/signup')[0].body).toEqual({
      studio_name: 'Lens and Light', full_name: 'Owner One', email: 'owner@lens.test', password: 'a-strong-pass-91',
    });
  });
});

describe('password links', () => {
  it('forgot password gives the same confirmation for any email', async () => {
    const s = session();
    const calls = mockApi({ ...s.routes, 'POST /api/v1/auth/password-reset': reply(204) });
    renderApp('/forgot-password');
    await screen.findByRole('heading', { name: 'Reset your password' });
    typeInto('Email', 'whoever@example.com');
    press('Send reset link');
    expect((await screen.findByRole('status')).textContent).toContain('If an account exists for whoever@example.com');
    expect(callsTo(calls, 'POST', '/api/v1/auth/password-reset')).toHaveLength(1);
  });

  it('a reset link sets the password and signs in', async () => {
    const s = session();
    const calls = mockApi({
      ...s.routes, ...events,
      'POST /api/v1/auth/password-set': () => {
        s.state.user = owner;
        return { user: owner };
      },
    });
    renderApp('/reset-password?uid=abc&token=xyz');
    await screen.findByRole('heading', { name: 'Choose a new password' });
    typeInto('New password', 'another-strong-pass-42');
    press('Save password');
    expect(await screen.findByRole('heading', { name: 'Events' })).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/auth/password-set')[0].body).toEqual({
      uid: 'abc', token: 'xyz', password: 'another-strong-pass-42',
    });
  });

  it('a staff invitation uses its own title', async () => {
    mockApi(session().routes);
    renderApp('/reset-password?uid=abc&token=xyz&invite=1');
    expect(await screen.findByRole('heading', { name: 'Choose a password to join your studio' })).toBeTruthy();
  });

  it('an expired link offers a new one', async () => {
    mockApi({ ...session().routes, 'POST /api/v1/auth/password-set': reply(400, { detail: 'This link is invalid or has expired.' }) });
    renderApp('/reset-password?uid=abc&token=old');
    await screen.findByRole('heading', { name: 'Choose a new password' });
    typeInto('New password', 'another-strong-pass-42');
    press('Save password');
    expect((await screen.findByRole('alert')).textContent).toContain('invalid or has expired');
    expect(screen.getByRole('link', { name: 'Request a new link' }).getAttribute('href')).toBe('/forgot-password');
  });
});

describe('email confirmation', () => {
  it('confirms a good link once', async () => {
    const s = session(owner);
    const calls = mockApi({ ...s.routes, 'POST /api/v1/auth/verify-email': reply(204) });
    renderApp('/verify-email?token=good');
    expect(await screen.findByText('Your email address is confirmed.')).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/auth/verify-email')).toHaveLength(1);
    expect(callsTo(calls, 'POST', '/api/v1/auth/verify-email')[0].body).toEqual({ token: 'good' });
  });

  it('says so when the link is bad', async () => {
    mockApi({ ...session().routes, 'POST /api/v1/auth/verify-email': reply(400, { detail: 'bad' }) });
    renderApp('/verify-email?token=bad');
    await waitFor(() => expect(screen.queryByText('Checking your link…')).toBeNull());
    expect(screen.queryByText('Your email address is confirmed.')).toBeNull();
  });
});

describe('the studio top bar', () => {
  it('owners see Staff and Branding; staff do not', async () => {
    mockApi({ ...session(owner).routes, ...events });
    const first = renderApp('/events');
    const nav = await screen.findByRole('navigation', { name: 'Main' });
    expect(['Events', 'Staff', 'Branding', 'Billing'].every((n) => nav.textContent?.includes(n))).toBe(true);
    first.unmount();

    mockApi({ ...session(staff).routes, ...events });
    renderApp('/events');
    const staffNav = await screen.findByRole('navigation', { name: 'Main' });
    expect(staffNav.textContent).toContain('Billing');
    expect(staffNav.textContent).not.toContain('Staff');
    expect(staffNav.textContent).not.toContain('Branding');
  });

  it('logging out returns to the login screen', async () => {
    const s = session(owner);
    const calls = mockApi({ ...s.routes, ...events });
    renderApp('/events');
    await screen.findByRole('heading', { name: 'Events' });
    press('Log out');
    expect(await screen.findByRole('heading', { name: 'Log in to your studio' })).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/auth/logout')).toHaveLength(1);
  });

  it('platform admins are pointed to the Django admin', async () => {
    mockApi({ ...session({ ...owner, studio: null, role: 'owner' }).routes, ...events });
    renderApp('/events');
    expect(await screen.findByText(/platform admin account/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Open admin' }).getAttribute('href')).toBe('/admin/');
  });

  it('asks unverified users to confirm their email and can resend the link', async () => {
    const calls = mockApi({
      ...session({ ...owner, email_verified: false }).routes, ...events,
      'POST /api/v1/auth/resend-verification': reply(204),
    });
    renderApp('/events');
    expect((await screen.findByText(/Confirm your email address/)).textContent).toContain('owner@lens.test');
    press('Send a new link');
    expect(await screen.findByText(/A new link is on its way/)).toBeTruthy();
    expect(callsTo(calls, 'POST', '/api/v1/auth/resend-verification')).toHaveLength(1);
  });

  it('does not ask to confirm the email when sharing does not need it', async () => {
    mockApi({
      ...session({ ...owner, email_verified: false, sharing: { client_email: false, confirm_email_first: false } }).routes,
      ...events,
    });
    renderApp('/events');
    await screen.findByRole('heading', { name: 'Events' });
    expect(screen.queryByText(/Confirm your email address/)).toBeNull();
  });

  it('warns when the trial is about to end', async () => {
    const until = new Date(Date.now() + 3 * 86400000).toISOString();
    mockApi({ ...session({ ...owner, billing: { ...billing, state: 'trial', plan: 'Free trial', until } }).routes, ...events });
    renderApp('/events');
    expect((await screen.findByText(/Your free trial ends in 3 days/)).textContent).toContain('Choose a plan');
  });

  it('says nothing about a trial with plenty of time left', async () => {
    const until = new Date(Date.now() + 25 * 86400000).toISOString();
    mockApi({ ...session({ ...owner, billing: { ...billing, state: 'trial', until } }).routes, ...events });
    renderApp('/events');
    await screen.findByRole('heading', { name: 'Events' });
    expect(screen.queryByText(/free trial ends/)).toBeNull();
  });

  it('shows a lapsed account clearly, and staff are sent to billing rather than a plan choice', async () => {
    const lapsed = { ...billing, state: 'lapsed', can_work: false, message: 'Your plan has ended. Your data is safe.' };
    mockApi({ ...session({ ...staff, billing: lapsed }).routes, ...events });
    renderApp('/events');
    const banner = await screen.findByText(/Your plan has ended/);
    expect(banner.closest('.banner')?.className).toContain('bad');
    expect(screen.getByRole('link', { name: 'See billing' })).toBeTruthy();
  });
});

describe('unknown addresses', () => {
  it('show a way back to the events', async () => {
    mockApi(session().routes);
    renderApp('/nowhere');
    expect(await screen.findByRole('heading', { name: 'Page not found' })).toBeTruthy();
    fireEvent.click(screen.getByRole('link', { name: 'Go to your events' }));
  });
});

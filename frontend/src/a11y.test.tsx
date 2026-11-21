// @vitest-environment jsdom
/**
 * Accessibility checks (WCAG 2 A and AA rules from axe-core) on the main screens.
 * Colour contrast needs a real layout engine, so it is checked by eye in the browser instead.
 */
import axe from 'axe-core';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { MemoryRouter, Route, Routes } from 'react-router';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AuthProvider } from './auth/AuthContext';
import { ClientLoginPage, GalleryPage } from './gallery/GalleryPages';
import { BillingPage } from './pages/BillingPage';
import { ThemePage } from './pages/ThemePage';
import { ForgotPasswordPage, LoginPage, ResetPasswordPage, SignupPage } from './pages/AuthPages';
import { EventsPage } from './pages/StudioPages';

const owner = {
  id: 'u1', email: 'o@x.com', full_name: 'Owner', role: 'owner', email_verified: true,
  studio: { id: 's1', name: 'Lens and Light', slug: 'lens' },
  billing: { state: 'trial', can_work: true, gallery_open: true, message: 'Free trial', until: null, plan: 'Free trial' },
};

const responses: Record<string, unknown> = {
  '/api/v1/auth/me': { user: owner },
  '/api/v1/events': [{ id: 'e1', title: 'Priya and Arun Wedding', event_date: null, status: 'shared', selection_limit: 200, photo_count: 4, created_at: '' }],
  '/api/v1/client/me': {
    client_name: 'Priya', studio_name: 'Lens and Light',
    event: { title: 'Wedding', selection_limit: 2, expires_at: null, submitted_at: null },
    photo_count: 2, selected: 1, albums: [{ id: 'a1', name: 'Reception' }],
    cover_url: 'data:,', branding: { logo_url: 'data:,', accent_color: '#8A1C3B' },
  },
  '/api/v1/studio/branding': { studio_name: 'Lens and Light', logo_url: null, accent_color: '#8A1C3B', allowed: true },
  '/api/v1/client/photos': {
    count: 2, next_page: null,
    results: [
      { id: 'p1', width: 1600, height: 1067, thumb_url: 'data:,', preview_url: 'data:,', selected: true, note: 'Cover' },
      { id: 'p2', width: 1600, height: 1067, thumb_url: 'data:,', preview_url: 'data:,', selected: false, note: '' },
    ],
  },
  '/api/v1/billing': {
    state: 'trial', can_work: true, message: 'Free trial', until: null, plan: 'Free trial', status: 'trialing',
    plan_code: null, cancel_at_period_end: false,
    limits: { max_active_events: 1, max_photos_per_event: 5000, max_staff: 2 },
    usage: { active_events: 1, staff: 1 },
    plans: [{ code: 'studio', name: 'Studio', price_inr: 2499, max_active_events: 20, max_photos_per_event: 8000, max_staff: 3, available: false }],
    payments_configured: false,
  },
};

beforeEach(() => {
  vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} });
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const path = url.split('?')[0];
    return new Response(JSON.stringify(responses[path] ?? {}), { status: 200, headers: { 'Content-Type': 'application/json' } });
  }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

async function violations(container: HTMLElement) {
  const result = await axe.run(container, {
    runOnly: ['wcag2a', 'wcag2aa'],
    rules: { 'color-contrast': { enabled: false } },
  });
  return result.violations.map((v) => `${v.id}: ${v.help} (${v.nodes.map((n) => n.target.join(' ')).join(', ')})`);
}

function page(element: ReactNode, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <Routes>
          <Route path="*" element={element} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe('accessibility', () => {
  it.each([
    ['login', <LoginPage />],
    ['sign-up', <SignupPage />],
    ['forgot password', <ForgotPasswordPage />],
    ['reset password', <ResetPasswordPage />],
    ['client gallery login', <ClientLoginPage />],
  ])('%s screen has no violations', async (_name, element) => {
    const { container } = page(element);
    expect(await violations(container)).toEqual([]);
  });

  it('events screen has no violations', async () => {
    const { container } = page(<EventsPage />);
    await screen.findByText('Priya and Arun Wedding');
    expect(await violations(container)).toEqual([]);
  });

  it('billing screen has no violations', async () => {
    const { container } = page(<BillingPage />);
    await screen.findByText('Studio');
    expect(await violations(container)).toEqual([]);
  });

  it('branding screen has no violations', async () => {
    const { container } = page(<ThemePage />);
    await screen.findByText('What clients see');
    expect(await violations(container)).toEqual([]);
  });

  it('client gallery has no violations', async () => {
    const { container } = page(<GalleryPage />);
    await waitFor(() => expect(container.querySelectorAll('.gallery-grid li').length).toBe(2));
    expect(await violations(container)).toEqual([]);
  });
});

/**
 * Helpers for tests that run the real app against a fake server: `mockApi` answers
 * /api/v1 requests from a table and records them, `renderApp` mounts the whole app at a path.
 */
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router';
import { afterEach, beforeEach, vi } from 'vitest';
import App from '../App';
import { AuthProvider } from '../auth/AuthContext';

export interface Call {
  method: string;
  path: string;
  query: string;
  body: unknown;
}

type Handler = unknown | ((call: Call) => unknown);

export const reply = (status: number, body?: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

/** Routes are keyed "METHOD /api/v1/path". A function gets the call and returns the body or a Response. */
export function mockApi(routes: Record<string, Handler>) {
  const calls: Call[] = [];
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const [rawPath, query = ''] = String(input).split('?');
      const path = rawPath.replace(/^https?:\/\/[^/]+/, '');
      const method = (init.method ?? 'GET').toUpperCase();
      let body: unknown = init.body;
      if (typeof body === 'string') {
        try {
          body = JSON.parse(body);
        } catch {
          /* keep the text */
        }
      }
      const call: Call = { method, path, query, body };
      calls.push(call);
      const handler = routes[`${method} ${path}`];
      if (handler === undefined) return reply(404, { detail: `No mock for ${method} ${path}` });
      const result = typeof handler === 'function' ? (handler as (c: Call) => unknown)(call) : handler;
      return result instanceof Response ? result : reply(200, result);
    }),
  );
  return calls;
}

export function callsTo(calls: Call[], method: string, path: string) {
  return calls.filter((c) => c.method === method && c.path === path);
}

/** Browser features jsdom lacks, a CSRF cookie so no extra request is made, and clean-up. */
export function installBrowserMocks() {
  beforeEach(() => {
    vi.stubGlobal('IntersectionObserver', class { observe() {} disconnect() {} });
    document.cookie = 'csrftoken=test-token';
    window.scrollTo = vi.fn();
    Element.prototype.scrollIntoView = vi.fn();
  });
  afterEach(async () => {
    cleanup();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    // jsdom keeps one history for every test: let a closed viewer take its Back step now,
    // so it cannot land in the next test.
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

export function renderApp(path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

export function typeInto(label: string | RegExp, value: string) {
  fireEvent.change(screen.getByLabelText(label), { target: { value } });
}

export function press(name: string | RegExp) {
  fireEvent.click(screen.getByRole('button', { name }));
}

export const billing = {
  state: 'active', can_work: true, gallery_open: true, message: '', until: null, plan: 'Studio',
};

export const owner = {
  id: 'u1', email: 'owner@lens.test', full_name: 'Owner One', role: 'owner', email_verified: true,
  studio: { id: 's1', name: 'Lens and Light', slug: 'lens' }, billing,
};

export const staff = { ...owner, id: 'u2', email: 'staff@lens.test', full_name: 'Staff One', role: 'staff' };

/** `me` answers: logged out until a login or signup call flips `session.user`. */
export function session(user: unknown = null) {
  const state = { user };
  return {
    state,
    routes: {
      'GET /api/v1/auth/me': () => (state.user ? { user: state.user } : reply(401, { detail: 'Not logged in.' })),
      'POST /api/v1/auth/logout': () => {
        state.user = null;
        return reply(204);
      },
    } as Record<string, Handler>,
  };
}

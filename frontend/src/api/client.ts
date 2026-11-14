/**
 * API client for the Django backend. Uses the session cookie and sends the CSRF token
 * on every request that changes data, as Django requires.
 */

export type FieldErrors = Record<string, string[]>;

export class ApiError extends Error {
  status: number;
  fields: FieldErrors;

  constructor(status: number, data: unknown) {
    const body = (data ?? {}) as Record<string, unknown>;
    const detail = typeof body.detail === 'string' ? body.detail : undefined;
    super(detail ?? (status === 429 ? 'Too many attempts. Wait a minute and try again.' : `Request failed (${status})`));
    this.status = status;
    this.fields = {};
    for (const [key, value] of Object.entries(body)) {
      if (key !== 'detail' && Array.isArray(value)) this.fields[key] = value.map(String);
    }
    const nonField = this.fields.non_field_errors;
    if (nonField?.length && !detail) this.message = nonField.join(' ');
  }
}

let csrfReady: Promise<void> | null = null;

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}

async function ensureCsrf(): Promise<void> {
  if (csrfToken()) return;
  csrfReady ??= fetch('/api/v1/auth/csrf', { credentials: 'same-origin' }).then(() => undefined);
  await csrfReady;
}

export async function api<T = unknown>(path: string, options: { method?: string; body?: unknown } = {}): Promise<T> {
  const method = options.method ?? 'GET';
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (method !== 'GET') {
    await ensureCsrf();
    headers['X-CSRFToken'] = csrfToken();
  }
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  const response = await fetch(`/api/v1${path}`, {
    method,
    headers,
    credentials: 'same-origin',
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  if (response.status === 204) return undefined as T;
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, data);
  return data as T;
}

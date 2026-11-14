// @vitest-environment jsdom
/** The Branding screen: logo, accent colour, plan lock and live preview. */
import { fireEvent, screen, waitFor } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { callsTo, mockApi, owner, press, renderApp, reply, session, staff, typeInto, installBrowserMocks } from './harness';

installBrowserMocks();

const base = { studio_name: 'Lens and Light', logo_url: null, accent_color: null, allowed: true };

function routes(initial: Record<string, unknown> = {}, extra: Record<string, unknown> = {}, user = owner) {
  const state = { ...base, ...initial };
  return {
    state,
    routes: {
      ...session(user).routes,
      'GET /api/v1/studio/branding': () => state,
      ...extra,
    },
  };
}

const saveButton = () => screen.getByRole('button', { name: 'Save colour' }) as HTMLButtonElement;

describe('accent colour', () => {
  it('starts with the PickSnap teal and nothing to save', async () => {
    mockApi(routes().routes);
    renderApp('/branding');
    expect(await screen.findByRole('heading', { name: 'Branding' })).toBeTruthy();
    expect((screen.getByLabelText('Colour code') as HTMLInputElement).value).toBe('#0E5E5A');
    expect(saveButton().disabled).toBe(true);
    expect(screen.getByText(/Readable on white/)).toBeTruthy();
  });

  it('a swatch fills the colour code and saves', async () => {
    const r = routes({}, {
      'PATCH /api/v1/studio/branding': (call: { body: { accent_color: string } }) => ({ ...base, accent_color: call.body.accent_color }),
    });
    const calls = mockApi(r.routes);
    renderApp('/branding');
    await screen.findByRole('heading', { name: 'Branding' });
    fireEvent.click(screen.getByRole('button', { name: 'Maroon' }));
    expect((screen.getByLabelText('Colour code') as HTMLInputElement).value).toBe('#8A1C3B');
    expect(screen.getByRole('button', { name: 'Maroon' }).getAttribute('aria-pressed')).toBe('true');
    fireEvent.click(saveButton());
    expect((await screen.findByRole('status')).textContent).toBe('Colour saved.');
    expect(callsTo(calls, 'PATCH', '/api/v1/studio/branding')[0].body).toEqual({ accent_color: '#8A1C3B' });
    expect(screen.getByRole('button', { name: /Reset to PickSnap teal/ })).toBeTruthy();
  });

  it('refuses a colour that is too light, with its contrast, and will not send it', async () => {
    const calls = mockApi(routes().routes);
    renderApp('/branding');
    await screen.findByRole('heading', { name: 'Branding' });
    typeInto('Colour code', '#FFD700');
    expect(saveButton().disabled).toBe(true);
    expect(screen.getByText(/Too light for text on white/).textContent).toContain('needs 4.5');
    expect(screen.getByLabelText('Colour code').getAttribute('aria-invalid')).toBe('true');
    expect(callsTo(calls, 'PATCH', '/api/v1/studio/branding')).toHaveLength(0);
  });

  it('refuses something that is not a colour code', async () => {
    mockApi(routes().routes);
    renderApp('/branding');
    await screen.findByRole('heading', { name: 'Branding' });
    typeInto('Colour code', 'maroon');
    expect(saveButton().disabled).toBe(true);
    expect(screen.getByText('Use a colour code like #8A1C3B.')).toBeTruthy();
  });

  it('resets to the standard teal', async () => {
    const r = routes({ accent_color: '#8A1C3B' }, {
      'PATCH /api/v1/studio/branding': () => ({ ...base, accent_color: null }),
    });
    const calls = mockApi(r.routes);
    renderApp('/branding');
    await screen.findByRole('heading', { name: 'Branding' });
    expect((screen.getByLabelText('Colour code') as HTMLInputElement).value).toBe('#8A1C3B');
    press(/Reset to PickSnap teal/);
    expect((await screen.findByRole('status')).textContent).toBe('Colour reset to PickSnap teal.');
    expect(callsTo(calls, 'PATCH', '/api/v1/studio/branding')[0].body).toEqual({ accent_color: null });
    expect((screen.getByLabelText('Colour code') as HTMLInputElement).value).toBe('#0E5E5A');
  });

  it('shows the server message when saving fails', async () => {
    mockApi(routes({}, {
      'PATCH /api/v1/studio/branding': reply(400, { accent_color: ['This colour is too light for text on white. Pick a darker shade.'] }),
    }).routes);
    renderApp('/branding');
    await screen.findByRole('heading', { name: 'Branding' });
    fireEvent.click(screen.getByRole('button', { name: 'Navy' }));
    fireEvent.click(saveButton());
    expect((await screen.findByRole('alert')).textContent).toContain('too light');
  });
});

describe('logo', () => {
  it('shows the current logo with a way to remove it', async () => {
    mockApi(routes({ logo_url: 'data:image/webp;base64,AAAA' }).routes);
    renderApp('/branding');
    const logos = await screen.findAllByAltText('Lens and Light logo');
    expect(logos).toHaveLength(1);
    expect(screen.getByRole('button', { name: 'Change logo' })).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Remove' })).toBeTruthy();
  });

  it('removes the logo', async () => {
    const r = routes({ logo_url: 'data:image/webp;base64,AAAA' }, { 'DELETE /api/v1/studio/branding/logo': reply(204) });
    const calls = mockApi(r.routes);
    renderApp('/branding');
    await screen.findByAltText('Lens and Light logo');
    press('Remove');
    expect((await screen.findByRole('status')).textContent).toBe('Logo removed.');
    expect(callsTo(calls, 'DELETE', '/api/v1/studio/branding/logo')).toHaveLength(1);
    expect(screen.queryByAltText('Lens and Light logo')).toBeNull();
    expect(screen.getByText('No logo yet')).toBeTruthy();
  });

  it('says so when the chosen file is not an image', async () => {
    mockApi(routes().routes);
    renderApp('/branding');
    await screen.findByRole('heading', { name: 'Branding' });
    // jsdom cannot decode images, so any file fails the same way a bad file would in a browser.
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [new File(['not an image'], 'logo.png', { type: 'image/png' })] } });
    expect((await screen.findByRole('alert')).textContent).toMatch(/could not be read|cannot resize|cannot make WebP/);
  });
});

describe('who can use it', () => {
  it('is locked, with a way to upgrade, when the plan has no branding', async () => {
    mockApi(routes({ allowed: false }).routes);
    renderApp('/branding');
    expect(await screen.findByText(/does not include studio branding/)).toBeTruthy();
    expect(screen.getByRole('link', { name: 'Choose a bigger plan' }).getAttribute('href')).toBe('/billing');
    expect((screen.getByRole('button', { name: 'Upload logo' }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByLabelText('Colour code') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Maroon' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('is for the owner only', async () => {
    mockApi(routes({}, {}, staff as typeof owner).routes);
    renderApp('/branding');
    expect((await screen.findByRole('alert')).textContent).toBe('Only the studio owner can change branding.');
  });

  it('shows the preview in the chosen colour using the studio name when there is no logo', async () => {
    mockApi(routes({ accent_color: '#8A1C3B' }).routes);
    renderApp('/branding');
    await screen.findByRole('heading', { name: 'What clients see' });
    const preview = document.querySelector('.brand-preview') as HTMLElement;
    expect(preview.className).toContain('branded');
    expect(preview.style.getPropertyValue('--brand-accent')).toBe('#8A1C3B');
    expect(preview.textContent).toContain('Lens and Light');
    expect(preview.textContent).toContain('Made with PickSnap');
  });

  it('the preview does not follow a colour that cannot be saved', async () => {
    mockApi(routes({ accent_color: '#8A1C3B' }).routes);
    renderApp('/branding');
    await screen.findByRole('heading', { name: 'What clients see' });
    typeInto('Colour code', '#FFD700');
    const preview = document.querySelector('.brand-preview') as HTMLElement;
    await waitFor(() => expect(preview.style.getPropertyValue('--brand-accent')).toBe('#8A1C3B'));
  });
});

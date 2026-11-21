import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Field, FormMessage, useSubmit } from '../components/Form';
import { familyInvitationText, formatPhone, invitationText, whatsappLink } from '../share/whatsapp';
import type { EventDetail } from './EventPage';

interface ClientLogin {
  id: string;
  client_name: string;
  email: string;
  phone: string;
  username: string;
  is_active: boolean;
  last_login_at: string | null;
  password?: string;
  role?: 'main' | 'helper';
  invited_by?: string | null;
}

interface ProgressInfo {
  status: string;
  selection_limit: number | null;
  selected: number;
  submitted_at: string | null;
  last_client_login: string | null;
}

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' }) : 'never';

/** Share the event with a client, see their progress, and manage their login. */
export function SharePanel({ event, onChanged }: { event: EventDetail; onChanged: () => void }) {
  const [clients, setClients] = useState<ClientLogin[]>([]);
  const [progress, setProgress] = useState<ProgressInfo | null>(null);
  const { user } = useAuth();
  const [form, setForm] = useState({ client_name: '', email: '', phone: '' });
  const [revealed, setRevealed] = useState<ClientLogin | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    const [c, p] = await Promise.all([
      api<ClientLogin[]>(`/events/${event.id}/clients`),
      api<ProgressInfo>(`/events/${event.id}/progress`),
    ]);
    setClients(c);
    setProgress(p);
  }, [event.id]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 30000);
    return () => window.clearInterval(timer);
  }, [load]);

  // Once the main client has a login, new logins are for family helping them.
  const main = clients.find((c) => c.role !== 'helper' && c.is_active) ?? null;
  const share = useSubmit(async () => {
    const created = await api<ClientLogin>(`/events/${event.id}/clients`, {
      method: 'POST',
      body: { ...form, role: main ? 'helper' : 'main' },
    });
    setRevealed(created);
    setForm({ client_name: '', email: '', phone: '' });
    await load();
    onChanged();
  });

  async function act(client: ClientLogin, action: 'reset-password' | 'revoke') {
    const question = action === 'revoke'
      ? `Turn off ${client.client_name}'s access? They will be logged out.`
      : `Make a new password for ${client.client_name}? ${client.email ? `We will email it to ${client.email}; ` : ''}you can also send it on WhatsApp.`;
    if (!window.confirm(question)) return;
    const updated = await api<ClientLogin>(`/client-access/${client.id}/${action}`, { method: 'POST' });
    if (updated.password) setRevealed(updated);
    await load();
  }

  async function reopen() {
    if (!window.confirm('Let the client change the submitted selection?')) return;
    await api(`/events/${event.id}/reopen`, { method: 'POST' });
    await load();
    onChanged();
  }

  const galleryLink = (username: string) => `${window.location.origin}/gallery/login?u=${username}`;

  const message = (c: ClientLogin) =>
    c.role === 'helper'
      ? familyInvitationText({
          helperName: c.client_name,
          mainName: c.invited_by ?? main?.client_name ?? '',
          eventTitle: event.title,
          galleryUrl: galleryLink(c.username),
          username: c.username,
          password: c.password ?? '',
          studioName: user?.studio?.name ?? '',
        })
      : invitationText({
      clientName: c.client_name,
      studioName: user?.studio?.name ?? '',
      eventTitle: event.title,
      galleryUrl: galleryLink(c.username),
      username: c.username,
      password: c.password ?? '',
      selectionLimit: event.selection_limit,
    });

  async function copy(c: ClientLogin) {
    await navigator.clipboard.writeText(message(c)).catch(() => undefined);
    setCopied(true);
  }

  const canShare = event.photo_count > 0 && event.status !== 'archived';
  // WhatsApp only until the server has an email service (see CLIENT_EMAIL_SHARING).
  const emailSharing = user?.sharing?.client_email !== false;

  return (
    <div className="panel">
      <h2>Client</h2>

      {progress && clients.length > 0 && (
        <div className="progress-box">
          <p className="big-number">
            {progress.selected}
            {progress.selection_limit ? <span> of {progress.selection_limit}</span> : null} selected
          </p>
          <p className="muted">
            {progress.submitted_at ? `Submitted ${when(progress.submitted_at)}` : 'Not submitted yet'}
            {' · '}Last visit {when(progress.last_client_login)}
          </p>
          {progress.status === 'submitted' && (
            <button className="link" onClick={reopen}>Let the client make changes</button>
          )}
        </div>
      )}

      {revealed?.password && (
        <div className="credentials" role="status">
          <p>
            <strong>Login for {revealed.client_name}</strong>
            {revealed.email ? ` (emailed to ${revealed.email})` : ''}
          </p>
          <dl>
            <dt>Gallery</dt><dd><code>{galleryLink(revealed.username)}</code></dd>
            <dt>Username</dt><dd><code>{revealed.username}</code></dd>
            <dt>Password</dt><dd><code>{revealed.password}</code></dd>
          </dl>
          <p className="muted">
            The password is shown only now.{' '}
            {revealed.phone
              ? `Send it on WhatsApp to ${formatPhone(revealed.phone)}.`
              : 'Send it on WhatsApp and choose the contact there.'}
          </p>
          <div className="actions">
            <a className="button whatsapp" href={whatsappLink(message(revealed), revealed.phone)} target="_blank" rel="noopener noreferrer">
              Send on WhatsApp
            </a>
            <button className="secondary" onClick={() => copy(revealed)}>{copied ? 'Copied' : 'Copy message'}</button>
            <button className="link" onClick={() => { setRevealed(null); setCopied(false); }}>Hide</button>
          </div>
        </div>
      )}

      {clients.length > 0 && (
        <ul className="plain-list">
          {clients.map((c) => (
            <li key={c.id}>
              <strong>{c.client_name}</strong>{' '}
              <span className="muted">
                · {c.role === 'helper' ? `Family, helping ${c.invited_by ?? 'the client'}` : 'Main client'} · {c.username}{c.phone ? ` · ${formatPhone(c.phone)}` : ''}{c.is_active ? '' : ' · access off'}
              </span>
              <div className="row-actions">
                <button className="link" onClick={() => act(c, 'reset-password')}>New password</button>
                {c.is_active && <button className="link danger" onClick={() => act(c, 'revoke')}>Turn off access</button>}
              </div>
            </li>
          ))}
        </ul>
      )}

      {canShare ? (
        <form onSubmit={share.onSubmit} noValidate>
          <p className="muted">
            {main
              ? `Add a family member to help ${main.client_name} choose. They get their own login; only ${main.client_name} can send the final selection. ${main.client_name} can also invite family from the gallery.`
              : 'Send the client a login to choose their photos.'}
            {emailSharing ? '' : ' You send it on WhatsApp.'}
          </p>
          <FormMessage error={share.error} />
          <Field label={main ? 'Family member name' : 'Client name'} name="client_name" required errors={share.fields}
            value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} />
          <Field label={main ? 'Their WhatsApp number' : 'Client WhatsApp number'} name="phone" type="tel" autoComplete="tel" inputMode="tel" errors={share.fields}
            required={!emailSharing}
            hint="For example 98765 43210. Add + and the country code for numbers outside India."
            value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />
          {emailSharing && (
            <Field label="Client email (optional)" name="email" type="email" errors={share.fields}
              hint="We email the login too when you add one."
              value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          )}
          <button type="submit" disabled={share.busy}>
            {share.busy ? 'Sharing…' : main ? 'Add family member' : 'Share with client'}
          </button>
        </form>
      ) : (
        <p className="muted">Upload photos before sharing this event.</p>
      )}
    </div>
  );
}

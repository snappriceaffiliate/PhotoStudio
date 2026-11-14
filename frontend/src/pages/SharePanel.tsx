import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { Field, FormMessage, useSubmit } from '../components/Form';
import type { EventDetail } from './EventPage';

interface ClientLogin {
  id: string;
  client_name: string;
  email: string;
  username: string;
  is_active: boolean;
  last_login_at: string | null;
  password?: string;
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
  const [form, setForm] = useState({ client_name: '', email: '' });
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

  const share = useSubmit(async () => {
    const created = await api<ClientLogin>(`/events/${event.id}/clients`, { method: 'POST', body: form });
    setRevealed(created);
    setForm({ client_name: '', email: '' });
    await load();
    onChanged();
  });

  async function act(client: ClientLogin, action: 'reset-password' | 'revoke') {
    const question = action === 'revoke'
      ? `Turn off ${client.client_name}'s access? They will be logged out.`
      : `Make a new password for ${client.client_name}? We will email it to ${client.email}.`;
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

  async function copy(c: ClientLogin) {
    const text = `Gallery: ${galleryLink(c.username)}\nUsername: ${c.username}\nPassword: ${c.password}`;
    await navigator.clipboard.writeText(text).catch(() => undefined);
    setCopied(true);
  }

  const canShare = event.photo_count > 0 && event.status !== 'archived';

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
          <p><strong>Login for {revealed.client_name}</strong> (emailed to {revealed.email})</p>
          <dl>
            <dt>Gallery</dt><dd><code>{galleryLink(revealed.username)}</code></dd>
            <dt>Username</dt><dd><code>{revealed.username}</code></dd>
            <dt>Password</dt><dd><code>{revealed.password}</code></dd>
          </dl>
          <p className="muted">The password is shown only now. Copy it if you also want to send it by WhatsApp.</p>
          <div className="actions">
            <button className="secondary" onClick={() => copy(revealed)}>{copied ? 'Copied' : 'Copy login details'}</button>
            <button className="link" onClick={() => { setRevealed(null); setCopied(false); }}>Hide</button>
          </div>
        </div>
      )}

      {clients.length > 0 && (
        <ul className="plain-list">
          {clients.map((c) => (
            <li key={c.id}>
              <strong>{c.client_name}</strong> <span className="muted">· {c.username}{c.is_active ? '' : ' · access off'}</span>
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
          <p className="muted">{clients.length ? 'Add another login, for example for family.' : 'Send the client a login to choose their photos.'}</p>
          <FormMessage error={share.error} />
          <Field label="Client name" name="client_name" required errors={share.fields}
            value={form.client_name} onChange={(e) => setForm({ ...form, client_name: e.target.value })} />
          <Field label="Client email" name="email" type="email" required errors={share.fields}
            value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <button type="submit" disabled={share.busy}>{share.busy ? 'Sharing…' : 'Share with client'}</button>
        </form>
      ) : (
        <p className="muted">Upload photos before sharing this event.</p>
      )}
    </div>
  );
}

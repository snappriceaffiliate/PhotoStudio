import { useCallback, useEffect, useState } from 'react';
import { api } from '../api/client';
import { Field, FormMessage, useSubmit } from '../components/Form';
import { familyInvitationText, formatPhone, whatsappLink } from '../share/whatsapp';

export interface Helper {
  id: string;
  client_name: string;
  phone: string;
  username: string;
  is_active: boolean;
  last_login_at: string | null;
  chosen: number;
  password?: string;
}

export interface Family {
  you: { client_name: string; chosen: number };
  helpers: Helper[];
  max_helpers: number;
}

export function useFamily(enabled: boolean) {
  const [family, setFamily] = useState<Family | null>(null);
  const load = useCallback(async () => {
    if (!enabled) return;
    setFamily(await api<Family>('/client/family').catch(() => null));
  }, [enabled]);
  useEffect(() => {
    void load();
  }, [load]);
  return { family, reload: load };
}

/** The main client invites relatives to help choose, each with their own login. */
export function FamilyPanel({ eventTitle, studioName, onClose }: { eventTitle: string; studioName: string; onClose: () => void }) {
  const { family, reload } = useFamily(true);
  const [form, setForm] = useState({ client_name: '', phone: '' });
  const [invited, setInvited] = useState<Helper | null>(null);
  const [copied, setCopied] = useState(false);

  const submit = useSubmit(async () => {
    const helper = await api<Helper>('/client/family', { method: 'POST', body: form });
    setInvited(helper);
    setCopied(false);
    setForm({ client_name: '', phone: '' });
    await reload();
  });

  const message = (h: Helper) =>
    familyInvitationText({
      helperName: h.client_name,
      mainName: family?.you.client_name ?? '',
      eventTitle,
      galleryUrl: `${window.location.origin}/gallery/login?u=${h.username}`,
      username: h.username,
      password: h.password ?? '',
      studioName,
    });

  async function turnOff(h: Helper) {
    if (!window.confirm(`Turn off ${h.client_name}'s login? Photos they chose stay chosen.`)) return;
    await api(`/client/family/${h.id}/turn-off`, { method: 'POST' });
    await reload();
  }

  const active = family?.helpers.filter((h) => h.is_active) ?? [];
  const full = family ? active.length >= family.max_helpers : false;

  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="family-title">
      <div className="dialog family-dialog">
        <h2 id="family-title">Invite family to help</h2>
        <p className="muted">
          Each person gets their own login. They can choose photos and you will see who chose what. Only you can send the
          final selection.
        </p>

        {invited?.password ? (
          <div className="credentials" role="status">
            <p><strong>Login for {invited.client_name} is ready.</strong> Send it now; the password is shown only once.</p>
            <div className="actions">
              <a className="button whatsapp" href={whatsappLink(message(invited), invited.phone)} target="_blank" rel="noopener noreferrer">
                {invited.phone ? `Send on WhatsApp to ${formatPhone(invited.phone)}` : 'Send on WhatsApp'}
              </a>
              <button type="button" className="secondary" onClick={async () => {
                await navigator.clipboard.writeText(message(invited)).catch(() => undefined);
                setCopied(true);
              }}>
                {copied ? 'Copied' : 'Copy message'}
              </button>
              <button type="button" className="link" onClick={() => setInvited(null)}>Invite someone else</button>
            </div>
          </div>
        ) : full ? (
          <p className="muted">You have invited {family?.max_helpers} people, the most allowed.</p>
        ) : (
          <form onSubmit={submit.onSubmit} noValidate>
            <FormMessage error={submit.error} />
            <div className="row">
              <Field label="Name" name="client_name" value={form.client_name} errors={submit.fields} required maxLength={150}
                onChange={(e) => setForm({ ...form, client_name: e.target.value })} placeholder="Ravi Uncle" />
              <Field label="WhatsApp number (optional)" name="phone" type="tel" value={form.phone} errors={submit.fields}
                onChange={(e) => setForm({ ...form, phone: e.target.value })} placeholder="98765 43210" />
            </div>
            <div className="actions">
              <button type="submit" disabled={submit.busy || !form.client_name.trim()}>
                {submit.busy ? 'Creating…' : 'Create their login'}
              </button>
            </div>
          </form>
        )}

        {family && family.helpers.length > 0 && (
          <>
            <h3 className="family-heading">Helping you</h3>
            <ul className="family-list">
              <li><span>You</span><span className="muted">{family.you.chosen} chosen</span></li>
              {family.helpers.map((h) => (
                <li key={h.id}>
                  <span>{h.client_name}{!h.is_active && <span className="muted"> · turned off</span>}</span>
                  <span className="muted">{h.chosen} chosen</span>
                  {h.is_active && <button type="button" className="link" onClick={() => turnOff(h)}>Turn off</button>}
                </li>
              ))}
            </ul>
          </>
        )}

        <div className="actions">
          <button type="button" className="secondary" onClick={onClose} autoFocus>Done</button>
        </div>
      </div>
    </div>
  );
}

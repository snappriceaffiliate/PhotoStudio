import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { FormMessage } from '../components/Form';
import { formatPhone, reminderText, whatsappLink } from '../share/whatsapp';

export interface DueReminder {
  id: string;
  client_name: string;
  phone: string;
  username: string;
  reason: 'first' | 'again' | 'expiring';
  shared_at: string;
  reminder_count: number;
  last_reminded_at: string | null;
  selected: number;
  event: { id: string; title: string; selection_limit: number | null; expires_at: string | null };
}

interface DueList {
  count: number;
  max_reminders: number;
  results: DueReminder[];
}

const daysSince = (iso: string) => Math.max(0, Math.floor((Date.now() - new Date(iso).getTime()) / 86400000));

/** Clients who have not submitted, with a one-tap WhatsApp reminder for each. */
export function RemindersPage() {
  const { user } = useAuth();
  const [data, setData] = useState<DueList | null>(null);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [copied, setCopied] = useState('');

  const load = useCallback(() => {
    api<DueList>('/reminders').then(setData).catch(() => setError('Could not load the reminders.'));
  }, []);
  useEffect(load, [load]);

  const message = (r: DueReminder) =>
    reminderText({
      clientName: r.client_name,
      studioName: user?.studio?.name ?? '',
      eventTitle: r.event.title,
      galleryUrl: `${window.location.origin}/gallery/login?u=${r.username}`,
      username: r.username,
      selected: r.selected,
      selectionLimit: r.event.selection_limit,
      closesOn: r.reason === 'expiring' ? r.event.expires_at : null,
    });

  async function markSent(r: DueReminder, done: string) {
    try {
      await api(`/reminders/${r.id}/sent`, { method: 'POST' });
      setNotice(done);
      load();
    } catch {
      setError('Could not save that. Try again.');
    }
  }

  async function copy(r: DueReminder) {
    await navigator.clipboard.writeText(message(r)).catch(() => undefined);
    setCopied(r.id);
  }

  const max = data?.max_reminders ?? 3;
  const why = (r: DueReminder) =>
    r.reason === 'expiring'
      ? 'Gallery closes tomorrow'
      : r.reminder_count === 0
        ? `Shared ${daysSince(r.shared_at)} days ago`
        : `Reminder ${r.reminder_count + 1} of ${max} · last one ${daysSince(r.last_reminded_at!)} days ago`;

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Reminders</h1>
          <p className="muted">
            Clients who have not submitted their selection. A reminder is suggested 2 days after sharing, then every
            3 days (up to {max}), and the day before a gallery closes. We also email you each morning when someone is due.
          </p>
        </div>
      </div>
      <FormMessage error={error} success={notice} />
      {data === null && !error && <p className="muted">Loading…</p>}
      {data && data.count === 0 && (
        <div className="empty">
          <h2>No reminders due</h2>
          <p>Every client has either submitted or was reminded recently.</p>
        </div>
      )}
      <ul className="reminder-list">
        {data?.results.map((r) => (
          <li key={r.id} className="panel reminder">
            <div>
              <h2>{r.client_name}</h2>
              <p className="muted">
                <Link to={`/events/${r.event.id}`}>{r.event.title}</Link> · {why(r)} ·{' '}
                {r.selected ? `${r.selected}${r.event.selection_limit ? ` of ${r.event.selection_limit}` : ''} chosen so far` : 'nothing chosen yet'}
              </p>
            </div>
            <div className="actions">
              <a
                className="button whatsapp"
                href={whatsappLink(message(r), r.phone)}
                target="_blank"
                rel="noopener noreferrer"
                onClick={() => markSent(r, `Reminder for ${r.client_name} marked as sent.`)}
              >
                {r.phone ? `Send on WhatsApp to ${formatPhone(r.phone)}` : 'Send on WhatsApp'}
              </a>
              <button type="button" className="secondary" onClick={() => copy(r)}>
                {copied === r.id ? 'Copied' : 'Copy message'}
              </button>
              <button type="button" className="link" onClick={() => markSent(r, `Skipped this reminder for ${r.client_name}.`)}>
                Skip this one
              </button>
            </div>
          </li>
        ))}
      </ul>
    </>
  );
}

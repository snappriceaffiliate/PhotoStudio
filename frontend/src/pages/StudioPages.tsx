import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Field, FormMessage, useSubmit } from '../components/Form';
import { PhotosIcon } from '../components/Brand';
import { STATUS_LABELS } from './EventPage';
import { deleteEventAfterConfirm } from './eventActions';

interface EventItem {
  id: string;
  title: string;
  event_date: string | null;
  status: string;
  selection_limit: number | null;
  photo_count: number;
  selected_count: number;
  cover_url: string | null;
  created_at: string;
}

interface StaffMember {
  id: string;
  email: string;
  full_name: string;
  role: 'owner' | 'staff';
  is_active: boolean;
  has_password: boolean;
}

function useList<T>(path: string) {
  const [items, setItems] = useState<T[] | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    api<T[]>(path)
      .then(setItems)
      .catch(() => setError('Could not load this list. Refresh to try again.'));
  }, [path]);
  useEffect(load, [load]);
  return { items, error, reload: load };
}

const FILTERS: { key: string; label: string; test: (e: EventItem) => boolean }[] = [
  { key: 'all', label: 'All', test: () => true },
  { key: 'active', label: 'Active', test: (e) => ['uploading', 'shared', 'submitted'].includes(e.status) },
  { key: 'draft', label: 'Draft', test: (e) => e.status === 'draft' },
  { key: 'archived', label: 'Archived', test: (e) => e.status === 'archived' },
];

export function EventsPage() {
  const { user } = useAuth();
  const { items, error, reload } = useList<EventItem>('/events');
  const [filter, setFilter] = useState('all');
  const [deleteError, setDeleteError] = useState('');
  const [remindersDue, setRemindersDue] = useState(0);
  useEffect(() => {
    api<{ count: number }>('/reminders').then((r) => setRemindersDue(r.count)).catch(() => undefined);
  }, []);
  const current = FILTERS.find((f) => f.key === filter) ?? FILTERS[0];
  const shown = items?.filter(current.test) ?? null;

  async function remove(event: EventItem) {
    setDeleteError('');
    try {
      if (await deleteEventAfterConfirm(event)) reload();
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Could not delete the event.');
    }
  }
  const [form, setForm] = useState({ title: '', event_date: '', selection_limit: '' });
  const [open, setOpen] = useState(false);
  const submit = useSubmit(async () => {
    await api('/events', {
      method: 'POST',
      body: {
        title: form.title,
        event_date: form.event_date || null,
        selection_limit: form.selection_limit ? Number(form.selection_limit) : null,
      },
    });
    setForm({ title: '', event_date: '', selection_limit: '' });
    setOpen(false);
    reload();
  });

  return (
    <>
      <div className="page-header">
        <h1>Events</h1>
        {!open && <button onClick={() => setOpen(true)}>New event</button>}
      </div>

      {remindersDue > 0 && (
        <div className="reminder-banner" role="status">
          <span>
            {remindersDue} {remindersDue === 1 ? 'client has' : 'clients have'} not chosen their photos yet.
          </span>
          <Link className="button secondary" to="/reminders">Send reminders</Link>
        </div>
      )}

      {open && (
        <form className="panel" onSubmit={submit.onSubmit} noValidate>
          <h2>New event</h2>
          <FormMessage error={submit.error} />
          <div className="row">
            <Field label="Event name" name="title" required placeholder="Priya and Arun Wedding" errors={submit.fields}
              value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
            <Field label="Event date" name="event_date" type="date" errors={submit.fields}
              value={form.event_date} onChange={(e) => setForm({ ...form, event_date: e.target.value })} />
            <Field label="Photos the client may select" name="selection_limit" type="number" min={1} errors={submit.fields}
              hint="Leave empty for no limit." value={form.selection_limit}
              onChange={(e) => setForm({ ...form, selection_limit: e.target.value })} />
          </div>
          <div className="actions">
            <button type="submit" disabled={submit.busy}>{submit.busy ? 'Creating…' : 'Create event'}</button>
            <button type="button" className="secondary" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </form>
      )}

      <FormMessage error={error || deleteError} />
      {items && items.length > 0 && (
        <div className="tabs filter-tabs" role="tablist" aria-label="Show events">
          {FILTERS.map((f) => (
            <button key={f.key} role="tab" aria-selected={filter === f.key} className={filter === f.key ? 'tab active' : 'tab'}
              onClick={() => setFilter(f.key)}>
              {f.label} <span className="count">{items.filter(f.test).length}</span>
            </button>
          ))}
        </div>
      )}
      {items === null && !error && <p className="muted">Loading events…</p>}
      {items?.length === 0 && (
        <div className="empty">
          <PhotosIcon size={48} />
          <h2>No events yet</h2>
          <p>Create an event for each shoot, then upload its folder of photos.</p>
        </div>
      )}
      {items && items.length > 0 && shown?.length === 0 && (
        <p className="muted">No {current.label.toLowerCase()} events.</p>
      )}
      {shown && shown.length > 0 && (
        <ul className="cards">
          {shown.map((e) => (
            <li key={e.id} className="card-item">
              <div className="card-cover">
                {e.cover_url ? <img src={e.cover_url} alt="" loading="lazy" /> : <PhotosIcon size={44} />}
              </div>
              <div className="card-body">
                <h3><Link to={`/events/${e.id}`} className="card-link">{e.title}</Link></h3>
                <p className="muted">
                  {e.event_date ? new Date(e.event_date).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : 'No date'}
                  {' · '}
                  {e.photo_count} photos
                </p>
                {e.selected_count > 0 && (
                  <>
                    <div className="meter" aria-hidden="true">
                      <span style={{ width: `${e.selection_limit ? Math.min(100, (e.selected_count / e.selection_limit) * 100) : 100}%` }} />
                    </div>
                    <p className="muted">
                      {e.selected_count}{e.selection_limit ? ` of ${e.selection_limit}` : ''} chosen by the client
                    </p>
                  </>
                )}
                <div className="card-foot">
                  <span className={`status status-${e.status}`}>{STATUS_LABELS[e.status] ?? e.status}</span>
                  {user?.role === 'owner' && (
                    <button type="button" className="link danger" onClick={() => remove(e)} aria-label={`Delete ${e.title}`}>Delete</button>
                  )}
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function StaffPage() {
  const { user } = useAuth();
  const { items, error, reload } = useList<StaffMember>('/staff');
  const [form, setForm] = useState({ full_name: '', email: '' });
  const [notice, setNotice] = useState('');
  const invite = useSubmit(async () => {
    await api('/staff', { method: 'POST', body: form });
    setNotice(`Invitation sent to ${form.email}.`);
    setForm({ full_name: '', email: '' });
    reload();
  });

  async function remove(member: StaffMember) {
    if (!window.confirm(`Remove ${member.full_name}? They will lose access straight away.`)) return;
    await api(`/staff/${member.id}`, { method: 'DELETE' });
    setNotice(`${member.full_name} no longer has access.`);
    reload();
  }

  const [turnOnError, setTurnOnError] = useState('');
  async function turnOn(member: StaffMember) {
    setTurnOnError('');
    try {
      await api(`/staff/${member.id}/turn-on`, { method: 'POST' });
      setNotice(`${member.full_name} has access again.`);
      reload();
    } catch (err) {
      setTurnOnError(err instanceof ApiError ? err.message : 'Could not turn them back on. Try again.');
    }
  }

  if (user?.role !== 'owner') return <FormMessage error="Only the studio owner can manage staff." />;

  return (
    <>
      <div className="page-header">
        <h1>Staff</h1>
      </div>
      <form className="panel" onSubmit={invite.onSubmit} noValidate>
        <h2>Add a staff member</h2>
        <p className="muted">They get an email with a link to choose a password. Staff can manage events but not billing or staff.</p>
        <FormMessage error={invite.error} success={notice} />
        <div className="row">
          <Field label="Name" name="full_name" required errors={invite.fields}
            value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          <Field label="Email" name="email" type="email" required errors={invite.fields}
            value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        </div>
        <div className="actions">
          <button type="submit" disabled={invite.busy}>{invite.busy ? 'Sending…' : 'Send invitation'}</button>
        </div>
      </form>

      <FormMessage error={error || turnOnError} />
      {items && (
        <div className="table-wrap">
          <table>
            <thead>
              <tr><th>Name</th><th>Email</th><th>Role</th><th>Status</th><th></th></tr>
            </thead>
            <tbody>
              {items.map((m) => (
                <tr key={m.id}>
                  <td>{m.full_name}</td>
                  <td>{m.email}</td>
                  <td>{m.role === 'owner' ? 'Owner' : 'Staff'}</td>
                  <td>{!m.is_active ? 'Removed' : m.has_password ? 'Active' : 'Invited'}</td>
                  <td>
                    {m.role === 'staff' && m.is_active && (
                      <button className="link danger" onClick={() => remove(m)}>Remove</button>
                    )}
                    {m.role === 'staff' && !m.is_active && (
                      <button className="link" onClick={() => turnOn(m)}>Turn back on</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  );
}

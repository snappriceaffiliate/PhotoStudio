import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Field, FormMessage, useSubmit } from '../components/Form';
import { PhotosIcon } from '../components/Brand';
import { STATUS_LABELS } from './EventPage';

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

export function EventsPage() {
  const { items, error, reload } = useList<EventItem>('/events');
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

      <FormMessage error={error} />
      {items === null && !error && <p className="muted">Loading events…</p>}
      {items?.length === 0 && (
        <div className="empty">
          <PhotosIcon size={48} />
          <h2>No events yet</h2>
          <p>Create an event for each shoot, then upload its folder of photos.</p>
        </div>
      )}
      {items && items.length > 0 && (
        <ul className="cards">
          {items.map((e) => (
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
                <span className={`status status-${e.status}`}>{STATUS_LABELS[e.status] ?? e.status}</span>
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

      <FormMessage error={error} />
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

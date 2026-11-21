import { useEffect, useState } from 'react';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { User } from '../auth/types';
import { Field, FormMessage, useSubmit } from '../components/Form';

interface Profile {
  name: string;
  phone: string;
  contact_email: string;
  address: string;
  city: string;
  pincode: string;
  website: string;
  instagram: string;
}

const EMPTY: Profile = { name: '', phone: '', contact_email: '', address: '', city: '', pincode: '', website: '', instagram: '' };

/** Shows a stored WhatsApp number (country code and digits) the way people write it. */
function showPhone(digits: string): string {
  if (!digits) return '';
  if (digits.startsWith('91') && digits.length === 12) return `+91 ${digits.slice(2, 7)} ${digits.slice(7)}`;
  return `+${digits}`;
}

/** Settings › Profile: the studio's details and the logged-in person's own account. */
export function ProfilePage() {
  const { user, refresh } = useAuth();
  const isOwner = user?.role === 'owner';
  const [profile, setProfile] = useState<Profile | null>(null);
  const [loadError, setLoadError] = useState('');

  useEffect(() => {
    api<Profile>('/studio/profile')
      .then((p) => setProfile({ ...EMPTY, ...p, phone: showPhone(p.phone) }))
      .catch(() => setLoadError('Could not load the studio profile.'));
  }, []);

  return (
    <>
      <p className="muted settings-intro">Your studio’s details, and your own name and password.</p>
      <FormMessage error={loadError} />
      {profile && <StudioForm initial={profile} editable={isOwner} onSaved={refresh} />}
      {user && <AccountForm user={user} onSaved={refresh} />}
      <PasswordForm />
    </>
  );
}

function StudioForm({ initial, editable, onSaved }: { initial: Profile; editable: boolean; onSaved: () => Promise<void> }) {
  const [form, setForm] = useState(initial);
  const [saved, setSaved] = useState('');
  const set = (key: keyof Profile) => (e: React.ChangeEvent<HTMLInputElement>) => {
    setSaved('');
    setForm((f) => ({ ...f, [key]: e.target.value }));
  };
  const { busy, error, fields, onSubmit } = useSubmit(async () => {
    const result = await api<Profile>('/studio/profile', { method: 'PATCH', body: form });
    setForm({ ...result, phone: showPhone(result.phone) });
    setSaved('Studio profile saved.');
    await onSaved();
  });

  return (
    <section className="panel">
      <h2>Studio profile</h2>
      <p className="muted">
        {editable
          ? 'Clients see your WhatsApp number, email, city, website and Instagram at the bottom of their gallery. Your street address and PIN code stay private.'
          : 'Only the studio owner can change these details.'}
      </p>
      <form onSubmit={onSubmit} noValidate>
        <FormMessage error={error} success={saved} />
        <fieldset disabled={!editable || busy} className="plain-fieldset">
          <Field label="Studio name" name="name" value={form.name} onChange={set('name')} errors={fields} required maxLength={200} />
          <div className="row">
            <Field label="WhatsApp number" name="phone" type="tel" value={form.phone} onChange={set('phone')} errors={fields}
              hint="Indian mobile, or add the + country code" autoComplete="tel" />
            <Field label="Contact email" name="contact_email" type="email" value={form.contact_email} onChange={set('contact_email')} errors={fields} autoComplete="email" />
          </div>
          <Field label="Address" name="address" value={form.address} onChange={set('address')} errors={fields} maxLength={300} autoComplete="street-address" />
          <div className="row">
            <Field label="City" name="city" value={form.city} onChange={set('city')} errors={fields} maxLength={100} autoComplete="address-level2" />
            <Field label="PIN code" name="pincode" value={form.pincode} onChange={set('pincode')} errors={fields} maxLength={7} inputMode="numeric" autoComplete="postal-code" />
          </div>
          <div className="row">
            <Field label="Website" name="website" value={form.website} onChange={set('website')} errors={fields} placeholder="yourstudio.in" />
            <Field label="Instagram" name="instagram" value={form.instagram} onChange={set('instagram')} errors={fields} placeholder="yourstudio" />
          </div>
        </fieldset>
        {editable && <div className="actions"><button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save studio profile'}</button></div>}
      </form>
    </section>
  );
}

function AccountForm({ user, onSaved }: { user: User; onSaved: () => Promise<void> }) {
  const [name, setName] = useState(user.full_name);
  const [saved, setSaved] = useState('');
  const { busy, error, fields, onSubmit } = useSubmit(async () => {
    await api('/auth/account', { method: 'PATCH', body: { full_name: name } });
    setSaved('Your name is saved.');
    await onSaved();
  });
  return (
    <section className="panel">
      <h2>Your account</h2>
      <form onSubmit={onSubmit} noValidate>
        <FormMessage error={error} success={saved} />
        <div className="row">
          <Field label="Your name" name="full_name" value={name} onChange={(e) => { setSaved(''); setName(e.target.value); }}
            errors={fields} required maxLength={150} autoComplete="name" />
          <Field label="Login email" name="email" value={user.email} readOnly disabled hint="Used to log in. It cannot be changed here." />
        </div>
        <div className="actions"><button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save name'}</button></div>
      </form>
    </section>
  );
}

function PasswordForm() {
  const [current, setCurrent] = useState('');
  const [next, setNext] = useState('');
  const [saved, setSaved] = useState('');
  const { busy, error, fields, onSubmit } = useSubmit(async () => {
    await api('/auth/password-change', { method: 'POST', body: { current_password: current, new_password: next } });
    setCurrent('');
    setNext('');
    setSaved('Password changed. Other devices will need to log in again.');
  });
  return (
    <section className="panel">
      <h2>Change password</h2>
      <form onSubmit={onSubmit} noValidate>
        <FormMessage error={error} success={saved} />
        <div className="row">
          <Field label="Current password" name="current_password" type="password" value={current}
            onChange={(e) => { setSaved(''); setCurrent(e.target.value); }} errors={fields} autoComplete="current-password" required />
          <Field label="New password" name="new_password" type="password" value={next}
            onChange={(e) => { setSaved(''); setNext(e.target.value); }} errors={fields} autoComplete="new-password"
            hint="At least 8 characters, not easy to guess" required />
        </div>
        <div className="actions"><button type="submit" disabled={busy}>{busy ? 'Saving…' : 'Change password'}</button></div>
      </form>
    </section>
  );
}

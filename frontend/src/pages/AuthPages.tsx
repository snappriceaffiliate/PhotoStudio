import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import type { MeResponse } from '../auth/types';
import { Field, FormMessage, useSubmit } from '../components/Form';
import { AuthLayout } from '../components/Layouts';

export function LoginPage() {
  const { setUser } = useAuth();
  const [form, setForm] = useState({ email: '', password: '' });
  const { busy, error, fields, onSubmit } = useSubmit(async () => {
    setUser((await api<MeResponse>('/auth/login', { method: 'POST', body: form })).user);
  });
  return (
    <AuthLayout
      title="Log in to your studio"
      footer={<>New here? <Link to="/signup">Create a studio account</Link></>}
    >
      <form onSubmit={onSubmit} noValidate>
        <FormMessage error={error} />
        <Field label="Email" name="email" type="email" autoComplete="email" required errors={fields}
          value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
        <Field label="Password" name="password" type="password" autoComplete="current-password" required errors={fields}
          value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <button type="submit" className="wide" disabled={busy}>{busy ? 'Logging in…' : 'Log in'}</button>
        <p className="aside"><Link to="/forgot-password">Forgot your password?</Link></p>
      </form>
    </AuthLayout>
  );
}

export function SignupPage() {
  const { setUser } = useAuth();
  const [form, setForm] = useState({
    studio_name: '', full_name: '', email: '', phone: '', pincode: '', password: '', password_confirm: '',
  });
  const set = (key: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, [key]: e.target.value });
  const { busy, error, fields, onSubmit } = useSubmit(async () => {
    // Catch a mistyped password here; the server checks it again.
    if (form.password_confirm && form.password_confirm !== form.password) {
      throw new ApiError(400, { password_confirm: ['The passwords do not match.'] });
    }
    setUser((await api<MeResponse>('/auth/signup', { method: 'POST', body: form })).user);
  });
  return (
    <AuthLayout title="Create your studio account" footer={<>Already have an account? <Link to="/login">Log in</Link></>}>
      <form onSubmit={onSubmit} noValidate>
        <FormMessage error={error} />
        <Field label="Studio name" name="studio_name" required autoComplete="organization" errors={fields}
          value={form.studio_name} onChange={set('studio_name')} />
        <Field label="Your name" name="full_name" required autoComplete="name" errors={fields}
          value={form.full_name} onChange={set('full_name')} />
        <Field label="Email" name="email" type="email" required autoComplete="email" errors={fields}
          value={form.email} onChange={set('email')} />
        <div className="row">
          <Field label="WhatsApp number" name="phone" type="tel" required autoComplete="tel" errors={fields}
            placeholder="98765 43210" value={form.phone} onChange={set('phone')} />
          <Field label="Studio PIN code" name="pincode" required autoComplete="postal-code" inputMode="numeric" maxLength={7} errors={fields}
            placeholder="600028" value={form.pincode} onChange={set('pincode')} />
        </div>
        <Field label="Password" name="password" type="password" required autoComplete="new-password" errors={fields}
          hint="At least 8 characters, not a common password." value={form.password} onChange={set('password')} />
        <Field label="Retype password" name="password_confirm" type="password" required autoComplete="new-password" errors={fields}
          value={form.password_confirm} onChange={set('password_confirm')} />
        <button type="submit" className="wide" disabled={busy}>{busy ? 'Creating…' : 'Create account'}</button>
      </form>
    </AuthLayout>
  );
}

export function ForgotPasswordPage() {
  const [email, setEmail] = useState('');
  const [sent, setSent] = useState(false);
  const { busy, error, fields, onSubmit } = useSubmit(async () => {
    await api('/auth/password-reset', { method: 'POST', body: { email } });
    setSent(true);
  });
  return (
    <AuthLayout title="Reset your password" footer={<Link to="/login">Back to log in</Link>}>
      {sent ? (
        <FormMessage success={`If an account exists for ${email}, we have sent a link to reset the password. It works for 3 days.`} />
      ) : (
        <form onSubmit={onSubmit} noValidate>
          <p>Enter your email and we will send you a link to choose a new password.</p>
          <FormMessage error={error} />
          <Field label="Email" name="email" type="email" required autoComplete="email" errors={fields}
            value={email} onChange={(e) => setEmail(e.target.value)} />
          <button type="submit" className="wide" disabled={busy}>{busy ? 'Sending…' : 'Send reset link'}</button>
        </form>
      )}
    </AuthLayout>
  );
}

/** Used both for password reset links and for staff invitations (invite=1). */
export function ResetPasswordPage() {
  const [params] = useSearchParams();
  const { setUser } = useAuth();
  const navigate = useNavigate();
  const [password, setPassword] = useState('');
  const invite = params.get('invite') === '1';
  const { busy, error, fields, onSubmit } = useSubmit(async () => {
    const me = await api<MeResponse>('/auth/password-set', {
      method: 'POST',
      body: { uid: params.get('uid') ?? '', token: params.get('token') ?? '', password },
    });
    setUser(me.user);
    navigate('/events');
  });
  return (
    <AuthLayout title={invite ? 'Choose a password to join your studio' : 'Choose a new password'}>
      <form onSubmit={onSubmit} noValidate>
        <FormMessage error={error} />
        <Field label="New password" name="password" type="password" required autoComplete="new-password" errors={fields}
          hint="At least 8 characters, not a common password." value={password} onChange={(e) => setPassword(e.target.value)} />
        <button type="submit" className="wide" disabled={busy}>{busy ? 'Saving…' : 'Save password'}</button>
        {error && <p className="aside"><Link to="/forgot-password">Request a new link</Link></p>}
      </form>
    </AuthLayout>
  );
}

export function VerifyEmailPage() {
  const [params] = useSearchParams();
  const { user, refresh } = useAuth();
  const [state, setState] = useState<'checking' | 'done' | 'failed'>('checking');
  const sent = useRef(false);

  useEffect(() => {
    if (sent.current) return; // React runs effects twice in development
    sent.current = true;
    api('/auth/verify-email', { method: 'POST', body: { token: params.get('token') ?? '' } })
      .then(async () => {
        await refresh();
        setState('done');
      })
      .catch(() => setState('failed'));
  }, [params, refresh]);

  return (
    <AuthLayout title="Email confirmation">
      {state === 'checking' && <p>Checking your link…</p>}
      {state === 'done' && <FormMessage success="Your email address is confirmed." />}
      {state === 'failed' && <FormMessage error="This link is invalid or has expired. Log in and send a new link from the banner." />}
      {state !== 'checking' && <Link className="button" to={user ? '/events' : '/login'}>{user ? 'Go to your events' : 'Log in'}</Link>}
    </AuthLayout>
  );
}

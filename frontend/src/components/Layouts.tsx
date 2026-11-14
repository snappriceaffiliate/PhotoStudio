import { useState, type ReactNode } from 'react';
import { Link, Navigate, NavLink, Outlet, useLocation, useNavigate } from 'react-router';
import { api } from '../api/client';
import { useAuth } from '../auth/AuthContext';

/** Centered card for sign-in, sign-up and password screens. */
export function AuthLayout({ title, children, footer }: { title: string; children: ReactNode; footer?: ReactNode }) {
  return (
    <div className="auth-page">
      <div className="auth-card">
        <p className="brand">Photo Selection</p>
        <h1>{title}</h1>
        {children}
      </div>
      {footer && <div className="auth-footer">{footer}</div>}
    </div>
  );
}

export function Loading() {
  return <div className="loading" aria-busy="true">Loading…</div>;
}

/** Studio screens: requires a logged-in studio member. */
export function StudioLayout() {
  const { user, loading, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const [resent, setResent] = useState(false);

  if (loading) return <Loading />;
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  if (!user.studio) {
    return (
      <AuthLayout title="No studio on this account">
        <p>This account is a platform admin account. Use the Django admin site instead.</p>
        <a className="button" href="/admin/">Open admin</a>
      </AuthLayout>
    );
  }

  async function resend() {
    await api('/auth/resend-verification', { method: 'POST' }).catch(() => undefined);
    setResent(true);
  }

  return (
    <div className="app">
      <header className="topbar">
        <div className="topbar-inner">
          <Link to="/events" className="studio-name">{user.studio.name}</Link>
          <nav aria-label="Main">
            <NavLink to="/events">Events</NavLink>
            {user.role === 'owner' && <NavLink to="/staff">Staff</NavLink>}
            <NavLink to="/billing">Billing</NavLink>
          </nav>
          <div className="account">
            <span className="account-name">{user.full_name}</span>
            <button
              className="link"
              onClick={async () => {
                await logout();
                navigate('/login');
              }}
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      {!user.email_verified && (
        <div className="banner" role="status">
          Confirm your email address using the link we sent to <strong>{user.email}</strong>.{' '}
          {resent ? 'A new link is on its way.' : <button className="link" onClick={resend}>Send a new link</button>}
        </div>
      )}
      <BillingBanner />
      <main className="page">
        <Outlet />
      </main>
    </div>
  );
}

/** Sign-in screens: sends logged-in users on to their studio. */
export function GuestOnly({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <Loading />;
  if (user) return <Navigate to={(location.state as { from?: string } | null)?.from ?? '/events'} replace />;
  return <>{children}</>;
}

/** Trial ending, payment problems and lapsed accounts, shown on every studio screen. */
function BillingBanner() {
  const { user } = useAuth();
  const billing = user?.billing;
  if (!billing) return null;
  const until = billing.until ? new Date(billing.until) : null;
  const daysLeft = until ? Math.ceil((until.getTime() - Date.now()) / 86400000) : null;
  let text = '';
  if (billing.state === 'trial' && daysLeft !== null && daysLeft <= 7) {
    text = `Your free trial ends in ${daysLeft} day${daysLeft === 1 ? '' : 's'}.`;
  } else if (billing.state === 'payment_due' || billing.state === 'ending' || billing.state === 'lapsed') {
    text = billing.message;
  }
  if (!text) return null;
  return (
    <div className={`banner ${billing.state === 'lapsed' ? 'bad' : ''}`} role="status">
      {text} <Link to="/billing">{user?.role === 'owner' ? 'Choose a plan' : 'See billing'}</Link>
    </div>
  );
}

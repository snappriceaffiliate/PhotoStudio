import { NavLink, Outlet } from 'react-router';
import { useAuth } from '../auth/AuthContext';

/** Settings: the studio profile and, for owners, the client gallery theme. Each is a tab. */
export function SettingsPage() {
  const { user } = useAuth();
  return (
    <>
      <div className="page-header">
        <h1>Settings</h1>
      </div>
      <nav className="tabs settings-tabs" aria-label="Settings">
        <NavLink to="/settings/profile" className={({ isActive }) => (isActive ? 'tab active' : 'tab')}>Profile</NavLink>
        {user?.role === 'owner' && (
          <NavLink to="/settings/theme" className={({ isActive }) => (isActive ? 'tab active' : 'tab')}>
            Theme <span className="premium-badge">Premium</span>
          </NavLink>
        )}
      </nav>
      <Outlet />
    </>
  );
}

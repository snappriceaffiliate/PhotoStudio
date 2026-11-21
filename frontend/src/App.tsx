import { lazy, Suspense } from 'react';
import { Link, Navigate, Route, Routes } from 'react-router';
import { AuthLayout, GuestOnly, Loading, StudioLayout } from './components/Layouts';
import { ForgotPasswordPage, LoginPage, ResetPasswordPage, SignupPage, VerifyEmailPage } from './pages/AuthPages';
import { ClientLoginPage, GalleryPage } from './gallery/GalleryPages';
import { BillingPage } from './pages/BillingPage';
import { BrandingPage } from './pages/BrandingPage';
import { EventPage } from './pages/EventPage';
import { EventPhotosPage } from './pages/EventPhotosPage';
import { ProfilePage } from './pages/ProfilePage';
import { EventsPage, StaffPage } from './pages/StudioPages';

// The Sprint 0 spike page is only bundled into development builds.
const SpikePage = import.meta.env.DEV ? lazy(() => import('./spike/SpikePage')) : null;

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Navigate to="/events" replace />} />
      <Route path="/login" element={<GuestOnly><LoginPage /></GuestOnly>} />
      <Route path="/signup" element={<GuestOnly><SignupPage /></GuestOnly>} />
      <Route path="/forgot-password" element={<GuestOnly><ForgotPasswordPage /></GuestOnly>} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/verify-email" element={<VerifyEmailPage />} />
      <Route path="/gallery/login" element={<ClientLoginPage />} />
      <Route path="/gallery" element={<GalleryPage />} />
      <Route element={<StudioLayout />}>
        <Route path="/events" element={<EventsPage />} />
        <Route path="/events/:eventId" element={<EventPage />} />
        <Route path="/events/:eventId/photos" element={<EventPhotosPage />} />
        <Route path="/staff" element={<StaffPage />} />
        <Route path="/branding" element={<BrandingPage />} />
        <Route path="/billing" element={<BillingPage />} />
        <Route path="/profile" element={<ProfilePage />} />
      </Route>
      {SpikePage && (
        <Route path="/dev/spikes" element={<Suspense fallback={<Loading />}><SpikePage /></Suspense>} />
      )}
      <Route
        path="*"
        element={
          <AuthLayout title="Page not found">
            <Link className="button" to="/events">Go to your events</Link>
          </AuthLayout>
        }
      />
    </Routes>
  );
}

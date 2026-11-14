import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { FormMessage } from '../components/Form';

interface PlanInfo {
  code: string;
  name: string;
  price_inr: number;
  max_active_events: number | null;
  max_photos_per_event: number;
  max_staff: number;
  available: boolean;
}

interface BillingInfo {
  state: 'trial' | 'active' | 'payment_due' | 'ending' | 'lapsed';
  can_work: boolean;
  message: string;
  until: string | null;
  plan: string;
  status: string;
  plan_code: string | null;
  cancel_at_period_end: boolean;
  limits: { max_active_events: number | null; max_photos_per_event: number; max_staff: number };
  usage: { active_events: number; staff: number };
  plans: PlanInfo[];
  payments_configured: boolean;
}

interface CheckoutStart {
  subscription_id: string;
  key_id: string;
  plan: PlanInfo;
  prefill: { name: string; email: string };
  studio_name: string;
}

interface RazorpayResponse {
  razorpay_payment_id: string;
  razorpay_subscription_id: string;
  razorpay_signature: string;
}

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => { open: () => void; on: (event: string, cb: (r: unknown) => void) => void };
  }
}

const day = (iso: string | null) => (iso ? new Date(iso).toLocaleDateString('en-IN', { dateStyle: 'medium' }) : '');
const rupees = (n: number) => `₹${n.toLocaleString('en-IN')}`;

function loadCheckout(): Promise<void> {
  if (window.Razorpay) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://checkout.razorpay.com/v1/checkout.js';
    script.onload = () => resolve();
    script.onerror = () => reject(new Error('Could not load Razorpay. Check your connection.'));
    document.body.appendChild(script);
  });
}

export function BillingPage() {
  const { user, refresh } = useAuth();
  const [info, setInfo] = useState<BillingInfo | null>(null);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');
  const [busy, setBusy] = useState('');
  const isOwner = user?.role === 'owner';

  const load = useCallback(async () => {
    setInfo(await api<BillingInfo>('/billing'));
  }, []);

  useEffect(() => {
    load().catch(() => setError('Could not load billing.'));
  }, [load]);

  async function choose(plan: PlanInfo) {
    setError('');
    setSuccess('');
    setBusy(plan.code);
    try {
      const start = await api<CheckoutStart>('/billing/subscribe', { method: 'POST', body: { plan: plan.code } });
      await loadCheckout();
      const checkout = new window.Razorpay!({
        key: start.key_id,
        subscription_id: start.subscription_id,
        name: 'Photo Selection',
        description: `${plan.name} plan for ${start.studio_name}`,
        prefill: start.prefill,
        theme: { color: '#2563eb' },
        handler: async (response: RazorpayResponse) => {
          try {
            await api('/billing/verify', { method: 'POST', body: response });
            setSuccess(`Payment received. You are on the ${plan.name} plan.`);
            await Promise.all([load(), refresh()]);
          } catch (err) {
            setError(err instanceof ApiError ? err.message : 'We could not confirm the payment yet. Refresh in a minute.');
          }
        },
        modal: { ondismiss: () => setBusy('') },
      });
      checkout.on('payment.failed', () => setError('The payment did not go through. You have not been charged; try again.'));
      checkout.open();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : err instanceof Error ? err.message : 'Could not start the payment.');
    } finally {
      setBusy('');
    }
  }

  async function cancel() {
    if (!window.confirm('Cancel your plan? It stays active until the end of the period you have paid for.')) return;
    setBusy('cancel');
    try {
      await api('/billing/cancel', { method: 'POST' });
      setSuccess('Your plan is cancelled and ends at the end of this period.');
      await Promise.all([load(), refresh()]);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not cancel.');
    } finally {
      setBusy('');
    }
  }

  if (!info) return <p className="muted">{error || 'Loading billing…'}</p>;

  const headline: Record<BillingInfo['state'], string> = {
    trial: `Free trial · ends ${day(info.until)}`,
    active: `${info.plan} plan${info.until ? ` · renews ${day(info.until)}` : ''}`,
    ending: `${info.plan} plan · ends ${day(info.until)}`,
    payment_due: `Payment due · fix by ${day(info.until)}`,
    lapsed: info.until && new Date(info.until) > new Date() ? `Plan ended · client galleries close ${day(info.until)}` : 'Plan ended',
  };
  const limit = (n: number | null) => (n === null ? 'Unlimited' : n.toLocaleString('en-IN'));

  return (
    <>
      <div className="page-header"><h1>Billing</h1></div>
      <FormMessage error={error} success={success} />

      <section className={`panel billing-status state-${info.state}`}>
        <h2>{headline[info.state]}</h2>
        {info.state !== 'active' && info.state !== 'trial' && <p>{info.message}</p>}
        <dl className="usage">
          <div><dt>Active events</dt><dd>{info.usage.active_events} / {limit(info.limits.max_active_events)}</dd></div>
          <div><dt>Photos per event</dt><dd>up to {limit(info.limits.max_photos_per_event)}</dd></div>
          <div><dt>People</dt><dd>{info.usage.staff} / {limit(info.limits.max_staff)}</dd></div>
        </dl>
        {isOwner && info.status === 'active' && !info.cancel_at_period_end && (
          <button className="link danger" onClick={cancel} disabled={busy === 'cancel'}>Cancel plan</button>
        )}
      </section>

      {!info.payments_configured && (
        <p className="warning">Online payments are not set up yet. Your free trial continues until they are.</p>
      )}
      {!isOwner && <p className="muted">Only the studio owner can change the plan.</p>}

      <ul className="plans">
        {info.plans.map((p) => {
          const current = info.plan_code === p.code && info.state !== 'lapsed';
          return (
            <li key={p.code} className={current ? 'plan current' : 'plan'}>
              <h3>{p.name}</h3>
              <p className="price">{rupees(p.price_inr)}<span> / month</span></p>
              <ul>
                <li>{p.max_active_events === null ? 'Unlimited active events' : `${p.max_active_events} active events`}</li>
                <li>Up to {p.max_photos_per_event.toLocaleString('en-IN')} photos per event</li>
                <li>{p.max_staff} {p.max_staff === 1 ? 'person' : 'people'}</li>
              </ul>
              {current ? (
                <span className="status status-shared">Current plan</span>
              ) : (
                isOwner && (
                  <button onClick={() => choose(p)} disabled={!p.available || busy !== ''}>
                    {busy === p.code ? 'Opening…' : p.available ? `Choose ${p.name}` : 'Not available yet'}
                  </button>
                )
              )}
            </li>
          );
        })}
      </ul>
      <p className="muted">Payments are handled by Razorpay; card details never reach this app.</p>
    </>
  );
}

import { useCallback, useEffect, useState } from 'react';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { FormMessage } from '../components/Form';
import { BRAND_NAME, CONTACT_EMAIL } from '../components/Brand';

interface PlanInfo {
  code: string;
  name: string;
  price_inr: number;
  max_active_events: number | null;
  max_photos_per_event: number;
  max_staff: number;
  custom_theme?: boolean;
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
  scheduled_plan_code?: string | null;
  scheduled_over_limits?: string[];
  limits: { max_active_events: number | null; max_photos_per_event: number; max_staff: number };
  usage: { active_events: number; staff: number };
  plans: PlanInfo[];
  payments_configured: boolean;
}

interface Quote {
  kind: 'new' | 'upgrade' | 'scheduled';
  plan: PlanInfo;
  charge_now_inr: number;
  days_left: number;
  starts_at: string | null;
  /** What the studio has beyond the plan's limits, and what happens to it. */
  over_limits?: string[];
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
  const [offer, setOffer] = useState<Quote | null>(null);
  const isOwner = user?.role === 'owner';

  const load = useCallback(async () => {
    setInfo(await api<BillingInfo>('/billing'));
  }, []);

  useEffect(() => {
    load().catch(() => setError('Could not load billing.'));
  }, [load]);

  const paying = info !== null && info.plan_code !== null && (info.state === 'active' || info.state === 'ending');

  /** While a plan is paid for, show what the change costs before Razorpay opens. */
  async function choose(plan: PlanInfo) {
    setError('');
    setSuccess('');
    setBusy(plan.code);
    try {
      const quote = await api<Quote>(`/billing/quote?plan=${encodeURIComponent(plan.code)}`);
      // Nothing running to change: go straight to Razorpay unless the plan is too small.
      if (!paying && !quote.over_limits?.length) {
        setBusy('');
        return checkout(plan, 'new');
      }
      setOffer(quote);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Could not work out the price. Try again.');
    } finally {
      setBusy('');
    }
  }

  const done: Record<Quote['kind'], (plan: PlanInfo, quote: Quote | null) => string> = {
    new: (plan) => `Payment received. You are on the ${plan.name} plan.`,
    upgrade: (plan, quote) => `You are on the ${plan.name} plan now. Full billing starts ${day(quote?.starts_at ?? null)}.`,
    scheduled: (plan, quote) =>
      plan.code === info?.plan_code
        ? `Your ${plan.name} plan continues after ${day(quote?.starts_at ?? null)}.`
        : `Done. You switch to the ${plan.name} plan on ${day(quote?.starts_at ?? null)}.`,
  };

  async function checkout(plan: PlanInfo, kind: Quote['kind'], quote: Quote | null = null) {
    setOffer(null);
    setBusy(plan.code);
    try {
      const start = await api<CheckoutStart>('/billing/subscribe', { method: 'POST', body: { plan: plan.code } });
      await loadCheckout();
      const checkout = new window.Razorpay!({
        key: start.key_id,
        subscription_id: start.subscription_id,
        name: BRAND_NAME,
        description: kind === 'new' ? `${plan.name} plan for ${start.studio_name}` : `Change to ${plan.name} for ${start.studio_name}`,
        prefill: start.prefill,
        image: new URL(`${import.meta.env.BASE_URL}icon-192.png`, window.location.origin).href,
        theme: { color: '#3b2f8f' },
        handler: async (response: RazorpayResponse) => {
          try {
            await api('/billing/verify', { method: 'POST', body: response });
            setSuccess(done[kind](plan, quote));
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
  const currentPlan = info.plans.find((p) => p.code === info.plan_code);
  const scheduled = info.plans.find((p) => p.code === info.scheduled_plan_code) ?? null;
  const label = (p: PlanInfo) => {
    if (!p.available) return 'Not available yet';
    if (!paying || !currentPlan) return `Choose ${p.name}`;
    if (p.code === currentPlan.code) return `Keep ${p.name}`;
    return p.price_inr > currentPlan.price_inr ? `Upgrade to ${p.name}` : `Switch to ${p.name}`;
  };

  return (
    <>
      <div className="page-header"><h1>Billing</h1></div>
      <FormMessage error={error} success={success} />

      <section className={`panel billing-status state-${info.state}`}>
        <h2>{headline[info.state]}</h2>
        {info.state !== 'active' && info.state !== 'trial' && <p>{info.message}</p>}
        {scheduled && <p>Switching to the {scheduled.name} plan on {day(info.until)}.</p>}
        {scheduled && !!info.scheduled_over_limits?.length && (
          <ul className="change-summary over-limits">
            {info.scheduled_over_limits.map((note) => <li key={note}>{note}</li>)}
          </ul>
        )}
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
          const keepable = current && paying && (info.cancel_at_period_end || info.state === 'ending' || scheduled !== null);
          return (
            <li key={p.code} className={current ? 'plan current' : 'plan'}>
              <h3>{p.name}</h3>
              <p className="price">{rupees(p.price_inr)}<span> / month</span></p>
              <ul>
                <li>{p.max_active_events === null ? 'Unlimited active events' : `${p.max_active_events} active events`}</li>
                <li>Up to {p.max_photos_per_event.toLocaleString('en-IN')} photos per event</li>
                <li>{p.max_staff} {p.max_staff === 1 ? 'person' : 'people'}</li>
                {p.custom_theme && <li>Your own theme and logo in client galleries</li>}
              </ul>
              {current && <span className="status status-shared">Current plan</span>}
              {scheduled?.code === p.code && <span className="status status-shared">From {day(info.until)}</span>}
              {(!current || keepable) && scheduled?.code !== p.code && isOwner && (
                <button onClick={() => choose(p)} disabled={!p.available || busy !== ''}>
                  {busy === p.code ? 'Opening…' : label(p)}
                </button>
              )}
            </li>
          );
        })}
      </ul>
      <p className="muted">Payments are handled by Razorpay; card details never reach this app.</p>
      <p className="muted">
        Questions about a payment or your plan? Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
      </p>
      {offer && (currentPlan || offer.kind === 'new') && (
        <ChangeDialog quote={offer} current={currentPlan} onCancel={() => setOffer(null)} onConfirm={() => checkout(offer.plan, offer.kind, offer)} />
      )}
    </>
  );
}

/** What a plan change does and costs, confirmed before Razorpay Checkout opens. */
function ChangeDialog({ quote, current, onCancel, onConfirm }: { quote: Quote; current?: PlanInfo; onCancel: () => void; onConfirm: () => void }) {
  const { plan } = quote;
  const from = day(quote.starts_at);
  const keep = plan.code === current?.code;
  const title = quote.kind === 'upgrade'
    ? `Upgrade to ${plan.name}`
    : quote.kind === 'new'
      ? `Choose the ${plan.name} plan`
      : keep ? `Keep the ${plan.name} plan` : `Switch to ${plan.name} on ${from}`;
  const over = quote.over_limits ?? [];
  return (
    <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="change-title">
      <div className="dialog">
        <h2 id="change-title">{title}</h2>
        {quote.kind === 'new' ? (
          <ul className="change-summary">
            <li><strong>{rupees(plan.price_inr)}</strong> every month, starting today.</li>
          </ul>
        ) : quote.kind === 'upgrade' && current ? (
          <ul className="change-summary">
            <li>The {plan.name} limits start <strong>now</strong>.</li>
            <li>
              {quote.charge_now_inr > 0 ? (
                <>Pay <strong>{rupees(quote.charge_now_inr)}</strong> today: the difference between {current.name} and {plan.name} for the {quote.days_left} {quote.days_left === 1 ? 'day' : 'days'} left this month.</>
              ) : (
                <>Nothing to pay today: only a few hours are left this month.</>
              )}
            </li>
            <li>From {from}: <strong>{rupees(plan.price_inr)}</strong> every month, instead of {rupees(current.price_inr)}.</li>
          </ul>
        ) : (
          <ul className="change-summary">
            {keep ? (
              <li>Your plan continues after {from}. Nothing to pay today.</li>
            ) : (
              <li>You keep the {current?.name} plan until {from}. Nothing to pay today, and no refund for this month.</li>
            )}
            <li>From {from}: <strong>{rupees(plan.price_inr)}</strong> every month.</li>
            {!keep && over.length === 0 && <li>Everything you have fits the {plan.name} plan. Nothing is deleted.</li>}
          </ul>
        )}
        {over.length > 0 && (
          <div className="over-limits" role="note">
            <h3>More than the {plan.name} plan allows</h3>
            <p className="muted">Nothing is deleted.</p>
            <ul className="change-summary">
              {over.map((note) => <li key={note}>{note}</li>)}
            </ul>
          </div>
        )}
        <p className="muted">Razorpay asks you to approve the new monthly amount.</p>
        <div className="actions">
          <button type="button" onClick={onConfirm}>{quote.charge_now_inr > 0 ? `Pay ${rupees(quote.charge_now_inr)}` : 'Continue to Razorpay'}</button>
          <button type="button" className="secondary" onClick={onCancel}>Not now</button>
        </div>
      </div>
    </div>
  );
}

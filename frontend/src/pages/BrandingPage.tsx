import { useEffect, useRef, useState, type ChangeEvent } from 'react';
import { Link } from 'react-router';
import { api, apiUpload, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { brandStyle, contrastWithWhite, isHexColour, makeLogo, MIN_CONTRAST } from '../branding/brand';
import { BRAND_NAME, HeartIcon } from '../components/Brand';
import { FormMessage } from '../components/Form';
import { Loading } from '../components/Layouts';

interface Branding {
  studio_name: string;
  logo_url: string | null;
  accent_color: string | null;
  allowed: boolean;
}

const DEFAULT_ACCENT = '#1C1A17';

// Darker colours that read well on white and suit Indian studio brands.
const SWATCHES = [
  { name: `Black (${BRAND_NAME})`, hex: '#1C1A17' },
  { name: 'Peacock', hex: '#0E5E5A' },
  { name: 'Maroon', hex: '#8A1C3B' },
  { name: 'Vermilion', hex: '#B3361B' },
  { name: 'Navy', hex: '#1F3A68' },
  { name: 'Forest', hex: '#2E5E3A' },
  { name: 'Plum', hex: '#5B2A6E' },
  { name: 'Charcoal', hex: '#333333' },
];

export function BrandingPage() {
  const { user } = useAuth();
  const [branding, setBranding] = useState<Branding | null>(null);
  const [colour, setColour] = useState(DEFAULT_ACCENT);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState<'' | 'logo' | 'colour'>('');
  const fileInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    api<Branding>('/studio/branding')
      .then((data) => {
        setBranding(data);
        setColour(data.accent_color ?? DEFAULT_ACCENT);
      })
      .catch((e: Error) => setError(e.message));
  }, []);

  if (user?.role !== 'owner') return <FormMessage error="Only the studio owner can change branding." />;
  if (!branding) return error ? <FormMessage error={error} /> : <Loading />;

  const valid = isHexColour(colour);
  const contrast = valid ? contrastWithWhite(colour) : 0;
  const readable = contrast >= MIN_CONTRAST;
  const unchanged = colour.toUpperCase() === (branding.accent_color ?? DEFAULT_ACCENT).toUpperCase();
  const locked = !branding.allowed;

  async function run(kind: 'logo' | 'colour', action: () => Promise<Branding | void>, done: string) {
    setBusy(kind);
    setError('');
    setNotice('');
    try {
      const result = await action();
      if (result) setBranding(result);
      setNotice(done);
    } catch (e) {
      setError(e instanceof ApiError ? Object.values(e.fields).flat().join(' ') || e.message : (e as Error).message);
    } finally {
      setBusy('');
    }
  }

  function chooseLogo(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    run('logo', async () => apiUpload<Branding>('/studio/branding/logo', 'logo', await makeLogo(file), 'logo.webp'), 'Logo saved. Clients will see it in their galleries.');
  }

  function removeLogo() {
    run('logo', async () => {
      await api('/studio/branding/logo', { method: 'DELETE' });
      return { ...branding!, logo_url: null };
    }, 'Logo removed.');
  }

  function saveColour(value: string | null) {
    run('colour', () => api<Branding>('/studio/branding', { method: 'PATCH', body: { accent_color: value } }),
      value ? 'Colour saved.' : `Colour reset to ${BRAND_NAME} black.`);
    if (!value) setColour(DEFAULT_ACCENT);
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Branding</h1>
          <p className="muted">Your logo and colour in every client gallery, so clients see your studio, not ours.</p>
        </div>
      </div>

      {locked && (
        <div className="banner warn" role="status">
          Your plan does not include studio branding. <Link to="/billing">Choose a bigger plan</Link> to turn it on.
        </div>
      )}
      <FormMessage error={error} success={notice} />

      <div className="branding-layout">
        <div>
          <section className="panel">
            <h2>Logo</h2>
            <p className="muted">PNG with a transparent background works best. We shrink it to a small file in your browser.</p>
            <div className="logo-drop">
              {branding.logo_url ? <img src={branding.logo_url} alt={`${branding.studio_name} logo`} /> : <span className="muted">No logo yet</span>}
            </div>
            <input ref={fileInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={chooseLogo} />
            <div className="actions">
              <button type="button" disabled={locked || busy !== ''} onClick={() => fileInput.current?.click()}>
                {busy === 'logo' ? 'Saving…' : branding.logo_url ? 'Change logo' : 'Upload logo'}
              </button>
              {branding.logo_url && (
                <button type="button" className="secondary" disabled={busy !== ''} onClick={removeLogo}>Remove</button>
              )}
            </div>
          </section>

          <section className="panel">
            <h2>Accent colour</h2>
            <p className="muted">Used for buttons and links in your galleries. Hearts stay marigold so choosing always looks the same.</p>
            <div className="swatches" role="group" aria-label="Suggested colours">
              {SWATCHES.map((s) => (
                <button
                  key={s.hex}
                  type="button"
                  className="swatch"
                  style={{ background: s.hex }}
                  aria-label={s.name}
                  aria-pressed={colour.toUpperCase() === s.hex}
                  disabled={locked}
                  onClick={() => setColour(s.hex)}
                />
              ))}
            </div>
            <div className="colour-row">
              <input type="color" aria-label="Pick any colour" value={valid ? colour : DEFAULT_ACCENT} disabled={locked}
                onChange={(e) => setColour(e.target.value.toUpperCase())} />
              <div className="field">
                <label htmlFor="accent-hex">Colour code</label>
                <input id="accent-hex" value={colour} maxLength={7} disabled={locked} spellCheck={false}
                  aria-invalid={!valid || !readable ? true : undefined} aria-describedby="accent-help"
                  onChange={(e) => setColour(e.target.value.trim())} />
              </div>
            </div>
            <p id="accent-help" className={valid && readable ? 'field-hint' : 'field-error'}>
              {!valid ? 'Use a colour code like #8A1C3B.'
                : readable ? `Readable on white (contrast ${contrast.toFixed(1)} : 1).`
                  : `Too light for text on white (contrast ${contrast.toFixed(1)} : 1, needs ${MIN_CONTRAST}). Pick a darker shade.`}
            </p>
            <div className="actions">
              <button type="button" disabled={locked || !valid || !readable || unchanged || busy !== ''} onClick={() => saveColour(colour)}>
                {busy === 'colour' ? 'Saving…' : 'Save colour'}
              </button>
              {branding.accent_color && (
                <button type="button" className="link" disabled={busy !== ''} onClick={() => saveColour(null)}>Reset to {BRAND_NAME} black</button>
              )}
            </div>
          </section>
        </div>

        <section className="panel" aria-labelledby="preview-title">
          <h2 id="preview-title">What clients see</h2>
          <div className="brand-preview branded" style={brandStyle(valid && readable ? colour : branding.accent_color)}>
            <div className="brand-preview-cover">
              {branding.logo_url ? <img className="studio-logo" src={branding.logo_url} alt="" /> : <p className="brand">{branding.studio_name}</p>}
              <strong>Priya and Arun Wedding</strong>
              <span>1,240 photos · choose up to 200</span>
              <span className="preview-button">Start choosing</span>
            </div>
            <div className="brand-preview-bar">
              <span className="preview-heart"><HeartIcon filled size={16} /></span>
              <span><strong>12</strong> of 200 chosen</span>
              <span className="preview-button small">Send selection</span>
            </div>
            <p className="brand-preview-foot">Made with {BRAND_NAME}</p>
          </div>
        </section>
      </div>
    </>
  );
}

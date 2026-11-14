import { useCallback, useEffect, useRef, useState, type TouchEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router';
import { api, ApiError } from '../api/client';
import { Field, FormMessage, useSubmit } from '../components/Form';
import { BRAND_NAME, HeartIcon } from '../components/Brand';
import { AuthLayout, Loading } from '../components/Layouts';
import { brandStyle, type StudioBranding } from '../branding/brand';

interface GalleryInfo {
  client_name: string;
  studio_name: string;
  event: { title: string; selection_limit: number | null; expires_at: string | null; submitted_at: string | null };
  photo_count: number;
  selected: number;
  albums: { id: string; name: string }[];
  cover_url: string | null;
  branding: StudioBranding | null;
}

interface GalleryPhoto {
  id: string;
  width: number | null;
  height: number | null;
  thumb_url: string;
  preview_url: string;
  selected: boolean;
  note: string;
}

interface PhotoPage {
  count: number;
  next_page: number | null;
  results: GalleryPhoto[];
}

export function ClientLoginPage() {
  const [params] = useSearchParams();
  const navigate = useNavigate();
  const [form, setForm] = useState({ username: params.get('u') ?? '', password: '' });
  const { busy, error, fields, onSubmit } = useSubmit(async () => {
    await api('/client/login', { method: 'POST', body: { ...form, username: form.username.trim() } });
    navigate('/gallery');
  });
  return (
    <AuthLayout title="Open your photo gallery">
      <form onSubmit={onSubmit} noValidate>
        <p className="muted">Use the username and password from the studio's email.</p>
        <FormMessage error={error} />
        <Field label="Username" name="username" required autoComplete="username" autoCapitalize="none" errors={fields}
          value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} />
        <Field label="Password" name="password" type="password" required autoComplete="current-password" errors={fields}
          value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
        <button type="submit" className="wide" disabled={busy}>{busy ? 'Opening…' : 'Open gallery'}</button>
      </form>
    </AuthLayout>
  );
}

/** The studio's logo when it has one (named for screen readers), otherwise its name. */
function StudioMark({ info }: { info: GalleryInfo }) {
  if (info.branding?.logo_url) {
    return <img className="studio-logo" src={info.branding.logo_url} alt={info.studio_name} />;
  }
  return <p className="brand">{info.studio_name}</p>;
}

export function GalleryPage() {
  const navigate = useNavigate();
  const [info, setInfo] = useState<GalleryInfo | null>(null);
  const [photos, setPhotos] = useState<GalleryPhoto[]>([]);
  const [count, setCount] = useState(0);
  const [nextPage, setNextPage] = useState<number | null>(null);
  const [onlySelected, setOnlySelected] = useState(false);
  const [album, setAlbum] = useState('');
  const [viewer, setViewer] = useState<number | null>(null);
  const [notice, setNotice] = useState('');
  const [confirming, setConfirming] = useState(false);
  const sentinel = useRef<HTMLDivElement>(null);
  const loadingMore = useRef(false);

  const submitted = Boolean(info?.event.submitted_at);
  const limit = info?.event.selection_limit ?? null;

  const query = useCallback(
    (page: number) => `/client/photos?page=${page}&page_size=60${onlySelected ? '&selected=1' : ''}${album ? `&album=${album}` : ''}`,
    [onlySelected, album],
  );

  const refreshInfo = useCallback(async () => {
    try {
      setInfo(await api<GalleryInfo>('/client/me'));
    } catch (error) {
      if (error instanceof ApiError && error.status === 403) navigate('/gallery/login');
    }
  }, [navigate]);

  useEffect(() => {
    void refreshInfo();
  }, [refreshInfo]);

  useEffect(() => {
    let current = true;
    api<PhotoPage>(query(1))
      .then((data) => {
        if (!current) return;
        setPhotos(data.results);
        setCount(data.count);
        setNextPage(data.next_page);
      })
      .catch(() => navigate('/gallery/login'));
    return () => {
      current = false;
    };
  }, [query, navigate]);

  const loadMore = useCallback(async () => {
    if (!nextPage || loadingMore.current) return;
    loadingMore.current = true;
    try {
      const data = await api<PhotoPage>(query(nextPage));
      setPhotos((p) => [...p, ...data.results]);
      setNextPage(data.next_page);
    } finally {
      loadingMore.current = false;
    }
  }, [nextPage, query]);

  useEffect(() => {
    const el = sentinel.current;
    if (!el) return;
    const observer = new IntersectionObserver((entries) => entries[0].isIntersecting && void loadMore(), { rootMargin: '600px' });
    observer.observe(el);
    return () => observer.disconnect();
  }, [loadMore]);

  function showNotice(text: string) {
    setNotice(text);
    window.setTimeout(() => setNotice(''), 4000);
  }

  async function toggle(photo: GalleryPhoto, note?: string) {
    if (submitted) return showNotice('Your selection is submitted. Contact the studio to change it.');
    const select = note !== undefined || !photo.selected;
    // Update straight away; undo if the server refuses.
    setPhotos((list) => list.map((p) => (p.id === photo.id ? { ...p, selected: select, note: note ?? (select ? p.note : '') } : p)));
    try {
      const result = await api<{ selected_count: number }>(`/client/selections/${photo.id}`, {
        method: select ? 'PUT' : 'DELETE',
        body: select ? { note: note ?? photo.note } : undefined,
      });
      setInfo((i) => (i ? { ...i, selected: result.selected_count } : i));
    } catch (error) {
      setPhotos((list) => list.map((p) => (p.id === photo.id ? photo : p)));
      showNotice(error instanceof ApiError ? error.message : 'Could not save. Check your connection.');
    }
  }

  async function submit() {
    try {
      await api('/client/submit', { method: 'POST' });
      setConfirming(false);
      await refreshInfo();
      window.scrollTo({ top: 0 });
    } catch (error) {
      setConfirming(false);
      showNotice(error instanceof ApiError ? error.message : 'Could not submit. Try again.');
    }
  }

  async function logout() {
    await api('/client/logout', { method: 'POST' });
    navigate('/gallery/login');
  }

  if (!info) return <Loading />;
  const atLimit = limit !== null && info.selected >= limit;

  return (
    <div className={info.branding?.accent_color ? 'gallery branded' : 'gallery'} style={brandStyle(info.branding?.accent_color)}>
      {info.cover_url ? (
        <header className="gallery-cover">
          <img src={info.cover_url} alt="" />
          <button className="link logout" onClick={logout}>Log out</button>
          <div className="gallery-cover-text">
            <StudioMark info={info} />
            <h1>{info.event.title}</h1>
            <p>
              {info.photo_count} photos
              {limit ? ` · choose up to ${limit}` : ''}
              {info.event.expires_at ? ` · open until ${new Date(info.event.expires_at).toLocaleDateString('en-IN', { dateStyle: 'medium' })}` : ''}
            </p>
            <button onClick={() => document.getElementById('photos')?.scrollIntoView({ behavior: 'smooth' })}>
              {submitted ? 'See your selection' : info.selected ? 'Continue choosing' : 'Start choosing'}
            </button>
          </div>
        </header>
      ) : (
        <header className="gallery-header">
          <div>
            <StudioMark info={info} />
            <h1>{info.event.title}</h1>
          </div>
          <button className="link" onClick={logout}>Log out</button>
        </header>
      )}

      <div id="photos" />
      {submitted ? (
        <div className="banner good" role="status" style={{ marginTop: 16 }}>
          You submitted {info.selected} photos. {info.studio_name} has been told. Thank you!
        </div>
      ) : (
        <p className="gallery-help">
          Tap the heart to choose a photo, or tap the photo to see it large.
          {limit ? ` You can choose up to ${limit}.` : ''} Your choices save as you go.
        </p>
      )}

      <div className="gallery-bar">
        <div className="tabs" role="tablist">
          <button role="tab" aria-selected={!onlySelected} className={!onlySelected ? 'tab active' : 'tab'} onClick={() => setOnlySelected(false)}>
            All {info.photo_count}
          </button>
          <button role="tab" aria-selected={onlySelected} className={onlySelected ? 'tab active' : 'tab'} onClick={() => setOnlySelected(true)}>
            Selected {info.selected}
          </button>
        </div>
        {info.albums.length > 0 && (
          <select aria-label="Album" value={album} onChange={(e) => setAlbum(e.target.value)}>
            <option value="">All albums</option>
            {info.albums.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
          </select>
        )}
      </div>

      {count === 0 && (
        <div className="empty" style={{ margin: '12px' }}>
          <HeartIcon size={36} />
          {onlySelected ? (
            <>
              <h2>Nothing chosen yet</h2>
              <p>Tap the heart on the photos you love. They will collect here.</p>
              <button className="secondary" onClick={() => setOnlySelected(false)}>See all photos</button>
            </>
          ) : (
            <h2>No photos here</h2>
          )}
        </div>
      )}

      <ul className="gallery-grid">
        {photos.map((p, index) => (
          <li key={p.id} className={p.selected ? 'picked' : ''}>
            <button className="gallery-thumb" onClick={() => setViewer(index)} aria-label="View photo large">
              <img src={p.thumb_url} alt="" loading="lazy" />
            </button>
            <button
              className="heart"
              aria-pressed={p.selected}
              aria-label={p.selected ? 'Remove from selection' : 'Add to selection'}
              onClick={() => toggle(p)}
              disabled={submitted}
            >
              <HeartIcon filled={p.selected} />
            </button>
            {p.note && <span className="note-dot" title={p.note}>✎</span>}
          </li>
        ))}
      </ul>
      <div ref={sentinel} />
      <p className="gallery-foot">
        Gallery by {info.studio_name} · made with <a href="/" rel="noopener">{BRAND_NAME}</a>
      </p>

      {!submitted && (
        <div className="submit-bar">
          <div className="submit-count" aria-live="polite">
            <strong>{info.selected}</strong>{limit ? ` of ${limit}` : ''} chosen
            {limit ? (
              <span className="muted">{atLimit ? ' · limit reached' : ` · ${limit - info.selected} left`}</span>
            ) : null}
            {limit ? (
              <div className="meter" aria-hidden="true">
                <span style={{ width: `${Math.min(100, (info.selected / limit) * 100)}%` }} />
              </div>
            ) : null}
          </div>
          <button onClick={() => setConfirming(true)} disabled={info.selected === 0}>Send selection</button>
        </div>
      )}

      {notice && <div className="toast" role="alert">{notice}</div>}

      {confirming && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
          <div className="dialog">
            <h2 id="confirm-title">Send {info.selected} photos to {info.studio_name}?</h2>
            <p>
              The studio will prepare these photos for printing. After you send, the selection is locked; to change it,
              ask the studio to reopen it.
            </p>
            <div className="actions">
              <button onClick={submit}>Send selection</button>
              <button className="secondary" onClick={() => setConfirming(false)} autoFocus>Keep choosing</button>
            </div>
          </div>
        </div>
      )}

      {viewer !== null && photos[viewer] && (
        <Viewer
          photos={photos}
          index={viewer}
          onIndex={(i) => {
            setViewer(i);
            if (i >= photos.length - 5) void loadMore();
          }}
          onClose={() => setViewer(null)}
          onToggle={toggle}
          readOnly={submitted}
        />
      )}
    </div>
  );
}

function Viewer({ photos, index, onIndex, onClose, onToggle, readOnly }: {
  photos: GalleryPhoto[];
  index: number;
  onIndex: (i: number) => void;
  onClose: () => void;
  onToggle: (p: GalleryPhoto, note?: string) => void;
  readOnly: boolean;
}) {
  const photo = photos[index];
  const [note, setNote] = useState(photo.note);
  const touchStart = useRef<number | null>(null);
  const closeButton = useRef<HTMLButtonElement>(null);

  // Keyboard and screen-reader users land in the viewer, and return to the grid after.
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    closeButton.current?.focus();
    return () => opener?.focus();
  }, []);

  useEffect(() => setNote(photo.note), [photo.id, photo.note]);

  const go = useCallback(
    (step: number) => {
      const next = index + step;
      if (next >= 0 && next < photos.length) onIndex(next);
    },
    [index, photos.length, onIndex],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      if (e.key === 'ArrowRight') go(1);
      if (e.key === 'ArrowLeft') go(-1);
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go, onClose]);

  // Preload neighbours so swiping feels instant.
  useEffect(() => {
    [photos[index + 1], photos[index - 1]].forEach((p) => p && (new Image().src = p.preview_url));
  }, [index, photos]);

  const onTouchStart = (e: TouchEvent) => (touchStart.current = e.touches[0].clientX);
  const onTouchEnd = (e: TouchEvent) => {
    if (touchStart.current === null) return;
    const dx = e.changedTouches[0].clientX - touchStart.current;
    if (Math.abs(dx) > 50) go(dx < 0 ? 1 : -1);
    touchStart.current = null;
  };

  return (
    <div className="viewer" role="dialog" aria-modal="true" aria-label="Photo viewer">
      <div className="viewer-top">
        <span>{index + 1} / {photos.length}</span>
        <button ref={closeButton} className="viewer-close" onClick={onClose} aria-label="Close">✕</button>
      </div>
      <div className="viewer-stage" onTouchStart={onTouchStart} onTouchEnd={onTouchEnd}>
        <button className="viewer-nav prev" onClick={() => go(-1)} disabled={index === 0} aria-label="Previous photo">‹</button>
        <img src={photo.preview_url} alt="" />
        <button className="viewer-nav next" onClick={() => go(1)} disabled={index === photos.length - 1} aria-label="Next photo">›</button>
      </div>
      <div className="viewer-bottom">
        <button className={photo.selected ? 'pick picked' : 'pick'} onClick={() => onToggle(photo)} disabled={readOnly} aria-pressed={photo.selected}>
          <HeartIcon filled={photo.selected} size={20} />
          {photo.selected ? 'Chosen' : 'Choose this photo'}
        </button>
        {photo.selected && !readOnly && (
          <form className="note-form" onSubmit={(e) => { e.preventDefault(); onToggle(photo, note); }}>
            <input aria-label="Note for the studio" placeholder="Note for the studio, e.g. album cover" maxLength={500}
              value={note} onChange={(e) => setNote(e.target.value)} />
            <button type="submit" className="secondary" disabled={note === photo.note}>Save note</button>
          </form>
        )}
        {readOnly && photo.note && <p className="muted">Note: {photo.note}</p>}
      </div>
    </div>
  );
}

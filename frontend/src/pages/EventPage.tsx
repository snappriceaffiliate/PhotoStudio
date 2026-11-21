import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router';
import { api, ApiError } from '../api/client';
import { useAuth } from '../auth/AuthContext';
import { Field, FormMessage, useSubmit } from '../components/Form';
import { duplicateNames, EventUploader, toUploadFiles, type Progress, type UploadFile } from '../upload/uploader';
import { ArchivePanel, SelectionPanel } from './SelectionPanel';
import { SharePanel } from './SharePanel';

export interface EventDetail {
  id: string;
  title: string;
  event_date: string | null;
  status: string;
  selection_limit: number | null;
  expires_at: string | null;
  watermark_enabled: boolean;
  watermark_text: string;
  photo_count: number;
}

interface Album {
  id: string;
  name: string;
  photo_count: number;
}

interface PhotoItem {
  id: string;
  relative_path: string;
  original_filename: string;
  thumb_url: string;
  preview_url: string;
}

interface PhotoPage {
  count: number;
  next_page: number | null;
  results: PhotoItem[];
}

export const STATUS_LABELS: Record<string, string> = {
  draft: 'Draft',
  uploading: 'Ready to share',
  shared: 'Shared with client',
  submitted: 'Selection received',
  archived: 'Archived',
};

function formatDuration(seconds: number): string {
  if (!Number.isFinite(seconds) || seconds <= 0) return '';
  if (seconds < 60) return `${Math.ceil(seconds)} s`;
  const minutes = Math.round(seconds / 60);
  return minutes < 60 ? `${minutes} min` : `${Math.floor(minutes / 60)} h ${minutes % 60} min`;
}

const STEPS = [
  { status: 'draft', label: 'Created' },
  { status: 'uploading', label: 'Photos uploaded' },
  { status: 'shared', label: 'Shared with client' },
  { status: 'submitted', label: 'Selection received' },
  { status: 'archived', label: 'Archived' },
];

/** Where the event is in its life, so the studio always knows the next step. */
function EventStepper({ status }: { status: string }) {
  const current = STEPS.findIndex((s) => s.status === status);
  return (
    <ol className="stepper" aria-label="Event progress">
      {STEPS.map((step, i) => (
        <li key={step.status} className={i < current ? 'done' : i === current ? 'current' : ''} aria-current={i === current ? 'step' : undefined}>
          {step.label}
        </li>
      ))}
    </ol>
  );
}

export function EventPage() {
  const { eventId } = useParams();
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [albums, setAlbums] = useState<Album[]>([]);
  const [loadError, setLoadError] = useState('');
  const [photosVersion, setPhotosVersion] = useState(0);
  const navigate = useNavigate();

  const load = useCallback(async () => {
    try {
      const [e, a] = await Promise.all([
        api<EventDetail>(`/events/${eventId}`),
        api<Album[]>(`/events/${eventId}/albums`),
      ]);
      setEvent(e);
      setAlbums(a);
    } catch {
      setLoadError('This event could not be found.');
    }
  }, [eventId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (loadError) return <FormMessage error={loadError} />;
  if (!event) return <p className="muted">Loading event…</p>;

  return (
    <>
      <p className="crumbs"><Link to="/events">Events</Link> / {event.title}</p>
      <div className="page-header">
        <div>
          <h1>{event.title}</h1>
          <p className="muted">
            {event.photo_count} photos · <span className={`status status-${event.status}`}>{STATUS_LABELS[event.status] ?? event.status}</span>
          </p>
        </div>
      </div>
      <EventStepper status={event.status} />

      <div className="two-col">
        <div>
          <SelectionPanel eventId={event.id} version={photosVersion} status={event.status} />
          {event.status !== 'archived' && <UploadPanel
            event={event}
            albums={albums}
            onEventChange={setEvent}
            onProgress={() => setPhotosVersion((v) => v + 1)}
            onFinished={() => {
              void load();
              setPhotosVersion((v) => v + 1);
            }}
          />}
          <PhotoGrid eventId={event.id} version={photosVersion} />
        </div>
        <aside>
          <SharePanel event={event} onChanged={() => { void load(); setPhotosVersion((v) => v + 1); }} />
          <SettingsPanel event={event} onSaved={setEvent} />
          <AlbumsPanel eventId={event.id} albums={albums} onChanged={load} />
          <ArchivePanel eventId={event.id} title={event.title} status={event.status}
            onChanged={() => { void load(); setPhotosVersion((v) => v + 1); }} onDeleted={() => navigate('/events')} />
        </aside>
      </div>
    </>
  );
}

function SettingsPanel({ event, onSaved }: { event: EventDetail; onSaved: (e: EventDetail) => void }) {
  const [form, setForm] = useState({
    title: event.title,
    event_date: event.event_date ?? '',
    selection_limit: event.selection_limit?.toString() ?? '',
    expires_at: event.expires_at ?? '',
    watermark_enabled: event.watermark_enabled,
    watermark_text: event.watermark_text,
  });
  const [saved, setSaved] = useState('');
  const submit = useSubmit(async () => {
    setSaved('');
    const updated = await api<EventDetail>(`/events/${event.id}`, {
      method: 'PATCH',
      body: {
        ...form,
        event_date: form.event_date || null,
        expires_at: form.expires_at || null,
        selection_limit: form.selection_limit ? Number(form.selection_limit) : null,
      },
    });
    onSaved(updated);
    setSaved('Settings saved.');
  });

  return (
    <form className="panel" onSubmit={submit.onSubmit} noValidate>
      <h2>Event settings</h2>
      <FormMessage error={submit.error} success={saved} />
      <Field label="Event name" name="title" required errors={submit.fields}
        value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} />
      <Field label="Event date" name="event_date" type="date" errors={submit.fields}
        value={form.event_date} onChange={(e) => setForm({ ...form, event_date: e.target.value })} />
      <Field label="Photos the client may select" name="selection_limit" type="number" min={1} errors={submit.fields}
        hint="Leave empty for no limit." value={form.selection_limit}
        onChange={(e) => setForm({ ...form, selection_limit: e.target.value })} />
      <Field label="Client link expires on" name="expires_at" type="date" errors={submit.fields}
        value={form.expires_at} onChange={(e) => setForm({ ...form, expires_at: e.target.value })} />
      <label className="check">
        <input type="checkbox" checked={form.watermark_enabled}
          onChange={(e) => setForm({ ...form, watermark_enabled: e.target.checked })} />
        Add a watermark to previews
      </label>
      {form.watermark_enabled && (
        <Field label="Watermark text" name="watermark_text" errors={submit.fields} placeholder="Your studio name"
          hint="Applies to photos uploaded after you save." value={form.watermark_text}
          onChange={(e) => setForm({ ...form, watermark_text: e.target.value })} />
      )}
      <div className="actions">
        <button type="submit" disabled={submit.busy}>{submit.busy ? 'Saving…' : 'Save settings'}</button>
      </div>
    </form>
  );
}

function AlbumsPanel({ eventId, albums, onChanged }: { eventId: string; albums: Album[]; onChanged: () => void }) {
  const [name, setName] = useState('');
  const submit = useSubmit(async () => {
    await api(`/events/${eventId}/albums`, { method: 'POST', body: { name } });
    setName('');
    onChanged();
  });
  return (
    <div className="panel">
      <h2>Albums</h2>
      <p className="muted">Optional. Group photos, for example Engagement, Wedding, Reception.</p>
      {albums.length > 0 && (
        <ul className="plain-list">
          {albums.map((a) => (
            <li key={a.id}>{a.name} <span className="muted">· {a.photo_count} photos</span></li>
          ))}
        </ul>
      )}
      <form onSubmit={submit.onSubmit} noValidate className="inline-form">
        <FormMessage error={submit.error} />
        <Field label="New album" name="name" errors={submit.fields} value={name} onChange={(e) => setName(e.target.value)} />
        <button type="submit" className="secondary" disabled={submit.busy || !name.trim()}>Add album</button>
      </form>
    </div>
  );
}

function UploadPanel({ event, albums, onEventChange, onProgress, onFinished }: {
  event: EventDetail;
  albums: Album[];
  onEventChange: (event: EventDetail) => void;
  onProgress: () => void;
  onFinished: () => void;
}) {
  const { user } = useAuth();
  const [asking, setAsking] = useState<'files' | 'drive' | null>(null);
  const [watermarkOn, setWatermarkOn] = useState(false);
  const [watermarkText, setWatermarkText] = useState('');
  const [watermarkError, setWatermarkError] = useState('');
  const folderInput = useRef<HTMLInputElement>(null);
  const uploader = useRef<EventUploader | null>(null);
  const [files, setFiles] = useState<UploadFile[]>([]);
  const [albumId, setAlbumId] = useState('');
  const [progress, setProgress] = useState<Progress | null>(null);
  const lastRefresh = useRef(0);
  const active = progress && ['preparing', 'uploading', 'paused', 'finishing'].includes(progress.phase);

  useEffect(() => {
    folderInput.current?.setAttribute('webkitdirectory', '');
  }, []);

  useEffect(() => {
    if (!active) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [active]);

  function choose(list: FileList | null) {
    if (!list) return;
    setFiles(toUploadFiles(list));
    setProgress(null);
  }

  /** Before every upload or import, ask whether to watermark the previews (default: the event's setting). */
  function askWatermark(mode: 'files' | 'drive') {
    setWatermarkOn(event.watermark_enabled);
    setWatermarkText(event.watermark_text || user?.studio?.name || '');
    setWatermarkError('');
    setAsking(mode);
  }

  async function confirmAndStart() {
    const text = watermarkText.trim();
    const changed = watermarkOn !== event.watermark_enabled || (watermarkOn && text !== event.watermark_text);
    if (changed) {
      try {
        const body = watermarkOn ? { watermark_enabled: true, watermark_text: text } : { watermark_enabled: false };
        onEventChange(await api<EventDetail>(`/events/${event.id}`, { method: 'PATCH', body }));
      } catch (err) {
        setWatermarkError(err instanceof Error ? err.message : 'Could not save the watermark.');
        return;
      }
    }
    const mode = asking;
    setAsking(null);
    if (mode === 'drive') void drive.start();
    else void start(watermarkOn ? text : undefined);
  }

  const drive = useDriveImport(event.id, albumId, onProgress, onFinished);

  async function start(watermark: string | undefined) {
    const run = new EventUploader((p) => {
      setProgress(p);
      if (Date.now() - lastRefresh.current > 5000) {
        lastRefresh.current = Date.now();
        onProgress();
      }
    });
    uploader.current = run;
    await run.run(event.id, files, {
      albumId: albumId || null,
      watermark,
    });
    onFinished();
  }

  const dupes = duplicateNames(files);
  const remaining = progress ? progress.total - progress.alreadyUploaded : 0;
  // Each photo counts twice: once when it is prepared (compressed), once when it is sent.
  const finished = progress ? progress.sent : 0;
  const elapsed = progress ? (Date.now() - progress.startedAt) / 1000 : 0;
  const perSecond = elapsed > 0 ? finished / elapsed : 0;
  const eta = perSecond > 0 ? (remaining - finished) / perSecond : NaN;
  const percent = progress?.phase === 'done'
    ? 100
    : remaining > 0 ? Math.min(100, Math.round(((progress!.prepared + progress!.sent) / (2 * remaining)) * 100)) : 0;

  return (
    <section className="panel">
      <h2>Upload photos</h2>
      <p className="muted">
        Choose the event's folder. Photos are compressed on this computer first, so only small previews are
        uploaded; RAW originals stay here. You can choose the same folder again later to finish an interrupted upload.
      </p>

      {!active && (
        <div className="controls">
          <label className="button">
            Choose folder
            <input ref={folderInput} type="file" multiple hidden onChange={(e) => choose(e.target.files)} />
          </label>
          <label className="button secondary">
            Choose files
            <input type="file" multiple hidden accept=".jpg,.jpeg,.cr2,.cr3,.nef,.nrw,.arw,.srf,.sr2,.raf,.orf,.rw2,.dng,.pef,.srw"
              onChange={(e) => choose(e.target.files)} />
          </label>
        </div>
      )}

      {files.length > 0 && !active && progress?.phase !== 'done' && (
        <div className="upload-ready">
          <p><strong>{files.length}</strong> photos ready to upload.</p>
          {dupes.length > 0 && (
            <p className="warning">
              {dupes.length} filename{dupes.length > 1 ? 's appear' : ' appears'} in more than one folder
              (for example {dupes[0]}). They are kept apart by folder, so the selection list will show the folder too.
            </p>
          )}
          {albums.length > 0 && (
            <div className="field">
              <label htmlFor="upload-album">Add to album</label>
              <select id="upload-album" value={albumId} onChange={(e) => setAlbumId(e.target.value)}>
                <option value="">No album</option>
                {albums.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
              </select>
            </div>
          )}
          <button onClick={() => askWatermark('files')}>Start upload</button>
        </div>
      )}

      {drive.enabled && !active && (
        <DriveImportBox drive={drive} albums={albums} albumId={albumId} onAlbum={setAlbumId}
          onImport={() => askWatermark('drive')} />
      )}

      {asking && (
        <div className="dialog-backdrop" role="dialog" aria-modal="true" aria-labelledby="watermark-title">
          <div className="dialog">
            <h2 id="watermark-title">Add a watermark?</h2>
            <p className="muted">
              The watermark is drawn on the previews your client sees, in the bottom corner. Your originals are not changed.
            </p>
            <label className="check">
              <input type="radio" name="watermark" checked={!watermarkOn} onChange={() => setWatermarkOn(false)} />
              No watermark
            </label>
            <label className="check">
              <input type="radio" name="watermark" checked={watermarkOn} onChange={() => setWatermarkOn(true)} />
              Add a watermark
            </label>
            {watermarkOn && (
              <Field label="Watermark text" name="watermark_choice" maxLength={80} hint="Usually your studio name."
                value={watermarkText} onChange={(e) => setWatermarkText(e.target.value)} />
            )}
            {watermarkError && <p className="form-error" role="alert">{watermarkError}</p>}
            <div className="actions">
              <button type="button" onClick={confirmAndStart} disabled={watermarkOn && !watermarkText.trim()}>
                {asking === 'drive' ? 'Start import' : 'Start upload'}
              </button>
              <button type="button" className="secondary" onClick={() => setAsking(null)}>Cancel</button>
            </div>
          </div>
        </div>
      )}

      {progress && (
        <div className="upload-progress" aria-live="polite">
          <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
            <span style={{ width: `${percent}%` }} />
          </div>
          <p>
            {progress.phase === 'preparing' && 'Preparing…'}
            {(progress.phase === 'uploading' || progress.phase === 'paused') &&
              `${progress.sent} of ${remaining} uploaded · ${progress.prepared} prepared${progress.phase === 'paused' ? ' · paused' : ''}${eta ? ` · about ${formatDuration(eta)} left` : ''}`}
            {progress.phase === 'finishing' && 'Finishing…'}
            {progress.phase === 'done' && `Done: ${progress.done} uploaded.`}
            {progress.phase === 'cancelled' && `Stopped after ${progress.done} photos. Choose the folder again to continue.`}
            {progress.phase === 'error' && <span className="error">Upload stopped: {progress.message}. Choose the folder again to continue.</span>}
            {progress.alreadyUploaded > 0 && ` ${progress.alreadyUploaded} were already uploaded and were skipped.`}
          </p>
          {active && progress.phase !== 'finishing' && (
            <div className="actions">
              {progress.phase === 'paused'
                ? <button onClick={() => uploader.current?.resume()}>Resume</button>
                : <button className="secondary" onClick={() => uploader.current?.pause()}>Pause</button>}
              <button className="secondary" onClick={() => uploader.current?.cancel()}>Stop</button>
            </div>
          )}
          {progress.failures.length > 0 && (
            <details className="failures">
              <summary>{progress.failures.length} photo{progress.failures.length === 1 ? '' : 's'} could not be uploaded</summary>
              <ul>
                {progress.failures.slice(0, 200).map((f) => <li key={f.path}><code>{f.path}</code>: {f.reason}</li>)}
              </ul>
              <p className="muted">Choose the folder again to retry them.</p>
            </details>
          )}
        </div>
      )}
    </section>
  );
}

interface DriveImport {
  id: string;
  folder_name: string;
  status: 'queued' | 'running' | 'done' | 'failed';
  total: number;
  imported: number;
  skipped: number;
  failed: number;
  failures: { path: string; reason: string }[];
  error: string;
}

type DriveState = ReturnType<typeof useDriveImport>;

const DRIVE_POLL_MS = 3000;

/** Imports from a shared Google Drive folder run on the server; this follows the latest one. */
function useDriveImport(eventId: string, albumId: string, onProgress: () => void, onFinished: () => void) {
  const [enabled, setEnabled] = useState(false);
  const [job, setJob] = useState<DriveImport | null>(null);
  const [link, setLink] = useState('');
  const [error, setError] = useState('');
  const running = job?.status === 'queued' || job?.status === 'running';
  // The page passes new callbacks on every render; keep the latest without restarting the poll.
  const callbacks = useRef({ onProgress, onFinished });
  useEffect(() => {
    callbacks.current = { onProgress, onFinished };
  });

  useEffect(() => {
    api<{ enabled: boolean; imports: DriveImport[] }>(`/events/${eventId}/drive-imports`)
      .then((d) => {
        setEnabled(d.enabled);
        setJob(d.imports[0] ?? null);
      })
      .catch(() => undefined);
  }, [eventId]);

  useEffect(() => {
    if (!running) return;
    const timer = window.setInterval(async () => {
      try {
        const d = await api<{ imports: DriveImport[] }>(`/events/${eventId}/drive-imports`);
        const latest = d.imports[0] ?? null;
        setJob(latest);
        if (latest && (latest.status === 'done' || latest.status === 'failed')) callbacks.current.onFinished();
        else callbacks.current.onProgress();
      } catch {
        // Keep the last known state; the next poll tries again.
      }
    }, DRIVE_POLL_MS);
    return () => window.clearInterval(timer);
  }, [eventId, running]);

  async function start() {
    setError('');
    try {
      const created = await api<DriveImport>(`/events/${eventId}/drive-imports`, {
        method: 'POST',
        body: { link: link.trim(), album_id: albumId || null },
      });
      setJob(created);
      setLink('');
    } catch (err) {
      if (err instanceof ApiError) {
        setError(err.fields.link?.[0] ?? err.message);
      } else {
        setError('Could not start the import.');
      }
    }
  }

  return { enabled, job, running, link, setLink, error, start };
}

function DriveImportBox({ drive, albums, albumId, onAlbum, onImport }: {
  drive: DriveState;
  albums: Album[];
  albumId: string;
  onAlbum: (id: string) => void;
  onImport: () => void;
}) {
  const job = drive.job;
  const toDo = job ? Math.max(0, job.total - job.skipped) : 0;
  const handled = job ? job.imported + job.failed : 0;
  const percent = job?.status === 'done' ? 100 : toDo > 0 ? Math.min(100, Math.round((handled / toDo) * 100)) : 0;
  return (
    <div className="drive-import">
      <h3>Or import from Google Drive</h3>
      {!drive.running && (
        <>
          <p className="muted">
            In Google Drive, share the event folder as “Anyone with the link”, then paste the link here. PickSnap
            copies small previews; your originals stay in Drive. Importing the same folder again adds only new photos.
          </p>
          <div className="drive-row">
            <div className="field">
              <label htmlFor="drive-link">Google Drive folder link</label>
              <input id="drive-link" type="url" inputMode="url" placeholder="https://drive.google.com/drive/folders/…"
                value={drive.link} onChange={(e) => drive.setLink(e.target.value)}
                aria-invalid={drive.error ? true : undefined} />
            </div>
            {albums.length > 0 && (
              <div className="field">
                <label htmlFor="drive-album">Add to album</label>
                <select id="drive-album" value={albumId} onChange={(e) => onAlbum(e.target.value)}>
                  <option value="">No album</option>
                  {albums.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
                </select>
              </div>
            )}
            <button type="button" className="secondary" onClick={onImport} disabled={!drive.link.trim()}>
              Import from Drive
            </button>
          </div>
          {drive.error && <p className="form-error" role="alert">{drive.error}</p>}
        </>
      )}
      {job && (
        <div className="upload-progress" aria-live="polite">
          {drive.running && (
            <div className="bar" role="progressbar" aria-label="Google Drive import" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent}>
              <span style={{ width: `${percent}%` }} />
            </div>
          )}
          <p>
            {job.status === 'queued' && 'Starting the import…'}
            {job.status === 'running' && (job.total
              ? `Importing ${job.folder_name ? `“${job.folder_name}”` : 'the folder'}: ${job.imported} of ${toDo} imported. You can leave this page; the import continues.`
              : 'Reading the folder from Google Drive…')}
            {job.status === 'done' &&
              `Last import${job.folder_name ? ` from “${job.folder_name}”` : ''}: ${job.imported} imported` +
              (job.skipped ? `, ${job.skipped} already here` : '') +
              (job.failed ? `, ${job.failed} could not be imported` : '') + '.'}
            {job.status === 'failed' && <span className="error">Import stopped: {job.error}</span>}
          </p>
          {job.failures.length > 0 && !drive.running && (
            <details className="failures">
              <summary>{job.failed} photo{job.failed === 1 ? '' : 's'} could not be imported</summary>
              <ul>
                {job.failures.map((f) => <li key={f.path}><code>{f.path}</code>: {f.reason}</li>)}
              </ul>
              <p className="muted">RAW files often have no preview in Google Drive. Upload those from your computer instead.</p>
            </details>
          )}
        </div>
      )}
    </div>
  );
}

/** How many photos the event page shows; the rest are on the photos page. */
export const PREVIEW_COUNT = 10;

function PhotoGrid({ eventId, version }: { eventId: string; version: number }) {
  const [photos, setPhotos] = useState<PhotoItem[]>([]);
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState<PhotoItem | null>(null);

  useEffect(() => {
    let current = true;
    api<PhotoPage>(`/events/${eventId}/photos?page=1&page_size=${PREVIEW_COUNT}`).then((data) => {
      if (!current) return;
      setPhotos(data.results);
      setCount(data.count);
    });
    return () => {
      current = false;
    };
  }, [eventId, version]);

  return (
    <section>
      <div className="page-header">
        <h2>Photos <span className="muted">({count})</span></h2>
        {count > 0 && <Link className="button secondary" to={`/events/${eventId}/photos`}>View all {count} photos</Link>}
      </div>
      {count === 0 && <div className="empty"><p>No photos yet. Upload the event folder above.</p></div>}
      <ul className="photo-grid">
        {photos.map((p) => (
          <li key={p.id}>
            <button className="thumb" onClick={() => setOpen(p)} title={p.relative_path}>
              <img src={p.thumb_url} alt={p.original_filename} loading="lazy" />
            </button>
          </li>
        ))}
      </ul>
      {count > photos.length && (
        <p className="muted">
          Showing {photos.length} of {count}. <Link to={`/events/${eventId}/photos`}>See them all, sort them or delete some</Link>.
        </p>
      )}
      {open && (
        <div className="lightbox" onClick={() => setOpen(null)}>
          <img src={open.preview_url} alt={open.original_filename} />
          <p>{open.relative_path} · click to close</p>
        </div>
      )}
    </section>
  );
}

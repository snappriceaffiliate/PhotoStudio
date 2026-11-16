import { useCallback, useEffect, useRef, useState, type DragEvent } from 'react';
import { copySelected, problemsCsv, type CopyProgress, type CopyResult } from './copy.ts';
import { readSelection, SelectionFileError, type Selection } from './csv.ts';
import { canTryDemo, createSample } from './demo.ts';
import { canPickFolders, pickFolder, SELECTED_DIR, type DirHandleLike } from './fs.ts';
import { buildPlan, suggestFolder, type Plan } from './plan.ts';
import { formatBytes } from './report.ts';
import { eventIdFromAddress, loadEventSelection, NotSignedInError, type EventSelection } from './source.ts';

function LogoMark({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="9" fill="var(--primary)" />
      <path d="M8 12V9a1 1 0 0 1 1-1h3M20 8h3a1 1 0 0 1 1 1v3M24 20v3a1 1 0 0 1-1 1h-3M12 24H9a1 1 0 0 1-1-1v-3"
        stroke="var(--on-primary)" strokeWidth="2" strokeLinecap="round" fill="none" />
      <path d="M16 21.2s-5-3-5-6.4a2.8 2.8 0 0 1 5-1.7 2.8 2.8 0 0 1 5 1.7c0 3.4-5 6.4-5 6.4Z" fill="var(--marigold)" />
    </svg>
  );
}

interface Props {
  /** Open the folder picker. Replaced in tests. */
  pick?: () => Promise<DirHandleLike>;
  /** Whether this browser can write to a folder. Replaced in tests. */
  supported?: boolean;
  /** The PickSnap event whose selection to load (from ?event= in the address). Replaced in tests. */
  eventId?: string | null;
  /** Fetches an event's selection from PickSnap. Replaced in tests. */
  loadEvent?: (eventId: string) => Promise<EventSelection>;
}

type LoadedSelection = Selection & { name: string; fromEvent?: boolean };

type Scan = { state: 'idle' } | { state: 'scanning'; checked: number; total: number } | { state: 'done'; plan: Plan; suggestion: string | null };

export default function App({
  pick = pickFolder,
  supported = canPickFolders(),
  eventId = eventIdFromAddress(typeof window === 'undefined' ? '' : window.location.search),
  loadEvent = loadEventSelection,
}: Props) {
  const [selection, setSelection] = useState<LoadedSelection | null>(null);
  const [fileError, setFileError] = useState('');
  const [signedOut, setSignedOut] = useState(false);
  const [loadingEvent, setLoadingEvent] = useState(Boolean(eventId));
  const [folder, setFolder] = useState<DirHandleLike | null>(null);
  const [folderError, setFolderError] = useState('');
  const [scan, setScan] = useState<Scan>({ state: 'idle' });
  const [copying, setCopying] = useState<CopyProgress | null>(null);
  const [result, setResult] = useState<CopyResult | null>(null);
  const [dragging, setDragging] = useState(false);
  const abort = useRef<AbortController | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);

  const plan = scan.state === 'done' ? scan.plan : null;
  const busy = copying !== null;

  // Look through the folder whenever the list or the folder changes.
  useEffect(() => {
    if (!selection || !folder) return;
    let current = true;
    setResult(null);
    setScan({ state: 'scanning', checked: 0, total: selection.photos.length });
    (async () => {
      try {
        const found = await buildPlan(folder, selection.photos, (p) => current && setScan({ state: 'scanning', ...p }));
        const suggestion = found.found.length === 0 ? await suggestFolder(folder, selection.photos) : null;
        if (current) setScan({ state: 'done', plan: found, suggestion });
      } catch (error) {
        if (current) {
          setScan({ state: 'idle' });
          setFolderError(`Could not read that folder: ${error instanceof Error ? error.message : String(error)}`);
        }
      }
    })();
    return () => {
      current = false;
    };
  }, [selection, folder]);

  useEffect(() => {
    if (!busy) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener('beforeunload', warn);
    return () => window.removeEventListener('beforeunload', warn);
  }, [busy]);

  const loadFromEvent = useCallback(async () => {
    if (!eventId) return;
    setLoadingEvent(true);
    setFileError('');
    setSignedOut(false);
    try {
      const loaded = await loadEvent(eventId);
      setSelection({ photos: loaded.photos, duplicates: loaded.duplicates, name: loaded.title, fromEvent: true });
    } catch (error) {
      setSelection(null);
      setSignedOut(error instanceof NotSignedInError);
      setFileError(error instanceof SelectionFileError ? error.message : 'The selection could not be loaded from PickSnap.');
    } finally {
      setLoadingEvent(false);
    }
  }, [eventId, loadEvent]);

  useEffect(() => {
    void loadFromEvent();
  }, [loadFromEvent]);

  const loadFile = useCallback(async (file: File | undefined) => {
    if (!file) return;
    setFileError('');
    try {
      const parsed = readSelection(file.name, await file.text());
      setSelection({ ...parsed, name: file.name });
    } catch (error) {
      setSelection(null);
      setFileError(error instanceof SelectionFileError ? error.message : 'This file could not be read.');
    }
  }, []);

  function onDrop(event: DragEvent) {
    event.preventDefault();
    setDragging(false);
    void loadFile(event.dataTransfer.files[0]);
  }

  async function chooseFolder() {
    setFolderError('');
    try {
      setFolder(await pick());
    } catch (error) {
      if (error instanceof DOMException && error.name === 'AbortError') return; // closed the picker
      setFolderError(`Could not open that folder: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  async function startCopy() {
    if (!folder || !plan) return;
    const controller = new AbortController();
    abort.current = controller;
    setResult(null);
    setCopying({ doneFiles: 0, totalFiles: plan.files.length, doneBytes: 0, totalBytes: plan.totalBytes, current: '' });
    try {
      setResult(await copySelected(folder, plan, { signal: controller.signal, onProgress: setCopying }));
    } finally {
      setCopying(null);
      abort.current = null;
    }
  }

  async function tryDemo() {
    const sample = await createSample();
    const parsed = readSelection(sample.csvName, sample.csvText);
    setSelection({ ...parsed, name: sample.csvName });
    setFolder(sample.folder);
  }

  function downloadProblems() {
    if (!plan) return;
    const blob = new Blob([problemsCsv(plan.missing, result)], { type: 'text/csv;charset=utf-8' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = 'photos-not-copied.csv';
    link.click();
    URL.revokeObjectURL(link.href);
  }

  function startAgain() {
    setSelection(null);
    setFolder(null);
    setScan({ state: 'idle' });
    setResult(null);
    setFileError('');
    setFolderError('');
    void loadFromEvent(); // when opened from an event, bring its selection back
  }

  const problems = (plan?.missing.length ?? 0) + (result?.failed.length ?? 0) + (result?.conflicts.length ?? 0);
  const percent = copying && copying.totalBytes > 0 ? Math.min(100, Math.round((copying.doneBytes / copying.totalBytes) * 100)) : 0;

  return (
    <main className="shell">
      <header className="top">
        <LogoMark />
        <div>
          <h1>Copy tool</h1>
          <p className="lead">Copy the photos your client chose into a new folder, straight from your original folder.</p>
        </div>
      </header>

      <p className="promise">Nothing is uploaded: everything happens on this computer. Your originals are only read, never changed or deleted.</p>

      {!supported && (
        <div className="notice bad" role="alert">
          <strong>This browser can’t copy into a folder.</strong> Open this page in <strong>Chrome or Edge on a computer</strong>
          {typeof window !== 'undefined' && !window.isSecureContext ? ' (and use an https:// address)' : ''}. Safari, Firefox and
          phones cannot do this. Or use the “Copy script” from the event page instead.
        </div>
      )}

      <section className={`card ${selection ? 'done' : ''}`} aria-labelledby="s1">
        <h2 id="s1"><span className="num">1</span> Choose the selection file</h2>
        <p className="help">
          {eventId
            ? 'Loaded for you from the event page. You can also choose a CSV file instead.'
            : 'The CSV you downloaded from the event page (“Spreadsheet (CSV)”). A plain list works too.'}
        </p>
        {loadingEvent && <p className="muted" role="status">Loading the client’s selection from PickSnap…</p>}
        <div
          className={`drop ${dragging ? 'over' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
        >
          <input ref={fileInput} type="file" accept=".csv,.txt,text/csv,text/plain" hidden
            onChange={(e) => { void loadFile(e.target.files?.[0]); e.target.value = ''; }} />
          <button type="button" disabled={busy} onClick={() => fileInput.current?.click()}>
            {selection || eventId ? 'Use a CSV file instead' : 'Choose CSV file'}
          </button>
          <span className="muted">or drop it here</span>
        </div>
        {fileError && (
          <p className="error" role="alert">
            {fileError}
            {signedOut && <> Open <a href="/">PickSnap</a>, log in, then click the button on the event page again.</>}
          </p>
        )}
        {selection && (
          <p className="ok" role="status">
            {selection.fromEvent ? <>Loaded from PickSnap: <strong>{selection.name}</strong></> : <strong>{selection.name}</strong>}
            : {selection.photos.length} {selection.photos.length === 1 ? 'photo' : 'photos'} chosen
            {selection.duplicates > 0 && ` (${selection.duplicates} repeated ${selection.duplicates === 1 ? 'line' : 'lines'} ignored)`}.
          </p>
        )}
      </section>

      <section className={`card ${plan ? 'done' : ''} ${selection ? '' : 'waiting'}`} aria-labelledby="s2">
        <h2 id="s2"><span className="num">2</span> Choose the original photo folder</h2>
        <p className="help">
          Pick the same folder you uploaded from: the one that holds your sub-folders (for example <em>Ceremony</em> and <em>Reception</em>).
          The browser will ask permission to see it and to save into it.
        </p>
        <button type="button" disabled={!selection || !supported || busy} onClick={chooseFolder}>
          {folder ? 'Choose a different folder' : 'Choose folder'}
        </button>
        {folderError && <p className="error" role="alert">{folderError}</p>}

        {scan.state === 'scanning' && (
          <p className="muted" role="status">Looking for your photos… {scan.checked} of {scan.total}</p>
        )}
        {plan && selection && (
          <div role="status">
            {plan.found.length > 0 ? (
              <p className="ok">
                Found <strong>{plan.found.length} of {selection.photos.length}</strong> photos in <strong>{folder?.name}</strong>
                : {plan.files.length} {plan.files.length === 1 ? 'file' : 'files'} ({formatBytes(plan.totalBytes)}), counting each
                RAW, JPEG and sidecar file.
              </p>
            ) : (
              <p className="error">
                None of the photos were found in <strong>{folder?.name}</strong>.
                {scan.state === 'done' && scan.suggestion
                  ? <> Did you mean the folder <strong>{scan.suggestion}</strong> inside it? Choose that one instead.</>
                  : <> Check that this is the same folder you uploaded from.</>}
              </p>
            )}
            {plan.missing.length > 0 && plan.found.length > 0 && (
              <details>
                <summary>{plan.missing.length} {plan.missing.length === 1 ? 'photo was' : 'photos were'} not found</summary>
                <ul className="list">
                  {plan.missing.slice(0, 200).map((m, i) => (
                    <li key={i}>
                      <code>{[...m.photo.folder, m.photo.filename].join('/')}</code>{' '}
                      <span className="muted">{m.reason === 'no-folder' ? 'folder not found' : 'no file with this name'}</span>
                    </li>
                  ))}
                </ul>
                {plan.missing.length > 200 && <p className="muted">Showing the first 200. Download the full list below.</p>}
              </details>
            )}
          </div>
        )}
      </section>

      <section className={`card ${result && !result.cancelled ? 'done' : ''} ${plan && plan.found.length > 0 ? '' : 'waiting'}`} aria-labelledby="s3">
        <h2 id="s3"><span className="num">3</span> Copy the photos</h2>
        {plan && plan.found.length > 0 && !copying && !result && (
          <>
            <p className="help">
              This makes a new folder called <strong>{SELECTED_DIR}</strong> inside <strong>{folder?.name}</strong> and copies
              {' '}{plan.files.length} {plan.files.length === 1 ? 'file' : 'files'} into it, keeping your sub-folders. Make sure the drive has {formatBytes(plan.totalBytes)} free.
            </p>
            <button type="button" onClick={startCopy}>Copy {plan.files.length} {plan.files.length === 1 ? 'file' : 'files'}</button>
          </>
        )}

        {copying && (
          <div aria-live="polite">
            <div className="bar" role="progressbar" aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} aria-label="Copy progress">
              <span style={{ width: `${percent}%` }} />
            </div>
            <p>
              Copying file {Math.min(copying.doneFiles + 1, copying.totalFiles)} of {copying.totalFiles} · {formatBytes(copying.doneBytes)} of {formatBytes(copying.totalBytes)}
            </p>
            <p className="muted file">{copying.current}</p>
            <button type="button" className="secondary" onClick={() => abort.current?.abort()}>Stop</button>
          </div>
        )}

        {result && (
          <div role="status">
            {result.cancelled ? (
              <p className="notice warn">Stopped. {result.copied} {result.copied === 1 ? 'file was' : 'files were'} copied; the one being copied was removed so nothing is half-done.</p>
            ) : (
              <p className="ok big">
                Done. {result.copied} {result.copied === 1 ? 'file' : 'files'} ({formatBytes(result.bytes)}) copied into the <strong>{SELECTED_DIR}</strong> folder inside <strong>{folder?.name}</strong>.
              </p>
            )}
            {result.skipped > 0 && <p className="muted">{result.skipped} {result.skipped === 1 ? 'file was' : 'files were'} already there and left as they were.</p>}
            {result.conflicts.length > 0 && (
              <p className="error">{result.conflicts.length} {result.conflicts.length === 1 ? 'file' : 'files'} not replaced because a different file with the same name is already in {SELECTED_DIR}.</p>
            )}
            {result.failed.length > 0 && (
              <details open>
                <summary className="error">{result.failed.length} {result.failed.length === 1 ? 'file' : 'files'} could not be copied</summary>
                <ul className="list">
                  {result.failed.slice(0, 50).map((f) => <li key={f.path}><code>{f.path}</code> <span className="muted">{f.reason}</span></li>)}
                </ul>
              </details>
            )}
            <div className="actions">
              {result.cancelled && <button type="button" onClick={startCopy}>Continue copying</button>}
              {problems > 0 && <button type="button" className="secondary" onClick={downloadProblems}>Download list of problems</button>}
              <button type="button" className="secondary" onClick={startAgain}>Start again</button>
            </div>
            {!result.cancelled && <p className="muted">Open the {SELECTED_DIR} folder in Finder or File Explorer to find your copies.</p>}
          </div>
        )}
      </section>

      <footer className="foot">
        {canTryDemo() && !busy && <button type="button" className="link" onClick={tryDemo}>Try it with sample files</button>}
        <span className="muted">Uses the same rules as the Mac and Windows copy scripts: every file with the chosen photo’s name is copied.</span>
      </footer>
    </main>
  );
}

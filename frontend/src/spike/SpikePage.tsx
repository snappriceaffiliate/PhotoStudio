import { useEffect, useMemo, useRef, useState } from 'react';
import { extensionOf, JPEG_EXTENSIONS, MAX_IMAGE_BYTES, RAW_EXTENSIONS, type CompressResult } from '../compression/compress';
import { CompressionPool, defaultPoolSize } from '../compression/pool';
import { requestUploadUrl, uploadAndConfirm } from '../api/spike';

interface Row {
  path: string;
  name: string;
  extension: string;
  status: 'queued' | 'done' | 'failed';
  result?: CompressResult;
  error?: string;
  ms?: number;
  previewUrl?: string;
  upload?: { state: 'uploading' | 'stored' | 'failed'; size?: number; url?: string; error?: string };
}

const SUPPORTED = new Set([...RAW_EXTENSIONS, ...JPEG_EXTENSIONS]);
const kb = (bytes: number) => (bytes / 1024).toFixed(1);

function summarize(rows: Row[]) {
  const done = rows.filter((r) => r.status === 'done');
  const byExt = new Map<string, { total: number; ok: number; failed: number }>();
  for (const r of rows) {
    const e = byExt.get(r.extension) ?? { total: 0, ok: 0, failed: 0 };
    e.total += 1;
    if (r.status === 'done') e.ok += 1;
    if (r.status === 'failed') e.failed += 1;
    byExt.set(r.extension, e);
  }
  const sizes = done.map((r) => r.result!.preview.blob.size);
  const times = done.map((r) => r.result!.ms);
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
  return {
    byExt: [...byExt.entries()].sort(),
    done: done.length,
    failed: rows.filter((r) => r.status === 'failed').length,
    queued: rows.filter((r) => r.status === 'queued').length,
    avgPreview: avg(sizes),
    maxPreview: sizes.length ? Math.max(...sizes) : 0,
    avgMs: avg(times),
  };
}

function toCsv(rows: Row[]): string {
  const head = ['path', 'extension', 'status', 'source', 'source_px', 'preview_px', 'preview_kb', 'preview_quality', 'ms', 'error'];
  const lines = rows.map((r) => {
    const x = r.result;
    return [
      r.path,
      r.extension,
      r.status,
      x?.source ?? '',
      x ? `${x.sourceWidth}x${x.sourceHeight}` : '',
      x ? `${x.preview.width}x${x.preview.height}` : '',
      x ? kb(x.preview.blob.size) : '',
      x ? x.preview.quality : '',
      x?.ms ?? r.ms ?? '',
      r.error ?? '',
    ]
      .map((v) => `"${String(v).replaceAll('"', '""')}"`)
      .join(',');
  });
  return [head.join(','), ...lines].join('\n');
}

export default function SpikePage() {
  const [rows, setRows] = useState<Row[]>([]);
  const [watermarkOn, setWatermarkOn] = useState(false);
  const [watermark, setWatermark] = useState('Studio name');
  const [running, setRunning] = useState(false);
  const [lightbox, setLightbox] = useState<Row | null>(null);
  const [limitCheck, setLimitCheck] = useState<string>('');
  const folderInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    folderInput.current?.setAttribute('webkitdirectory', '');
  }, []);

  const summary = useMemo(() => summarize(rows), [rows]);

  const update = (path: string, patch: Partial<Row>) =>
    setRows((prev) => prev.map((r) => (r.path === path ? { ...r, ...patch } : r)));

  async function run(fileList: FileList | null) {
    if (!fileList?.length) return;
    rows.forEach((r) => r.previewUrl && URL.revokeObjectURL(r.previewUrl));
    const files = [...fileList].filter((f) => SUPPORTED.has(extensionOf(f.name)));
    const fresh: Row[] = files.map((f) => ({
      path: f.webkitRelativePath || f.name,
      name: f.name,
      extension: extensionOf(f.name),
      status: 'queued',
    }));
    setRows(fresh);
    setRunning(true);
    const pool = new CompressionPool(defaultPoolSize(), { watermark: watermarkOn ? watermark : undefined });
    await Promise.all(
      files.map(async (file, i) => {
        const outcome = await pool.compress(file, fresh[i].path);
        if (outcome.ok) {
          update(outcome.path, {
            status: 'done',
            result: outcome.result,
            previewUrl: URL.createObjectURL(outcome.result.preview.blob),
          });
        } else {
          update(outcome.path, { status: 'failed', error: outcome.error, ms: outcome.ms });
        }
      }),
    );
    pool.terminate();
    setRunning(false);
  }

  async function uploadSample() {
    const sample = rows.filter((r) => r.status === 'done').slice(0, 5);
    for (const r of sample) {
      update(r.path, { upload: { state: 'uploading' } });
      try {
        const stored = await uploadAndConfirm(r.name.replace(/\.[^.]+$/, '.webp'), r.result!.preview.blob);
        update(r.path, { upload: { state: 'stored', size: stored.size, url: stored.downloadUrl } });
      } catch (error) {
        update(r.path, { upload: { state: 'failed', error: String(error) } });
      }
    }
  }

  async function checkLimit() {
    try {
      await requestUploadUrl('too-big.webp', 'image/webp', MAX_IMAGE_BYTES + 1);
      setLimitCheck('Not refused: the server accepted an image over the size limit.');
    } catch (error) {
      setLimitCheck(`Refused as expected (${String(error).slice(0, 120)})`);
    }
  }

  function downloadCsv() {
    const url = URL.createObjectURL(new Blob([toCsv(rows)], { type: 'text/csv' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'compression-spike-report.csv';
    a.click();
    URL.revokeObjectURL(url);
  }

  const stored = rows.filter((r) => r.upload);

  return (
    <main>
      <header>
        <h1>Sprint 0 spikes</h1>
        <p>
          Checks the two riskiest parts of the upload: getting a preview out of RAW files in the browser, and fitting every
          each photo into one image of at most 40 KB. Files never leave this computer unless you use the storage test.
        </p>
      </header>

      <section className="card">
        <h2>1. Compression</h2>
        <div className="controls">
          <label className="button">
            Choose a folder
            <input ref={folderInput} type="file" multiple hidden onChange={(e) => run(e.target.files)} disabled={running} />
          </label>
          <label className="button secondary">
            Choose files
            <input type="file" multiple hidden onChange={(e) => run(e.target.files)} disabled={running} />
          </label>
          <label className="check">
            <input type="checkbox" checked={watermarkOn} onChange={(e) => setWatermarkOn(e.target.checked)} /> Watermark
          </label>
          {watermarkOn && <input className="text" value={watermark} onChange={(e) => setWatermark(e.target.value)} />}
          <span className="hint">
            Supported: {RAW_EXTENSIONS.join(', ')}, {JPEG_EXTENSIONS.join(', ')}. Using {defaultPoolSize()} workers.
          </span>
        </div>

        {rows.length > 0 && (
          <>
            <dl className="stats">
              <div><dt>Done</dt><dd>{summary.done} / {rows.length}</dd></div>
              <div><dt>Failed</dt><dd className={summary.failed ? 'bad' : ''}>{summary.failed}</dd></div>
              <div><dt>Avg preview</dt><dd>{kb(summary.avgPreview)} KB</dd></div>
              <div><dt>Largest preview</dt><dd className={summary.maxPreview > MAX_IMAGE_BYTES ? 'bad' : ''}>{kb(summary.maxPreview)} KB</dd></div>
              <div><dt>Avg time per photo</dt><dd>{Math.round(summary.avgMs)} ms</dd></div>
            </dl>
            <p className="hint">
              By type:{' '}
              {summary.byExt.map(([ext, s]) => `.${ext} ${s.ok}/${s.total} ok${s.failed ? `, ${s.failed} failed` : ''}`).join(' · ')}
              {running && ` · ${summary.queued} still running`}
            </p>
            <div className="controls">
              <button className="secondary" onClick={downloadCsv} disabled={running}>Download CSV report</button>
            </div>
            <div className="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th></th><th>File</th><th>Source</th><th>Original px</th><th>Preview px</th>
                    <th>Preview KB</th><th>Quality</th><th>ms</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.path} className={r.status} onClick={() => r.previewUrl && setLightbox(r)}>
                      <td>{r.previewUrl ? <img src={r.previewUrl} alt="" /> : <span className="dot" />}</td>
                      <td title={r.path}>{r.path}{r.error && <div className="error">{r.error}</div>}</td>
                      <td>{r.result?.source === 'embedded-jpeg' ? 'RAW preview' : r.result ? 'JPEG' : r.status}</td>
                      <td>{r.result && `${r.result.sourceWidth} × ${r.result.sourceHeight}`}</td>
                      <td>{r.result && `${r.result.preview.width} × ${r.result.preview.height}`}</td>
                      <td>{r.result && kb(r.result.preview.blob.size)}</td>
                      <td>{r.result?.preview.quality}</td>
                      <td>{r.result?.ms ?? r.ms}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </section>

      <section className="card">
        <h2>2. Storage</h2>
        <p className="hint">
          Uploads the first five previews straight to storage with signed URLs, has the server check each size, then
          shows them through signed delivery URLs. Needs the backend running with SPIKES_ENABLED=true.
        </p>
        <div className="controls">
          <button onClick={uploadSample} disabled={running || summary.done === 0}>Upload 5 previews</button>
          <button className="secondary" onClick={checkLimit}>Check size limit refusal</button>
          {limitCheck && <span className="hint">{limitCheck}</span>}
        </div>
        {stored.length > 0 && (
          <div className="grid">
            {stored.map((r) => (
              <figure key={r.path}>
                {r.upload?.url ? <img src={r.upload.url} alt={r.name} /> : <div className="placeholder">{r.upload?.state}</div>}
                <figcaption>
                  {r.name}
                  <br />
                  {r.upload?.state === 'stored' && `Stored, ${kb(r.upload.size!)} KB, served by signed URL`}
                  {r.upload?.state === 'failed' && <span className="error">{r.upload.error}</span>}
                </figcaption>
              </figure>
            ))}
          </div>
        )}
      </section>

      {lightbox?.previewUrl && (
        <div className="lightbox" onClick={() => setLightbox(null)}>
          <img src={lightbox.previewUrl} alt={lightbox.name} />
          <p>
            {lightbox.path} · {lightbox.result!.preview.width} × {lightbox.result!.preview.height} ·{' '}
            {kb(lightbox.result!.preview.blob.size)} KB · quality {lightbox.result!.preview.quality} · click to close
          </p>
        </div>
      )}
    </main>
  );
}

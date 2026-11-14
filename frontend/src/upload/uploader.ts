/**
 * Uploads a folder of photos to one event.
 *
 * Each photo is compressed in a web worker into a WebP preview and thumbnail (each at most
 * 100 KB), sent straight to storage with signed URLs, then confirmed by the server.
 * Work runs in batches: the next batch compresses while the current one uploads.
 * The run is resumable: choosing the same folder again skips photos already stored.
 */
import { api } from '../api/client';
import { extensionOf, JPEG_EXTENSIONS, RAW_EXTENSIONS, type CompressResult } from '../compression/compress';
import { CompressionPool, defaultPoolSize } from '../compression/pool';

export const SUPPORTED_EXTENSIONS = new Set([...RAW_EXTENSIONS, ...JPEG_EXTENSIONS]);
const REGISTER_CHUNK = 2000;
const BATCH = 12;
const PUT_CONCURRENCY = 6;
const RETRIES = 3;

export interface UploadFile {
  file: File;
  path: string; // relative to the chosen folder, e.g. "Ceremony/DSC_0001.NEF"
}

export interface Failure {
  path: string;
  reason: string;
}

export interface Progress {
  phase: 'preparing' | 'uploading' | 'paused' | 'finishing' | 'done' | 'cancelled' | 'error';
  total: number;
  alreadyUploaded: number;
  done: number;
  failures: Failure[];
  bytesSent: number;
  startedAt: number;
  message?: string;
}

interface Registered {
  id: string;
  relative_path: string;
  status: 'pending' | 'ready' | 'failed';
}

/** Paths relative to the chosen folder: the folder's own name is dropped. */
export function toUploadFiles(list: FileList | File[]): UploadFile[] {
  return [...list]
    .filter((f) => SUPPORTED_EXTENSIONS.has(extensionOf(f.name)))
    .map((file) => {
      const rel = file.webkitRelativePath || file.name;
      const parts = rel.split('/');
      return { file, path: parts.length > 1 ? parts.slice(1).join('/') : rel };
    })
    .sort((a, b) => a.path.localeCompare(b.path, undefined, { numeric: true }));
}

/** Filenames that appear in more than one folder: worth a warning, though they upload fine. */
export function duplicateNames(files: UploadFile[]): string[] {
  const seen = new Map<string, number>();
  for (const f of files) seen.set(f.file.name.toLowerCase(), (seen.get(f.file.name.toLowerCase()) ?? 0) + 1);
  return [...seen.entries()].filter(([, n]) => n > 1).map(([name]) => name);
}

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function withRetry<T>(work: () => Promise<T>): Promise<T> {
  let lastError: unknown;
  for (let attempt = 0; attempt <= RETRIES; attempt += 1) {
    try {
      return await work();
    } catch (error) {
      lastError = error;
      if (attempt < RETRIES) await sleep(1000 * 2 ** attempt);
    }
  }
  throw lastError;
}

async function putObject(url: string, blob: Blob) {
  await withRetry(async () => {
    const response = await fetch(url, { method: 'PUT', body: blob, headers: { 'Content-Type': 'image/webp' } });
    if (!response.ok) throw new Error(`Storage returned ${response.status}`);
  });
}

async function runLimited<T>(items: T[], limit: number, work: (item: T) => Promise<void>) {
  let next = 0;
  const lanes = Array.from({ length: Math.min(limit, items.length) }, async () => {
    while (next < items.length) await work(items[next++]);
  });
  await Promise.all(lanes);
}

export class EventUploader {
  private paused = false;
  private cancelled = false;
  private progress: Progress;
  private readonly onProgress: (p: Progress) => void;

  constructor(onProgress: (p: Progress) => void) {
    this.onProgress = onProgress;
    this.progress = { phase: 'preparing', total: 0, alreadyUploaded: 0, done: 0, failures: [], bytesSent: 0, startedAt: Date.now() };
  }

  pause() {
    this.paused = true;
    this.emit({ phase: 'paused' });
  }

  resume() {
    this.paused = false;
    this.emit({ phase: 'uploading' });
  }

  cancel() {
    this.cancelled = true;
    this.paused = false;
  }

  private emit(patch: Partial<Progress>) {
    this.progress = { ...this.progress, ...patch };
    this.onProgress(this.progress);
  }

  private fail(path: string, reason: string) {
    this.emit({ failures: [...this.progress.failures, { path, reason }] });
  }

  private async waitWhilePaused() {
    while (this.paused && !this.cancelled) await sleep(250);
  }

  async run(eventId: string, files: UploadFile[], options: { albumId?: string | null; watermark?: string }) {
    this.emit({ phase: 'preparing', total: files.length, startedAt: Date.now() });
    try {
      const { id: uploadId } = await api<{ id: string }>(`/events/${eventId}/uploads`, { method: 'POST' });

      const registered = new Map<string, Registered>();
      for (let i = 0; i < files.length; i += REGISTER_CHUNK) {
        const chunk = files.slice(i, i + REGISTER_CHUNK);
        const body = { files: chunk.map((f) => ({ relative_path: f.path, album_id: options.albumId ?? null })) };
        const { files: rows } = await api<{ files: Registered[] }>(`/uploads/${uploadId}/files`, { method: 'POST', body });
        rows.forEach((r) => registered.set(r.relative_path, r));
      }

      const todo = files.filter((f) => registered.get(f.path)?.status !== 'ready');
      this.emit({ phase: 'uploading', alreadyUploaded: files.length - todo.length, startedAt: Date.now() });

      const pool = new CompressionPool(defaultPoolSize(), { watermark: options.watermark });
      try {
        const batches: UploadFile[][] = [];
        for (let i = 0; i < todo.length; i += BATCH) batches.push(todo.slice(i, i + BATCH));

        let compressing = batches.length ? this.compressBatch(pool, batches[0]) : null;
        for (let b = 0; b < batches.length && !this.cancelled; b += 1) {
          const compressed = await compressing!;
          compressing = b + 1 < batches.length ? this.compressBatch(pool, batches[b + 1]) : null;
          await this.waitWhilePaused();
          if (this.cancelled) break;
          await this.uploadBatch(uploadId, compressed, registered);
        }
      } finally {
        pool.terminate();
      }

      this.emit({ phase: 'finishing' });
      await api(`/uploads/${uploadId}/complete`, { method: 'POST' });
      this.emit({ phase: this.cancelled ? 'cancelled' : 'done' });
    } catch (error) {
      this.emit({ phase: 'error', message: error instanceof Error ? error.message : String(error) });
    }
  }

  private async compressBatch(pool: CompressionPool, batch: UploadFile[]) {
    const outcomes = await Promise.all(batch.map((f) => pool.compress(f.file, f.path)));
    const ok: { path: string; result: CompressResult }[] = [];
    for (const o of outcomes) {
      if (o.ok) ok.push({ path: o.path, result: o.result });
      else this.fail(o.path, o.error);
    }
    return ok;
  }

  private async uploadBatch(uploadId: string, items: { path: string; result: CompressResult }[], registered: Map<string, Registered>) {
    if (!items.length) return;
    const byId = new Map(items.map((i) => [registered.get(i.path)!.id, i]));
    const { urls } = await withRetry(() =>
      api<{ urls: { id: string; preview_url: string; thumb_url: string }[] }>(`/uploads/${uploadId}/urls`, {
        method: 'POST',
        body: { photo_ids: [...byId.keys()] },
      }),
    );

    const sent: string[] = [];
    await runLimited(urls, PUT_CONCURRENCY, async (u) => {
      const item = byId.get(u.id)!;
      try {
        await putObject(u.preview_url, item.result.preview.blob);
        await putObject(u.thumb_url, item.result.thumb.blob);
        sent.push(u.id);
        this.emit({ bytesSent: this.progress.bytesSent + item.result.preview.blob.size + item.result.thumb.blob.size });
      } catch (error) {
        this.fail(item.path, `Upload failed: ${error instanceof Error ? error.message : String(error)}`);
      }
    });
    if (!sent.length) return;

    const photos = sent.map((id) => {
      const r = byId.get(id)!.result;
      return { id, width: r.preview.width, height: r.preview.height, source: r.source === 'embedded-jpeg' ? 'raw' : 'jpeg' };
    });
    const { results } = await withRetry(() =>
      api<{ results: (Registered & { failure_reason: string })[] }>(`/uploads/${uploadId}/confirm`, {
        method: 'POST',
        body: { photos },
      }),
    );
    let ready = 0;
    for (const r of results) {
      if (r.status === 'ready') ready += 1;
      else this.fail(r.relative_path, r.failure_reason || 'Not accepted by the server');
    }
    this.emit({ done: this.progress.done + ready });
  }
}

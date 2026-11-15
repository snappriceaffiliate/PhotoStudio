// @vitest-environment jsdom
/** A whole upload run: register, compress in batches, send to storage, confirm. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { EventUploader, type Progress, type UploadFile } from './uploader';

const pool = vi.hoisted(() => ({
  options: [] as unknown[],
  terminated: 0,
  compress: null as null | ((file: File, path: string) => Promise<unknown>),
}));

vi.mock('../compression/pool', () => ({
  defaultPoolSize: () => 1,
  CompressionPool: class {
    constructor(_size: number, options: unknown) {
      pool.options.push(options);
    }
    compress(file: File, path: string) {
      return pool.compress!(file, path);
    }
    terminate() {
      pool.terminated += 1;
    }
  },
}));

const compressed = (file: File, path: string, source = 'jpeg') => ({
  ok: true as const, file, path,
  result: {
    source, preview: { blob: new Blob(['preview']), width: 1600, height: 1067 },
    thumb: { blob: new Blob(['thumb']), width: 400, height: 267 },
  },
});

const files = (n: number, ext = 'jpg'): UploadFile[] =>
  Array.from({ length: n }, (_, i) => ({ file: new File(['x'], `IMG_${i}.${ext}`), path: `Day/IMG_${String(i).padStart(3, '0')}.${ext}` }));

interface Calls { method: string; url: string; body: any }
let calls: Calls[];
let alreadyReady: Set<string>;
let rejected: Map<string, string>;
let putStatus: (url: string) => number;
let startError: Response | null;

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

beforeEach(() => {
  calls = [];
  alreadyReady = new Set();
  rejected = new Map();
  putStatus = () => 200;
  startError = null;
  pool.options = [];
  pool.terminated = 0;
  pool.compress = async (file, path) => compressed(file, path);
  document.cookie = 'csrftoken=t';
  vi.stubGlobal('fetch', vi.fn(async (input: string, init: RequestInit = {}) => {
    const url = String(input);
    const method = init.method ?? 'GET';
    const body = typeof init.body === 'string' ? JSON.parse(init.body) : init.body;
    calls.push({ method, url, body });
    if (method === 'PUT') return new Response(null, { status: putStatus(url) });
    if (url === '/api/v1/events/e1/uploads') return startError ?? json({ id: 'u1' });
    if (url === '/api/v1/uploads/u1/files') {
      return json({
        files: body.files.map((f: { relative_path: string }) => ({
          id: `id:${f.relative_path}`, relative_path: f.relative_path,
          status: alreadyReady.has(f.relative_path) ? 'ready' : 'pending',
        })),
      });
    }
    if (url === '/api/v1/uploads/u1/urls') {
      return json({
        urls: body.photo_ids.map((id: string) => ({ id, preview_url: `https://r2.test/${id}/preview`, thumb_url: `https://r2.test/${id}/thumb` })),
      });
    }
    if (url === '/api/v1/uploads/u1/confirm') {
      return json({
        results: body.photos.map((p: { id: string }) => {
          const path = p.id.replace('id:', '');
          return rejected.has(path)
            ? { id: p.id, relative_path: path, status: 'failed', failure_reason: rejected.get(path) }
            : { id: p.id, relative_path: path, status: 'ready', failure_reason: '' };
        }),
      });
    }
    if (url === '/api/v1/uploads/u1/complete') return new Response(null, { status: 204 });
    return json({ detail: `unexpected ${method} ${url}` }, 404);
  }));
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

async function run(list: UploadFile[], options: { albumId?: string | null; watermark?: string } = {}, onProgress?: (p: Progress, u: EventUploader) => void) {
  const seen: Progress[] = [];
  const uploader: EventUploader = new EventUploader((p) => {
    seen.push(p);
    onProgress?.(p, uploader);
  });
  await uploader.run('e1', list, options);
  return { seen, last: seen[seen.length - 1], uploader };
}

const puts = () => calls.filter((c) => c.method === 'PUT');
const posts = (suffix: string) => calls.filter((c) => c.method === 'POST' && c.url.endsWith(suffix));

describe('a successful upload', () => {
  it('registers, sends previews and thumbnails, confirms and finishes', async () => {
    const { last } = await run(files(3));
    expect(last).toMatchObject({ phase: 'done', total: 3, done: 3, alreadyUploaded: 0, failures: [] });
    expect(puts()).toHaveLength(6); // a preview and a thumbnail for each photo
    expect(puts().every((c) => (c.body as Blob).size > 0)).toBe(true);
    expect(posts('/complete')).toHaveLength(1);
    expect(pool.terminated).toBe(1);
  });

  it('registers every path once, in order, with the album', async () => {
    await run(files(2), { albumId: 'a1' });
    expect(posts('/files')[0].body.files).toEqual([
      { relative_path: 'Day/IMG_000.jpg', album_id: 'a1' },
      { relative_path: 'Day/IMG_001.jpg', album_id: 'a1' },
    ]);
  });

  it('confirms the size of each preview and where it came from', async () => {
    pool.compress = async (file, path) => compressed(file, path, 'embedded-jpeg');
    await run(files(1, 'nef'));
    expect(posts('/confirm')[0].body.photos).toEqual([{ id: 'id:Day/IMG_000.nef', width: 1600, height: 1067, source: 'raw' }]);
  });

  it('works through large folders in batches of 12', async () => {
    const { last } = await run(files(30));
    expect(last).toMatchObject({ phase: 'done', done: 30 });
    expect(posts('/urls')).toHaveLength(3); // 12 + 12 + 6
    expect(posts('/confirm')).toHaveLength(3);
    expect(posts('/urls')[2].body.photo_ids).toHaveLength(6);
  });

  it('passes the watermark text to the compressor', async () => {
    await run(files(1), { watermark: 'Lens and Light' });
    expect(pool.options[0]).toEqual({ watermark: 'Lens and Light' });
  });

  it('reports progress as it goes', async () => {
    const { seen } = await run(files(2));
    expect(seen[0].phase).toBe('preparing');
    expect(seen.map((p) => p.phase)).toContain('uploading');
    expect(seen.map((p) => p.phase)).toContain('finishing');
    expect(seen[seen.length - 1].bytesSent).toBeGreaterThan(0);
  });
});

describe('resuming', () => {
  it('skips photos the server already has', async () => {
    alreadyReady = new Set(['Day/IMG_000.jpg']);
    const { last } = await run(files(3));
    expect(last).toMatchObject({ phase: 'done', alreadyUploaded: 1, done: 2 });
    expect(puts()).toHaveLength(4);
    expect(posts('/urls')[0].body.photo_ids).toEqual(['id:Day/IMG_001.jpg', 'id:Day/IMG_002.jpg']);
  });

  it('finishes cleanly when everything is already uploaded', async () => {
    alreadyReady = new Set(files(2).map((f) => f.path));
    const { last } = await run(files(2));
    expect(last).toMatchObject({ phase: 'done', alreadyUploaded: 2, done: 0 });
    expect(puts()).toHaveLength(0);
    expect(posts('/urls')).toHaveLength(0);
  });
});

describe('when things go wrong', () => {
  it('lists a photo that could not be compressed and uploads the rest', async () => {
    pool.compress = async (file, path) =>
      path.endsWith('001.jpg') ? { ok: false, file, path, error: 'Cannot read this image', ms: 5 } : compressed(file, path);
    const { last } = await run(files(3));
    expect(last.phase).toBe('done');
    expect(last.done).toBe(2);
    expect(last.failures).toEqual([{ path: 'Day/IMG_001.jpg', reason: 'Cannot read this image' }]);
  });

  it('lists a photo the server refuses, with its reason', async () => {
    rejected.set('Day/IMG_002.jpg', 'Not a WebP image');
    const { last } = await run(files(3));
    expect(last.done).toBe(2);
    expect(last.failures).toEqual([{ path: 'Day/IMG_002.jpg', reason: 'Not a WebP image' }]);
  });

  it('a refusal without a reason still says something', async () => {
    rejected.set('Day/IMG_000.jpg', '');
    const { last } = await run(files(1));
    expect(last.failures[0].reason).toBe('Not accepted by the server');
  });

  it('retries a storage failure, then reports the photo and carries on', async () => {
    vi.useFakeTimers();
    putStatus = (url) => (url.includes('IMG_001') || url.includes('id:Day/IMG_001') ? 500 : 200);
    const pending = run(files(2));
    await vi.advanceTimersByTimeAsync(20_000); // the waits between retries
    const { last } = await pending;
    expect(last.phase).toBe('done');
    expect(last.failures).toHaveLength(1);
    expect(last.failures[0]).toMatchObject({ path: 'Day/IMG_001.jpg' });
    expect(last.failures[0].reason).toContain('Upload failed: Storage returned 500');
    expect(last.done).toBe(1);
  });

  it('recovers when storage fails once and then works', async () => {
    vi.useFakeTimers();
    let failures = 1;
    putStatus = () => (failures-- > 0 ? 503 : 200);
    const pending = run(files(1));
    await vi.advanceTimersByTimeAsync(5_000);
    const { last } = await pending;
    expect(last).toMatchObject({ phase: 'done', done: 1, failures: [] });
  });

  it('stops with the server message when the upload cannot start', async () => {
    startError = json({ detail: 'Your plan allows 5,000 photos per event.' }, 402);
    const { last } = await run(files(1));
    expect(last.phase).toBe('error');
    expect(last.message).toBe('Your plan allows 5,000 photos per event.');
    expect(puts()).toHaveLength(0);
  });
});

describe('stopping', () => {
  it('cancelling ends the run without sending more, and still closes the upload', async () => {
    const { last } = await run(files(30), {}, (p, u) => {
      if (p.phase === 'uploading') u.cancel();
    });
    expect(last.phase).toBe('cancelled');
    expect(last.done).toBe(0);
    expect(puts()).toHaveLength(0);
    expect(posts('/complete')).toHaveLength(1);
    expect(pool.terminated).toBe(1);
  });

  it('pause and resume announce themselves', async () => {
    const seen: string[] = [];
    const uploader = new EventUploader((p) => seen.push(p.phase));
    uploader.pause();
    uploader.resume();
    expect(seen).toEqual(['paused', 'uploading']);
  });
});

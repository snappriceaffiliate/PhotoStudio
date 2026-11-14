import type { CompressOptions, CompressResult } from './compress';
import type { WorkerRequest } from './compress.worker';

export type PoolOutcome =
  | { ok: true; file: File; path: string; result: CompressResult }
  | { ok: false; file: File; path: string; error: string; ms: number };

interface Job {
  file: File;
  path: string;
  started: number;
  resolve: (outcome: PoolOutcome) => void;
}

/** Runs compression in a few web workers so the page stays responsive. */
export class CompressionPool {
  private workers: Worker[] = [];
  private idle: Worker[] = [];
  private queue: { file: File; path: string; resolve: Job['resolve'] }[] = [];
  private running = new Map<number, Job>();
  private nextId = 1;
  private options: CompressOptions;

  constructor(size: number, options: CompressOptions) {
    this.options = options;
    for (let i = 0; i < size; i += 1) {
      const worker = new Worker(new URL('./compress.worker.ts', import.meta.url), { type: 'module' });
      worker.onmessage = (event: MessageEvent<{ id: number; result?: CompressResult; error?: string }>) => {
        const job = this.running.get(event.data.id);
        if (!job) return;
        this.running.delete(event.data.id);
        job.resolve(
          event.data.result
            ? { ok: true, file: job.file, path: job.path, result: event.data.result }
            : { ok: false, file: job.file, path: job.path, error: event.data.error ?? 'Unknown error', ms: Math.round(performance.now() - job.started) },
        );
        this.idle.push(worker);
        this.pump();
      };
      this.workers.push(worker);
      this.idle.push(worker);
    }
  }

  compress(file: File, path: string): Promise<PoolOutcome> {
    return new Promise((resolve) => {
      this.queue.push({ file, path, resolve });
      this.pump();
    });
  }

  private pump() {
    while (this.idle.length && this.queue.length) {
      const worker = this.idle.pop()!;
      const next = this.queue.shift()!;
      const id = this.nextId++;
      this.running.set(id, { ...next, started: performance.now() });
      const request: WorkerRequest = { id, file: next.file, path: next.path, options: this.options };
      worker.postMessage(request);
    }
  }

  terminate() {
    this.workers.forEach((w) => w.terminate());
  }
}

export function defaultPoolSize(): number {
  return Math.max(1, Math.min(4, (navigator.hardwareConcurrency || 2) - 1));
}

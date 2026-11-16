/**
 * Copies the planned files into a "Selected" folder inside the event folder, keeping the
 * sub-folders. Originals are only read. Nothing is ever overwritten, and a file that is
 * stopped or fails halfway is removed, so "Selected" never holds a half-written photo.
 */
import { isNotFound, SELECTED_DIR, type DirHandleLike } from './fs.ts';
import { csvCell } from './report.ts';
import type { MissingPhoto, Plan, PlannedFile } from './plan.ts';

export interface CopyProgress {
  doneFiles: number;
  totalFiles: number;
  doneBytes: number;
  totalBytes: number;
  current: string;
}

export interface FileProblem {
  path: string;
  reason: string;
}

export interface CopyResult {
  copied: number;
  /** Already in Selected with the same size (a second run, or an earlier copy). */
  skipped: number;
  /** Selected holds a different file with this name; it was left alone. */
  conflicts: FileProblem[];
  failed: FileProblem[];
  cancelled: boolean;
  bytes: number;
}

const pathOf = (f: PlannedFile) => [...f.folder, f.name].join('/');

async function ensureFolder(dir: DirHandleLike, segments: string[]): Promise<DirHandleLike> {
  let current = dir;
  for (const segment of segments) current = await current.getDirectoryHandle(segment, { create: true });
  return current;
}

export async function copySelected(
  root: DirHandleLike,
  plan: Plan,
  options: { signal?: AbortSignal; onProgress?: (p: CopyProgress) => void } = {},
): Promise<CopyResult> {
  const { signal, onProgress } = options;
  const result: CopyResult = { copied: 0, skipped: 0, conflicts: [], failed: [], cancelled: false, bytes: 0 };
  const selected = await root.getDirectoryHandle(SELECTED_DIR, { create: true });
  let doneBytes = 0;
  let lastReport = 0;

  const report = (current: string, force = false) => {
    const now = Date.now();
    if (!force && now - lastReport < 100) return;
    lastReport = now;
    onProgress?.({
      doneFiles: result.copied + result.skipped + result.conflicts.length + result.failed.length,
      totalFiles: plan.files.length,
      doneBytes,
      totalBytes: plan.totalBytes,
      current,
    });
  };

  for (const planned of plan.files) {
    if (signal?.aborted) {
      result.cancelled = true;
      break;
    }
    const path = pathOf(planned);
    report(path, true);
    let target: DirHandleLike | null = null;
    let created = false;
    try {
      target = await ensureFolder(selected, planned.folder);
      const source = await planned.handle.getFile();

      try {
        const existing = await (await target.getFileHandle(planned.name)).getFile();
        if (existing.size === source.size) {
          result.skipped += 1;
          doneBytes += source.size;
        } else {
          result.conflicts.push({ path, reason: 'A different file with this name is already in Selected, so it was not replaced.' });
        }
        continue;
      } catch (error) {
        if (!isNotFound(error)) throw error;
      }

      const out = await target.getFileHandle(planned.name, { create: true });
      created = true;
      const writable = await out.createWritable();
      let written = 0;
      const counter = new TransformStream<Uint8Array, Uint8Array>({
        transform(chunk, controller) {
          written += chunk.byteLength;
          doneBytes += chunk.byteLength;
          report(path);
          controller.enqueue(chunk);
        },
      });
      const before = doneBytes;
      try {
        await source.stream().pipeThrough(counter, { signal }).pipeTo(writable);
      } catch (error) {
        doneBytes = before;
        throw error;
      }

      const copy = await out.getFile();
      if (copy.size !== source.size || written !== source.size) {
        throw new Error(`The copy is ${copy.size} bytes but the original is ${source.size} bytes.`);
      }
      result.copied += 1;
      result.bytes += source.size;
    } catch (error) {
      if (created && target) await target.removeEntry(planned.name).catch(() => undefined);
      if (signal?.aborted) {
        result.cancelled = true;
        break;
      }
      result.failed.push({ path, reason: error instanceof Error ? error.message : String(error) });
    }
  }
  report('', true);
  return result;
}

/** A list the studio can keep: what was not found, and what could not be copied. */
export function problemsCsv(missing: MissingPhoto[], result: CopyResult | null): string {
  const rows: string[][] = [['status', 'folder', 'filename', 'detail']];
  for (const m of missing) {
    rows.push([
      'not found',
      m.photo.folder.join('/'),
      m.photo.filename,
      m.reason === 'no-folder' ? 'The folder was not found in the event folder' : 'No file with this name in the folder',
    ]);
  }
  for (const f of result?.failed ?? []) rows.push(['failed', '', f.path, f.reason]);
  for (const f of result?.conflicts ?? []) rows.push(['not replaced', '', f.path, f.reason]);
  return `﻿${rows.map((r) => r.map(csvCell).join(',')).join('\r\n')}\r\n`;
}

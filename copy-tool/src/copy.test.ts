import { describe, expect, it } from 'vitest';
import { copySelected, problemsCsv, type CopyProgress } from './copy.ts';
import { readSelection } from './csv.ts';
import { buildPlan } from './plan.ts';
import { csvCell, formatBytes } from './report.ts';
import { MemDir, MemFile } from './test/memfs.ts';

const selection = (...paths: string[]) => readSelection('s.txt', paths.join('\n')).photos;

function eventFolder() {
  const root = new MemDir('Priya Wedding');
  root.put('Ceremony/IMG_0001.CR3', 'raw-1');
  root.put('Ceremony/IMG_0001.JPG', 'jpg-1');
  root.put('Ceremony/IMG_0001.xmp', 'xmp-1');
  root.put('Ceremony/IMG_0002.CR3', 'raw-2');
  root.put('Reception/Day 2/IMG_0100.NEF', 'nef-100');
  root.put('IMG_9000.JPG', 'top-level');
  return root;
}

const text = (root: MemDir, path: string) => new TextDecoder().decode((root.find(path) as MemFile).data);

async function run(root: MemDir, paths: string[], options?: Parameters<typeof copySelected>[2]) {
  const plan = await buildPlan(root, selection(...paths));
  return { plan, result: await copySelected(root, plan, options) };
}

describe('copySelected', () => {
  it('copies into Selected, keeping the folders, and leaves the originals alone', async () => {
    const root = eventFolder();
    const before = root.list();
    const { result } = await run(root, ['Ceremony/IMG_0001.CR3', 'Reception/Day 2/IMG_0100.NEF', 'IMG_9000.JPG']);

    expect(result).toMatchObject({ copied: 5, skipped: 0, conflicts: [], failed: [], cancelled: false });
    expect((root.find('Selected') as MemDir).list()).toEqual([
      'Ceremony/IMG_0001.CR3',
      'Ceremony/IMG_0001.JPG',
      'Ceremony/IMG_0001.xmp',
      'IMG_9000.JPG',
      'Reception/Day 2/IMG_0100.NEF',
    ]);
    expect(text(root, 'Selected/Ceremony/IMG_0001.CR3')).toBe('raw-1');
    expect(text(root, 'Selected/Reception/Day 2/IMG_0100.NEF')).toBe('nef-100');
    // Every original is still there, untouched.
    expect(root.list().filter((p) => !p.startsWith('Selected/'))).toEqual(before);
    expect(text(root, 'Ceremony/IMG_0001.CR3')).toBe('raw-1');
  });

  it('copies exact bytes, including large and binary files', async () => {
    const root = new MemDir('e');
    const big = new Uint8Array(3 * 1024 * 1024).map((_, i) => (i * 31) % 256);
    root.put('A/IMG_1.CR3', big);
    const { result } = await run(root, ['A/IMG_1.CR3']);
    expect(result.copied).toBe(1);
    expect(result.bytes).toBe(big.byteLength);
    expect((root.find('Selected/A/IMG_1.CR3') as MemFile).data).toEqual(big);
  });

  it('can be run again: what is already there is skipped, not copied twice', async () => {
    const root = eventFolder();
    await run(root, ['Ceremony/IMG_0002.CR3']);
    const second = await run(root, ['Ceremony/IMG_0002.CR3', 'IMG_9000.JPG']);
    expect(second.result).toMatchObject({ copied: 1, skipped: 1, failed: [], conflicts: [] });
  });

  it('never replaces a different file that is already in Selected', async () => {
    const root = eventFolder();
    root.put('Selected/IMG_9000.JPG', 'someone else’s file with another size');
    const { result } = await run(root, ['IMG_9000.JPG']);
    expect(result.copied).toBe(0);
    expect(result.conflicts).toHaveLength(1);
    expect(result.conflicts[0].path).toBe('IMG_9000.JPG');
    expect(text(root, 'Selected/IMG_9000.JPG')).toBe('someone else’s file with another size');
  });

  it('reports a failed read, removes the half-made copy and carries on with the rest', async () => {
    const root = eventFolder();
    (root.find('Ceremony/IMG_0001.JPG') as MemFile).failRead = true;
    const { result } = await run(root, ['Ceremony/IMG_0001.CR3', 'Ceremony/IMG_0002.CR3']);
    expect(result.failed).toHaveLength(1);
    expect(result.failed[0].path).toBe('Ceremony/IMG_0001.JPG');
    expect(result.failed[0].reason).toMatch(/could not be read/);
    expect(result.copied).toBe(3);
    expect((root.find('Selected') as MemDir).list()).not.toContain('Ceremony/IMG_0001.JPG');
  });

  it('notices a copy that came out the wrong size', async () => {
    const root = eventFolder();
    (root.find('Selected') as MemDir | undefined)?.dropBytesFor.add('IMG_9000.JPG');
    const selected = new MemDir('Selected');
    selected.dropBytesFor.add('IMG_9000.JPG');
    root.children.set('Selected', selected);
    const { result } = await run(root, ['IMG_9000.JPG']);
    expect(result.copied).toBe(0);
    expect(result.failed[0].reason).toMatch(/bytes but the original is/);
    expect(selected.find('IMG_9000.JPG')).toBeUndefined(); // the bad copy was removed
  });

  it('stops when asked, and leaves no half-written file behind', async () => {
    const root = eventFolder();
    const controller = new AbortController();
    const plan = await buildPlan(root, selection('Ceremony/IMG_0001.CR3', 'Ceremony/IMG_0002.CR3', 'IMG_9000.JPG'));
    let seen = 0;
    const result = await copySelected(root, plan, {
      signal: controller.signal,
      onProgress: (p) => {
        seen += 1;
        if (p.doneFiles >= 2) controller.abort();
      },
    });
    expect(result.cancelled).toBe(true);
    expect(seen).toBeGreaterThan(0);
    const copied = (root.find('Selected') as MemDir).list();
    expect(copied.length).toBe(result.copied);
    expect(copied.length).toBeLessThan(plan.files.length);
    for (const path of copied) expect(text(root, `Selected/${path}`).length).toBeGreaterThan(0);
  });

  it('does nothing and creates nothing when it is stopped before it starts', async () => {
    const root = eventFolder();
    const controller = new AbortController();
    controller.abort();
    const { result } = await run(root, ['IMG_9000.JPG'], { signal: controller.signal });
    expect(result.cancelled).toBe(true);
    expect(result.copied).toBe(0);
  });

  it('reports progress up to the full size', async () => {
    const root = eventFolder();
    const reports: CopyProgress[] = [];
    const { plan } = await run(root, ['Ceremony/IMG_0001.CR3'], { onProgress: (p) => reports.push(p) });
    const last = reports[reports.length - 1];
    expect(last).toMatchObject({ doneFiles: 3, totalFiles: 3, doneBytes: plan.totalBytes, totalBytes: plan.totalBytes });
  });

  it('makes only the Selected folder when nothing matched', async () => {
    const root = eventFolder();
    const { result, plan } = await run(root, ['Nowhere/IMG_1.CR3']);
    expect(plan.files).toEqual([]);
    expect(result.copied).toBe(0);
  });
});

describe('the list of problems', () => {
  it('lists what was not found and what failed, in a CSV a spreadsheet opens safely', async () => {
    const root = eventFolder();
    const plan = await buildPlan(root, selection('Ceremony/IMG_7777.CR3', 'Nowhere/=SUM(1).jpg', 'IMG_9000.JPG'));
    const csv = problemsCsv(plan.missing, {
      copied: 1, skipped: 0, cancelled: false, bytes: 1,
      conflicts: [{ path: 'IMG_9000.JPG', reason: 'Not replaced' }],
      failed: [{ path: 'A/B.jpg', reason: 'Disk full, sorry' }],
    });
    const lines = csv.replace(/^﻿/, '').trim().split('\r\n');
    expect(lines[0]).toBe('status,folder,filename,detail');
    expect(lines).toContain('not found,Ceremony,IMG_7777.CR3,No file with this name in the folder');
    expect(lines.some((l) => l.startsWith('not found,Nowhere,\'=SUM(1).jpg'))).toBe(true);
    expect(lines).toContain('failed,,A/B.jpg,"Disk full, sorry"');
    expect(lines).toContain('not replaced,,IMG_9000.JPG,Not replaced');
  });
});

describe('report helpers', () => {
  it('quotes cells and guards formulas', () => {
    expect(csvCell('plain')).toBe('plain');
    expect(csvCell('a,b')).toBe('"a,b"');
    expect(csvCell('say "hi"')).toBe('"say ""hi"""');
    expect(csvCell('=1+1')).toBe("'=1+1");
    expect(csvCell('')).toBe('');
  });

  it('writes sizes people can read', () => {
    expect(formatBytes(0)).toBe('0 B');
    expect(formatBytes(1536)).toBe('1.5 KB');
    expect(formatBytes(25 * 1024 * 1024)).toBe('25.0 MB');
    expect(formatBytes(120 * 1024 ** 3)).toBe('120 GB');
  });
});

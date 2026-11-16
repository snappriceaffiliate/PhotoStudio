/**
 * "Try it with sample files": builds a small pretend event folder inside the browser's private
 * storage (nothing is written to the real disk) together with a matching selection CSV.
 */
import type { DirHandleLike } from './fs.ts';

export function canTryDemo(): boolean {
  return typeof navigator !== 'undefined' && 'storage' in navigator && typeof navigator.storage.getDirectory === 'function';
}

async function write(dir: DirHandleLike, path: string, bytes: number) {
  const parts = path.split('/');
  const name = parts.pop()!;
  let folder = dir;
  for (const part of parts) folder = await folder.getDirectoryHandle(part, { create: true });
  const handle = await folder.getFileHandle(name, { create: true });
  const writable = await handle.createWritable();
  const data = new Uint8Array(bytes);
  for (let i = 0; i < data.length; i += 65536) crypto.getRandomValues(data.subarray(i, i + 65536));
  const writer = writable.getWriter();
  await writer.write(data);
  await writer.close();
}

export async function createSample(): Promise<{ folder: DirHandleLike; csvName: string; csvText: string }> {
  const root = (await navigator.storage.getDirectory()) as unknown as DirHandleLike;
  await root.removeEntry('Sample wedding', { recursive: true }).catch(() => undefined);
  const folder = await root.getDirectoryHandle('Sample wedding', { create: true });

  const files: [string, number][] = [];
  for (const n of [1, 2, 3]) {
    const id = `IMG_${String(n).padStart(4, '0')}`;
    files.push([`Ceremony/${id}.CR3`, 1_500_000], [`Ceremony/${id}.JPG`, 400_000], [`Ceremony/${id}.xmp`, 4_000]);
  }
  for (const n of [101, 102]) {
    files.push([`Reception/Dinner/IMG_${n}.NEF`, 1_800_000], [`Reception/Dinner/IMG_${n}.JPG`, 350_000]);
  }
  files.push(['IMG_9000.JPG', 500_000], ['Ceremony/IMG_0004.CR3', 1_500_000]); // not selected below
  for (const [path, bytes] of files) await write(folder, path, bytes);

  const rows = [
    ['Ceremony', 'IMG_0001.CR3', 'Album cover'],
    ['Ceremony', 'IMG_0003.CR3', ''],
    ['Reception/Dinner', 'IMG_101.NEF', 'Black and white, please'],
    ['Reception/Dinner', 'IMG_102.NEF', ''],
    ['', 'IMG_9000.JPG', ''],
    ['Ceremony', 'IMG_0099.CR3', 'This one is not in the folder'], // shows what "not found" looks like
  ];
  const csv = [
    'number,folder,filename,path,album,note,selected_at,photo_id',
    ...rows.map(([f, n, note], i) => `${i + 1},${f},${n},${f ? `${f}/` : ''}${n},,${note ? `"${note}"` : ''},2026-12-01 10:00,sample-${i + 1}`),
  ].join('\r\n');
  return { folder, csvName: 'sample-wedding-selection.csv', csvText: `﻿${csv}\r\n` };
}

import { describe, expect, it } from 'vitest';
import { readSelection } from './csv.ts';
import { buildPlan, suggestFolder } from './plan.ts';
import { MemDir } from './test/memfs.ts';

const selection = (...paths: string[]) => readSelection('s.txt', paths.join('\n')).photos;
const names = (plan: Awaited<ReturnType<typeof buildPlan>>) => plan.files.map((f) => [...f.folder, f.name].join('/')).sort();

function eventFolder() {
  const root = new MemDir('Priya Wedding');
  root.put('Ceremony/IMG_0001.CR3', 'raw-1');
  root.put('Ceremony/IMG_0001.JPG', 'jpg-1');
  root.put('Ceremony/IMG_0001.xmp', 'xmp-1');
  root.put('Ceremony/IMG_0002.CR3', 'raw-2');
  root.put('Ceremony/IMG_0010.CR3', 'raw-10');
  root.put('Reception/Day 2/IMG_0100.NEF', 'nef-100');
  root.put('IMG_9000.JPG', 'top');
  return root;
}

describe('buildPlan', () => {
  it('takes every file that shares the selected photo’s base name', async () => {
    const plan = await buildPlan(eventFolder(), selection('Ceremony/IMG_0001.CR3'));
    expect(names(plan)).toEqual(['Ceremony/IMG_0001.CR3', 'Ceremony/IMG_0001.JPG', 'Ceremony/IMG_0001.xmp']);
    expect(plan.found).toHaveLength(1);
    expect(plan.missing).toEqual([]);
  });

  it('does not take a photo whose name only starts the same way', async () => {
    const plan = await buildPlan(eventFolder(), selection('Ceremony/IMG_0001.CR3'));
    expect(names(plan)).not.toContain('Ceremony/IMG_0010.CR3');
    const other = await buildPlan(eventFolder(), selection('Ceremony/IMG_0010.CR3'));
    expect(names(other)).toEqual(['Ceremony/IMG_0010.CR3']);
  });

  it('finds photos in nested folders and at the top level', async () => {
    const plan = await buildPlan(eventFolder(), selection('Reception/Day 2/IMG_0100.NEF', 'IMG_9000.JPG'));
    expect(names(plan)).toEqual(['IMG_9000.JPG', 'Reception/Day 2/IMG_0100.NEF']);
  });

  it('ignores upper and lower case in folder and file names', async () => {
    const plan = await buildPlan(eventFolder(), selection('CEREMONY/img_0002.cr3'));
    expect(names(plan)).toEqual(['Ceremony/IMG_0002.CR3']);
  });

  it('matches a RAW in the list with the JPEG next to it, and the other way round', async () => {
    const root = new MemDir('e');
    root.put('A/IMG_1.JPG', 'j');
    root.put('A/IMG_1.CR3', 'r');
    expect(names(await buildPlan(root, selection('A/IMG_1.CR3')))).toEqual(['A/IMG_1.CR3', 'A/IMG_1.JPG']);
    expect(names(await buildPlan(root, selection('A/IMG_1.JPG')))).toEqual(['A/IMG_1.CR3', 'A/IMG_1.JPG']);
  });

  it('reports a missing folder and a missing file differently', async () => {
    const plan = await buildPlan(eventFolder(), selection('Ceremony/IMG_7777.CR3', 'Nowhere/IMG_1.CR3', 'Ceremony/IMG_0002.CR3'));
    expect(plan.found).toHaveLength(1);
    expect(plan.missing.map((m) => [m.photo.filename, m.reason])).toEqual([
      ['IMG_7777.CR3', 'no-file'],
      ['IMG_1.CR3', 'no-folder'],
    ]);
  });

  it('adds up the size of what will be copied', async () => {
    const plan = await buildPlan(eventFolder(), selection('Ceremony/IMG_0001.CR3'));
    expect(plan.totalBytes).toBe('raw-1'.length + 'jpg-1'.length + 'xmp-1'.length);
  });

  it('copies a file once when two selected photos overlap on it', async () => {
    const root = new MemDir('e');
    root.put('A/IMG_1.jpg', 'a');
    root.put('A/IMG_1.edit.jpg', 'b');
    const plan = await buildPlan(root, selection('A/IMG_1.jpg', 'A/IMG_1.edit.jpg'));
    expect(names(plan)).toEqual(['A/IMG_1.edit.jpg', 'A/IMG_1.jpg']);
  });

  it('never reads from the Selected folder', async () => {
    const root = eventFolder();
    root.put('Selected/Ceremony/IMG_0001.CR3', 'old copy');
    const plan = await buildPlan(root, selection('Selected/Ceremony/IMG_0001.CR3'));
    expect(plan.files).toEqual([]);
    expect(plan.missing[0].reason).toBe('no-folder');
  });

  it('ignores a folder that has the photo’s name', async () => {
    const root = new MemDir('e');
    root.put('A/IMG_1.jpg/inside.txt', 'x');
    const plan = await buildPlan(root, selection('A/IMG_1.jpg'));
    expect(plan.files).toEqual([]);
    expect(plan.missing[0].reason).toBe('no-file');
  });

  it('reports how far it has got', async () => {
    const seen: number[] = [];
    await buildPlan(eventFolder(), selection('Ceremony/IMG_0001.CR3', 'IMG_9000.JPG'), (p) => seen.push(p.checked));
    expect(seen[seen.length - 1]).toBe(2);
  });
});

describe('suggestFolder', () => {
  it('points at the folder inside when the parent was picked', async () => {
    const parent = new MemDir('Weddings');
    parent.children.set('Priya Wedding', eventFolder());
    parent.put('Other event/readme.txt', 'x');
    const photos = selection('Ceremony/IMG_0001.CR3');
    expect((await buildPlan(parent, photos)).found).toHaveLength(0);
    expect(await suggestFolder(parent, photos)).toBe('Priya Wedding');
  });

  it('says nothing when no folder fits', async () => {
    const root = new MemDir('Elsewhere');
    root.put('Random/file.txt', 'x');
    expect(await suggestFolder(root, selection('Ceremony/IMG_0001.CR3'))).toBeNull();
  });

  it('does not suggest the Selected folder', async () => {
    const root = new MemDir('e');
    root.put('Selected/Ceremony/IMG_0001.CR3', 'copy');
    expect(await suggestFolder(root, selection('Ceremony/IMG_0001.CR3'))).toBeNull();
  });
});

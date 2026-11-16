/**
 * Looks through the event folder and works out which files belong to the selected photos,
 * before anything is copied. A selected photo owns every file in its folder whose name starts
 * with "<base name>." (the RAW and the JPEG, the .xmp sidecar, and so on): the same rule as the
 * Mac and Windows copy scripts.
 */
import { normalizeName, type SelectedPhoto } from './csv.ts';
import { isNotFound, SELECTED_DIR, type DirHandleLike, type FileHandleLike } from './fs.ts';

export interface PlannedFile {
  photo: SelectedPhoto;
  /** Folder segments below the event folder. */
  folder: string[];
  name: string;
  size: number;
  handle: FileHandleLike;
}

export type MissingReason = 'no-folder' | 'no-file';

export interface MissingPhoto {
  photo: SelectedPhoto;
  reason: MissingReason;
}

export interface Plan {
  files: PlannedFile[];
  /** Selected photos that have at least one file. */
  found: SelectedPhoto[];
  missing: MissingPhoto[];
  totalBytes: number;
}

export interface ScanProgress {
  checked: number;
  total: number;
}

const folderKey = (folder: string[]) => folder.map(normalizeName).join('/');

/**
 * Walks down from `root`, matching each segment without regard to case. Returns the folder and
 * its real names (as they are on the disk), or null if a segment is missing.
 */
async function findFolder(
  root: DirHandleLike,
  segments: string[],
): Promise<{ dir: DirHandleLike; names: string[] } | null> {
  let dir = root;
  const names: string[] = [];
  for (const segment of segments) {
    const wanted = normalizeName(segment);
    let next: DirHandleLike | null = null;
    for await (const [name, handle] of dir.entries()) {
      if (handle.kind === 'directory' && normalizeName(name) === wanted) {
        next = handle;
        names.push(name);
        break;
      }
    }
    if (!next) return null;
    dir = next;
  }
  return { dir, names };
}

export async function buildPlan(
  root: DirHandleLike,
  photos: SelectedPhoto[],
  onProgress?: (p: ScanProgress) => void,
): Promise<Plan> {
  const byFolder = new Map<string, SelectedPhoto[]>();
  for (const photo of photos) {
    const key = folderKey(photo.folder);
    byFolder.set(key, [...(byFolder.get(key) ?? []), photo]);
  }

  const files: PlannedFile[] = [];
  const found: SelectedPhoto[] = [];
  const missing: MissingPhoto[] = [];
  let checked = 0;

  for (const group of byFolder.values()) {
    const segments = group[0].folder;
    // Never read from the Selected folder itself: it holds the copies.
    const insideSelected = segments.length > 0 && normalizeName(segments[0]) === normalizeName(SELECTED_DIR);
    const located = insideSelected ? null : await findFolder(root, segments);
    if (!located) {
      for (const photo of group) missing.push({ photo, reason: 'no-folder' });
      checked += group.length;
      onProgress?.({ checked, total: photos.length });
      continue;
    }

    const names: { normalized: string; handle: FileHandleLike }[] = [];
    for await (const [name, handle] of located.dir.entries()) {
      if (handle.kind === 'file') names.push({ normalized: normalizeName(name), handle });
    }

    for (const photo of group) {
      const prefix = `${normalizeName(photo.base)}.`;
      const matches = names.filter((n) => n.normalized.startsWith(prefix));
      if (matches.length === 0) {
        missing.push({ photo, reason: 'no-file' });
      } else {
        found.push(photo);
        for (const match of matches) {
          const file = await match.handle.getFile();
          files.push({ photo, folder: located.names, name: match.handle.name, size: file.size, handle: match.handle });
        }
      }
      checked += 1;
      if (checked % 25 === 0) onProgress?.({ checked, total: photos.length });
    }
    onProgress?.({ checked, total: photos.length });
  }

  // Two selected photos can share a file only when their base names overlap, for example
  // "IMG_1" and "IMG_1.edit"; copy it once.
  const unique = new Map<string, PlannedFile>();
  for (const f of files) unique.set(`${folderKey(f.folder)}/${f.name}`, f);
  const list = [...unique.values()];
  return { files: list, found, missing, totalBytes: list.reduce((sum, f) => sum + f.size, 0) };
}

/**
 * When nothing was found, the studio has often picked the parent of the event folder, or a
 * sub-folder of it. Looks one level down and returns the name of a folder that does contain
 * some of the photos, so the screen can say "did you mean this one?".
 */
export async function suggestFolder(root: DirHandleLike, photos: SelectedPhoto[]): Promise<string | null> {
  const sample = photos.slice(0, 10);
  for await (const [name, handle] of root.entries()) {
    if (handle.kind !== 'directory' || normalizeName(name) === normalizeName(SELECTED_DIR)) continue;
    try {
      const plan = await buildPlan(handle, sample);
      if (plan.found.length > 0) return name;
    } catch (error) {
      if (!isNotFound(error)) throw error;
    }
  }
  return null;
}

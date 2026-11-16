/**
 * Reads a PickSnap selection file: the CSV from "Spreadsheet (CSV)" (columns folder,
 * filename, path, album, note, ...) or the plain list from "Plain list" (one path per line).
 */

export class SelectionFileError extends Error {}

export interface SelectedPhoto {
  /** Folder segments below the event folder, for example ["Ceremony", "Day 1"]. Empty = top level. */
  folder: string[];
  /** The file name the studio uploaded, for example "IMG_0001.CR3". */
  filename: string;
  /** The name without its extension. Every file starting with "<base>." is copied. */
  base: string;
  note: string;
  album: string;
}

export interface Selection {
  photos: SelectedPhoto[];
  /** Rows that repeated a photo already in the list. */
  duplicates: number;
}

/** Splits CSV text into rows of cells (quotes, doubled quotes, commas and line breaks inside quotes). */
export function parseCsv(text: string): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let cell = '';
  let quoted = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (quoted) {
      if (ch === '"') {
        if (text[i + 1] === '"') {
          cell += '"';
          i += 1;
        } else {
          quoted = false;
        }
      } else {
        cell += ch;
      }
    } else if (ch === '"') {
      quoted = true;
    } else if (ch === ',') {
      row.push(cell);
      cell = '';
    } else if (ch === '\n' || ch === '\r') {
      if (ch === '\r' && text[i + 1] === '\n') i += 1;
      row.push(cell);
      rows.push(row);
      row = [];
      cell = '';
    } else {
      cell += ch;
    }
  }
  if (cell !== '' || row.length > 0) {
    row.push(cell);
    rows.push(row);
  }
  return rows.filter((r) => r.some((c) => c.trim() !== ''));
}

/** PickSnap puts a ' in front of cells starting with = + - @ so a spreadsheet cannot run them. */
export function removeFormulaGuard(value: string): string {
  return value.length > 1 && value[0] === "'" && '=+-@\t\r'.includes(value[1]) ? value.slice(1) : value;
}

/** A name without its extension; never empty, so a pattern can never match everything. */
export function baseName(filename: string): string {
  const dot = filename.lastIndexOf('.');
  const stem = dot > 0 ? filename.slice(0, dot) : filename;
  return stem || filename;
}

/** Lower case, accents composed: so "ÉCRAN.JPG" typed on one computer matches the file on another. */
export function normalizeName(name: string): string {
  return name.normalize('NFC').toLowerCase();
}

/** Splits "Ceremony/Day 1" into segments, refusing anything that could leave the event folder. */
export function folderSegments(folder: string): string[] {
  const segments = folder
    .normalize('NFC')
    .split(/[\\/]+/)
    .map((s) => s.trim())
    .filter((s) => s !== '' && s !== '.');
  if (segments.some((s) => s === '..')) {
    throw new SelectionFileError('The list contains a folder path with "..", which is not allowed.');
  }
  return segments;
}

function photoFrom(path: string, note = '', album = ''): SelectedPhoto | null {
  const clean = removeFormulaGuard(path.trim()).normalize('NFC').replace(/\\/g, '/');
  if (!clean || clean.endsWith('/')) return null;
  const slash = clean.lastIndexOf('/');
  const folder = folderSegments(slash >= 0 ? clean.slice(0, slash) : '');
  const filename = clean.slice(slash + 1);
  return { folder, filename, base: baseName(filename), note, album };
}

function dedupe(photos: SelectedPhoto[]): Selection {
  const seen = new Set<string>();
  const unique: SelectedPhoto[] = [];
  for (const p of photos) {
    const key = `${p.folder.map(normalizeName).join('/')}\u0000${normalizeName(p.base)}`;
    if (seen.has(key)) continue;
    seen.add(key);
    unique.push(p);
  }
  return { photos: unique, duplicates: photos.length - unique.length };
}

/** Reads the file's text. `name` decides between the CSV and the plain list. */
export function readSelection(name: string, text: string): Selection {
  const body = text.replace(/^﻿/, '');
  if (/\.txt$/i.test(name)) {
    const photos = body
      .split(/\r?\n/)
      .map((line) => photoFrom(line))
      .filter((p): p is SelectedPhoto => p !== null);
    if (photos.length === 0) throw new SelectionFileError('This list is empty.');
    return dedupe(photos);
  }

  const rows = parseCsv(body);
  if (rows.length === 0) throw new SelectionFileError('This file is empty.');
  const header = rows[0].map((h) => h.trim().toLowerCase());
  const col = (n: string) => header.indexOf(n);
  const folderCol = col('folder');
  const fileCol = col('filename');
  const pathCol = col('path');
  if (pathCol < 0 && (folderCol < 0 || fileCol < 0)) {
    throw new SelectionFileError(
      'This does not look like a PickSnap selection file. It needs "folder" and "filename" columns (or a "path" column). Use "Spreadsheet (CSV)" on the event page.',
    );
  }
  const noteCol = col('note');
  const albumCol = col('album');
  const cell = (r: string[], c: number) => (c >= 0 ? (r[c] ?? '') : '');

  const photos: SelectedPhoto[] = [];
  for (const r of rows.slice(1)) {
    let path: string;
    if (fileCol >= 0 && folderCol >= 0 && cell(r, fileCol).trim() !== '') {
      const folder = removeFormulaGuard(cell(r, folderCol).trim());
      path = `${folder ? `${folder}/` : ''}${removeFormulaGuard(cell(r, fileCol).trim())}`;
    } else {
      path = cell(r, pathCol);
    }
    const photo = photoFrom(path, cell(r, noteCol), cell(r, albumCol));
    if (photo) photos.push(photo);
  }
  if (photos.length === 0) throw new SelectionFileError('The file has no photos in it.');
  return dedupe(photos);
}

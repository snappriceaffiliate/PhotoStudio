import { describe, expect, it } from 'vitest';
import {
  baseName,
  folderSegments,
  normalizeName,
  parseCsv,
  readSelection,
  removeFormulaGuard,
  SelectionFileError,
} from './csv.ts';

const HEADER = 'number,folder,filename,path,album,note,selected_at,photo_id';

describe('parseCsv', () => {
  it('reads plain rows', () => {
    expect(parseCsv('a,b,c\n1,2,3\n')).toEqual([['a', 'b', 'c'], ['1', '2', '3']]);
  });

  it('handles Windows line endings and a missing final newline', () => {
    expect(parseCsv('a,b\r\n1,2')).toEqual([['a', 'b'], ['1', '2']]);
  });

  it('keeps commas, quotes and line breaks inside quoted cells', () => {
    const rows = parseCsv('a,b\n"one, two","say ""hi""\nsecond line"\n');
    expect(rows[1]).toEqual(['one, two', 'say "hi"\nsecond line']);
  });

  it('keeps empty cells and drops blank lines', () => {
    expect(parseCsv('a,b,c\n\n1,,3\n\n')).toEqual([['a', 'b', 'c'], ['1', '', '3']]);
  });
});

describe('file names', () => {
  it('takes the base name the way the copy scripts do', () => {
    expect(baseName('IMG_0001.CR3')).toBe('IMG_0001');
    expect(baseName('IMG.edit.1.jpg')).toBe('IMG.edit.1');
    expect(baseName('noextension')).toBe('noextension');
    expect(baseName('.hidden')).toBe('.hidden'); // never empty, so a pattern cannot match everything
    expect(baseName('trailing.')).toBe('trailing');
  });

  it('compares names without caring about case or accent form', () => {
    expect(normalizeName('IMG_0001.JPG')).toBe(normalizeName('img_0001.jpg'));
    expect(normalizeName('Café.jpg')).toBe(normalizeName('Café.jpg')); // composed vs separate accent
  });

  it('removes the spreadsheet guard PickSnap adds, and only that', () => {
    expect(removeFormulaGuard("'=IMG_1.jpg")).toBe('=IMG_1.jpg');
    expect(removeFormulaGuard("'-weird.jpg")).toBe('-weird.jpg');
    expect(removeFormulaGuard("'quoted name.jpg")).toBe("'quoted name.jpg");
    expect(removeFormulaGuard('plain.jpg')).toBe('plain.jpg');
  });

  it('splits folders and refuses ways out of the event folder', () => {
    expect(folderSegments('Ceremony/Day 1')).toEqual(['Ceremony', 'Day 1']);
    expect(folderSegments('')).toEqual([]);
    expect(folderSegments('./a//b/')).toEqual(['a', 'b']);
    expect(folderSegments('a\\b')).toEqual(['a', 'b']);
    expect(() => folderSegments('a/../b')).toThrow(SelectionFileError);
  });
});

describe('readSelection: the CSV from PickSnap', () => {
  it('reads folder and filename, with a byte-order mark and quoted notes', () => {
    const text = `﻿${HEADER}\r\n1,Ceremony,IMG_0001.CR3,Ceremony/IMG_0001.CR3,Reception,"Album cover, please",2026-12-01 10:00,p1\r\n2,,IMG_0002.JPG,IMG_0002.JPG,,,2026-12-01 10:01,p2\r\n`;
    const { photos, duplicates } = readSelection('wedding-selection.csv', text);
    expect(duplicates).toBe(0);
    expect(photos).toHaveLength(2);
    expect(photos[0]).toMatchObject({
      folder: ['Ceremony'], filename: 'IMG_0001.CR3', base: 'IMG_0001', note: 'Album cover, please', album: 'Reception',
    });
    expect(photos[1]).toMatchObject({ folder: [], filename: 'IMG_0002.JPG', base: 'IMG_0002' });
  });

  it('undoes the guard on names that start with = + - or @', () => {
    const text = `${HEADER}\n1,"'-Day","'=IMG.jpg","'-Day/'=IMG.jpg",,,,p1\n`;
    const [photo] = readSelection('s.csv', text).photos;
    expect(photo.folder).toEqual(['-Day']);
    expect(photo.filename).toBe('=IMG.jpg');
  });

  it('works from the path column alone', () => {
    const { photos } = readSelection('s.csv', 'path,note\nDay 1/Sub/IMG_5.NEF,hello\n');
    expect(photos[0]).toMatchObject({ folder: ['Day 1', 'Sub'], filename: 'IMG_5.NEF', note: 'hello' });
  });

  it('accepts upper-case headers and extra columns', () => {
    const { photos } = readSelection('s.csv', 'Folder,FileName,Extra\nA,b.jpg,zzz\n');
    expect(photos[0]).toMatchObject({ folder: ['A'], filename: 'b.jpg' });
  });

  it('ignores repeated photos, comparing without regard to case', () => {
    const text = `${HEADER}\n1,A,IMG_1.jpg,A/IMG_1.jpg,,,,p1\n2,a,img_1.JPG,a/img_1.JPG,,,,p2\n3,A,IMG_2.jpg,A/IMG_2.jpg,,,,p3\n`;
    const result = readSelection('s.csv', text);
    expect(result.photos).toHaveLength(2);
    expect(result.duplicates).toBe(1);
  });

  it('treats a RAW and its JPEG as one selected photo', () => {
    const text = `${HEADER}\n1,A,IMG_1.CR3,A/IMG_1.CR3,,,,p1\n2,A,IMG_1.JPG,A/IMG_1.JPG,,,,p2\n`;
    expect(readSelection('s.csv', text).photos).toHaveLength(1);
  });

  it('refuses files that are not selection lists', () => {
    expect(() => readSelection('s.csv', 'name,email\nA,a@x.com\n')).toThrow(/does not look like a PickSnap selection file/);
    expect(() => readSelection('s.csv', '')).toThrow(/empty/);
    expect(() => readSelection('s.csv', `${HEADER}\n`)).toThrow(/no photos/);
  });

  it('refuses a path that climbs out of the event folder', () => {
    expect(() => readSelection('s.csv', 'path\n../secret/IMG.jpg\n')).toThrow(SelectionFileError);
  });
});

describe('readSelection: the plain list', () => {
  it('reads one path per line, with Windows line endings, and skips blanks', () => {
    const { photos } = readSelection('wedding-selection.txt', 'Ceremony/IMG_1.jpg\r\n\r\nIMG_2.jpg\r\n');
    expect(photos.map((p) => [...p.folder, p.filename].join('/'))).toEqual(['Ceremony/IMG_1.jpg', 'IMG_2.jpg']);
  });

  it('refuses an empty list', () => {
    expect(() => readSelection('x.txt', '\n\n')).toThrow(/empty/);
  });
});

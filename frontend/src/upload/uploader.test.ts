import { describe, expect, it } from 'vitest';
import { duplicateNames, toUploadFiles } from './uploader';

function fileAt(path: string): File {
  const name = path.split('/').pop()!;
  const file = new File(['x'], name);
  Object.defineProperty(file, 'webkitRelativePath', { value: path });
  return file;
}

describe('preparing a folder for upload', () => {
  it('keeps supported photos, drops the chosen folder name and sorts naturally', () => {
    const files = toUploadFiles([
      fileAt('Wedding/Ceremony/DSC_10.NEF'),
      fileAt('Wedding/Ceremony/DSC_9.NEF'),
      fileAt('Wedding/notes.txt'),
      fileAt('Wedding/Reception/IMG_1.JPG'),
    ]);
    expect(files.map((f) => f.path)).toEqual(['Ceremony/DSC_9.NEF', 'Ceremony/DSC_10.NEF', 'Reception/IMG_1.JPG']);
  });

  it('uses the plain name for files chosen without a folder', () => {
    expect(toUploadFiles([new File(['x'], 'a.jpg')])[0].path).toBe('a.jpg');
  });

  it('flags filenames that appear in more than one folder', () => {
    const files = toUploadFiles([fileAt('W/Cam A/IMG_0001.jpg'), fileAt('W/Cam B/IMG_0001.JPG'), fileAt('W/Cam B/IMG_0002.jpg')]);
    expect(duplicateNames(files)).toEqual(['img_0001.jpg']);
  });
});

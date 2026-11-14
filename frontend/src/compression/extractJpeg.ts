/**
 * Finds JPEG images embedded in a RAW file (CR2, CR3, NEF, ARW, RAF, DNG and others).
 *
 * Cameras store one or more ordinary JPEG previews inside the RAW file. We scan for
 * JPEG start markers, walk the marker structure to validate each candidate, and keep
 * only baseline or progressive JPEGs. Lossless JPEG (SOF3) is skipped: some formats
 * store the sensor data that way, and browsers cannot decode it.
 */

export interface EmbeddedJpeg {
  offset: number;
  length: number;
  width: number;
  height: number;
}

const SOI = 0xd8;
const EOI = 0xd9;
const SOS = 0xda;

function isDecodableFrame(marker: number): boolean {
  return marker === 0xc0 || marker === 0xc1 || marker === 0xc2;
}

function isOtherFrame(marker: number): boolean {
  // SOF3, SOF5-SOF7, SOF9-SOF11, SOF13-SOF15: lossless, hierarchical or arithmetic.
  return marker >= 0xc3 && marker <= 0xcf && marker !== 0xc4 && marker !== 0xc8 && marker !== 0xcc;
}

function isStandalone(marker: number): boolean {
  return marker === SOI || marker === 0x01 || (marker >= 0xd0 && marker <= 0xd7);
}

/** Validate the JPEG that starts at `start`; return its extent and size, or null. */
export function parseJpegAt(b: Uint8Array, start: number): EmbeddedJpeg | null {
  let p = start + 2;
  let width = 0;
  let height = 0;

  while (p + 3 < b.length) {
    if (b[p] !== 0xff) return null;
    const marker = b[p + 1];
    if (marker === 0xff) {
      p += 1;
      continue;
    }
    if (isStandalone(marker)) {
      p += 2;
      continue;
    }
    if (marker === EOI) return null; // ended before any image data
    const length = (b[p + 2] << 8) | b[p + 3];
    if (length < 2 || p + 2 + length > b.length) return null;

    if (isDecodableFrame(marker)) {
      if (p + 8 >= b.length) return null;
      height = (b[p + 5] << 8) | b[p + 6];
      width = (b[p + 7] << 8) | b[p + 8];
    } else if (isOtherFrame(marker)) {
      return null;
    }

    if (marker !== SOS) {
      p += 2 + length;
      continue;
    }

    // Start of scan: skip entropy-coded data until the next real marker.
    if (width === 0 || height === 0) return null;
    let q = p + 2 + length;
    let nextMarker = -1;
    while (q + 1 < b.length) {
      if (b[q] === 0xff) {
        const n = b[q + 1];
        if (n === 0x00 || (n >= 0xd0 && n <= 0xd7) || n === 0xff) {
          q += n === 0xff ? 1 : 2;
          continue;
        }
        nextMarker = q;
        break;
      }
      q += 1;
    }
    if (nextMarker < 0) return null;
    if (b[nextMarker + 1] === EOI) {
      return { offset: start, length: nextMarker + 2 - start, width, height };
    }
    p = nextMarker; // progressive JPEG: more tables and scans follow
  }
  return null;
}

export function findEmbeddedJpegs(b: Uint8Array): EmbeddedJpeg[] {
  const found: EmbeddedJpeg[] = [];
  let i = 0;
  while (i + 2 < b.length) {
    if (b[i] === 0xff && b[i + 1] === SOI && b[i + 2] === 0xff) {
      const jpeg = parseJpegAt(b, i);
      if (jpeg) {
        found.push(jpeg);
        i = jpeg.offset + jpeg.length; // skip thumbnails nested inside this preview
        continue;
      }
    }
    i += 1;
  }
  return found;
}

export function largestEmbeddedJpeg(b: Uint8Array): EmbeddedJpeg | null {
  let best: EmbeddedJpeg | null = null;
  for (const jpeg of findEmbeddedJpegs(b)) {
    if (!best || jpeg.width * jpeg.height > best.width * best.height) best = jpeg;
  }
  return best;
}

import { describe, expect, it } from 'vitest';
import { findEmbeddedJpegs, largestEmbeddedJpeg } from './extractJpeg';

/** Build a structurally valid JPEG: SOI, APP0, SOFn, (DHT, SOS, data) x scans, EOI. */
function jpeg(frameMarker: number, width: number, height: number, scans = 1): number[] {
  const out = [0xff, 0xd8];
  out.push(0xff, 0xe0, 0x00, 0x10, ...'JFIF'.split('').map((c) => c.charCodeAt(0)), 0, 1, 1, 0, 0, 1, 0, 1, 0, 0);
  out.push(0xff, frameMarker, 0x00, 0x11, 8, height >> 8, height & 255, width >> 8, width & 255, 3);
  out.push(1, 0x22, 0, 2, 0x11, 1, 3, 0x11, 1);
  for (let s = 0; s < scans; s += 1) {
    out.push(0xff, 0xc4, 0x00, 0x04, 0x00, 0x00); // a (fake) Huffman table segment
    out.push(0xff, 0xda, 0x00, 0x0c, 3, 1, 0, 2, 0x11, 3, 0x11, 0, 63, 0);
    out.push(0x12, 0xff, 0x00, 0x34, 0xff, 0xd0, 0x56); // entropy data with stuffing and a restart
  }
  out.push(0xff, 0xd9);
  return out;
}

const filler = (n: number) => Array.from({ length: n }, (_, i) => (i * 37) % 251);

describe('embedded JPEG extraction', () => {
  it('finds the largest decodable preview and skips lossless sensor data', () => {
    const small = jpeg(0xc0, 160, 120);
    const preview = jpeg(0xc0, 6000, 4000);
    const lossless = jpeg(0xc3, 8000, 6000); // how some RAW formats store sensor data
    const raw = new Uint8Array([...filler(500), ...small, ...filler(300), ...lossless, ...filler(200), ...preview, ...filler(100)]);

    const found = findEmbeddedJpegs(raw);
    expect(found.map((j) => [j.width, j.height])).toEqual([
      [160, 120],
      [6000, 4000],
    ]);
    const best = largestEmbeddedJpeg(raw)!;
    expect([best.width, best.height]).toEqual([6000, 4000]);
    expect(raw.slice(best.offset, best.offset + best.length)).toEqual(new Uint8Array(preview));
  });

  it('follows progressive JPEGs across several scans', () => {
    const progressive = jpeg(0xc2, 1620, 1080, 3);
    const best = largestEmbeddedJpeg(new Uint8Array([...filler(64), ...progressive]))!;
    expect(best.length).toBe(progressive.length);
  });

  it('returns null when no preview is present', () => {
    expect(largestEmbeddedJpeg(new Uint8Array(filler(10_000)))).toBeNull();
  });

  it('ignores a truncated JPEG', () => {
    const cut = jpeg(0xc0, 100, 100).slice(0, -2);
    expect(findEmbeddedJpegs(new Uint8Array(cut))).toEqual([]);
  });
});

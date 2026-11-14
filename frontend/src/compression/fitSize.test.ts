import { describe, expect, it } from 'vitest';
import { fitUnderLimit, type Encode } from './fitSize';

const LIMIT = 100 * 1024;

/** A size model: bytes grow with pixel count and with quality; `detail` is how busy the photo is. */
function photo(detail: number): Encode<null> {
  return async (longEdge, quality) => {
    const pixels = longEdge * longEdge * (2 / 3);
    const size = pixels * detail * (0.15 + quality * quality);
    return { size: Math.round(size), result: null };
  };
}

const options = { maxBytes: LIMIT, longEdge: 1600, minLongEdge: 800 };

describe('fitting a preview under 100 KB', () => {
  it('keeps simple photos at full size and high quality in one encode', async () => {
    const fit = await fitUnderLimit(photo(0.04), options);
    expect([fit.longEdge, fit.quality, fit.encodes]).toEqual([1600, 0.85, 1]);
  });

  it('lowers quality but stays at full size when the floor is enough', async () => {
    const fit = await fitUnderLimit(photo(0.07), options);
    expect(fit.longEdge).toBe(1600);
    expect(fit.quality).toBeGreaterThanOrEqual(0.55);
    expect(fit.size).toBeLessThanOrEqual(LIMIT);
    expect(fit.encodes).toBeLessThanOrEqual(5);
  });

  it('shrinks a detailed photo a little instead of smearing it', async () => {
    const fit = await fitUnderLimit(photo(0.16), options);
    expect(fit.quality).toBeGreaterThanOrEqual(0.55); // never below the floor
    expect(fit.longEdge).toBeGreaterThanOrEqual(1150);
    expect(fit.longEdge).toBeLessThan(1600);
    expect(fit.size).toBeLessThanOrEqual(LIMIT);
    expect(fit.encodes).toBeLessThanOrEqual(8);
  });

  it('only goes below the quality floor at the smallest allowed size', async () => {
    const fit = await fitUnderLimit(photo(0.6), options);
    expect(fit.longEdge).toBe(800);
    expect(fit.quality).toBeLessThan(0.55);
    expect(fit.size).toBeLessThanOrEqual(LIMIT);
  });

  it('gives up clearly when nothing fits', async () => {
    await expect(fitUnderLimit(photo(5), options)).rejects.toThrow('Could not fit');
  });
});

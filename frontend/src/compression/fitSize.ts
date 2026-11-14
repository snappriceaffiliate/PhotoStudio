/**
 * Chooses the image size and WebP quality for a preview that must stay under a byte limit.
 *
 * Lowering WebP quality far makes fine detail (leaves, grass, fabric) smear, while a slightly
 * smaller image looks cleaner at the same file size. So the search:
 *   1. tries full size at high quality (most photos of people fit here, in one encode);
 *   2. otherwise finds the highest quality that fits, never going below a quality floor;
 *   3. if even the floor is too big, estimates the size that would fit (file size grows with
 *      the pixel count) and goes straight there instead of stepping down;
 *   4. only at the smallest allowed size does quality go below the floor.
 *
 * Kept free of browser APIs so the strategy can be unit-tested with a size model.
 */

export interface Attempt<T> {
  size: number;
  longEdge: number;
  quality: number;
  result: T;
}

export interface FitOptions {
  maxBytes: number;
  longEdge: number;
  minLongEdge: number;
  maxQuality?: number;
  qualityFloor?: number;
  lastResortQualities?: number[];
}

export type Encode<T> = (longEdge: number, quality: number) => Promise<{ size: number; result: T }>;

const SEARCH_STEPS = 3;
const SAFETY = 0.94; // aim a little under the limit when estimating a smaller size

export async function fitUnderLimit<T>(encode: Encode<T>, options: FitOptions): Promise<Attempt<T> & { encodes: number }> {
  const maxQuality = options.maxQuality ?? 0.85;
  const floor = options.qualityFloor ?? 0.55;
  const lastResort = options.lastResortQualities ?? [0.5, 0.45, 0.4, 0.35, 0.3];
  let encodes = 0;

  const attempt = async (longEdge: number, quality: number): Promise<Attempt<T>> => {
    encodes += 1;
    const { size, result } = await encode(longEdge, quality);
    return { size, longEdge, quality, result };
  };
  const fits = (a: Attempt<T>) => a.size <= options.maxBytes;
  const done = (a: Attempt<T>) => ({ ...a, encodes });

  let edge = options.longEdge;
  let tooBigEdge: number | null = null; // last size that did not fit even at the floor
  for (let round = 0; round < 6; round += 1) {
    const best = await attempt(edge, maxQuality);
    if (fits(best)) return done(best);

    let atFloor = await attempt(edge, floor);
    if (fits(atFloor) && tooBigEdge !== null && tooBigEdge - edge > 64) {
      // The size estimate is cautious; one try halfway back wins back resolution if it fits.
      const between = Math.round((edge + tooBigEdge) / 2);
      const tryBetween = await attempt(between, floor);
      if (fits(tryBetween)) {
        edge = between;
        atFloor = tryBetween;
      }
    }
    if (fits(atFloor)) {
      // Highest quality between the floor and the maximum that still fits.
      let good = atFloor;
      let low = floor;
      let high = maxQuality;
      for (let step = 0; step < SEARCH_STEPS; step += 1) {
        const mid = Math.round(((low + high) / 2) * 100) / 100;
        if (mid <= low || mid >= high) break;
        const tryMid = await attempt(edge, mid);
        if (fits(tryMid)) {
          good = tryMid;
          low = mid;
        } else {
          high = mid;
        }
      }
      return done(good);
    }

    if (edge <= options.minLongEdge) break;
    tooBigEdge = edge;
    // File size grows roughly with pixel count, so scale the long edge by sqrt(limit / size).
    const scale = Math.sqrt(options.maxBytes / atFloor.size) * SAFETY;
    edge = Math.max(options.minLongEdge, Math.min(Math.round(edge * scale), edge - 32));
  }

  for (const quality of lastResort) {
    const tryLow = await attempt(edge, quality);
    if (fits(tryLow)) return done(tryLow);
  }
  throw new Error(`Could not fit the image under ${options.maxBytes} bytes`);
}

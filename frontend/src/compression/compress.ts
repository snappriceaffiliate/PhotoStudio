import { largestEmbeddedJpeg } from './extractJpeg';
import { fitUnderLimit } from './fitSize';

/** One image per photo, used as both thumbnail and preview. Small files matter more than
 * clarity: the client only needs to recognise and choose the photo. */
export const MAX_IMAGE_BYTES = 40 * 1024;
export const IMAGE_LONG_EDGE = 1200;
const MIN_IMAGE_LONG_EDGE = 480;
// Below this WebP quality detail smears badly; shrink the image a little instead.
const IMAGE_QUALITY_FLOOR = 0.35;
const IMAGE_MAX_QUALITY = 0.75;

export const RAW_EXTENSIONS = ['cr2', 'cr3', 'nef', 'nrw', 'arw', 'srf', 'sr2', 'raf', 'orf', 'rw2', 'dng', 'pef', 'srw'];
export const JPEG_EXTENSIONS = ['jpg', 'jpeg'];

export interface EncodedImage {
  blob: Blob;
  width: number;
  height: number;
  quality: number;
}

export interface CompressOptions {
  watermark?: string;
}

export interface CompressResult {
  name: string;
  path: string;
  extension: string;
  source: 'embedded-jpeg' | 'direct';
  sourceWidth: number;
  sourceHeight: number;
  /** The one stored image (thumbnail and preview in one). */
  preview: EncodedImage;
  ms: number;
}

export function extensionOf(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot < 0 ? '' : name.slice(dot + 1).toLowerCase();
}

/** Decode the photo: the largest embedded JPEG for RAW files, the file itself for JPEGs. */
async function decode(file: File, ext: string): Promise<{ bitmap: ImageBitmap; source: CompressResult['source'] }> {
  if (RAW_EXTENSIONS.includes(ext)) {
    const bytes = new Uint8Array(await file.arrayBuffer());
    const jpeg = largestEmbeddedJpeg(bytes);
    if (!jpeg) throw new Error('No embedded JPEG preview found');
    const blob = new Blob([bytes.subarray(jpeg.offset, jpeg.offset + jpeg.length)], { type: 'image/jpeg' });
    return { bitmap: await createImageBitmap(blob, { imageOrientation: 'from-image' }), source: 'embedded-jpeg' };
  }
  if (JPEG_EXTENSIONS.includes(ext)) {
    return { bitmap: await createImageBitmap(file, { imageOrientation: 'from-image' }), source: 'direct' };
  }
  throw new Error(`Unsupported file type .${ext}`);
}

function draw(bitmap: ImageBitmap, longEdge: number, watermark?: string): OffscreenCanvas {
  const scale = Math.min(1, longEdge / Math.max(bitmap.width, bitmap.height));
  const width = Math.round(bitmap.width * scale);
  const height = Math.round(bitmap.height * scale);
  const canvas = new OffscreenCanvas(width, height);
  const ctx = canvas.getContext('2d')!;
  ctx.imageSmoothingEnabled = true;
  ctx.imageSmoothingQuality = 'high';
  ctx.drawImage(bitmap, 0, 0, width, height);
  if (watermark) drawWatermark(ctx, width, height, watermark);
  return canvas;
}

/** Large and see-through, across the middle along the photo's diagonal, so it cannot be
 * cropped away but the photo can still be judged. The server draws the same for Drive imports. */
export function watermarkSize(textWidthAt100: number, width: number, height: number): number {
  const diagonal = Math.hypot(width, height);
  // The text spans about 70% of the diagonal, but is never taller than a fifth of the short side.
  return Math.max(16, Math.min((diagonal * 0.7 * 100) / Math.max(1, textWidthAt100), Math.min(width, height) * 0.2));
}

function drawWatermark(ctx: OffscreenCanvasRenderingContext2D, width: number, height: number, text: string) {
  const font = (px: number) => `700 ${px}px system-ui, sans-serif`;
  ctx.font = font(100);
  const size = watermarkSize(ctx.measureText(text).width, width, height);
  ctx.save();
  ctx.translate(width / 2, height / 2);
  ctx.rotate(-Math.atan2(height, width));
  ctx.font = font(size);
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineJoin = 'round';
  ctx.lineWidth = Math.max(1, size / 14);
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.4)';
  ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
  ctx.strokeText(text, 0, 0);
  ctx.fillText(text, 0, 0);
  ctx.restore();
}

/** Encode as WebP under the byte limit, preferring a slightly smaller image to heavy
 * compression artefacts (see fitSize.ts for the search). */
async function encodeUnder(
  bitmap: ImageBitmap,
  longEdge: number,
  minLongEdge: number,
  maxBytes: number,
  qualityFloor: number,
  maxQuality: number,
  watermark?: string,
): Promise<EncodedImage> {
  const canvases = new Map<number, OffscreenCanvas>();
  const fit = await fitUnderLimit<{ blob: Blob; width: number; height: number }>(
    async (edge, quality) => {
      let canvas = canvases.get(edge);
      if (!canvas) {
        canvas = draw(bitmap, edge, watermark);
        canvases.set(edge, canvas);
      }
      const blob = await canvas.convertToBlob({ type: 'image/webp', quality });
      if (blob.type !== 'image/webp') throw new Error('This browser cannot encode WebP');
      return { size: blob.size, result: { blob, width: canvas.width, height: canvas.height } };
    },
    { maxBytes, longEdge, minLongEdge, qualityFloor, maxQuality, lastResortQualities: [0.3, 0.25, 0.2] },
  );
  return { ...fit.result, quality: fit.quality };
}

export async function compressFile(file: File, path: string, options: CompressOptions = {}): Promise<CompressResult> {
  const started = performance.now();
  const ext = extensionOf(file.name);
  const { bitmap, source } = await decode(file, ext);
  try {
    const preview = await encodeUnder(
      bitmap, IMAGE_LONG_EDGE, MIN_IMAGE_LONG_EDGE, MAX_IMAGE_BYTES, IMAGE_QUALITY_FLOOR, IMAGE_MAX_QUALITY, options.watermark,
    );
    return {
      name: file.name,
      path,
      extension: ext,
      source,
      sourceWidth: bitmap.width,
      sourceHeight: bitmap.height,
      preview,
      ms: Math.round(performance.now() - started),
    };
  } finally {
    bitmap.close();
  }
}

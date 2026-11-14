import { largestEmbeddedJpeg } from './extractJpeg';
import { fitUnderLimit } from './fitSize';

export const MAX_IMAGE_BYTES = 100 * 1024;
export const PREVIEW_LONG_EDGE = 1600;
export const THUMB_LONG_EDGE = 400;
const MIN_PREVIEW_LONG_EDGE = 800;
const MIN_THUMB_LONG_EDGE = 200;
// Below these WebP qualities fine detail starts to smear; shrink the image a little instead.
const PREVIEW_QUALITY_FLOOR = 0.55;
const THUMB_QUALITY_FLOOR = 0.45;

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
  preview: EncodedImage;
  thumb: EncodedImage;
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
  if (watermark) {
    const size = Math.max(14, Math.round(width * 0.03));
    ctx.font = `600 ${size}px system-ui, sans-serif`;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'bottom';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.55)';
    ctx.strokeStyle = 'rgba(0, 0, 0, 0.35)';
    ctx.lineWidth = Math.max(1, size / 14);
    ctx.strokeText(watermark, width - size, height - size);
    ctx.fillText(watermark, width - size, height - size);
  }
  return canvas;
}

/** Encode as WebP under the byte limit, preferring a slightly smaller image to heavy
 * compression artefacts (see fitSize.ts for the search). */
async function encodeUnder(
  bitmap: ImageBitmap,
  longEdge: number,
  minLongEdge: number,
  maxBytes: number,
  qualityFloor: number,
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
    { maxBytes, longEdge, minLongEdge, qualityFloor },
  );
  return { ...fit.result, quality: fit.quality };
}

export async function compressFile(file: File, path: string, options: CompressOptions = {}): Promise<CompressResult> {
  const started = performance.now();
  const ext = extensionOf(file.name);
  const { bitmap, source } = await decode(file, ext);
  try {
    const preview = await encodeUnder(bitmap, PREVIEW_LONG_EDGE, MIN_PREVIEW_LONG_EDGE, MAX_IMAGE_BYTES, PREVIEW_QUALITY_FLOOR, options.watermark);
    const thumb = await encodeUnder(bitmap, THUMB_LONG_EDGE, MIN_THUMB_LONG_EDGE, MAX_IMAGE_BYTES, THUMB_QUALITY_FLOOR);
    return {
      name: file.name,
      path,
      extension: ext,
      source,
      sourceWidth: bitmap.width,
      sourceHeight: bitmap.height,
      preview,
      thumb,
      ms: Math.round(performance.now() - started),
    };
  } finally {
    bitmap.close();
  }
}

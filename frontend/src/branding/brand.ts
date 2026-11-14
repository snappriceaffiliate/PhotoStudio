/**
 * Studio branding helpers: colour checks that match the server, the CSS variables a
 * studio's accent colour sets, and turning a logo file into a small WebP.
 */
import type { CSSProperties } from 'react';

export const LOGO_MAX_BYTES = 55 * 1024; // the server refuses anything over 60 KB
export const LOGO_LONG_EDGE = 480;
export const MIN_CONTRAST = 4.5;
const HEX = /^#[0-9a-f]{6}$/i;

export interface StudioBranding {
  logo_url: string | null;
  accent_color: string | null;
}

export function isHexColour(value: string): boolean {
  return HEX.test(value);
}

function luminance(hex: string): number {
  const channel = (i: number) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  };
  return 0.2126 * channel(1) + 0.7152 * channel(3) + 0.0722 * channel(5);
}

export function contrastWithWhite(hex: string): number {
  return 1.05 / (luminance(hex) + 0.05);
}

/** Inline style that hands the accent colour to the stylesheet (see .branded in index.css). */
export function brandStyle(accent: string | null | undefined): CSSProperties | undefined {
  if (!accent || !isHexColour(accent)) return undefined;
  return { '--brand-accent': accent } as CSSProperties;
}

/** Resize a PNG, JPEG or WebP logo and encode it as WebP under LOGO_MAX_BYTES. Keeps transparency. */
export async function makeLogo(file: File): Promise<Blob> {
  let bitmap: ImageBitmap;
  try {
    bitmap = await createImageBitmap(file);
  } catch {
    throw new Error('This file could not be read as an image. Use a PNG, JPG or WebP file.');
  }
  try {
    let edge = Math.min(LOGO_LONG_EDGE, Math.max(bitmap.width, bitmap.height));
    for (let attempt = 0; attempt < 6; attempt++) {
      const scale = edge / Math.max(bitmap.width, bitmap.height);
      const width = Math.max(1, Math.round(bitmap.width * scale));
      const height = Math.max(1, Math.round(bitmap.height * scale));
      const canvas = document.createElement('canvas');
      canvas.width = width;
      canvas.height = height;
      const context = canvas.getContext('2d');
      if (!context) throw new Error('This browser cannot resize images.');
      context.drawImage(bitmap, 0, 0, width, height);
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/webp', 0.9));
      if (!blob || blob.type !== 'image/webp') throw new Error('This browser cannot make WebP images. Try Chrome, Edge or Firefox.');
      if (blob.size <= LOGO_MAX_BYTES) return blob;
      edge = Math.round(edge * 0.75);
    }
    throw new Error('This logo is too detailed to make small enough. Try a simpler version.');
  } finally {
    bitmap.close();
  }
}

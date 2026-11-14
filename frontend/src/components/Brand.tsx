/**
 * Brand mark and shared icons. The mark is a camera viewfinder (four corners) framing a
 * heart: the moment a client chooses a photo. Product name lives in one place: BRAND_NAME.
 */

export const BRAND_NAME = 'Pickframe';

export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
      <rect width="32" height="32" rx="9" fill="var(--primary)" />
      <path
        d="M8 12V9a1 1 0 0 1 1-1h3M20 8h3a1 1 0 0 1 1 1v3M24 20v3a1 1 0 0 1-1 1h-3M12 24H9a1 1 0 0 1-1-1v-3"
        stroke="var(--on-primary)" strokeWidth="2" strokeLinecap="round" fill="none"
      />
      <path
        d="M16 21.2s-5-3-5-6.4a2.8 2.8 0 0 1 5-1.7 2.8 2.8 0 0 1 5 1.7c0 3.4-5 6.4-5 6.4Z"
        fill="var(--marigold)"
      />
    </svg>
  );
}

export function Logo({ size = 32, withName = true }: { size?: number; withName?: boolean }) {
  return (
    <span className="logo">
      <LogoMark size={size} />
      {withName && <span className="wordmark">{BRAND_NAME}</span>}
    </span>
  );
}

export function HeartIcon({ filled = false, size = 22 }: { filled?: boolean; size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M12 20.5s-7.5-4.6-7.5-10.1A4.4 4.4 0 0 1 12 7.6a4.4 4.4 0 0 1 7.5 2.8c0 5.5-7.5 10.1-7.5 10.1Z"
        fill={filled ? 'currentColor' : 'none'} stroke="currentColor" strokeWidth="2" strokeLinejoin="round"
      />
    </svg>
  );
}

export function PhotosIcon({ size = 40 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" aria-hidden="true" focusable="false" fill="none"
      stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="5" width="15" height="13" rx="2" />
      <path d="M6 18l4-5 3 3.5 2-2.5 3 4" />
      <circle cx="13.5" cy="9" r="1.4" />
      <path d="M21 8v11a2 2 0 0 1-2 2H7" />
    </svg>
  );
}

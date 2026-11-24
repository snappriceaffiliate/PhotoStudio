/**
 * Brand mark and shared icons. The mark is a photo whose horizon is a tick: the moment a client
 * chooses a photo. The files for print, web and social media are in brand/ at the repo root.
 * Product name lives in one place: BRAND_NAME.
 */
import { useId } from 'react';
import { LOGO_HEIGHT, LOGO_WIDTH, PICK_PATH, SNAP_PATH, TEXT_BASELINE, TEXT_X } from './logoPaths';

export const BRAND_NAME = 'PickSnap';

/** Where studios reach PickSnap for help, billing questions and feedback. */
export const CONTACT_EMAIL = 'contact@picksnap.in';

/** The icon's shapes in its own 6..74 box; the colours are fixed brand colours. */
function MarkShapes() {
  const clip = useId();
  return (
    <>
      <defs>
        <clipPath id={clip}><rect x="6" y="6" width="68" height="68" rx="16" /></clipPath>
      </defs>
      <rect x="6" y="6" width="68" height="68" rx="16" fill="#3b2f8f" />
      <circle cx="54" cy="22" r="7" fill="#ffd9a0" />
      <path d="M0 40L30 62L80 18V80H0Z" fill="#ff6b5a" clipPath={`url(#${clip})`} />
    </>
  );
}

export function LogoMark({ size = 32 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="6 6 68 68" aria-hidden="true" focusable="false">
      <MarkShapes />
    </svg>
  );
}

/** The icon and the name on one line; `size` is the icon's height. */
export function Logo({ size = 32, withName = true }: { size?: number; withName?: boolean }) {
  if (!withName) {
    return <span className="logo"><LogoMark size={size} /></span>;
  }
  const iconScale = LOGO_HEIGHT / 68;
  return (
    <span className="logo">
      <svg width={(size * LOGO_WIDTH) / LOGO_HEIGHT} height={size} viewBox={`0 0 ${LOGO_WIDTH} ${LOGO_HEIGHT}`}
        role="img" aria-label={BRAND_NAME}>
        <g transform={`scale(${iconScale}) translate(-6 -6)`}><MarkShapes /></g>
        <g transform={`translate(${TEXT_X} ${TEXT_BASELINE})`}>
          <path className="logo-pick" d={PICK_PATH} />
          <path className="logo-snap" d={SNAP_PATH} />
        </g>
      </svg>
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

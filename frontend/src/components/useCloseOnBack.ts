import { useEffect, useRef } from 'react';

// A history step removal waiting to happen; cancelled if the overlay opens again at once
// (React runs effects twice in development, and the second run reuses the step).
let pendingBack: ReturnType<typeof setTimeout> | undefined;

/**
 * While `open`, the phone's Back button (or the browser's) closes the overlay instead of
 * leaving the page. Opening adds a history step at the same address; Back removes it and
 * calls onClose. Closing another way (✕, Escape, a tap) takes that step back out, so the
 * history stays as it was.
 */
export function useCloseOnBack(open: boolean, onClose: () => void) {
  const close = useRef(onClose);
  useEffect(() => {
    close.current = onClose;
  });

  useEffect(() => {
    if (!open) return;
    clearTimeout(pendingBack);
    if (!window.history.state?.overlay) {
      // Keep the router's own state on the entry so it treats Back as staying on this page.
      window.history.pushState({ ...(window.history.state ?? {}), overlay: true }, '');
    }
    let closedByBack = false;
    const onPop = () => {
      closedByBack = true;
      close.current();
    };
    window.addEventListener('popstate', onPop);
    return () => {
      window.removeEventListener('popstate', onPop);
      if (closedByBack) return;
      pendingBack = setTimeout(() => {
        if (window.history.state?.overlay) window.history.back();
      }, 0);
    };
  }, [open]);
}

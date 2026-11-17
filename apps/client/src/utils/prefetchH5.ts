let scheduled = false;

/** Idle-prefetch stack + radio so the first header tap is not a cold chunk. */
export function prefetchCoreChunks() {
  if (process.env.TARO_ENV !== "h5" || scheduled || typeof window === "undefined") return;
  scheduled = true;
  const run = () => {
    void import("../packageStack/pages/search/index");
    void import("../packageStack/pages/notifications/index");
    void import("../packageStack/pages/pricing/index");
    void import("../packageSocial/pages/radio/index");
    void import("../packageCreator/CreatorDesk");
  };
  const ric = (window as Window & { requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => void })
    .requestIdleCallback;
  if (typeof ric === "function") ric(run, { timeout: 2500 });
  else setTimeout(run, 1200);
}

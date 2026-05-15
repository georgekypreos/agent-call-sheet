/** Open a URL in a single reusable browser tab per "key". Subsequent calls re-navigate. */
const REFS: Record<string, Window | null> = {};

export function openSingleTab(key: string, url: string): void {
  try {
    const existing = REFS[key];
    if (existing && !existing.closed) {
      existing.location.href = url;
      try { existing.focus(); } catch {}
    } else {
      REFS[key] = window.open(url, `${key}-window`);
    }
  } catch (err) {
    console.warn("openSingleTab error:", err);
    window.open(url, "_blank");
  }
}

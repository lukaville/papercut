// Persisted FlexLayout arrangement. Bump the key when the default layout's
// component set changes so returning users don't get a stale layout missing
// newly added panels.
export const LAYOUT_KEY = "papercut-manual-layout-v5";

export function clearSavedLayout(): void {
  try {
    localStorage.removeItem(LAYOUT_KEY);
  } catch {
    // ignore
  }
}

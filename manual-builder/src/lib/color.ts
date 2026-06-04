/** Mix a hex color toward white by `amount` (0 = unchanged, 1 = white). */
export function lighten(hex: string, amount: number): string {
  const rgb = parseHex(hex);
  if (!rgb) return hex;
  const mix = (c: number) => Math.round(c + (255 - c) * amount);
  return toHex(mix(rgb.r), mix(rgb.g), mix(rgb.b));
}

/**
 * Display color for a part: lightened 50% toward white. Source CAD colors are
 * often dark and blend together (and with the dark sheet labels) in the
 * viewport, so we render a lighter, more distinguishable variant everywhere a
 * part color is shown (mesh + swatches).
 */
export function partColor(hex: string): string {
  return lighten(hex, 0.5);
}

function parseHex(hex: string): { r: number; g: number; b: number } | null {
  let h = hex.trim().replace(/^#/, "");
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2];
  if (h.length !== 6 || /[^0-9a-fA-F]/.test(h)) return null;
  return {
    r: parseInt(h.slice(0, 2), 16),
    g: parseInt(h.slice(2, 4), 16),
    b: parseInt(h.slice(4, 6), 16),
  };
}

function toHex(r: number, g: number, b: number): string {
  const c = (n: number) => n.toString(16).padStart(2, "0");
  return `#${c(r)}${c(g)}${c(b)}`;
}

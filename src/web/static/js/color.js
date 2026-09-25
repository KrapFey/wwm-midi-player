// Color helpers for the visualizer and track swatches.

const PITCHED_COLOR_INDICES = [...Array(16).keys()].filter((i) => i !== 9);

/**
 * Color a note by its track (not its MIDI channel: many files route every
 * instrument through one channel and tell them apart by track), cycling the
 * skin's 16 note colors minus index 9, which is reserved for drums.
 */
export function noteColor(noteColors, track, isDrum) {
  if (isDrum) return noteColors[9];
  return noteColors[PITCHED_COLOR_INDICES[track % PITCHED_COLOR_INDICES.length]];
}

export function hexToRgb(hex) {
  const value = parseInt(hex.slice(1), 16);
  return [(value >> 16) & 255, (value >> 8) & 255, value & 255];
}

export function rgba(hex, alpha) {
  const [r, g, b] = hexToRgb(hex);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

function rgbToHsv(r, g, b) {
  const max = Math.max(r, g, b);
  const delta = max - Math.min(r, g, b);
  let h = 0;
  if (delta) {
    if (max === r) h = ((g - b) / delta) % 6;
    else if (max === g) h = (b - r) / delta + 2;
    else h = (r - g) / delta + 4;
  }
  return [(h * 60 + 360) % 360, max ? delta / max : 0, max];
}

function hsvToHex(h, s, v) {
  const c = v * s;
  const x = c * (1 - Math.abs(((h / 60) % 2) - 1));
  const m = v - c;
  const [r, g, b] = h < 60 ? [c, x, 0] : h < 120 ? [x, c, 0] : h < 180 ? [0, c, x]
    : h < 240 ? [0, x, c] : h < 300 ? [x, 0, c] : [c, 0, x];
  return "#" + [r, g, b].map((n) => Math.round(n + m).toString(16).padStart(2, "0")).join("");
}

// The visualizer shades every note every frame from a small set of track
// colors, so results are memoized rather than recomputed through HSV.
const shadeCache = new Map();

/**
 * Scale the HSV value by factor / 100 (> 100 lighter, < 100 darker); if that
 * overflows, desaturate by the overflow instead. These are Qt's
 * QColor.lighter/darker semantics, kept from the original Qt UI so skins
 * shade notes the same way.
 */
export function shade(hex, factor) {
  const cacheKey = `${hex}|${factor}`;
  let shaded = shadeCache.get(cacheKey);
  if (shaded === undefined) {
    shaded = computeShade(hex, factor);
    shadeCache.set(cacheKey, shaded);
  }
  return shaded;
}

function computeShade(hex, factor) {
  const [h, s, v] = rgbToHsv(...hexToRgb(hex));
  let value = (v * factor) / 100;
  let saturation = s * 255;
  if (value > 255) {
    saturation = Math.max(0, saturation - (value - 255));
    value = 255;
  }
  return hsvToHex(h, saturation / 255, value);
}

export const lighter = (hex, factor) => shade(hex, factor);
export const darker = (hex, factor) => shade(hex, 10000 / factor);

// Applies the active skin (utils/skins.py, via Api.get_state) to a page as CSS
// variables + effect attributes (data-glass/data-hud/data-glow, shared by any
// skin that opts in), data-skin=<key> (for one skin's own CSS block), and
// data-variant=dark|light (for a skin's light-variant tweaks).
// Shared by the main window and the mini player.

const FALLBACK_FONTS = ['"Segoe UI"', "system-ui", "sans-serif"];
const fontStack = (families) => [...families.map((f) => `"${f}"`), ...FALLBACK_FONTS].join(", ");

const baseSkin = (state) => state.skins[state.skin] ?? state.skins.default;

/** The variant a skin renders (Skin.resolve_variant: single-variant skins ignore the preference). */
const variantOf = (skin, theme) => (skin.palettes[theme] ? theme : Object.keys(skin.palettes)[0]);

/** The active skin with its variant's overrides (note colors, piano, glow, scanlines) merged in. */
export function activeSkin(state) {
  const skin = baseSkin(state);
  const overrides = skin.variant_styles[variantOf(skin, state.theme)] ?? {};
  const set = Object.entries(overrides).filter(([, value]) => value !== null);
  return { ...skin, ...Object.fromEntries(set) };
}

/** Returns {skin, palette} for the rendered variant. */
export function applySkin(state) {
  const skin = activeSkin(state);
  const variant = variantOf(skin, state.theme);
  const palette = skin.palettes[variant];
  const root = document.documentElement;
  for (const [name, hex] of Object.entries(palette)) {
    root.style.setProperty(`--${name.toLowerCase().replaceAll("_", "-")}`, hex);
  }
  const body = skin.font_families;
  root.style.setProperty("--font-body", fontStack(body));
  root.style.setProperty("--font-heading", fontStack(skin.heading_families.length ? skin.heading_families : body));
  root.style.setProperty("--font-mono", fontStack(skin.mono_families.length ? skin.mono_families : body));
  root.style.setProperty("--radius-sm", `${skin.radius_sm}px`);
  root.style.setProperty("--radius-md", `${skin.radius_md}px`);
  root.style.colorScheme = variant;
  root.toggleAttribute("data-glass", skin.glass);
  root.toggleAttribute("data-hud", skin.hud);
  root.toggleAttribute("data-glow", skin.neon_glow);
  root.dataset.skin = state.skins[state.skin] ? state.skin : "default";
  root.dataset.variant = variant;
  return { skin, palette };
}

/**
 * Show a song title, restarting its "flicker" animation when the text changes
 * (skins that style .flicker/.glitch animate it; data-text feeds the glitch
 * layers, which duplicate the title via CSS content: attr(data-text)).
 */
export function setTitle(element, text) {
  if (element.textContent === text) return;
  element.textContent = text;
  element.dataset.text = text;
  element.classList.remove("flicker");
  void element.offsetWidth;  // restart the CSS animation
  element.classList.add("flicker");
}

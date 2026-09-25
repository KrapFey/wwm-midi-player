// Applies the active skin (utils/skins.py, via Api.get_state) to a page as CSS
// variables + effect attributes. Shared by the main window and the mini player.

const FALLBACK_FONTS = ['"Segoe UI"', "system-ui", "sans-serif"];
const fontStack = (families) => [...families.map((f) => `"${f}"`), ...FALLBACK_FONTS].join(", ");

export const activeSkin = (state) => state.skins[state.skin] ?? state.skins.default;

/** Returns {skin, palette} for the rendered variant (dark-only skins ignore a Light preference). */
export function applySkin(state) {
  const skin = activeSkin(state);
  const variant = skin.palettes[state.theme] ? state.theme : Object.keys(skin.palettes)[0];
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
  return { skin, palette };
}

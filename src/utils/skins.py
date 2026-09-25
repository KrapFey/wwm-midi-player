"""Skin registry: every visual parameter that differs between app skins.

Pure data, so it's unit-testable. web.api.Api.get_state() sends every skin to
the page, where web/static/js/skin.js turns the active one into CSS variables
(each PALETTE_KEYS entry becomes --lower-kebab-case, e.g. ACCENT_1 ->
--accent-1) plus data-glass/data-hud/data-glow attributes for shared effects
and data-skin=<key> for skin-specific CSS.

A skin's palettes are keyed by variant ("dark"/"light"); a variant can also
override the skin's note colors, piano, glow, and scanlines via
Skin.variant_styles, and the page gets data-variant=<variant> for
variant-specific CSS. The user's Dark/Light preference is kept separately
from the skin, so switching to a single-variant skin and back restores the
user's original choice - see Skin.resolve_variant().
"""

from dataclasses import dataclass, field

DEFAULT_SKIN: str = "default"
VARIANTS: tuple[str, ...] = ("dark", "light")
# Every palette must define exactly these colors (the CSS reads each one).
PALETTE_KEYS: tuple[str, ...] = (
    "ACCENT_1", "ACCENT_2", "HIGHLIGHT", "VOLUME", "MODE", "SOLO",
    "BACKGROUND", "BACKGROUND_1", "BACKGROUND_2", "BORDER",
    "RED", "GREEN", "BLUE", "BLACK", "WHITE", "TEXT_MUTED",
)

# Falling-note colors for the piano visualizer, one per MIDI channel (0-15).
# Index 9 (the GM percussion channel) gets a distinct silver/grey so drum hits
# read as visually different from pitched instruments.
CHANNEL_COLORS: tuple[str, ...] = (
    "#4FC3F7", "#81C784", "#FFB74D", "#E57373",
    "#BA68C8", "#4DB6AC", "#FFD54F", "#7986CB",
    "#F06292", "#B0BEC5",
    "#AED581", "#FF8A65", "#9575CD", "#4DD0E1",
    "#DCE775", "#F48FB1",
)


@dataclass(frozen=True, slots=True)
class PianoColors:
    """Visualizer keyboard colors, independent of the app palette.

    Attributes:
        white_top: White-key gradient top color.
        white_bottom: White-key gradient bottom color.
        black_top: Black-key gradient top color.
        black_bottom: Black-key gradient bottom color.
        border: Outline between white keys, or None to use Colors.BACKGROUND.
    """

    white_top: str
    white_bottom: str
    black_top: str
    black_bottom: str
    border: str|None = None


@dataclass(frozen=True, slots=True)
class VariantStyle:
    """Per-variant overrides of a skin's rendering (None keeps the skin's own).

    Attributes:
        note_colors: 16 note colors for this variant (neons that glow on
            black wash out on white).
        piano: Visualizer keyboard colors for this variant.
        neon_glow: Whether this variant draws neon glows.
        scanlines: Whether to draw visualizer scanlines in this variant.
    """

    note_colors: tuple[str, ...]|None = None
    piano: PianoColors|None = None
    neon_glow: bool|None = None
    scanlines: bool|None = None


@dataclass(frozen=True, slots=True)
class Skin:
    """One app skin.

    Attributes:
        display_name: Name shown in the Settings skin picker.
        palettes: Variant name -> {color name: hex}. Every palette must
            define exactly PALETTE_KEYS.
        note_colors: 16 visualizer/track-swatch colors, index 9 reserved
            for drums (see noteColor in web/static/js/color.js).
        piano: Visualizer keyboard colors.
        radius_sm: Corner radius for buttons, inputs, and list rows.
        radius_md: Corner radius for panels/cards.
        font_families: Preferred body font families in fallback order, or
            empty for the system UI font.
        heading_families: Preferred font families for headings (song title,
            window title, tabs), or empty to use the body font.
        mono_families: Preferred monospaced families for numbers/readouts
            (time label, visualizer telemetry), or empty to use the body font.
        neon_glow: Draw soft outer glows around notes, bars, the play button,
            toggles, and key text, instead of flat solid color.
        glass: Glassmorphism: a softly lit window backdrop behind
            translucent-looking cards with a subtle top sheen, and the
            visualizer drawn as a rounded card.
        note_style: How the visualizer draws notes: "gradient" (shaded bars)
            or "neon" (neon tubes: a bright outline around a dim fill, lit
            solid while sounding).
        scanlines: Draw faint CRT scanlines over the visualizer's falling
            notes (only there - over text they just blur it).
        hud: Sci-fi instrumentation: segmented LED progress/volume bars, a
            telemetry grid and live readouts in the visualizer, status chips,
            and uppercase technical captions.
        variant_styles: Variant name -> overrides of note_colors/piano/
            neon_glow/scanlines for that variant (merged over the skin in
            js/skin.js).
    """

    display_name: str
    palettes: dict[str, dict[str, str]]
    note_colors: tuple[str, ...]
    piano: PianoColors
    radius_sm: int = 6
    radius_md: int = 10
    font_families: tuple[str, ...] = ()
    heading_families: tuple[str, ...] = ()
    mono_families: tuple[str, ...] = ()
    neon_glow: bool = False
    glass: bool = False
    hud: bool = False
    note_style: str = "gradient"
    scanlines: bool = False
    variant_styles: dict[str, VariantStyle] = field(default_factory=dict)

    @property
    def variants(self) -> tuple[str, ...]:
        """Return the variants this skin supports, in preference order.

        Returns:
            The skin's variant names, e.g. ("dark", "light").
        """
        return tuple(self.palettes)

    def resolve_variant(self, preferred: str) -> str:
        """Return preferred if this skin supports it, else the skin's first variant.

        Args:
            preferred: The user's Dark/Light preference.

        Returns:
            The variant to actually render with.
        """
        return preferred if preferred in self.palettes else self.variants[0]

    def note_colors_for(self, variant: str) -> tuple[str, ...]:
        """Return the note colors a variant renders with.

        Args:
            variant: A variant name, e.g. from resolve_variant().

        Returns:
            The variant's override if it has one, else the skin's note_colors.
        """
        style = self.variant_styles.get(variant)
        return style.note_colors if style and style.note_colors else self.note_colors


_DEFAULT_DARK: dict[str, str] = {
    "ACCENT_1": "#2E7D32",
    "ACCENT_2": "#8D6E63",
    "HIGHLIGHT": "#C0A060",
    "VOLUME": "#2E7D32",
    "MODE": "#2E7D32",
    "SOLO": "#E5A93E",
    "BACKGROUND": "#111111",
    "BACKGROUND_1": "#101010",
    "BACKGROUND_2": "#2A2A2A",
    "BORDER": "#111111",
    "RED": "#FF0000",
    "GREEN": "#00FF00",
    "BLUE": "#0000FF",
    "BLACK": "#000000",
    "WHITE": "#FFFFFF",
    "TEXT_MUTED": "#999999",
}

_DEFAULT_LIGHT: dict[str, str] = {
    **_DEFAULT_DARK,
    "WHITE": "#1A1A1A",
    "BACKGROUND": "#F0F0F0",
    "BACKGROUND_1": "#FFFFFF",
    "BACKGROUND_2": "#D0D0D0",
    "BORDER": "#F0F0F0",
    "TEXT_MUTED": "#666666",
}

# Neon Glass - a neon HUD on dark glass: near-black charcoal, layered cards
# with thin borders, and one glowing accent per category - blue playback
# (ACCENT_1), green volume & "live" state (VOLUME/GREEN), purple Audio/WWM
# mode (MODE), yellow solo (SOLO), red close/errors (RED) - with cyan as the
# shared gradient tail.
_NEON_GLASS_DARK: dict[str, str] = {
    "ACCENT_1": "#3B8BFF",
    "ACCENT_2": "#8B5CF6",
    "HIGHLIGHT": "#22D3EE",
    "VOLUME": "#39E58C",
    "MODE": "#A855F7",
    "SOLO": "#FACC15",
    "BACKGROUND": "#0A0C10",
    "BACKGROUND_1": "#12161C",
    "BACKGROUND_2": "#1F2630",
    "BORDER": "#262E3A",
    "RED": "#FF4D6D",
    "GREEN": "#39E58C",
    "BLUE": "#3B8BFF",
    "BLACK": "#000000",
    "WHITE": "#E6EDF3",
    "TEXT_MUTED": "#7D8998",
}

# Tracks cycle through the same category neons (green, yellow, blue, purple,
# red, ...) so the visualizer reads like the rest of the HUD.
_NEON_GLASS_NOTE_COLORS: tuple[str, ...] = (
    "#39E58C", "#FACC15", "#3B8BFF", "#A855F7",
    "#FF4D6D", "#22D3EE", "#FB923C", "#F472B6",
    "#84CC16", "#94A3B8",
    "#2DD4BF", "#818CF8", "#FDE047", "#C084FC",
    "#60A5FA", "#FB7185",
)

# Neon Glass light - frosted white glass: cool grey backdrop, white cards,
# slate text, and the same category hues deepened so they hold up on white.
_NEON_GLASS_LIGHT: dict[str, str] = {
    "ACCENT_1": "#2563EB",
    "ACCENT_2": "#7C3AED",
    "HIGHLIGHT": "#0891B2",
    "VOLUME": "#059669",
    "MODE": "#9333EA",
    "SOLO": "#D97706",
    "BACKGROUND": "#E4E9F0",
    "BACKGROUND_1": "#FFFFFF",
    "BACKGROUND_2": "#D3DAE4",
    "BORDER": "#C8D1DD",
    "RED": "#E11D48",
    "GREEN": "#059669",
    "BLUE": "#2563EB",
    "BLACK": "#000000",
    "WHITE": "#0F172A",
    "TEXT_MUTED": "#526072",
}

_NEON_GLASS_LIGHT_NOTE_COLORS: tuple[str, ...] = (
    "#059669", "#D97706", "#2563EB", "#9333EA",
    "#E11D48", "#0891B2", "#EA580C", "#DB2777",
    "#65A30D", "#64748B",
    "#0D9488", "#4F46E5", "#CA8A04", "#A855F7",
    "#0284C7", "#BE185D",
)

# Cyberpunk - Night City: acid yellow primary on near-black, cyan for data,
# hot red for frames and alerts, magenta mode, orange solo, warm off-white
# text. BORDER is a dim red, so panel edges and the visualizer grid read as
# faint red HUD lines. The angular shapes, glitch, and scanlines live in
# css/app.css under [data-skin="cyberpunk"].
_CYBERPUNK_DARK: dict[str, str] = {
    "ACCENT_1": "#FCEE0A",
    "ACCENT_2": "#00F0FF",
    "HIGHLIGHT": "#00F0FF",
    "VOLUME": "#00F0FF",
    "MODE": "#FF2BD6",
    "SOLO": "#FF9E00",
    "BACKGROUND": "#050507",
    "BACKGROUND_1": "#0B0C10",
    "BACKGROUND_2": "#1C1D24",
    "BORDER": "#3B1018",
    "RED": "#FF003C",
    "GREEN": "#1AFF8C",
    "BLUE": "#00F0FF",
    "BLACK": "#000000",
    "WHITE": "#ECE9D8",
    "TEXT_MUTED": "#8A94A0",
}

_CYBERPUNK_NOTE_COLORS: tuple[str, ...] = (
    "#FCEE0A", "#00F0FF", "#FF003C", "#1AFF8C",
    "#FF2BD6", "#FF9E00", "#7A5CFF", "#ECE9D8",
    "#00B3FF", "#807E6C",
    "#C6FF00", "#FF5C8A", "#00FFC8", "#FFD000",
    "#B388FF", "#FF6B00",
)

# Cyberpunk light - corporate daylight (Arasaka lobby, not the street): warm
# off-white panels framed in black ink, red primary, deep cyan data, and
# black-on-yellow hazard tags (css/app.css, [data-variant="light"]). No neon
# haze - glows only read on black.
_CYBERPUNK_LIGHT: dict[str, str] = {
    "ACCENT_1": "#D6002A",
    "ACCENT_2": "#00707E",
    "HIGHLIGHT": "#00707E",
    "VOLUME": "#00707E",
    "MODE": "#B0007A",
    "SOLO": "#C25E00",
    "BACKGROUND": "#E6E4DC",
    "BACKGROUND_1": "#F7F6F1",
    "BACKGROUND_2": "#D9D6CB",
    "BORDER": "#EDC3CB",
    "RED": "#D6002A",
    "GREEN": "#00845A",
    "BLUE": "#005FB8",
    "BLACK": "#000000",
    "WHITE": "#0B0C10",
    "TEXT_MUTED": "#565D68",
}

_CYBERPUNK_LIGHT_NOTE_COLORS: tuple[str, ...] = (
    "#D6002A", "#00707E", "#B39500", "#00845A",
    "#B0007A", "#C25E00", "#5A3FD1", "#3A3F47",
    "#005FB8", "#8A8F99",
    "#5E8F00", "#C2185B", "#00897B", "#9E7C00",
    "#7E57C2", "#BF360C",
)

SKINS: dict[str, Skin] = {
    "default": Skin(
        display_name="Default",
        palettes={"dark": _DEFAULT_DARK, "light": _DEFAULT_LIGHT},
        note_colors=CHANNEL_COLORS,
        piano=PianoColors("#FFFFFF", "#D8D8D8", "#3A3A3A", "#000000"),
    ),
    "cyberpunk": Skin(
        display_name="Cyberpunk",
        palettes={"dark": _CYBERPUNK_DARK, "light": _CYBERPUNK_LIGHT},
        note_colors=_CYBERPUNK_NOTE_COLORS,
        piano=PianoColors("#111216", "#08080B", "#000000", "#000000", border="#2B2A12"),
        # Angular: square everywhere; panels get chamfered corners in CSS.
        radius_sm=0,
        radius_md=0,
        # Bahnschrift (Windows 10/11) is a variable font with a width axis,
        # so the CSS can condense it (font-stretch) for the Night City look.
        font_families=("Bahnschrift", "Segoe UI"),
        heading_families=("Bahnschrift", "Segoe UI"),
        mono_families=("Cascadia Mono", "Consolas"),
        neon_glow=True,
        hud=True,
        note_style="neon",
        scanlines=True,
        variant_styles={"light": VariantStyle(
            note_colors=_CYBERPUNK_LIGHT_NOTE_COLORS,
            piano=PianoColors("#FFFFFF", "#E9E7E0", "#1A1B20", "#050507", border="#B7B2A4"),
            neon_glow=False,
            scanlines=False,
        )},
    ),
    "neon_glass": Skin(
        display_name="Neon Glass",
        palettes={"dark": _NEON_GLASS_DARK, "light": _NEON_GLASS_LIGHT},
        note_colors=_NEON_GLASS_NOTE_COLORS,
        piano=PianoColors("#1C222B", "#12161C", "#07090C", "#000000", border="#2A3340"),
        radius_sm=10,
        radius_md=16,
        # All ship with Windows 10/11 (earlier entries preferred): a
        # macOS-like body face, a futuristic heading face, and a technical
        # monospace for instrumentation-style numbers.
        font_families=("Segoe UI Variable Text", "Segoe UI"),
        heading_families=("Bahnschrift", "Segoe UI Variable Display", "Segoe UI"),
        mono_families=("Cascadia Mono", "Consolas"),
        neon_glow=True,
        glass=True,
        hud=True,
        variant_styles={"light": VariantStyle(
            note_colors=_NEON_GLASS_LIGHT_NOTE_COLORS,
            piano=PianoColors("#FFFFFF", "#E2E8F0", "#1E293B", "#0F172A", border="#CBD5E1"),
        )},
    ),
}


def get_skin(name: str) -> Skin:
    """Return the named skin, or the default skin if name is unknown.

    Args:
        name: A key of SKINS, e.g. from a user's settings file.

    Returns:
        The matching skin, falling back to SKINS[DEFAULT_SKIN].
    """
    return SKINS.get(name, SKINS[DEFAULT_SKIN])

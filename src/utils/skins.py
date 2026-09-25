"""Skin registry: every visual parameter that differs between app skins.

Pure data, so it's unit-testable. web.api.Api.get_state() sends every skin to
the page, where web/static/js/skin.js turns the active one into CSS variables
(each PALETTE_KEYS entry becomes --lower-kebab-case, e.g. ACCENT_1 ->
--accent-1) plus data-glass/data-hud/data-glow attributes for shared effects
and data-skin=<key> for skin-specific CSS.

A skin's palettes are keyed by variant ("dark"/"light"). The user's
Dark/Light preference is kept separately from the skin, so switching to a
dark-only skin and back restores the user's original choice - see
Skin.resolve_variant().
"""

from dataclasses import dataclass

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
        hud: Sci-fi instrumentation: segmented LED progress/volume bars, a
            telemetry grid and live readouts in the visualizer, status chips,
            and uppercase technical captions.
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
    "TEXT_MUTED": "#807E6C",
}

_CYBERPUNK_NOTE_COLORS: tuple[str, ...] = (
    "#FCEE0A", "#00F0FF", "#FF003C", "#1AFF8C",
    "#FF2BD6", "#FF9E00", "#7A5CFF", "#ECE9D8",
    "#00B3FF", "#807E6C",
    "#C6FF00", "#FF5C8A", "#00FFC8", "#FFD000",
    "#B388FF", "#FF6B00",
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
        palettes={"dark": _CYBERPUNK_DARK},
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
    ),
    "neon_glass": Skin(
        display_name="Neon Glass",
        palettes={"dark": _NEON_GLASS_DARK},
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

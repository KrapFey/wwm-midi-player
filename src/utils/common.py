"""Common functionality used by different modules."""

import functools
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from utils.skins import DEFAULT_SKIN, SKINS, VARIANTS, Skin, get_skin


def resource_path(path: str) -> Path:
    """Resolve a bundled resource path for both source and PyInstaller onedir builds.

    PyInstaller's onedir build collects data files under an ``_internal`` directory
    next to the executable, while running from source resolves paths relative to the
    working directory. Callers pass a path as it exists in the source tree (e.g.
    ``"src/input/logo.ico"``); if that path doesn't exist and an ``_internal``
    directory is present, the ``_internal``-prefixed location is returned instead.

    Args:
        path: Resource path as it exists in the source tree.

    Returns:
        The resolved path, adjusted for a PyInstaller onedir build if needed.
    """
    resolved: Path = Path(path)
    if resolved.exists() or not Path("_internal").is_dir():
        return resolved
    return Path("_internal") / resolved

class Singleton(type):
    """Singleton implementation."""

    _instances: dict[Callable, Callable] = {}

    def __call__(cls, *args, **kwargs) -> Callable:
        """Return the shared instance, constructing it on first call.

        Args:
            *args: Positional arguments forwarded to the class constructor
                on first call; ignored on subsequent calls.
            **kwargs: Keyword arguments forwarded to the class constructor
                on first call; ignored on subsequent calls.

        Returns:
            The singleton instance of cls.
        """
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]

# eq=False: members are compared by identity, so two Colors members that
# happen to share a hex value never collapse into one Enum alias.
@dataclass(eq=False)
class Color:
    """Color representation class."""

    hex: str = "#000000"
    qcolor: QColor  = field(init=False)

    def __post_init__(self) -> None:
        """Post initialization calculation."""
        if not self.hex.startswith("#"):
            self.hex = "#" + self.hex
        self.qcolor = QColor(self.hex)

class Colors(Enum):
    """Global colors enumeration.

    Every member's value comes from the active skin's palette (see
    utils.skins and apply_skin/apply_theme below). Switching skin or theme
    mutates each member's `Color` - including its `.qcolor` - in place, so
    every `Colors.X.value.hex`/`.qcolor` read, and every QColor reference a
    widget cached at construction time, stays correct without call sites
    needing to change. Populated from the default skin at import time.
    """

    ACCENT_1 = Color()
    ACCENT_2 = Color()
    HIGHLIGHT = Color()
    VOLUME = Color()
    MODE = Color()
    SOLO = Color()
    BACKGROUND = Color()
    BACKGROUND_1 = Color()
    BACKGROUND_2 = Color()
    BORDER = Color()
    RED = Color()
    GREEN = Color()
    BLUE = Color()
    BLACK = Color()
    WHITE = Color()
    TEXT_MUTED = Color()

_current_skin: str = DEFAULT_SKIN
_current_theme: str = "dark"
_base_font: QFont|None = None


class _ThemeBus(QObject):
    """Signal bus notifying widgets to restyle after a skin or theme switch."""

    changed: Signal = Signal()


theme_bus: _ThemeBus = _ThemeBus()


def current_theme() -> str:
    """Return the user's Dark/Light preference.

    This is the preference, not necessarily what's rendered: a dark-only
    skin renders dark regardless (see Skin.resolve_variant).

    Returns:
        "dark" or "light".
    """
    return _current_theme


def current_skin_name() -> str:
    """Return the active skin's key in utils.skins.SKINS.

    Returns:
        The active skin's name, e.g. "default" or "cyberpunk".
    """
    return _current_skin


def active_skin() -> Skin:
    """Return the active skin.

    Returns:
        The active Skin.
    """
    return get_skin(_current_skin)


def apply_theme(name: str) -> None:
    """Set the Dark/Light preference and re-apply the active skin.

    Unknown names fall back to "dark", so a bad settings file never crashes
    startup.

    Args:
        name: The theme to switch to, "dark" or "light".
    """
    global _current_theme
    _current_theme = name if name in VARIANTS else "dark"
    _apply_appearance()


def apply_skin(name: str) -> None:
    """Switch the active skin, keeping the user's Dark/Light preference.

    Unknown names fall back to the default skin, so a bad settings file
    never crashes startup.

    Args:
        name: A key of utils.skins.SKINS.
    """
    global _current_skin
    _current_skin = name if name in SKINS else DEFAULT_SKIN
    _apply_appearance()


def _apply_font(skin: Skin) -> None:
    """Set the app-wide font to the skin's preferred families, if an app exists.

    Widgets without an explicit font family (every widget here - QSS only
    ever sets size/weight) pick the new family up automatically.

    Args:
        skin: The skin being applied.
    """
    global _base_font
    if QApplication.instance() is None:
        return
    if _base_font is None:
        _base_font = QApplication.font()
    font: QFont = QFont(_base_font)
    if skin.font_families:
        font.setFamilies(list(skin.font_families))
    QApplication.setFont(font)


def _apply_appearance() -> None:
    """Copy the active skin/variant palette into Colors in place, then notify widgets."""
    skin: Skin = active_skin()
    palette: dict[str, str] = skin.palettes[skin.resolve_variant(_current_theme)]
    for member in Colors:
        hex_value: str = palette[member.name]
        member.value.hex = hex_value
        member.value.qcolor.setRgba(QColor(hex_value).rgba())
    _apply_font(skin)
    theme_bus.changed.emit()


_apply_appearance()


@functools.cache
def resolve_font_family(families: tuple[str, ...]) -> str:
    """Return the first of families installed on this system, or "" if none are.

    QSS font-family takes a single family (no fallback list), so a skin's
    preference list is resolved against the installed fonts up front.
    Cached, since installed fonts don't change while the app runs.

    Args:
        families: Preferred font families, in fallback order.

    Returns:
        The first installed family, or "" if none is installed.
    """
    installed: set[str] = set(QFontDatabase.families())
    return next((family for family in families if family in installed), "")


def _font_family_qss(families: tuple[str, ...]) -> str:
    """Return a QSS font-family declaration for families, or "" to keep the inherited font.

    Args:
        families: Preferred font families, in fallback order.

    Returns:
        E.g. 'font-family: "Bahnschrift";', or "" if none is installed.
    """
    family: str = resolve_font_family(families)
    return f'font-family: "{family}";' if family else ""


def heading_font_qss() -> str:
    """Return the active skin's heading font-family QSS, or "" for the body font.

    Returns:
        A QSS font-family declaration, or "".
    """
    return _font_family_qss(active_skin().heading_families)


def mono_font_qss() -> str:
    """Return the active skin's monospaced font-family QSS, or "" for the body font.

    Returns:
        A QSS font-family declaration, or "".
    """
    return _font_family_qss(active_skin().mono_families)


def window_background_qss() -> str:
    """Return QSS background declarations for the window/dialog backdrop.

    Glass skins get a soft light source glowing down from the top center,
    which the translucent-looking cards and transparent chrome sit on;
    other skins get the flat BACKGROUND color.

    Returns:
        A QSS background declaration.
    """
    base: QColor = Colors.BACKGROUND.value.qcolor
    if not active_skin().glass:
        return f"background-color: {base.name()};"
    return (f"background: qradialgradient(cx:0.5, cy:0, radius:1.1, fx:0.5, fy:0, "
            f"stop:0 {base.lighter(190).name()}, stop:0.6 {base.name()}, "
            f"stop:1 {base.darker(130).name()});")


def panel_background_qss() -> str:
    """Return QSS background declarations for a card/panel.

    Glass skins get a subtle top-to-bottom sheen, reading as a lit,
    translucent pane layered over the backdrop; other skins get the flat
    BACKGROUND_1 color.

    Returns:
        A QSS background declaration.
    """
    base: QColor = Colors.BACKGROUND_1.value.qcolor
    if not active_skin().glass:
        return f"background-color: {base.name()};"
    return (f"background: qlineargradient(x1:0, y1:0, x2:0, y2:1, "
            f"stop:0 {base.lighter(125).name()}, stop:1 {base.name()});")


def scrollbar_qss() -> str:
    """Return QSS for a slim, theme-matched vertical scrollbar.

    A function (not a constant) since it reads theme-dependent Colors
    values that must be re-evaluated after a theme switch, not baked in
    once at import time. Appended to a scrollable widget's own stylesheet
    wherever it needs one - there's no default styling otherwise, which
    leaves the OS's native scrollbar clashing with the app's own chrome.

    Returns:
        A QSS block targeting QScrollBar:vertical and its sub-controls.
    """
    return f"""
        QScrollBar:vertical {{
            background: transparent;
            width: 10px;
            margin: 2px 2px 2px 0px;
        }}
        QScrollBar::handle:vertical {{
            background: {Colors.BACKGROUND_2.value.hex};
            border-radius: 4px;
            min-height: 24px;
        }}
        QScrollBar::handle:vertical:hover {{
            background: {Colors.ACCENT_1.value.hex};
        }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
            height: 0px;
            border: none;
            background: none;
        }}
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
            background: none;
        }}
    """

def channel_color_hex(channel: int) -> str:
    """Return the active skin's hex color for a MIDI channel, wrapping via modulo 16.

    Args:
        channel: MIDI channel number; wrapped via modulo 16 if out of range.

    Returns:
        The channel's hex color string, e.g. "#4FC3F7".
    """
    return active_skin().note_colors[channel % 16]

# Index 9 is reserved exclusively for drum-channel notes (see note_color_hex)
# so percussion always reads as visually distinct; pitched tracks cycle
# through the other 15.
_PITCHED_COLOR_INDICES: tuple[int, ...] = tuple(i for i in range(16) if i != 9)


def note_color_hex(track: int, is_drum: bool) -> str:
    """Return the hex color for a note, keyed by its originating track.

    Colors by track rather than MIDI channel: many real-world files route
    every instrument through the same channel (commonly channel 0) and
    differentiate instruments by track instead, so coloring by channel alone
    would collapse them all into a single color. Drum-channel notes still get
    the same reserved color regardless of track, so percussion always stands
    out.

    Args:
        track: Originating MIDI track index.
        is_drum: Whether the note is on the GM percussion channel.

    Returns:
        The note's hex color string.
    """
    colors: tuple[str, ...] = active_skin().note_colors
    if is_drum:
        return colors[9]
    return colors[_PITCHED_COLOR_INDICES[track % len(_PITCHED_COLOR_INDICES)]]

# Corner radii are per-skin: see active_skin().radius_sm/radius_md.

# Shared spacing scale, applied consistently for margins/spacing in layouts.
SPACING_XS: int = 4
SPACING_SM: int = 8
SPACING_MD: int = 12
SPACING_LG: int = 16

TITLEBAR_HEIGHT: int = 32
RESIZE_MARGIN: int = 6

"""Persisted app settings: volume, Audio/WWM mode, playlist/selection, theme, and skin.

Mirrors utils.wwm_macro.KeyManager's keybindings.json persistence pattern:
a JSON file resolved via utils.common.resource_path, loaded on startup with
a safe fallback to defaults, saved on close.
"""

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from utils.common import resource_path

DEFAULT_VOLUME: int = 100
SETTINGS_PATH: Path = resource_path("src/input/settings.json")


@dataclass
class AppSettings:
    """Everything persisted between launches.

    Attributes:
        volume: Master volume slider value (0-127).
        is_audio_mode: True for Audio mode, False for WWM mode.
        playlist: File paths of the last-loaded playlist.
        current_index: Index into playlist of the last-selected track, or
            -1 if none was selected.
        theme: Dark/Light preference, "dark" or "light".
        skin: Active skin, a key of utils.skins.SKINS.
    """

    volume: int = DEFAULT_VOLUME
    is_audio_mode: bool = False
    playlist: list[str] = field(default_factory=list)
    current_index: int = -1
    theme: str = "dark"
    skin: str = "default"


def load_settings(path: Path = SETTINGS_PATH) -> AppSettings:
    """Load settings from disk, falling back to defaults if missing or invalid.

    Args:
        path: Path to the settings JSON file.

    Returns:
        The loaded settings, or AppSettings() defaults if the file is
        missing, unreadable, or malformed.
    """
    if not path.exists():
        return AppSettings()
    try:
        with path.open(encoding="utf-8") as f:
            data: dict = json.load(f)
        known_fields: set[str] = {
            "volume", "is_audio_mode", "playlist", "current_index", "theme", "skin"}
        return AppSettings(**{key: value for key, value in data.items() if key in known_fields})
    except (OSError, json.JSONDecodeError, TypeError):
        return AppSettings()


def save_settings(settings: AppSettings, path: Path = SETTINGS_PATH) -> None:
    """Save settings to disk, overwriting any existing file.

    Args:
        settings: The settings to persist.
        path: Path to write the settings JSON file to.
    """
    with path.open("w", encoding="utf-8") as f:
        json.dump(asdict(settings), f, indent=4)

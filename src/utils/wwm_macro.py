"""WWM Macro Module (Konghou) — programmatic mapping + calibration."""

import json
from copy import deepcopy
from enum import IntEnum
from pathlib import Path

import win32api
import win32con

from utils.resources import Singleton, resource_path

NOTE_MIN: int = 48
NOTE_MAX: int = 83
OCTAVE: int = 12


def fold_note(note: int, note_min: int = NOTE_MIN, note_max: int = NOTE_MAX) -> int:
    """Fold a MIDI note into [note_min, note_max] by shifting whole octaves.

    Notes below the range always land on the range's lowest octave and notes
    above it always land on the highest octave, so pitch class (the note
    "name") is always preserved exactly - only octave information for notes
    more than one octave outside the range can be lost.

    Args:
        note: The MIDI note number to fold.
        note_min: Lower bound of the target range, inclusive.
        note_max: Upper bound of the target range, inclusive.

    Returns:
        The folded note number, within [note_min, note_max].
    """
    while note < note_min:
        note += OCTAVE
    while note > note_max:
        note -= OCTAVE
    return note


def merge_keybindings(defaults: dict[str, dict[str, str]],
                      loaded: object) -> dict[str, dict[str, str]]:
    """Overlay user-saved keybindings onto the defaults, ignoring anything malformed.

    A saved file that isn't a {octave: {degree: key}} mapping, or that is
    missing octaves/degrees (e.g. hand-edited, or written by an older
    version), would otherwise raise KeyError the first time the note map is
    built. Only non-empty string keys for octave/degree pairs the defaults
    already define are taken from loaded; everything else keeps its default.

    Args:
        defaults: The built-in keybindings, as {octave: {degree: key}}.
        loaded: The raw JSON-decoded contents of the saved keybindings file,
            or None if there is no usable file.

    Returns:
        A fresh {octave: {degree: key}} dict with every default
        octave/degree present.
    """
    merged: dict[str, dict[str, str]] = deepcopy(defaults)
    if not isinstance(loaded, dict):
        return merged
    for octave, degrees in merged.items():
        saved: object = loaded.get(octave)
        if not isinstance(saved, dict):
            continue
        for degree in degrees:
            key: object = saved.get(degree)
            if isinstance(key, str) and key:
                degrees[degree] = key
    return merged


class KeyManager(metaclass=Singleton):
    """WWM Key binding manager."""

    class _Note(IntEnum):
        """Note information enumeration."""

        MIN = NOTE_MIN
        MAX = NOTE_MAX
        OFFSET = OCTAVE
        SEMITONE_OFFSET = 0

    def __init__(self) -> None:
        """Initialize WWM Key binding manager."""
        self.__offsets: dict[str, int] = {
            "1" : 0,  "#1": 1,
            "2" : 2,
            "b3": 3,  "3" : 4,
            "4" : 5,  "#4": 6,
            "5" : 7,  "#5": 8,
            "6" : 9,
            "b7": 10, "7" : 11,
        }
        self.__default_bindings: dict[str, dict[str, str]] = {
            "high": {
                "1" : "Q",      "#1": "Shift+Q",
                "2" : "W",
                "b3": "Ctrl+E", "3" : "E",
                "4" : "R",      "#4": "Shift+R",
                "5" : "T",      "#5": "Shift+T",
                "6" : "Y",
                "b7": "Ctrl+U", "7" : "U",
            },
            "med": {
                "1" : "A",      "#1": "Shift+A",
                "2" : "S",
                "b3": "Ctrl+D", "3" : "D",
                "4" : "F",      "#4": "Shift+F",
                "5" : "G",      "#5": "Shift+G",
                "6" : "H",
                "b7": "Ctrl+J", "7" : "J",
            },
            "low": {
                "1" : "Z",      "#1": "Shift+Z",
                "2" : "X",
                "b3": "Ctrl+C", "3" : "C",
                "4" : "V",      "#4": "Shift+V",
                "5" : "B",      "#5": "Shift+B",
                "6" : "N",
                "b7": "Ctrl+M", "7" : "M",
            },
        }
        self.__bindings: dict[str, dict[str, str]] = {}
        self.__base_notes: dict[str, int] = {
            "low": 48,   # C3
            "med": 60,   # C4
            "high": 72,  # C5
        }
        self.__mapping: dict[int, str] = {}
        self.__scan_code_cache: dict[int, int] = {}
        self.__vk_scan_cache: dict[str, int] = {}
        self.__cache: Path = resource_path("src/input/keybindings.json")
        self.__load_keybindings()
        self.__build_map()

    @property
    def default_bindings(self) -> dict[str, dict[str, str]]:
        """Return the built-in default keybindings, keyed by octave register then scale degree.

        Returns:
            The default keybindings, as {octave: {degree: key}}.
        """
        return self.__default_bindings

    @property
    def bindings(self) -> dict[str, dict[str, str]]:
        """Return the current (possibly user-remapped) keybindings.

        Returns:
            The active keybindings, as {octave: {degree: key}}.
        """
        return self.__bindings

    def update_keybinding(self, octave: str, note: str, new_key: str) -> None:
        """Rebind one scale degree's key, keeping its sharp/flat variants in sync.

        Args:
            octave: Octave register to update ("low", "med", or "high").
            note: Scale degree to rebind (e.g. "1", "3").
            new_key: The new key string to bind (e.g. "Q", "Shift+Q").
        """
        octave_info: dict[str, str] = self.__bindings.get(octave, {})
        if not octave_info:
            return
        if note not in octave_info:
            return
        if new_key == octave_info.get(note, ""):
            return
        octave_info[note] = new_key
        sharp_note: str = f"#{note}"
        if sharp_note in octave_info:
            octave_info[sharp_note] = f"{octave_info[sharp_note].split('+')[0]}+{new_key}"
        b_note: str = f"b{note}"
        if b_note in octave_info:
            octave_info[b_note] = f"{octave_info[b_note].split('+')[0]}+{new_key}"
        self.__build_map()
        self.__save_keybindings()

    def reset_keybindings(self) -> None:
        """Reset keybindings."""
        self.__bindings = deepcopy(self.__default_bindings)
        self.__build_map()
        self.__save_keybindings()

    def __load_keybindings(self) -> None:
        """Load saved keybindings, falling back to defaults if missing or invalid."""
        loaded: object = None
        if self.__cache.exists():
            try:
                with self.__cache.open(encoding="utf-8") as f:
                    loaded = json.load(f)
            except (OSError, ValueError):  # ValueError covers JSONDecodeError/UnicodeDecodeError
                loaded = None
        self.__bindings = merge_keybindings(self.__default_bindings, loaded)

    def __save_keybindings(self) -> None:
        """Save current keybinding."""
        with self.__cache.open("w", encoding="utf-8") as f:
            json.dump(self.__bindings, f, indent=4)

    def __build_map(self) -> None:
        """Construct NOTE_TO_WWM_KEY from BASE_NOTES, DEGREE_OFFSETS, and REGISTER_KEYS."""
        for note_type, note in self.__base_notes.items():
            base: int = note + self._Note.SEMITONE_OFFSET
            for degree, key in self.__bindings[note_type].items():
                note: int = base + self.__offsets[degree]
                if self._Note.MIN <= note <= self._Note.MAX:
                    self.__mapping[note] = key

    def __get_note(self, note: int) -> str|None:
        """Fold note into [48, 83] by octaves to reach playable range.

        Args:
            note: The MIDI note number to look up.

        Returns:
            The bound key string for this note, or None if unmapped.
        """
        return self.__mapping.get(fold_note(note, self._Note.MIN, self._Note.MAX), None)

    def __scan_code(self, vk_code: int) -> int:
        """Return the hardware scan code for a virtual-key code, caching per code.

        MapVirtualKey is a deterministic Windows API call - the same vk_code
        always yields the same scan code, so repeating it for every keypress
        of a long song is pure overhead.

        Args:
            vk_code: The Windows virtual-key code to convert.

        Returns:
            The corresponding hardware scan code.
        """
        scan_code: int|None = self.__scan_code_cache.get(vk_code)
        if scan_code is None:
            scan_code = win32api.MapVirtualKey(vk_code, 0)
            self.__scan_code_cache[vk_code] = scan_code
        return scan_code

    def __vk_scan(self, main_char: str) -> int:
        """Return the virtual-key code for a character, caching per character.

        Args:
            main_char: The character to convert (e.g. "Q").

        Returns:
            The corresponding Windows virtual-key code.
        """
        vk: int|None = self.__vk_scan_cache.get(main_char)
        if vk is None:
            vk = win32api.VkKeyScan(main_char) & 0xFF
            self.__vk_scan_cache[main_char] = vk
        return vk

    def __make_lparam(self, key: int, is_down: bool=False) -> int:
        """Construct the complex lParam integer that Windows expects.

        This mimics the hardware details of a keypress.

        Args:
            key: The virtual-key code the lParam is being built for.
            is_down: Whether this is a key-down (True) or key-up (False) event.

        Returns:
            The packed lParam value for WM_KEYDOWN/WM_KEYUP.
        """
        scan_code: int = self.__scan_code(key)
        lparam: int = 1
        lparam |= (scan_code << 16)
        if not is_down:
            lparam |= (1 << 30)
            lparam |= (1 << 31)
        return lparam

    def __post_key_event(self, handle: int, vk_code: int) -> None:
        """Send a complete Press & Release cycle.

        Args:
            handle: Window handle to post the key events to.
            vk_code: Virtual-key code to press and release.
        """
        lparam_down: int = self.__make_lparam(vk_code, True)
        lparam_up: int = self.__make_lparam(vk_code, False)
        win32api.PostMessage(handle, win32con.WM_KEYDOWN, vk_code, lparam_down)
        win32api.PostMessage(handle, win32con.WM_KEYUP, vk_code, lparam_up)

    def __send_keypress_to_window(self, handle: int, key_string: str) -> None:
        """Send keypress to a specified window.

        Args:
            handle: Window handle to post the key events to.
            key_string: Key combo to send, e.g. "Q" or "Shift+Q".
        """
        parts: list[str] = key_string.split("+")
        modifier_vk: int|None = None
        main_char: str = parts[-1]
        if "Shift" in parts:
            modifier_vk = win32con.VK_SHIFT
        elif "Ctrl" in parts:
            modifier_vk = win32con.VK_CONTROL
        main_vk: int = self.__vk_scan(main_char)
        if modifier_vk:
            lp_mod: int = self.__make_lparam(modifier_vk, True)
            win32api.PostMessage(handle, win32con.WM_KEYDOWN, modifier_vk, lp_mod)
        self.__post_key_event(handle, main_vk)
        if modifier_vk:
            lp_mod_up: int = self.__make_lparam(modifier_vk, False)
            win32api.PostMessage(handle, win32con.WM_KEYUP, modifier_vk, lp_mod_up)

    def play_note(self, handle: int, note: int) -> None:
        """Play a single MIDI note by posting its bound key to the game window.

        Args:
            handle: Window handle of the game window to send the key to.
            note: MIDI note number to play; unmapped notes are silently skipped.
        """
        if key := self.__get_note(note):
            self.__send_keypress_to_window(handle, key)

    def play_chord(self, handle: int, notes: list[int]) -> None:
        """Play every note in a chord by posting each one's bound key in turn.

        Args:
            handle: Window handle of the game window to send the keys to.
            notes: MIDI note numbers to play.
        """
        for n in notes:
            self.play_note(handle, n)

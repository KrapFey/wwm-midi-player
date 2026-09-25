"""Tests for the pure note-folding and keybinding-merge logic in utils.wwm_macro.

fold_note is verified to match, note-for-note, the reference WWM MIDI
player's (github.com/SnowiyQ/Where-Winds-Meet-Midi-Player) 36-key "Closest"
mode: same [48, 83] range, same <60/<72 register thresholds, same
pitch-class-preserving octave folding, and - like that reference - no
attempt to disambiguate simultaneous notes that fold onto the same key.
"""

from utils.wwm_macro import fold_note, merge_keybindings

DEFAULTS: dict[str, dict[str, str]] = {
    "low": {"1": "Z", "#1": "Shift+Z"},
    "med": {"1": "A", "#1": "Shift+A"},
}


def test_fold_note_leaves_in_range_note_unchanged() -> None:
    assert fold_note(60) == 60


def test_fold_note_below_range_lands_on_lowest_octave() -> None:
    assert fold_note(0) == 48
    assert fold_note(36) == 48


def test_fold_note_above_range_lands_on_highest_octave() -> None:
    assert fold_note(96) == 72
    assert fold_note(120) == 72


def test_fold_note_preserves_pitch_class() -> None:
    for note in range(0, 128):
        assert fold_note(note) % 12 == note % 12


def test_merge_keybindings_none_returns_defaults_copy() -> None:
    merged = merge_keybindings(DEFAULTS, None)
    assert merged == DEFAULTS
    merged["low"]["1"] = "X"
    assert DEFAULTS["low"]["1"] == "Z"


def test_merge_keybindings_non_dict_returns_defaults() -> None:
    assert merge_keybindings(DEFAULTS, ["not", "a", "dict"]) == DEFAULTS


def test_merge_keybindings_applies_valid_overrides() -> None:
    merged = merge_keybindings(DEFAULTS, {"low": {"1": "Q", "#1": "Shift+Q"}})
    assert merged["low"] == {"1": "Q", "#1": "Shift+Q"}
    assert merged["med"] == DEFAULTS["med"]


def test_merge_keybindings_fills_missing_octaves_and_degrees() -> None:
    merged = merge_keybindings(DEFAULTS, {"low": {"1": "Q"}})
    assert merged["low"] == {"1": "Q", "#1": "Shift+Z"}
    assert merged["med"] == DEFAULTS["med"]


def test_merge_keybindings_ignores_malformed_and_unknown_entries() -> None:
    loaded = {"low": {"1": 5, "#1": "", "9": "P"}, "med": "A", "extra": {"1": "K"}}
    assert merge_keybindings(DEFAULTS, loaded) == DEFAULTS

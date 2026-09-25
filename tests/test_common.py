"""Tests for shared resource-path resolution, note coloring, and the skin/theme palette switch."""

from pathlib import Path

import pytest

from utils.common import (
    Colors,
    active_skin,
    apply_skin,
    apply_theme,
    channel_color_hex,
    current_skin_name,
    current_theme,
    note_color_hex,
    resource_path,
)
from utils.skins import CHANNEL_COLORS, SKINS


@pytest.fixture(autouse=True)
def _isolated_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)


def test_returns_original_path_when_it_exists() -> None:
    Path("logo.ico").touch()
    assert resource_path("logo.ico") == Path("logo.ico")


def test_returns_original_path_when_missing_and_no_internal_dir() -> None:
    assert resource_path("missing.ico") == Path("missing.ico")


def test_returns_internal_prefixed_path_when_missing_and_internal_dir_exists() -> None:
    Path("_internal").mkdir()
    assert resource_path("missing.ico") == Path("_internal/missing.ico")


def test_prefers_direct_path_over_internal_when_both_could_apply() -> None:
    Path("_internal").mkdir()
    Path("present.ico").touch()
    assert resource_path("present.ico") == Path("present.ico")


def test_channel_color_hex_returns_distinct_color_for_drum_channel() -> None:
    drum_channel = 9
    assert channel_color_hex(drum_channel) not in (
        channel_color_hex(channel) for channel in range(16) if channel != drum_channel
    )


def test_channel_color_hex_wraps_out_of_range_channel() -> None:
    assert channel_color_hex(16) == channel_color_hex(0)


def test_channel_color_hex_covers_all_16_channels() -> None:
    assert len(CHANNEL_COLORS) == 16
    assert all(color.startswith("#") for color in CHANNEL_COLORS)


def test_note_color_hex_differs_across_tracks_sharing_a_channel() -> None:
    # This is the scenario that used to collapse every instrument into one
    # color: multiple tracks all routed through channel 0.
    assert note_color_hex(0, is_drum=False) != note_color_hex(1, is_drum=False)


def test_note_color_hex_drum_is_constant_regardless_of_track() -> None:
    assert note_color_hex(0, is_drum=True) == note_color_hex(5, is_drum=True)


def test_note_color_hex_drum_color_never_used_for_pitched_tracks() -> None:
    drum_color = note_color_hex(0, is_drum=True)
    assert all(note_color_hex(track, is_drum=False) != drum_color for track in range(30))


@pytest.fixture(autouse=True)
def _reset_theme():
    yield
    apply_skin("default")
    apply_theme("dark")


def test_default_theme_is_dark() -> None:
    assert current_theme() == "dark"


def test_apply_theme_updates_current_theme() -> None:
    apply_theme("light")
    assert current_theme() == "light"


def test_apply_theme_mutates_variant_members_in_place() -> None:
    background_before = Colors.BACKGROUND.value
    apply_theme("light")
    assert Colors.BACKGROUND.value is background_before
    assert Colors.BACKGROUND.value.hex != "#111111"
    apply_theme("dark")
    assert Colors.BACKGROUND.value.hex == "#111111"


def test_apply_theme_leaves_invariant_members_unchanged() -> None:
    accent_before = Colors.ACCENT_1.value.hex
    black_before = Colors.BLACK.value.hex
    apply_theme("light")
    assert Colors.ACCENT_1.value.hex == accent_before
    assert Colors.BLACK.value.hex == black_before


def test_apply_theme_keeps_qcolor_in_sync_with_hex() -> None:
    apply_theme("light")
    assert Colors.WHITE.value.qcolor.name().lower() == Colors.WHITE.value.hex.lower()


def test_apply_theme_unknown_name_falls_back_to_dark() -> None:
    apply_theme("neon-pink")
    assert current_theme() == "dark"


def test_apply_skin_unknown_name_falls_back_to_default() -> None:
    apply_skin("does-not-exist")
    assert current_skin_name() == "default"


def test_apply_skin_recolors_every_member_from_skin_palette() -> None:
    apply_skin("cyberpunk")
    palette = SKINS["cyberpunk"].palettes["dark"]
    for member in Colors:
        assert member.value.hex == palette[member.name]


def test_apply_skin_mutates_cached_qcolor_in_place() -> None:
    # Widgets cache Colors.X.value.qcolor at construction time; a skin switch
    # must update that same QColor object, not replace it.
    cached = Colors.ACCENT_1.value.qcolor
    apply_skin("cyberpunk")
    assert cached is Colors.ACCENT_1.value.qcolor
    assert cached.name().lower() == SKINS["cyberpunk"].palettes["dark"]["ACCENT_1"].lower()


def test_dark_only_skin_renders_dark_but_keeps_light_preference() -> None:
    apply_theme("light")
    apply_skin("cyberpunk")
    assert current_theme() == "light"
    assert Colors.BACKGROUND.value.hex == SKINS["cyberpunk"].palettes["dark"]["BACKGROUND"]
    apply_skin("default")
    assert Colors.BACKGROUND.value.hex == SKINS["default"].palettes["light"]["BACKGROUND"]


def test_note_colors_follow_active_skin() -> None:
    apply_skin("cyberpunk")
    assert channel_color_hex(0) == active_skin().note_colors[0]
    assert note_color_hex(0, is_drum=True) == SKINS["cyberpunk"].note_colors[9]

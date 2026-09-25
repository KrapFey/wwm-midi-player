"""Tests for the skin registry's consistency and variant/shape resolution."""

import pytest

from utils.skins import DEFAULT_SKIN, PALETTE_KEYS, SKINS, VARIANTS, get_skin


@pytest.mark.parametrize("name", list(SKINS))
def test_every_palette_defines_exactly_the_palette_keys(name: str) -> None:
    for variant, palette in SKINS[name].palettes.items():
        assert set(palette) == set(PALETTE_KEYS), (name, variant)


@pytest.mark.parametrize("name", list(SKINS))
def test_every_palette_value_is_a_hex_color(name: str) -> None:
    for palette in SKINS[name].palettes.values():
        for value in palette.values():
            assert value.startswith("#")
            assert len(value) == 7


@pytest.mark.parametrize("name", list(SKINS))
def test_every_skin_has_16_note_colors_and_known_variants(name: str) -> None:
    skin = SKINS[name]
    assert len(skin.note_colors) == 16
    assert skin.variants
    assert set(skin.variants) <= set(VARIANTS)


@pytest.mark.parametrize("name", list(SKINS))
def test_every_skin_uses_a_known_note_style(name: str) -> None:
    assert SKINS[name].note_style in {"gradient", "neon"}


def test_default_skin_supports_dark_and_light() -> None:
    assert SKINS[DEFAULT_SKIN].variants == ("dark", "light")


@pytest.mark.parametrize("name", ["cyberpunk", "neon_glass"])
def test_neon_skins_are_dark_only(name: str) -> None:
    assert SKINS[name].variants == ("dark",)


def test_resolve_variant_honors_supported_preference() -> None:
    assert SKINS[DEFAULT_SKIN].resolve_variant("light") == "light"


def test_resolve_variant_falls_back_to_first_variant() -> None:
    assert SKINS["cyberpunk"].resolve_variant("light") == "dark"


def test_get_skin_unknown_name_returns_default() -> None:
    assert get_skin("nope") is SKINS[DEFAULT_SKIN]

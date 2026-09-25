"""Tests for the skin registry's consistency and variant/shape resolution."""

from dataclasses import replace

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


@pytest.mark.parametrize("name", list(SKINS))
def test_every_skin_supports_dark_and_light(name: str) -> None:
    assert SKINS[name].variants == ("dark", "light")


@pytest.mark.parametrize("name", list(SKINS))
def test_variant_styles_only_target_existing_variants(name: str) -> None:
    skin = SKINS[name]
    assert set(skin.variant_styles) <= set(skin.variants)
    for style in skin.variant_styles.values():
        assert style.note_colors is None or len(style.note_colors) == 16


@pytest.mark.parametrize("name", ["cyberpunk", "neon_glass"])
def test_light_variants_swap_note_colors(name: str) -> None:
    skin = SKINS[name]
    assert skin.note_colors_for("dark") == skin.note_colors
    assert skin.note_colors_for("light") != skin.note_colors


def test_resolve_variant_honors_supported_preference() -> None:
    assert SKINS[DEFAULT_SKIN].resolve_variant("light") == "light"


def test_resolve_variant_falls_back_to_first_variant() -> None:
    dark_only = replace(SKINS["cyberpunk"], palettes={"dark": SKINS["cyberpunk"].palettes["dark"]})
    assert dark_only.resolve_variant("light") == "dark"


def test_get_skin_unknown_name_returns_default() -> None:
    assert get_skin("nope") is SKINS[DEFAULT_SKIN]


def _luminance(hex_color: str) -> float:
    """WCAG relative luminance of a #RRGGBB color."""
    def channel(value: int) -> float:
        c = value / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def _contrast(foreground: str, background: str) -> float:
    lighter, darker = sorted((_luminance(foreground), _luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


_SKIN_VARIANTS = [(name, variant) for name, skin in SKINS.items() for variant in skin.variants]


@pytest.mark.parametrize(("name", "variant"), _SKIN_VARIANTS)
def test_palette_text_is_readable_on_panels(name: str, variant: str) -> None:
    palette = SKINS[name].palettes[variant]
    panel = palette["BACKGROUND_1"]
    assert _contrast(palette["WHITE"], panel) >= 7, "body text (WCAG AAA)"
    assert _contrast(palette["TEXT_MUTED"], panel) >= 4.5, "secondary text (WCAG AA)"
    assert _contrast(palette["ACCENT_1"], panel) >= 3, "accent titles/controls (WCAG non-text)"
    if name == "cyberpunk":  # Night City sets artist names and the time in HIGHLIGHT
        assert _contrast(palette["HIGHLIGHT"], panel) >= 4.5, "highlight text (WCAG AA)"

"""Tests for persisted app settings."""

from pathlib import Path

from utils.app_settings import AppSettings, load_settings, save_settings


def test_load_returns_defaults_when_file_missing(tmp_path: Path) -> None:
    settings = load_settings(tmp_path / "missing.json")
    assert settings == AppSettings()


def test_load_returns_defaults_when_file_corrupt(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("not valid json", encoding="utf-8")
    assert load_settings(path) == AppSettings()


def test_load_returns_defaults_when_file_has_unexpected_shape(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"volume": 80, "unknown_field": {"nested": true}}', encoding="utf-8")
    settings = load_settings(path)
    assert settings.volume == 80


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    original = AppSettings(volume=42, is_audio_mode=True,
                            playlist=["a.mid", "b.mid"], current_index=1, theme="light",
                            skin="cyberpunk")
    save_settings(original, path)
    assert load_settings(path) == original


def test_load_defaults_theme_when_missing_from_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"volume": 80}', encoding="utf-8")
    assert load_settings(path).theme == "dark"


def test_load_defaults_skin_when_missing_from_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text('{"volume": 80}', encoding="utf-8")
    assert load_settings(path).skin == "default"


def test_save_overwrites_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(AppSettings(volume=10), path)
    save_settings(AppSettings(volume=99), path)
    assert load_settings(path).volume == 99


def test_transpose_round_trips_and_drops_malformed_entries(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    save_settings(AppSettings(transpose={"a.mid": -5, "b.mid": 12}), path)
    assert load_settings(path).transpose == {"a.mid": -5, "b.mid": 12}
    path.write_text('{"transpose": {"a.mid": 3, "b.mid": "x", "c.mid": true}}', encoding="utf-8")
    assert load_settings(path).transpose == {"a.mid": 3}
    path.write_text('{"transpose": [1, 2]}', encoding="utf-8")
    assert load_settings(path).transpose == {}

"""Tests for bundled resource-path resolution (source tree vs. PyInstaller onedir)."""

from pathlib import Path

import pytest

from utils.resources import resource_path


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

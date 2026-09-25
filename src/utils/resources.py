"""Shared helpers: bundled resource path resolution and a Singleton metaclass."""

from collections.abc import Callable
from pathlib import Path


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

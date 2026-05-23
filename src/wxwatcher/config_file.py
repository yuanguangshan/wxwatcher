"""Config file discovery and loading."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_FILENAMES = (".wxwatcher.yml", "wxwatcher.yml")

_XDG_CONFIG_HOME = os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config"))
_GLOBAL_PATHS = [
    Path.home() / ".wxwatcher" / "config.yml",
    Path(_XDG_CONFIG_HOME) / "wxwatcher" / "config.yml",
]


def find_config_file(explicit: str | None = None) -> Optional[Path]:
    """Search for a config file in order.

    Search order:
    1. explicit path (if provided)
    2. current directory and parent directories (up to home)
    3. ~/.wxwatcher/config.yml
    4. ~/.config/wxwatcher/config.yml

    Args:
        explicit: User-specified config file path via --config flag

    Returns:
        Path to config file, or None if not found
    """
    if explicit:
        return Path(explicit)

    # Search current directory and parents (like .gitignore behavior)
    cwd = Path.cwd()
    for base in [cwd] + list(cwd.parents):
        for name in CONFIG_FILENAMES:
            candidate = base / name
            if candidate.is_file():
                return candidate
        # Stop at home directory to avoid searching too far
        if base == Path.home():
            break

    # Check global locations
    for path in _GLOBAL_PATHS:
        if path.is_file():
            return path

    return None


def load_config_file(path: Path) -> Dict[str, Any]:
    """Load and parse a YAML config file.

    Args:
        path: Path to the YAML config file

    Returns:
        Dict of config settings

    Raises:
        ImportError: If pyyaml is not installed
        ValueError: If the YAML content is not a mapping
    """
    try:
        import yaml
    except ImportError:
        raise ImportError(
            "Config file found but pyyaml is not installed. "
            "Run: pip install wxwatcher[config]"
        )

    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Config file must be a YAML mapping, got {type(data).__name__}"
        )
    return data

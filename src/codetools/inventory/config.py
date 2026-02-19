import json
import os
from pathlib import Path
from typing import Any

import commentjson  # type: ignore


class ConfigurationManager:
    """
    Manages loading and merging of application configuration.
    """

    def __init__(self, *, base_path: Path | None = None) -> None:
        self._base_path = base_path or Path(__file__).parent

    def load_config(
        self, user_config_path: str | None, cli_overrides: dict[str, Any]
    ) -> dict[str, Any]:
        """
        Loads defaults, merges with user JSON, and applies CLI overrides.
        """
        config = self._load_defaults()

        if user_config_path:
            self._merge_user_file(config, Path(user_config_path))

        # Apply CLI overrides (filtering out None values)
        config.update({k: v for k, v in cli_overrides.items() if v is not None})

        # Ensure concurrency is set
        if not config.get("concurrency"):
            config["concurrency"] = os.cpu_count() or 1

        return config

    def _load_defaults(self) -> dict[str, Any]:
        defaults_path = self._base_path / "defaults.json"
        if not defaults_path.exists():
            return {}

        try:
            with open(defaults_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _merge_user_file(self, config: dict[str, Any], path: Path) -> None:
        if not path.is_file():
            raise FileNotFoundError(f"Config file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as f:
                user_conf = commentjson.load(f)
            config.update(user_conf)
        except Exception as e:
            raise IOError(f"Failed to parse config file {path}: {e}")

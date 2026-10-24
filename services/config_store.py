import json
import os
from pathlib import Path
from typing import Any


class ConfigStoreError(Exception):
    """Raised when the server configuration cannot be read or saved."""


class ConfigStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._config: dict[str, str] | None = None

    def load(self) -> dict[str, str]:
        if self._config is not None:
            return self._config.copy()

        try:
            raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            self._config = {}
            return {}
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ConfigStoreError(
                f"Impossible de lire le fichier {self.path}."
            ) from error

        if not isinstance(raw, dict) or any(
            not isinstance(guild_id, str) or not isinstance(channel_id, str)
            for guild_id, channel_id in raw.items()
        ):
            raise ConfigStoreError(
                f"Le format de configuration dans {self.path} est invalide."
            )
        self._config = raw
        return raw.copy()

    def get_channel(self, guild_id: int) -> int | None:
        channel_id = self.load().get(str(guild_id))
        if channel_id is None:
            return None
        try:
            return int(channel_id)
        except ValueError as error:
            raise ConfigStoreError(
                f"L'identifiant du salon du serveur {guild_id} est invalide."
            ) from error

    def set_channel(self, guild_id: int, channel_id: int) -> None:
        config = self.load()
        config[str(guild_id)] = str(channel_id)
        self._save(config)

    def disable_guild(self, guild_id: int) -> None:
        config = self.load()
        config.pop(str(guild_id), None)
        self._save(config)

    def _save(self, config: dict[str, str]) -> None:
        temporary_path = self.path.with_name(f"{self.path.name}.tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary_path.write_text(
                json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            os.replace(temporary_path, self.path)
        except OSError as error:
            raise ConfigStoreError(
                f"Impossible d'enregistrer le fichier {self.path}."
            ) from error
        self._config = config.copy()

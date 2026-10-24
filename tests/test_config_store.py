import json
import tempfile
import unittest
from pathlib import Path

from services.config_store import ConfigStore, ConfigStoreError


class ConfigStoreTests(unittest.TestCase):
    def test_set_get_and_disable_channel(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = ConfigStore(Path(directory) / "data" / "config.json")

            store.set_channel(123, 456)
            self.assertEqual(store.get_channel(123), 456)

            store.disable_guild(123)
            self.assertIsNone(store.get_channel(123))

    def test_invalid_json_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            path.write_text("{invalid", encoding="utf-8")
            store = ConfigStore(path)

            with self.assertRaises(ConfigStoreError):
                store.load()

    def test_saved_json_uses_string_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            ConfigStore(path).set_channel(123, 456)

            self.assertEqual(
                json.loads(path.read_text(encoding="utf-8")),
                {"123": "456"},
            )

    def test_configuration_is_cached_and_isolated_per_server(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config.json"
            store = ConfigStore(path)
            store.set_channel(123, 456)
            store.set_channel(789, 101112)

            path.write_text("{invalid", encoding="utf-8")

            self.assertEqual(store.get_channel(123), 456)
            self.assertEqual(store.get_channel(789), 101112)
            self.assertIsNone(store.get_channel(999))


if __name__ == "__main__":
    unittest.main()

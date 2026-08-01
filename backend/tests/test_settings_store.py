import json
import os
import tempfile
import unittest
from unittest.mock import patch

from services import settings_store


class SettingsStoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.settings_file = os.path.join(self.temporary.name, "settings.json")
        self.patcher = patch.object(settings_store, "SETTINGS_FILE", self.settings_file)
        self.patcher.start()

    def tearDown(self):
        self.patcher.stop()
        self.temporary.cleanup()

    def write(self, value):
        with open(self.settings_file, "w", encoding="utf-8") as file:
            json.dump(value, file)

    def test_migrates_legacy_key_only_to_sentiment_task(self):
        self.write({"api_key": "sk-legacy-secret", "analysis_mode": "llm"})

        value = settings_store.load_settings()

        self.assertEqual(value["llm"]["sentiment"]["api_key"], "sk-legacy-secret")
        self.assertEqual(value["llm"]["summary"]["api_key"], "")
        with open(self.settings_file, encoding="utf-8") as file:
            migrated = json.load(file)
        self.assertNotIn("api_key", migrated)

    def test_public_settings_never_exposes_secret(self):
        self.write({"api_key": "sk-1234567890-secret"})

        public = settings_store.public_settings()
        serialized = json.dumps(public, ensure_ascii=False)

        self.assertNotIn("sk-1234567890-secret", serialized)
        self.assertTrue(public["llm"]["sentiment"]["has_api_key"])
        self.assertIn("****", public["llm"]["sentiment"]["api_key_preview"])

    def test_tasks_update_independently_and_omitted_key_is_retained(self):
        settings_store.update_settings({
            "llm": {
                "sentiment": {"api_key": "sentiment-key"},
                "summary": {
                    "provider": "deepseek",
                    "api_key": "summary-key",
                    "base_url": "https://api.deepseek.com",
                    "model": "deepseek-v4-flash",
                },
            },
        })
        settings_store.update_settings({
            "llm": {"summary": {"model": "deepseek-v4-pro"}},
        })
        value = settings_store.load_settings()

        self.assertEqual(value["llm"]["sentiment"]["api_key"], "sentiment-key")
        self.assertEqual(value["llm"]["summary"]["api_key"], "summary-key")
        self.assertEqual(value["llm"]["summary"]["model"], "deepseek-v4-pro")

    def test_clear_key_and_provider_switch(self):
        settings_store.update_settings({"llm": {"summary": {"api_key": "old-key"}}})
        settings_store.update_settings({
            "llm": {
                "summary": {
                    "provider": "deepseek",
                    "api_key": "new-key",
                },
            },
        })
        switched = settings_store.load_settings()["llm"]["summary"]
        self.assertEqual(switched["model"], "deepseek-v4-flash")
        self.assertEqual(switched["api_key"], "new-key")

        settings_store.update_settings({"llm": {"summary": {"clear_api_key": True}}})
        self.assertEqual(settings_store.load_settings()["llm"]["summary"]["api_key"], "")


if __name__ == "__main__":
    unittest.main()

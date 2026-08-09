import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from starlette.requests import Request

import main
from api.auth_routes import list_accounts
from services import auth, runtime_state, secure_store, settings_store


class _EmptyQuery:
    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return []


class _EmptyDb:
    def query(self, *_args, **_kwargs):
        return _EmptyQuery()

    def close(self):
        pass


def _request(path: str, token: str = "") -> Request:
    headers = [(b"x-bili-local-token", token.encode("utf-8"))] if token else []
    return Request({
        "type": "http", "method": "GET", "path": path,
        "headers": headers, "scheme": "http", "server": ("127.0.0.1", 1),
    })


class PortableRuntimeTests(unittest.TestCase):
    def test_plaintext_secret_is_marked_for_migration(self):
        self.assertEqual(secure_store.unprotect("plain-key"), ("plain-key", True))

    def test_settings_migrates_secret_without_exposing_it(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(settings_store, "SETTINGS_FILE", os.path.join(temporary, "settings.json")), \
                patch.object(settings_store, "protect", side_effect=lambda value: "enc:v1:" + value), \
                patch.object(settings_store, "unprotect", side_effect=lambda value: (value.removeprefix("enc:v1:"), not str(value).startswith("enc:v1:"))):
            settings_store.update_settings({"llm": {"summary": {"api_key": "secret"}}})
            stored = json.loads(Path(settings_store.SETTINGS_FILE).read_text(encoding="utf-8"))
            self.assertEqual(stored["llm"]["summary"]["api_key"], "enc:v1:secret")
            self.assertEqual(settings_store.get_task_config("summary")["api_key"], "secret")

    def test_unavailable_dpapi_key_is_never_overwritten(self):
        encrypted = "enc:v1:unavailable-on-this-machine"
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(settings_store, "SETTINGS_FILE", os.path.join(temporary, "settings.json")), \
                patch.object(settings_store, "unprotect", side_effect=secure_store.SecretUnavailableError("other machine")):
            Path(settings_store.SETTINGS_FILE).write_text(json.dumps({
                "llm": {"summary": {"api_key": encrypted}},
            }), encoding="utf-8")
            loaded = settings_store.load_settings()
            public = settings_store.public_settings(loaded)
            settings_store.update_settings({"llm": {"summary": {"model": "new-model"}}})
            stored = json.loads(Path(settings_store.SETTINGS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(loaded["llm"]["summary"]["api_key"], "")
        self.assertTrue(public["credential_reentry_required"])
        self.assertEqual(stored["llm"]["summary"]["api_key"], encrypted)

    def test_auth_migrates_cookie_atomically(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(auth, "AUTH_FILE", os.path.join(temporary, "auth.json")), \
                patch.object(auth, "protect", side_effect=lambda value: "enc:v1:" + value), \
                patch.object(auth, "unprotect", side_effect=lambda value: (value.removeprefix("enc:v1:"), not str(value).startswith("enc:v1:"))):
            Path(auth.AUTH_FILE).write_text(json.dumps({"cookie": "SESSDATA=legacy", "accounts": []}), encoding="utf-8")
            self.assertEqual(auth.get_cookie(), "SESSDATA=legacy")
            stored = json.loads(Path(auth.AUTH_FILE).read_text(encoding="utf-8"))
            self.assertEqual(stored["cookie"], "enc:v1:SESSDATA=legacy")

    def test_public_account_list_never_exposes_cookie(self):
        with patch("api.auth_routes.get_accounts", return_value=[{
            "index": 3, "name": "测试用户", "cookie": "SESSDATA=private-cookie",
        }]):
            response = list_accounts()
        serialized = json.dumps(response, ensure_ascii=False)
        self.assertEqual(response["accounts"], [{"index": 3, "name": "测试用户"}])
        self.assertNotIn("private-cookie", serialized)
        self.assertNotIn("cookie", serialized)

    def test_activity_contract_is_idle(self):
        with patch.object(runtime_state, "SessionLocal", return_value=_EmptyDb()):
            value = runtime_state.current_activity()
        self.assertFalse(value["active"])
        self.assertEqual(value["analyses"], [])

    def test_desktop_token_protects_api_but_not_health_probe(self):
        async def next_handler(_request):
            return {"ok": True}

        with patch.dict(os.environ, {"BILI_DESKTOP_MODE": "1", "BILI_LOCAL_TOKEN": "expected"}, clear=False):
            denied = asyncio.run(main.require_local_token(_request("/api/history"), next_handler))
            accepted = asyncio.run(main.require_local_token(_request("/api/history", "expected"), next_handler))
            health = asyncio.run(main.require_local_token(_request("/api/runtime/health"), next_handler))
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(accepted, {"ok": True})
        self.assertEqual(health, {"ok": True})

    def test_handshake_is_atomically_written(self):
        with tempfile.TemporaryDirectory() as temporary, patch.dict(os.environ, {
            "BILI_HANDSHAKE_PATH": os.path.join(temporary, "handshake.json"),
            "BILI_BOUND_PORT": "41234",
        }, clear=False):
            main._write_handshake()
            value = json.loads(Path(os.environ["BILI_HANDSHAKE_PATH"]).read_text(encoding="utf-8"))
        self.assertEqual(value["port"], 41234)
        self.assertEqual(value["schema"], 1)
        self.assertEqual(value["pid"], os.getpid())


if __name__ == "__main__":
    unittest.main()

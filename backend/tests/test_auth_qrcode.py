import asyncio
import base64
import json
import os
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

import httpx
from fastapi.testclient import TestClient

import main
from api import auth_routes
from services import auth


class _QRCodeClient:
    def __init__(self, response):
        self.response = response
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class _MutatingNavClient(_QRCodeClient):
    async def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        auth.clear_cookie()
        return self.response


class AuthQRCodeTests(unittest.TestCase):
    def test_qrcode_is_locally_encoded_as_png_data_url(self):
        response = httpx.Response(
            200,
            json={
                "code": 0,
                "data": {
                    "url": "https://passport.bilibili.com/h5-app/passport/sso/scan?oauthKey=example",
                    "qrcode_key": "qr-key",
                },
            },
            request=httpx.Request("GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"),
        )
        client = _QRCodeClient(response)
        with patch.object(auth.httpx, "AsyncClient", return_value=client):
            result = asyncio.run(auth.generate_qrcode())

        self.assertEqual(result["qrcode_key"], "qr-key")
        self.assertNotIn("url", result)
        self.assertTrue(result["image_data_url"].startswith("data:image/png;base64,"))
        payload = base64.b64decode(result["image_data_url"].split(",", 1)[1])
        self.assertEqual(payload[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(client.calls[0][0], "https://passport.bilibili.com/x/passport-login/web/qrcode/generate")

    def test_qrcode_upstream_error_is_safe_for_the_login_ui(self):
        response = httpx.Response(
            503,
            request=httpx.Request("GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"),
        )
        with patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)):
            result = asyncio.run(auth.generate_qrcode())

        self.assertEqual(result, {"error": "无法连接 B站登录服务，请检查网络后重试"})

    def test_qrcode_rejects_malformed_or_incomplete_upstream_payloads(self):
        request = httpx.Request("GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/generate")
        for response in (
            httpx.Response(200, json=[], request=request),
            httpx.Response(200, json={"code": 0, "data": {"url": "https://example.invalid"}}, request=request),
        ):
            with self.subTest(response=response.json()):
                with patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)):
                    result = asyncio.run(auth.generate_qrcode())
                self.assertEqual(result, {"error": "B站暂时无法生成登录二维码，请稍后重试"})

    def test_poll_reports_scan_states_without_persisting_a_cookie(self):
        request = httpx.Request("GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/poll")
        cases = {
            86090: ("scanned", "已扫码，请在手机上确认"),
            86101: ("waiting", "等待扫码"),
            86038: ("expired", "二维码已过期"),
        }
        for code, expected in cases.items():
            with self.subTest(code=code):
                response = httpx.Response(200, json={"code": 0, "data": {"code": code}}, request=request)
                with patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)), \
                        patch.object(auth, "save_cookie", new_callable=AsyncMock) as save_cookie:
                    result = asyncio.run(auth.poll_qrcode("qr-key"))
                self.assertEqual((result["status"], result["message"]), expected)
                save_cookie.assert_not_awaited()

    def test_poll_saves_session_cookie_asynchronously_after_success(self):
        response = httpx.Response(
            200,
            headers=[
                # An Expires date contains a comma. The separate header must
                # not make the SESSDATA cookie disappear during parsing.
                (b"set-cookie", b"bili_jct=csrf; Expires=Wed, 21 Oct 2030 07:28:00 GMT; Path=/"),
                (b"set-cookie", b"SESSDATA=session-value; Path=/; HttpOnly"),
            ],
            json={"code": 0, "data": {"code": 0}},
            request=httpx.Request("GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"),
        )
        with patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)), \
                patch.object(auth, "save_cookie", new_callable=AsyncMock) as save_cookie:
            result = asyncio.run(auth.poll_qrcode("qr-key"))

        self.assertEqual(result, {"status": "success", "message": "登录成功"})
        save_cookie.assert_awaited_once_with("SESSDATA=session-value")

    def test_poll_returns_safe_error_when_credential_save_fails(self):
        response = httpx.Response(
            200,
            headers=[(b"set-cookie", b"SESSDATA=session-value; Path=/; HttpOnly")],
            json={"code": 0, "data": {"code": 0}},
            request=httpx.Request("GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"),
        )
        with patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)), \
                patch.object(auth, "save_cookie", new_callable=AsyncMock, return_value=False):
            result = asyncio.run(auth.poll_qrcode("qr-key"))

        serialized = json.dumps(result, ensure_ascii=False)
        self.assertEqual(result["status"], "error")
        self.assertIn("保存失败", result["message"])
        self.assertNotIn("session-value", serialized)
        self.assertNotIn("SESSDATA", serialized)

    def test_poll_never_reports_success_without_session_cookie(self):
        response = httpx.Response(
            200,
            json={"code": 0, "data": {"code": 0}},
            request=httpx.Request("GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"),
        )
        with patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)), \
                patch.object(auth, "save_cookie", new_callable=AsyncMock) as save_cookie:
            result = asyncio.run(auth.poll_qrcode("qr-key"))

        self.assertEqual(result, {"status": "error", "message": "登录授权未返回会话信息，请重新扫码"})
        save_cookie.assert_not_awaited()

    def test_poll_safely_handles_upstream_failure_and_malformed_payload(self):
        request = httpx.Request("GET", "https://passport.bilibili.com/x/passport-login/web/qrcode/poll")
        cases = (
            (httpx.Response(503, request=request), {"status": "error", "message": "无法连接 B站登录服务，请检查网络后重试"}),
            (httpx.Response(200, json=[], request=request), {"status": "error", "message": "B站登录服务返回了无效响应"}),
        )
        for response, expected in cases:
            with self.subTest(status=response.status_code):
                with patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)):
                    result = asyncio.run(auth.poll_qrcode("qr-key"))
                self.assertEqual(result, expected)


class AuthCredentialPersistenceTests(unittest.TestCase):
    def test_saved_account_indices_stay_stable_when_an_unreadable_account_is_hidden(self):
        encrypted = "enc:v1:from-another-profile"

        def decode(value):
            if value == encrypted:
                raise auth.SecretUnavailableError("other profile")
            return value, False

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(auth, "AUTH_FILE", os.path.join(directory, "auth.json")), \
                patch.object(auth, "unprotect", side_effect=decode), \
                patch.object(auth, "protect", side_effect=lambda value: value), \
                patch.object(auth, "_auth_revision", 0), \
                patch.object(auth, "_credential_reentry_required", False):
            with open(auth.AUTH_FILE, "w", encoding="utf-8") as file:
                json.dump({
                    "cookie": "",
                    "accounts": [
                        {"cookie": encrypted, "name": "旧账号"},
                        {"cookie": "SESSDATA=usable", "name": "可用账号"},
                    ],
                }, file)

            self.assertEqual(auth.get_accounts(), [{"index": 1, "name": "可用账号"}])
            self.assertTrue(auth.switch_account(1))
            with open(auth.AUTH_FILE, encoding="utf-8") as file:
                stored = json.load(file)

        self.assertEqual(stored["cookie"], "SESSDATA=usable")

    def test_logout_removes_an_active_cookie_that_cannot_be_decrypted(self):
        encrypted = "enc:v1:from-another-profile"
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(auth, "AUTH_FILE", os.path.join(directory, "auth.json")), \
                patch.object(auth, "unprotect", side_effect=auth.SecretUnavailableError("other profile")), \
                patch.object(auth, "_auth_revision", 0), \
                patch.object(auth, "_credential_reentry_required", False):
            with open(auth.AUTH_FILE, "w", encoding="utf-8") as file:
                json.dump({"cookie": encrypted, "accounts": []}, file)

            auth.clear_cookie()
            with open(auth.AUTH_FILE, encoding="utf-8") as file:
                stored = json.load(file)

        self.assertEqual(stored["cookie"], "")

    def test_save_cookie_returns_false_when_local_persistence_fails(self):
        response = httpx.Response(
            200,
            json={"data": {"uname": "测试用户"}},
            request=httpx.Request("GET", "https://api.bilibili.com/x/web-interface/nav"),
        )
        with patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)), \
                patch.object(auth, "_save", side_effect=OSError("disk full")):
            self.assertFalse(asyncio.run(auth.save_cookie("SESSDATA=session-value")))

    def test_save_cookie_returns_false_when_dpapi_protection_fails(self):
        response = httpx.Response(
            200,
            json={"data": {"uname": "测试用户"}},
            request=httpx.Request("GET", "https://api.bilibili.com/x/web-interface/nav"),
        )
        with patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)), \
                patch.object(auth, "protect", side_effect=auth.SecretUnavailableError("dpapi unavailable")):
            self.assertFalse(asyncio.run(auth.save_cookie("SESSDATA=session-value")))

    def test_save_cookie_does_not_overwrite_logout_during_profile_lookup(self):
        response = httpx.Response(
            200,
            json={"data": {"uname": "测试用户"}},
            request=httpx.Request("GET", "https://api.bilibili.com/x/web-interface/nav"),
        )
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(auth, "AUTH_FILE", os.path.join(directory, "auth.json")), \
                patch.object(auth, "protect", side_effect=lambda value: value), \
                patch.object(auth, "unprotect", side_effect=lambda value: (value, False)), \
                patch.object(auth, "_auth_revision", 0), \
                patch.object(auth.httpx, "AsyncClient", return_value=_MutatingNavClient(response)):
            self.assertFalse(asyncio.run(auth.save_cookie("SESSDATA=session-value")))
            with open(auth.AUTH_FILE, encoding="utf-8") as file:
                stored = json.loads(file.read())

        self.assertEqual(stored["cookie"], "")

    def test_successful_save_clears_stale_credential_reentry_marker(self):
        response = httpx.Response(
            200,
            json={"data": {"uname": "测试用户"}},
            request=httpx.Request("GET", "https://api.bilibili.com/x/web-interface/nav"),
        )
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(auth, "AUTH_FILE", os.path.join(directory, "auth.json")), \
                patch.object(auth, "protect", side_effect=lambda value: value), \
                patch.object(auth, "unprotect", side_effect=lambda value: (value, False)), \
                patch.object(auth, "_auth_revision", 0), \
                patch.object(auth, "_credential_reentry_required", True), \
                patch.object(auth.httpx, "AsyncClient", return_value=_QRCodeClient(response)):
            self.assertTrue(asyncio.run(auth.save_cookie("SESSDATA=session-value")))
            self.assertFalse(auth.credential_reentry_required())


class AuthRouteContractTests(unittest.TestCase):
    def test_qrcode_status_is_post_json_without_key_in_url(self):
        client = TestClient(main.app)
        with patch.object(auth_routes, "poll_qrcode", new_callable=AsyncMock, return_value={"status": "waiting"}) as poll:
            response = client.post("/api/auth/qrcode/status", json={"qrcode_key": "short-lived-key"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "waiting"})
        self.assertEqual(response.request.url.query, b"")
        self.assertNotIn("short-lived-key", str(response.request.url))
        poll.assert_awaited_once_with("short-lived-key")
        self.assertNotEqual(
            client.get("/api/auth/qrcode/status?qrcode_key=short-lived-key").status_code,
            200,
        )

    def test_qrcode_status_rejects_missing_or_blank_json_key(self):
        client = TestClient(main.app)
        self.assertEqual(client.post("/api/auth/qrcode/status", json={}).status_code, 422)
        self.assertEqual(client.post("/api/auth/qrcode/status", json={"qrcode_key": ""}).status_code, 422)


if __name__ == "__main__":
    unittest.main()

import base64
import io
import json
import os
import tempfile
import threading

import httpx
import qrcode

from services.runtime_paths import auth_path
from services.secure_store import SecretUnavailableError, is_encrypted, protect, unprotect


AUTH_FILE = os.environ.get("BILI_AUTH_PATH", str(auth_path()))
_credential_reentry_required = False
AUTH_LOCK = threading.RLock()
_auth_revision = 0
_UNAVAILABLE_COOKIE = "_unavailable_cookie_ciphertext"


def _decode_cookie(value):
    global _credential_reentry_required
    try:
        cookie, migrated = unprotect(value)
        return cookie, migrated, ""
    except SecretUnavailableError:
        _credential_reentry_required = True
        # Keep inaccessible ciphertext private in memory. It must not be
        # returned by API helpers, but non-secret writes must not erase it.
        return "", False, value if is_encrypted(value) else ""


def _decode_auth(data):
    migrated = False
    data = data if isinstance(data, dict) else {}
    cookie, cookie_migrated, unavailable_cookie = _decode_cookie(data.get("cookie", ""))
    data["cookie"] = cookie
    if unavailable_cookie:
        data[_UNAVAILABLE_COOKIE] = unavailable_cookie
    migrated = cookie_migrated
    accounts = data.get("accounts") if isinstance(data.get("accounts"), list) else []
    safe_accounts = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        current = dict(account)
        current["cookie"], account_migrated, unavailable_cookie = _decode_cookie(current.get("cookie", ""))
        if unavailable_cookie:
            current[_UNAVAILABLE_COOKIE] = unavailable_cookie
        migrated = migrated or account_migrated
        safe_accounts.append(current)
    data["accounts"] = safe_accounts
    return data, migrated


def _encode_auth(data):
    persisted = dict(data)
    unavailable_cookie = persisted.pop(_UNAVAILABLE_COOKIE, "")
    cookie = str(persisted.get("cookie", "") or "")
    persisted["cookie"] = (
        unavailable_cookie if not cookie and is_encrypted(unavailable_cookie) else protect(cookie)
    )
    accounts = []
    for account in persisted.get("accounts", []) or []:
        if isinstance(account, dict):
            current = dict(account)
            unavailable_cookie = current.pop(_UNAVAILABLE_COOKIE, "")
            cookie = str(current.get("cookie", "") or "")
            current["cookie"] = (
                unavailable_cookie if not cookie and is_encrypted(unavailable_cookie) else protect(cookie)
            )
            accounts.append(current)
    persisted["accounts"] = accounts
    return persisted


def _load():
    if os.path.exists(AUTH_FILE):
        try:
            with open(AUTH_FILE, "r", encoding="utf-8") as file:
                value, migrated = _decode_auth(json.load(file))
            if migrated:
                _save(value)
            return value
        except UnicodeDecodeError:
            # Older Windows builds wrote the local JSON with the active ANSI
            # code page.  Read once for compatibility, then rewrite UTF-8.
            try:
                with open(AUTH_FILE, "r", encoding="gbk") as file:
                    value, _ = _decode_auth(json.load(file))
                _save(value)
                return value
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                pass
        except (OSError, json.JSONDecodeError):
            pass
    return {"cookie": "", "accounts": []}


def _save(data):
    directory = os.path.dirname(AUTH_FILE)
    if directory:
        os.makedirs(directory, exist_ok=True)
    persisted = _encode_auth(data)
    descriptor, temporary = tempfile.mkstemp(
        prefix=".auth-", suffix=".tmp", dir=directory or ".", text=True
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(persisted, file, indent=2, ensure_ascii=False)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, AUTH_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def get_cookie() -> str:
    with AUTH_LOCK:
        return _load().get("cookie", "")


async def save_cookie(cookie: str) -> bool:
    """Validate and atomically persist a new QR-login cookie.

    The profile lookup is intentionally outside ``AUTH_LOCK``. On return we
    reload disk state before writing and reject an intervening logout/account
    switch, so a delayed QR poll cannot resurrect an older session.
    """
    global _auth_revision, _credential_reentry_required
    if not isinstance(cookie, str) or not cookie.strip():
        return False
    with AUTH_LOCK:
        initial_revision = _auth_revision
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                "https://api.bilibili.com/x/web-interface/nav",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com", "Cookie": cookie},
            )
            response.raise_for_status()
            payload = response.json()
        name = payload.get("data", {}).get("uname", "B站用户") if isinstance(payload, dict) else "B站用户"
    except (httpx.HTTPError, ValueError, TypeError):
        name = "B站用户"

    try:
        with AUTH_LOCK:
            if initial_revision != _auth_revision:
                return False
            # Reload after the network request: account state may have changed
            # while Bilibili's profile endpoint was in flight.
            data = _load()
            accounts = [
                account for account in data.get("accounts", [])
                if isinstance(account, dict) and not account.get(_UNAVAILABLE_COOKIE)
            ]
            cookie_prefix = cookie[:40]
            if not any(
                isinstance(account, dict) and account.get("cookie", "")[:40] == cookie_prefix
                for account in accounts
            ):
                accounts.insert(0, {"cookie": cookie, "name": str(name or "B站用户")})
                accounts = accounts[:5]
            data["cookie"] = cookie
            data.pop(_UNAVAILABLE_COOKIE, None)
            data["accounts"] = accounts
            _save(data)
            _auth_revision += 1
            # A successfully encrypted replacement makes the prior DPAPI
            # re-entry warning stale for the active session.
            _credential_reentry_required = False
            return True
    except (OSError, SecretUnavailableError, TypeError, ValueError):
        return False


def clear_cookie():
    global _auth_revision, _credential_reentry_required
    with AUTH_LOCK:
        data = _load()
        data["cookie"] = ""
        # Logout is an explicit secret-clearing action. Do not preserve an
        # active DPAPI ciphertext that belongs to another Windows profile.
        data.pop(_UNAVAILABLE_COOKIE, None)
        _save(data)
        _auth_revision += 1
        _credential_reentry_required = any(
            isinstance(account, dict) and account.get(_UNAVAILABLE_COOKIE)
            for account in data.get("accounts", [])
        )


def get_accounts() -> list:
    with AUTH_LOCK:
        return [
            {
                "index": index,
                "name": str(account.get("name") or "B站用户"),
            }
            for index, account in enumerate(_load().get("accounts", []))
            if isinstance(account, dict) and not account.get(_UNAVAILABLE_COOKIE)
        ]


def credential_reentry_required() -> bool:
    with AUTH_LOCK:
        return _credential_reentry_required


def switch_account(index: int) -> bool:
    global _auth_revision
    with AUTH_LOCK:
        data = _load()
        accounts = data.get("accounts", [])
        if 0 <= index < len(accounts) and not accounts[index].get(_UNAVAILABLE_COOKIE):
            data["cookie"] = accounts[index]["cookie"]
            _save(data)
            _auth_revision += 1
            return True
        return False


def _qrcode_data_url(payload: str) -> str:
    """Encode a Bilibili QR payload locally so the desktop WebView needs no third-party image host."""
    image = qrcode.make(payload, border=2)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


async def generate_qrcode() -> dict:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"},
            )
            response.raise_for_status()
            data = response.json()
        payload = data.get("data") if isinstance(data, dict) else None
        url = payload.get("url") if isinstance(payload, dict) else None
        qrcode_key = payload.get("qrcode_key") if isinstance(payload, dict) else None
        if not isinstance(data, dict) or data.get("code") != 0 or not isinstance(url, str) or not isinstance(qrcode_key, str):
            return {"error": "B站暂时无法生成登录二维码，请稍后重试"}
        return {
            "qrcode_key": qrcode_key,
            "image_data_url": _qrcode_data_url(url),
        }
    except (httpx.HTTPError, ValueError, TypeError):
        return {"error": "无法连接 B站登录服务，请检查网络后重试"}


async def poll_qrcode(qrcode_key: str) -> dict:
    if not isinstance(qrcode_key, str) or not qrcode_key.strip():
        return {"status": "error", "message": "登录二维码无效，请重新生成"}
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
                params={"qrcode_key": qrcode_key},
                headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"},
            )
            response.raise_for_status()
            data = response.json()
        inner = data.get("data") if isinstance(data, dict) else None
        if not isinstance(data, dict) or data.get("code") != 0 or not isinstance(inner, dict):
            return {"status": "error", "message": "B站登录服务返回了无效响应"}
        code = inner.get("code", -1)
        if code == 0:
            # httpx parses individual Set-Cookie headers safely.  Splitting a
            # combined header on commas corrupts cookies with an Expires date.
            sessdata = response.cookies.get("SESSDATA", "")
            if not sessdata:
                return {"status": "error", "message": "登录授权未返回会话信息，请重新扫码"}
            if not await save_cookie("SESSDATA=" + sessdata):
                return {"status": "error", "message": "登录信息保存失败，请检查本地存储后重试"}
            return {"status": "success", "message": "登录成功"}
        messages = {86090: ("scanned", "已扫码，请在手机上确认"), 86101: ("waiting", "等待扫码"), 86038: ("expired", "二维码已过期")}
        status, message = messages.get(code, ("unknown", "登录状态未知，请重新生成二维码"))
        return {"status": status, "message": message}
    except (httpx.HTTPError, ValueError, TypeError):
        return {"status": "error", "message": "无法连接 B站登录服务，请检查网络后重试"}

import asyncio
import json
import os

import httpx

from services.runtime_paths import auth_path
from services.secure_store import SecretUnavailableError, protect, unprotect


AUTH_FILE = os.environ.get("BILI_AUTH_PATH", str(auth_path()))
_credential_reentry_required = False


def _decode_cookie(value):
    global _credential_reentry_required
    try:
        return unprotect(value)
    except SecretUnavailableError:
        _credential_reentry_required = True
        return "", False


def _decode_auth(data):
    migrated = False
    data = data if isinstance(data, dict) else {}
    cookie, cookie_migrated = _decode_cookie(data.get("cookie", ""))
    data["cookie"] = cookie
    migrated = cookie_migrated
    accounts = data.get("accounts") if isinstance(data.get("accounts"), list) else []
    safe_accounts = []
    for account in accounts:
        if not isinstance(account, dict):
            continue
        current = dict(account)
        current["cookie"], account_migrated = _decode_cookie(current.get("cookie", ""))
        migrated = migrated or account_migrated
        safe_accounts.append(current)
    data["accounts"] = safe_accounts
    return data, migrated


def _encode_auth(data):
    persisted = dict(data)
    persisted["cookie"] = protect(str(persisted.get("cookie", "") or ""))
    accounts = []
    for account in persisted.get("accounts", []) or []:
        if isinstance(account, dict):
            current = dict(account)
            current["cookie"] = protect(str(current.get("cookie", "") or ""))
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
    os.makedirs(directory, exist_ok=True)
    temporary = AUTH_FILE + ".tmp"
    with open(temporary, "w", encoding="utf-8") as file:
        json.dump(_encode_auth(data), file, indent=2, ensure_ascii=False)
    os.replace(temporary, AUTH_FILE)


def get_cookie() -> str:
    return _load().get("cookie", "")


def save_cookie(cookie: str):
    data = _load()
    data["cookie"] = cookie
    try:
        async def _get_name():
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    "https://api.bilibili.com/x/web-interface/nav",
                    headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com", "Cookie": cookie},
                )
                return response.json().get("data", {}).get("uname", "Unknown")
        name = asyncio.run(_get_name())
    except Exception:
        name = "B站用户"
    accounts = data.get("accounts", [])
    cookie_prefix = cookie[:40]
    if not any(account.get("cookie", "")[:40] == cookie_prefix for account in accounts):
        accounts.insert(0, {"cookie": cookie, "name": name})
        accounts = accounts[:5]
    data["accounts"] = accounts
    _save(data)


def clear_cookie():
    data = _load()
    data["cookie"] = ""
    _save(data)


def get_accounts() -> list:
    return _load().get("accounts", [])


def credential_reentry_required() -> bool:
    return _credential_reentry_required


def switch_account(index: int) -> bool:
    data = _load()
    accounts = data.get("accounts", [])
    if 0 <= index < len(accounts):
        data["cookie"] = accounts[index]["cookie"]
        _save(data)
        return True
    return False


async def generate_qrcode() -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/generate",
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"},
        )
        data = response.json()
        if data.get("code") != 0:
            return {"error": "Failed to generate QR code"}
        return {"url": data["data"]["url"], "qrcode_key": data["data"]["qrcode_key"]}


async def poll_qrcode(qrcode_key: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        response = await client.get(
            "https://passport.bilibili.com/x/passport-login/web/qrcode/poll",
            params={"qrcode_key": qrcode_key},
            headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bilibili.com"},
        )
        data = response.json()
        if data.get("code") != 0:
            return {"status": "error", "message": "API error"}
        inner = data["data"]
        code = inner.get("code", -1)
        if code == 0:
            sessdata = ""
            for part in response.headers.get("set-cookie", "").split(","):
                part = part.strip()
                if part.startswith("SESSDATA="):
                    sessdata = part.split(";", 1)[0]
                    break
            if sessdata:
                save_cookie(sessdata)
            return {"status": "success", "message": "Logged in"}
        messages = {86090: ("scanned", "Scanned, confirm on phone"), 86101: ("waiting", "Waiting for scan"), 86038: ("expired", "QR expired")}
        status, message = messages.get(code, ("unknown", f"Code {code}"))
        return {"status": status, "message": message}

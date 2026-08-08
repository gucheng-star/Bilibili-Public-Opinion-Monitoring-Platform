"""Small Windows DPAPI adapter used for portable credentials.

Encrypted values are intentionally tied to the current Windows user and
machine.  A copied portable folder therefore keeps analysis history but asks
the user to log in/configure provider keys again on another computer.
"""

from __future__ import annotations

import base64
import ctypes
import os
from ctypes import POINTER, Structure, byref, c_char, c_void_p, cast, sizeof


PREFIX = "enc:v1:"


class SecretUnavailableError(RuntimeError):
    """DPAPI cannot decrypt a value in the current Windows profile."""


class _DATA_BLOB(Structure):
    _fields_ = [("cbData", ctypes.c_ulong), ("pbData", POINTER(c_char))]


def is_encrypted(value: object) -> bool:
    return isinstance(value, str) and value.startswith(PREFIX)


def _windows_protect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecretUnavailableError("当前系统不支持 Windows 凭据保护")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source_buffer = ctypes.create_string_buffer(data)
    source = _DATA_BLOB(len(data), cast(source_buffer, POINTER(c_char)))
    target = _DATA_BLOB()
    if not crypt32.CryptProtectData(byref(source), None, None, None, None, 0, byref(target)):
        raise SecretUnavailableError("无法使用 Windows 凭据保护")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(cast(target.pbData, c_void_p))


def _windows_unprotect(data: bytes) -> bytes:
    if os.name != "nt":
        raise SecretUnavailableError("当前系统不支持 Windows 凭据保护")
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    source_buffer = ctypes.create_string_buffer(data)
    source = _DATA_BLOB(len(data), cast(source_buffer, POINTER(c_char)))
    target = _DATA_BLOB()
    if not crypt32.CryptUnprotectData(byref(source), None, None, None, None, 0, byref(target)):
        raise SecretUnavailableError("此凭据来自另一台电脑或另一个 Windows 用户")
    try:
        return ctypes.string_at(target.pbData, target.cbData)
    finally:
        kernel32.LocalFree(cast(target.pbData, c_void_p))


def protect(value: str) -> str:
    if not value:
        return ""
    if is_encrypted(value):
        return value
    encrypted = _windows_protect(value.encode("utf-8"))
    return PREFIX + base64.b64encode(encrypted).decode("ascii")


def unprotect(value: object) -> tuple[str, bool]:
    """Return ``(plaintext, needs_migration)`` without silently accepting bad data."""
    if not isinstance(value, str) or not value:
        return "", False
    if not is_encrypted(value):
        return value, True
    try:
        payload = base64.b64decode(value[len(PREFIX):], validate=True)
        return _windows_unprotect(payload).decode("utf-8"), False
    except (ValueError, UnicodeDecodeError, SecretUnavailableError) as exc:
        raise SecretUnavailableError("保存的凭据无法在当前电脑使用，请重新输入") from exc

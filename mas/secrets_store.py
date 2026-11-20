"""Pilot password storage. Never prints or logs secrets.

Order of preference:
1. OS keyring (Windows Credential Manager / macOS Keychain / Linux Secret Service).
2. Fallback file `.secrets/pilots.json` (git-ignored, chmod 600) when no keyring backend works.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

SERVICE = 'spacemolt-mas'
ROOT = Path(__file__).resolve().parents[1]
SECRETS_DIR = ROOT / '.secrets'
FILE = SECRETS_DIR / 'pilots.json'


def _keyring():
    try:
        import keyring
        from keyring.backends import fail
        if isinstance(keyring.get_keyring(), fail.Keyring):
            return None
        return keyring
    except Exception:
        return None


def _read_file() -> dict:
    if not FILE.exists():
        return {}
    return json.loads(FILE.read_text(encoding='utf-8'))


def _write_file(data: dict) -> None:
    SECRETS_DIR.mkdir(exist_ok=True)
    try:
        os.chmod(SECRETS_DIR, 0o700)
    except OSError:
        pass
    tmp = FILE.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, indent=2), encoding='utf-8')
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    tmp.replace(FILE)


def set_password(username: str, password: str) -> str:
    """Store a password; returns where it was stored ('keyring' or 'file')."""
    kr = _keyring()
    if kr is not None:
        try:
            kr.set_password(SERVICE, username, password)
            if kr.get_password(SERVICE, username) == password:
                return 'keyring'
        except Exception:
            pass
    data = _read_file()
    data[username] = password
    _write_file(data)
    return 'file'


def get_password(username: str) -> str | None:
    env = os.environ.get('SPACEMOLT_PASSWORD_' + username.upper().replace('-', '_'))
    if env:
        return env
    kr = _keyring()
    if kr is not None:
        try:
            pw = kr.get_password(SERVICE, username)
            if pw:
                return pw
        except Exception:
            pass
    return _read_file().get(username)


def save_raw_private(name: str, text: str) -> Path:
    """Keep an unparsed sensitive server response privately so nothing is lost."""
    SECRETS_DIR.mkdir(exist_ok=True)
    path = SECRETS_DIR / name
    path.write_text(text, encoding='utf-8')
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return path

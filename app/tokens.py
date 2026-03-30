from __future__ import annotations

import secrets
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path

from app.data import _atomic_write   # 원자적 저장 헬퍼 재사용

import json

_DEFAULT_TTL = 300  # 5분


@dataclass
class ClaimToken:
    token: str
    discord_user_id: int
    discord_username: str       # 웹 claim 시 UserRecord 갱신용
    discord_display_name: str
    device_label: str
    person_name: str
    created_at: str             # ISO 8601
    expires_at: str             # ISO 8601
    used: bool


class TokenStore:
    """일회용 IP claim 토큰 저장소."""

    def __init__(self, path: str = "data/ip-tokens.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._tokens: dict[str, ClaimToken] = {}
        self._load()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def create(
        self,
        user_id: int,
        discord_username: str,
        discord_display_name: str,
        device_label: str,
        person_name: str,
        ttl_seconds: int = _DEFAULT_TTL,
    ) -> str:
        """토큰을 생성하고 저장한 뒤 토큰 문자열을 반환한다."""
        self._cleanup_expired()
        token_str = secrets.token_urlsafe(32)
        now = datetime.now()
        entry = ClaimToken(
            token=token_str,
            discord_user_id=user_id,
            discord_username=discord_username,
            discord_display_name=discord_display_name,
            device_label=device_label,
            person_name=person_name,
            created_at=now.isoformat(timespec="seconds"),
            expires_at=(now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds"),
            used=False,
        )
        self._tokens[token_str] = entry
        self._save()
        return token_str

    def peek(self, token_str: str) -> bool:
        """토큰이 유효한지 확인만 한다. 소비하지 않는다."""
        entry = self._tokens.get(token_str)
        if entry is None or entry.used:
            return False
        if datetime.now() > datetime.fromisoformat(entry.expires_at):
            return False
        return True

    def consume(self, token_str: str) -> ClaimToken | None:
        """
        토큰을 검증하고 소비(used=True)한다.
        유효하면 ClaimToken 반환, 만료/사용됨/없음이면 None.
        """
        entry = self._tokens.get(token_str)
        if entry is None or entry.used:
            return None
        if datetime.now() > datetime.fromisoformat(entry.expires_at):
            return None
        entry.used = True
        self._save()
        return entry

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _cleanup_expired(self) -> None:
        now = datetime.now()
        self._tokens = {
            k: v for k, v in self._tokens.items()
            if not v.used and datetime.fromisoformat(v.expires_at) > now
        }

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
            for item in raw.get("tokens", []):
                t = ClaimToken(**item)
                self._tokens[t.token] = t
        except Exception:
            self._tokens.clear()

    def _save(self) -> None:
        data = {"tokens": [asdict(t) for t in self._tokens.values()]}
        _atomic_write(self._path, data)

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path


@dataclass
class IPEntry:
    address: str
    device_label: str    # 기기 이름
    person_name: str     # 사람 이름
    source: str          # "manual" | "auto"
    created_at: str      # ISO 8601 (초 단위)
    last_seen_at: str    # ISO 8601 (초 단위)


@dataclass
class UserRecord:
    user_id: int
    username: str        # Discord username
    display_name: str    # 표시 이름 (닉네임 등)
    ips: list[IPEntry] = field(default_factory=list)


class IPRegistry:
    """JSON 파일 기반 IP 등록 저장소. 1 유저 → 다수 IP 지원."""

    def __init__(self, path: str = "data/ip-state.json") -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._users: dict[int, UserRecord] = {}   # user_id → UserRecord
        self._ip_owner: dict[str, int] = {}       # address → user_id
        self._load()

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def register(
        self,
        user_id: int,
        username: str,
        display_name: str,
        address: str,
        device_label: str = "",
        person_name: str = "",
        source: str = "manual",
    ) -> tuple[bool, str]:
        """
        IP를 등록한다.
        - 같은 유저 + 같은 IP: 갱신
        - 다른 유저가 이미 사용 중: 충돌 오류
        - 신규: 추가
        """
        now = datetime.now().isoformat(timespec="seconds")

        # 충돌 검사
        owner_id = self._ip_owner.get(address)
        if owner_id is not None and owner_id != user_id:
            owner = self._users.get(owner_id)
            owner_name = owner.display_name if owner else str(owner_id)
            return False, f"`{address}` 은(는) 이미 **{owner_name}**님이 사용 중입니다."

        # UserRecord 가져오거나 생성
        user = self._users.get(user_id)
        if user is None:
            user = UserRecord(user_id=user_id, username=username, display_name=display_name)
            self._users[user_id] = user
        else:
            user.username = username or user.username
            user.display_name = display_name or user.display_name

        # 이미 등록된 IP면 갱신
        for entry in user.ips:
            if entry.address == address:
                entry.last_seen_at = now
                if device_label:
                    entry.device_label = device_label
                if person_name:
                    entry.person_name = person_name
                self._save()
                return True, f"`{address}` 정보를 갱신했습니다."

        # 신규 등록
        entry = IPEntry(
            address=address,
            device_label=device_label,
            person_name=person_name,
            source=source,
            created_at=now,
            last_seen_at=now,
        )
        user.ips.append(entry)
        self._ip_owner[address] = user_id
        self._save()
        return True, f"`{address}` 을(를) 등록했습니다."

    def release(self, user_id: int, address: str) -> tuple[bool, str]:
        """특정 IP 등록을 해제한다."""
        user = self._users.get(user_id)
        if user is None:
            return False, "등록된 IP가 없습니다."

        for i, entry in enumerate(user.ips):
            if entry.address == address:
                user.ips.pop(i)
                self._ip_owner.pop(address, None)
                if not user.ips:
                    del self._users[user_id]
                self._save()
                return True, f"`{address}` 등록을 해제했습니다."

        return False, f"`{address}` 은(는) 내 IP 목록에 없습니다."

    def release_by_person(self, person_name: str) -> tuple[bool, str]:
        """사람 이름으로 등록된 모든 IP를 해제한다 (대소문자 구분 없음)."""
        name_lower = person_name.strip().lower()
        released: list[str] = []

        for user_id, user in list(self._users.items()):
            remaining = []
            for entry in user.ips:
                if entry.person_name.strip().lower() == name_lower:
                    self._ip_owner.pop(entry.address, None)
                    released.append(entry.address)
                else:
                    remaining.append(entry)
            user.ips = remaining
            if not user.ips:
                del self._users[user_id]

        if not released:
            return False, f"**{person_name}** 이름으로 등록된 IP가 없습니다."

        self._save()
        ip_list = ", ".join(f"`{a}`" for a in released)
        return True, f"**{person_name}** 의 IP {len(released)}개를 해제했습니다: {ip_list}"

    def update_labels(
        self,
        user_id: int,
        address: str,
        device_label: str | None = None,
        person_name: str | None = None,
    ) -> tuple[bool, str]:
        """등록된 IP의 기기 이름 / 사람 이름을 수정한다."""
        user = self._users.get(user_id)
        if user is None:
            return False, "등록된 IP가 없습니다."

        for entry in user.ips:
            if entry.address == address:
                if device_label is not None:
                    entry.device_label = device_label
                if person_name is not None:
                    entry.person_name = person_name
                entry.last_seen_at = datetime.now().isoformat(timespec="seconds")
                self._save()
                return True, f"`{address}` 정보를 업데이트했습니다."

        return False, f"`{address}` 은(는) 내 IP 목록에 없습니다."

    def get_user_ips(self, user_id: int) -> list[IPEntry]:
        user = self._users.get(user_id)
        return list(user.ips) if user else []

    def find_ip_owner(self, address: str) -> UserRecord | None:
        owner_id = self._ip_owner.get(address)
        if owner_id is None:
            return None
        return self._users.get(owner_id)

    def get_all_entries(self) -> list[tuple[UserRecord, IPEntry]]:
        """(UserRecord, IPEntry) 쌍을 IP 오름차순으로 반환한다."""
        pairs = [
            (user, entry)
            for user in self._users.values()
            for entry in user.ips
        ]
        return sorted(pairs, key=lambda p: _ip_sort_key(p[1].address))

    def count(self) -> int:
        return sum(len(u.ips) for u in self._users.values())

    # ------------------------------------------------------------------ #
    # Internal                                                             #
    # ------------------------------------------------------------------ #

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            with open(self._path, encoding="utf-8") as f:
                raw = json.load(f)
            for uid_str, udata in raw.get("users", {}).items():
                user_id = int(uid_str)
                ips = [IPEntry(**ip) for ip in udata.get("ips", [])]
                user = UserRecord(
                    user_id=user_id,
                    username=udata.get("username", ""),
                    display_name=udata.get("display_name", ""),
                    ips=ips,
                )
                self._users[user_id] = user
                for entry in ips:
                    self._ip_owner[entry.address] = user_id
        except Exception:
            self._users.clear()
            self._ip_owner.clear()

    def _save(self) -> None:
        data = {
            "users": {
                str(uid): {
                    "username": u.username,
                    "display_name": u.display_name,
                    "ips": [asdict(ip) for ip in u.ips],
                }
                for uid, u in self._users.items()
            }
        }
        _atomic_write(self._path, data)


def _atomic_write(path: Path, data: dict) -> None:
    """임시 파일에 쓰고 rename — 손상 없는 저장 보장."""
    dir_ = path.parent
    dir_.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, str(path))
    except Exception:
        os.unlink(tmp)
        raise


def _ip_sort_key(ip: str) -> tuple[int, ...]:
    try:
        return tuple(int(o) for o in ip.split("."))
    except ValueError:
        return (0, 0, 0, 0)

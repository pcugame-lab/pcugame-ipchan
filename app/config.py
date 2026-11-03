from __future__ import annotations

import os
import ipaddress
import json
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GuildConfig:
    guild_id: int
    channel_id: int | None       # None이면 모든 채널에서 사용 가능
    allowed_role_id: int | None  # None이면 역할 제한 없음


@dataclass(frozen=True)
class WakeTarget:
    ip: str
    mac: str
    name: str


@dataclass(frozen=True)
class Config:
    discord_token: str
    guilds: tuple[GuildConfig, ...]
    ip_prefix: str          # 허용 IP 앞 3옥텟 (예: "203.250.133")
    ip_state_file: str      # IP 등록 상태 JSON 경로
    token_file: str         # Claim 토큰 JSON 경로
    web_host: str           # 웹서버 bind 주소
    web_port: int           # 웹서버 포트
    web_base_url: str       # 클라이언트가 접속하는 공개 URL (claim 링크 생성용)
    token_ttl_seconds: int  # Claim 토큰 유효 시간(초)
    rate_limit_window: int = 60
    rate_limit_max: int = 10
    admin_user_ids: frozenset[int] = frozenset()
    ip_last_octet_range: tuple[int, int] | None = None
    wol_targets: tuple[WakeTarget, ...] = ()

    def is_admin(self, user_id: int) -> bool:
        return user_id in self.admin_user_ids


def load_config() -> Config:
    token = os.environ.get("DISCORD_TOKEN", "").strip()
    if not token:
        raise ValueError("DISCORD_TOKEN 환경변수가 설정되지 않았습니다.")

    guilds = _load_guilds()
    ip_prefix = os.environ.get("IP_PREFIX", "").strip()
    if not ip_prefix:
        raise ValueError("IP_PREFIX 환경변수가 설정되지 않았습니다. (예: 192.168.1)")
    ip_state_file = os.environ.get("IP_STATE_FILE", "data/ip-state.json").strip()
    token_file = os.environ.get("TOKEN_FILE", "data/ip-tokens.json").strip()
    web_host = os.environ.get("WEB_HOST", "127.0.0.1").strip()
    web_port = int(os.environ.get("WEB_PORT", "8080"))
    web_base_url = os.environ.get("WEB_BASE_URL", f"http://localhost:{web_port}").strip().rstrip("/")
    token_ttl = int(os.environ.get("TOKEN_TTL_SECONDS", "300"))

    return Config(
        discord_token=token,
        guilds=tuple(guilds),
        ip_prefix=ip_prefix,
        ip_state_file=ip_state_file,
        token_file=token_file,
        web_host=web_host,
        web_port=web_port,
        web_base_url=web_base_url,
        token_ttl_seconds=token_ttl,
        rate_limit_window=int(os.environ.get("RATE_LIMIT_WINDOW", "60")),
        rate_limit_max=int(os.environ.get("RATE_LIMIT_MAX", "10")),
        admin_user_ids=_load_admin_user_ids(),
        ip_last_octet_range=_load_ip_last_octet_range(),
        wol_targets=_load_wol_targets(ip_prefix),
    )


def _load_guilds() -> list[GuildConfig]:
    guilds: list[GuildConfig] = []
    i = 1
    while True:
        guild_id_str = os.environ.get(f"GUILD_{i}_ID", "").strip()
        if not guild_id_str:
            break
        channel_id_str = os.environ.get(f"GUILD_{i}_CHANNEL_ID", "").strip()
        role_id_str = os.environ.get(f"GUILD_{i}_ROLE_ID", "").strip()
        try:
            guilds.append(GuildConfig(
                guild_id=int(guild_id_str),
                channel_id=int(channel_id_str) if channel_id_str else None,
                allowed_role_id=int(role_id_str) if role_id_str else None,
            ))
        except ValueError as e:
            raise ValueError(f"GUILD_{i}_* 환경변수 형식 오류: {e}") from e
        i += 1

    if not guilds:
        raise ValueError("GUILD_1_ID 환경변수가 설정되지 않았습니다.")
    return guilds


def _load_admin_user_ids() -> frozenset[int]:
    raw = os.environ.get("ADMIN_USER_IDS", "").strip()
    if not raw:
        return frozenset()
    ids = set()
    for value in raw.split(","):
        value = value.strip()
        if not value.isascii() or not value.isdecimal() or not 0 < int(value) < 2**64:
            raise ValueError("ADMIN_USER_IDS에는 쉼표로 구분한 Discord 사용자 ID를 입력하세요.")
        ids.add(int(value))
    return frozenset(ids)


def _load_ip_last_octet_range() -> tuple[int, int] | None:
    raw = os.environ.get("IP_LAST_OCTET_RANGE", "").strip()
    if not raw:
        return None
    parts = raw.split("-")
    if len(parts) != 2 or any(not p.strip().isascii() or not p.strip().isdecimal() for p in parts):
        raise ValueError("IP_LAST_OCTET_RANGE는 시작-끝 형식이어야 합니다. 예: 221-254")
    start, end = (int(p.strip()) for p in parts)
    if not 1 <= start <= end <= 254:
        raise ValueError("IP_LAST_OCTET_RANGE는 1~254 사이의 오름차순 범위여야 합니다.")
    return start, end


def _load_wol_targets(prefix: str) -> tuple[WakeTarget, ...]:
    raw = os.environ.get('WOL_TARGETS', '').strip()
    if not raw:
        return ()
    try:
        rows = json.loads(raw)
        network = ipaddress.IPv4Network(f'{prefix}.0/24')
        if not isinstance(rows, list) or len(rows) > 25:
            raise ValueError('대상은 최대 25개의 배열로 지정하세요.')
        targets = []
        seen_ips, seen_macs = set(), set()
        for row in rows:
            ip = str(row['ip']).strip()
            if ip.isascii() and ip.isdecimal():
                ip = f'{prefix}.{ip}'
            address = ipaddress.IPv4Address(ip)
            if address not in network or address in (network.network_address, network.broadcast_address):
                raise ValueError('같은 대역의 PC IP를 지정하세요.')
            mac = row['mac'].strip().lower().replace('-', ':')
            if not re.fullmatch(r'(?:[0-9a-f]{2}:){5}[0-9a-f]{2}', mac):
                raise ValueError('유선 MAC 주소 형식을 확인하세요.')
            if int(mac[:2], 16) & 1 or mac == '00:00:00:00:00:00':
                raise ValueError('PC의 유니캐스트 MAC 주소를 지정하세요.')
            name = row.get('name', '').strip() or f'PC {address.packed[-1]}'
            if len(name) > 80 or any(ord(c) < 32 for c in name):
                raise ValueError('기기 이름은 제어문자 없이 80자 이내로 지정하세요.')
            if ip in seen_ips or mac in seen_macs:
                raise ValueError('중복된 IP 또는 MAC 주소가 있습니다.')
            seen_ips.add(ip)
            seen_macs.add(mac)
            targets.append(WakeTarget(ip, mac, name))
        return tuple(targets)
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f'WOL_TARGETS 설정 오류: {exc}') from exc

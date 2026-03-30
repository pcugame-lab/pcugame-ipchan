from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class GuildConfig:
    guild_id: int
    channel_id: int | None       # None이면 모든 채널에서 사용 가능
    allowed_role_id: int | None  # None이면 역할 제한 없음


@dataclass(frozen=True)
class Config:
    discord_token: str
    guilds: tuple[GuildConfig, ...]
    ip_prefix: str          # 허용 IP 앞 3옥텟 (예: "192.168.1")
    ip_state_file: str      # IP 등록 상태 JSON 경로
    token_file: str         # Claim 토큰 JSON 경로
    web_host: str           # 웹서버 bind 주소
    web_port: int           # 웹서버 포트
    web_base_url: str       # 클라이언트가 접속하는 공개 URL (claim 링크 생성용)
    token_ttl_seconds: int  # Claim 토큰 유효 시간(초)
    rate_limit_window: int  # Rate limit 윈도우(초)
    rate_limit_max: int     # 윈도우 내 최대 요청 수


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
    rate_limit_window = int(os.environ.get("RATE_LIMIT_WINDOW", "60"))
    rate_limit_max = int(os.environ.get("RATE_LIMIT_MAX", "10"))

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
        rate_limit_window=rate_limit_window,
        rate_limit_max=rate_limit_max,
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

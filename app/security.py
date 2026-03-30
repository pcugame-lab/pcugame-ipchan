from __future__ import annotations

import logging
from typing import Optional

import discord

from app.config import GuildConfig

logger = logging.getLogger(__name__)


def find_guild_config(
    guilds: tuple[GuildConfig, ...],
    guild_id: int,
) -> Optional[GuildConfig]:
    for g in guilds:
        if g.guild_id == guild_id:
            return g
    return None


def check_all_permissions(
    interaction: discord.Interaction,
    guilds: tuple[GuildConfig, ...],
) -> tuple[Optional[str], Optional[GuildConfig]]:
    """
    권한을 순서대로 확인한다.
    Returns (error_message, guild_config)
      - 통과: (None, GuildConfig)
      - 실패: (오류 메시지, None)
    """
    guild_cfg = find_guild_config(guilds, interaction.guild_id or 0)
    if guild_cfg is None:
        logger.warning(f"unknown guild: user={interaction.user.id}, guild={interaction.guild_id}")
        return "이 서버에서는 사용할 수 없는 명령어입니다.", None

    # 채널 제한이 설정된 경우에만 확인
    if guild_cfg.channel_id is not None and interaction.channel_id != guild_cfg.channel_id:
        logger.info(
            f"channel mismatch: user={interaction.user.id}, "
            f"channel={interaction.channel_id}, expected={guild_cfg.channel_id}"
        )
        return f"이 명령어는 <#{guild_cfg.channel_id}> 채널에서만 사용할 수 있습니다.", None

    # 역할 제한이 설정된 경우에만 확인
    if guild_cfg.allowed_role_id is not None:
        if not isinstance(interaction.user, discord.Member):
            return "서버 멤버만 사용할 수 있습니다.", None
        if not any(r.id == guild_cfg.allowed_role_id for r in interaction.user.roles):
            logger.warning(f"role missing: user={interaction.user.id}, guild={interaction.guild_id}")
            return "이 명령어를 실행할 권한(역할)이 없습니다.", None

    return None, guild_cfg

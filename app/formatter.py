from __future__ import annotations

import logging
import math

import discord

from app.data import IPEntry, UserRecord

logger = logging.getLogger(__name__)

_PER_PAGE = 20  # 페이지당 항목 수 (embed 필드 1024자 제한 고려)


# ---------------------------------------------------------------------------
# 상태 embed 빌더
# ---------------------------------------------------------------------------

def build_status_pages(
    entries: list[tuple[UserRecord, IPEntry]],
    ip_prefix: str,
) -> list[discord.Embed]:
    """(UserRecord, IPEntry) 쌍 목록을 페이지 embed 목록으로 변환한다."""
    if not entries:
        embed = discord.Embed(
            title=f"🖥️ {ip_prefix}.x 사용 현황",
            description="현재 등록된 IP가 없습니다.",
            color=discord.Color.blue(),
        )
        return [embed]

    total = len(entries)
    total_pages = max(1, math.ceil(total / _PER_PAGE))
    pages = []

    for p in range(total_pages):
        chunk = entries[p * _PER_PAGE : (p + 1) * _PER_PAGE]

        col_ip = "\n".join(f"`{ip.address}`" for _, ip in chunk)
        col_person = "\n".join(ip.person_name or "—" for _, ip in chunk)
        col_detail = "\n".join(
            f"{ip.device_label or '—'} · {ip.created_at[:10]} "
            f"{'🤖' if ip.source == 'auto' else '✏️'}"
            for _, ip in chunk
        )

        embed = discord.Embed(
            title=f"🖥️ {ip_prefix}.x 사용 현황",
            color=discord.Color.blue(),
        )
        embed.add_field(name="IP주소",       value=col_ip,     inline=True)
        embed.add_field(name="이름",          value=col_person, inline=True)
        embed.add_field(name="기기 · 등록일", value=col_detail, inline=True)
        embed.set_footer(text=f"페이지 {p + 1}/{total_pages}  |  총 {total}개 IP")
        pages.append(embed)

    return pages


# ---------------------------------------------------------------------------
# 페이지네이션 뷰
# ---------------------------------------------------------------------------

class StatusView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed]) -> None:
        super().__init__(timeout=120)
        self.pages = pages
        self.page = 0
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self.btn_prev.disabled = self.page == 0
        self.btn_next.disabled = self.page >= len(self.pages) - 1

    @discord.ui.button(label="◀ 이전", style=discord.ButtonStyle.secondary, disabled=True)
    async def btn_prev(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page -= 1
        self._refresh_buttons()
        try:
            await interaction.response.edit_message(embed=self.pages[self.page], view=self)
        except Exception:
            logger.exception("btn_prev edit_message 실패")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("❌ 페이지 전환 중 오류가 발생했습니다.", ephemeral=True)

    @discord.ui.button(label="다음 ▶", style=discord.ButtonStyle.secondary)
    async def btn_next(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.page += 1
        self._refresh_buttons()
        try:
            await interaction.response.edit_message(embed=self.pages[self.page], view=self)
        except Exception:
            logger.exception("btn_next edit_message 실패")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("❌ 페이지 전환 중 오류가 발생했습니다.", ephemeral=True)

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True


# ---------------------------------------------------------------------------
# 도움말 embed
# ---------------------------------------------------------------------------

def build_help_embed(ip_prefix: str) -> discord.Embed:
    embed = discord.Embed(
        title="📖 IP 등록 봇 도움말",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name="/register [ip] [device] [person]",
        value=(
            f"IP를 등록합니다. (아이피의 맨 마지막 세자리만 입력해도 됩니다. 예: 229)\n"
            f"• `ip` 생략시 → 자동 감지 링크 발급 (버튼 클릭으로 현재 IP 등록)\n"
            f"• `ip` 입력시 → 수동 등록 (예: `{ip_prefix}.100`)\n"
            f"• `person` 입력시 → 수동 등록 (예: `박진성`)\n"
            f"• `person` 미입력시 → 디스코드 Pronoun으로 등록 (예: `25 박진성`)\n"
            f"• 나중에 `/change`로 수정 가능"
        ),
        inline=False,
    )
    embed.add_field(
        name="/release [ip] [person]",
        value=f"특정 IP를 해제하거나, 특정 개인의 IP 등록을 전부 해제합니다. 예: `/release {ip_prefix}.***`, `/release 송지한`",
        inline=False,
    )
    embed.add_field(
        name="/change <ip> [device] [person]",
        value=(
            f"등록된 IP의 기기 이름 또는 사람 이름을 수정합니다.\n"
            f"예: `/change {ip_prefix}.100 device:테스트노트북 person:이영희`"
        ),
        inline=False,
    )
    embed.add_field(
        name="/status",
        value="현재 등록된 모든 IP정보를 표시합니다.",
        inline=False,
    )
    embed.add_field(
        name="/help",
        value="이 도움말을 표시합니다.",
        inline=False,
    )
    embed.set_footer(text=f"허용 대역: {ip_prefix}.1 ~ {ip_prefix}.254  |  ✏️ 수동  🤖 자동")
    return embed

from __future__ import annotations

import logging
import math
import unicodedata

import discord

from app.data import IPEntry, UserRecord

logger = logging.getLogger(__name__)

_PER_PAGE = 15  # 페이지당 항목 수 (코드 블록 2000자 제한 고려)


# ---------------------------------------------------------------------------
# 문자열 표시 폭 계산 (한글·전각 = 2, 반각 = 1)
# ---------------------------------------------------------------------------

def _display_width(s: str) -> int:
    """문자열의 터미널 표시 폭을 계산한다. 전각(한글 등) = 2, 반각 = 1."""
    w = 0
    for ch in s:
        cat = unicodedata.east_asian_width(ch)
        w += 2 if cat in ("W", "F") else 1
    return w


def _pad(s: str, width: int) -> str:
    """표시 폭 기준으로 오른쪽 패딩을 추가한다."""
    return s + " " * (width - _display_width(s))


def _truncate(s: str, max_width: int) -> str:
    """표시 폭 기준으로 잘라내고 말줄임표를 붙인다."""
    w = 0
    for i, ch in enumerate(s):
        cat = unicodedata.east_asian_width(ch)
        cw = 2 if cat in ("W", "F") else 1
        if w + cw > max_width - 1:
            return s[:i] + "…"
        w += cw
    return s


# ---------------------------------------------------------------------------
# 상태 embed 빌더
# ---------------------------------------------------------------------------

def build_status_pages(
    entries: list[tuple[UserRecord, IPEntry]],
    ip_prefix: str,
) -> list[discord.Embed]:
    """(UserRecord, IPEntry) 쌍 목록을 코드 블록 표 형식의 embed 목록으로 변환한다."""
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

    # 컬럼 폭 설정
    col_ip = 5    # 마지막 옥텟 (최대 3자리 + 여유)
    col_name = 10  # 이름
    col_dev = 10   # 기기
    col_date = 10  # 등록일
    col_src = 2    # 방식

    header = (
        f" {'IP':>{col_ip}} │ "
        f"{'이름':<{col_name - 2}}│ "
        f"{'기기':<{col_dev - 2}}│ "
        f"{'등록일':<{col_date - 2}}│"
        f"{'':>{col_src}}"
    )
    separator = "─" * (col_ip + 1) + "┼" + "─" * (col_name + 1) + "┼" + "─" * (col_dev + 1) + "┼" + "─" * (col_date + 1) + "┼" + "─" * (col_src + 1)

    for p in range(total_pages):
        chunk = entries[p * _PER_PAGE : (p + 1) * _PER_PAGE]
        lines = [header, separator]

        for _, ip in chunk:
            last_octet = ip.address.split(".")[-1] if "." in ip.address else ip.address
            name = _truncate(ip.person_name or "—", col_name)
            dev = _truncate(ip.device_label or "—", col_dev)
            date = ip.created_at[:10]
            src = "🤖" if ip.source == "auto" else "✏️"

            lines.append(
                f" {last_octet:>{col_ip}} │ "
                f"{_pad(name, col_name)}│ "
                f"{_pad(dev, col_dev)}│ "
                f"{date:<{col_date}}│"
                f"{src}"
            )
            lines.append(separator)

        table = "```\n" + "\n".join(lines) + "\n```"

        embed = discord.Embed(
            title=f"🖥️ {ip_prefix}.x 사용 현황",
            description=table,
            color=discord.Color.blue(),
        )
        embed.set_footer(text=f"페이지 {p + 1}/{total_pages}  |  총 {total}개 IP  |  ✏️ 수동  🤖 자동")
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

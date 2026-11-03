from __future__ import annotations

import logging
import unicodedata

import discord

from app.data import IPEntry, UserRecord

logger = logging.getLogger(__name__)

_PER_PAGE = 20


def _clean(value: str) -> str:
    # Keep user input inside the code fence and on a single logical line.
    return " ".join("".join(
        ch for ch in value.replace("`", "ˋ")
        if not unicodedata.category(ch).startswith("C") or ch.isspace()
    ).split()) or "—"


def _width(value: str) -> int:
    return sum(0 if unicodedata.combining(ch) else
               2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1
               for ch in value)


def _wrap(value: str, width: int) -> list[str]:
    lines, line = [], ""
    for ch in _clean(value):
        if _width(line + ch) > width:
            lines.append(line)
            line = ""
        line += ch
    return lines + [line]


def _status_box(ip: IPEntry, mobile: bool) -> str:
    source = "자동" if ip.source == "auto" else "수동"
    values = [ip.address, ip.person_name, ip.device_label, ip.created_at[:10], source]
    if mobile:
        values[0] = ip.address.rsplit(".", 1)[-1]
        return "```\n" + "\n".join(
            "\n".join(_wrap(f"{label}: {value or '—'}", 26))
            for label, value in zip(("IP", "이름", "기기", "등록일", "방식"), values)
        ) + "\n```"
    raise ValueError("Mobile boxes only")


def _build_column_pages(entries, ip_prefix):
    chunks, columns = [], [[], [], []]
    for _, ip in entries:
        source = "🤖" if ip.source == "auto" else "✏️"
        cells = [f"`{_clean(ip.address)}`", f"`{_clean(ip.person_name)}`",
                 f"`{_clean(ip.device_label)} · {_clean(ip.created_at[:10])}` {source}"]
        if columns[0] and (len(columns[0]) >= _PER_PAGE or any(
                len("\n".join(col + [cell])) > 1024
                for col, cell in zip(columns, cells))):
            chunks.append(columns)
            columns = [[], [], []]
        for col, cell in zip(columns, cells):
            col.append(cell)
    if columns[0]:
        chunks.append(columns)
    pages = []
    for index, columns in enumerate(chunks or [None]):
        embed = discord.Embed(title=f"🖥️ {ip_prefix}.x 사용 현황", color=discord.Color.blue())
        if columns:
            for name, col in zip(("IP주소", "이름", "기기 · 등록일"), columns):
                embed.add_field(name=name, value="\n".join(col), inline=True)
        else:
            embed.description = "현재 등록된 IP가 없습니다."
        embed.set_footer(text=f"페이지 {index + 1}/{len(chunks) or 1}  |  총 {len(entries)}개 IP")
        pages.append(embed)
    return pages


def build_status_pages(
    entries: list[tuple[UserRecord, IPEntry]],
    ip_prefix: str,
    mobile: bool = False,
) -> list[discord.Embed]:
    """Keep the original three embed columns, with inline-code cells."""
    if not mobile:
        return _build_column_pages(entries, ip_prefix)

    def render(rows: list[str]) -> str:
        return "\n".join(rows)

    descriptions, rows = [], []
    for _, ip in entries:
        row = _status_box(ip, mobile)
        if rows and (len(rows) >= (5 if mobile else _PER_PAGE)
                     or len(render(rows + [row])) > 4000):
            descriptions.append(render(rows))
            rows = []
        rows.append(row)
    if rows:
        descriptions.append(render(rows))
    if not descriptions:
        descriptions = ["현재 등록된 IP가 없습니다."]
    pages = []
    for index, description in enumerate(descriptions):
        embed = discord.Embed(title=f"🖥️ {ip_prefix}.x 사용 현황",
                              description=description, color=discord.Color.blue())
        mode = "모바일" if mobile else "표"
        embed.set_footer(text=f"페이지 {index + 1}/{len(descriptions)}  |  총 {len(entries)}개 IP  |  {mode} 보기")
        pages.append(embed)
    return pages


# ---------------------------------------------------------------------------
# 페이지네이션 뷰
# ---------------------------------------------------------------------------

class StatusView(discord.ui.View):
    def __init__(self, pages: list[discord.Embed], mobile_pages: list[discord.Embed] | None = None) -> None:
        super().__init__(timeout=120)
        self.table_pages = pages
        self.mobile_pages = mobile_pages or pages
        self.mobile = False
        self.pages = pages
        self.page = 0
        self._refresh_buttons()

    def _refresh_buttons(self) -> None:
        self.btn_layout.label = "표 보기" if self.mobile else "모바일 보기"
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

    @discord.ui.button(label="모바일 보기", style=discord.ButtonStyle.primary)
    async def btn_layout(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.mobile = not self.mobile
        self.pages = self.mobile_pages if self.mobile else self.table_pages
        self.page = 0
        self._refresh_buttons()
        try:
            await interaction.response.edit_message(embed=self.pages[0], view=self)
        except Exception:
            logger.exception("btn_layout edit_message 실패")
            if not interaction.response.is_done():
                await interaction.response.defer(ephemeral=True)
            await interaction.followup.send("❌ 보기 전환 중 오류가 발생했습니다.", ephemeral=True)

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
        name="/release <ip>",
        value=f"내 IP 등록을 해제합니다. 관리자는 다른 사람의 IP도 해제할 수 있습니다. 예: `/release {ip_prefix}.***`",
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
        value="전체 IP를 IP주소·이름·기기/등록일 열로 표시합니다. `모바일 보기` 버튼으로 세로 박스로 전환할 수 있습니다.",
        inline=False,
    )
    embed.add_field(
        name="/help",
        value="이 도움말을 표시합니다.",
        inline=False,
    )
    embed.add_field(name="/howtoconnect [ip]", value="인터넷 설정값을 복사용 코드 박스로 표시합니다. 설정 방법 보기로 사진 안내를 열 수 있습니다.", inline=False)
    embed.add_field(name="/recommend", value="미등록 IP 추천 목록에서 번호를 선택하면 본인 IP로 등록됩니다.", inline=False)
    embed.set_footer(text=f"허용 대역: {ip_prefix}.1 ~ {ip_prefix}.254  |  ✏️ 수동  🤖 자동")
    return embed

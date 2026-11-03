from __future__ import annotations

from pathlib import Path

import discord

GUIDE_ASSETS = Path(__file__).parent / 'assets' / 'connect'
GUIDE_STEPS = (
    ('① 이더넷 열기', '01-ethernet.png',
     '랜선을 연결하고 `Win + I`를 누르세요.\n'
     '**네트워크 및 인터넷**에서 사진의 빨간 칸 **이더넷**을 누르세요.'),
    ('② IP 할당 편집', '02-ip-edit.png',
     '사진의 빨간 칸처럼 **IP 할당** 옆 **편집**을 누르세요.'),
    ('③ 값 입력', '03-ipv4.png',
     '사진처럼 **수동**을 선택하고 **IPv4**를 켜세요.\n'
     '사진은 **221번 예시**입니다. **아래 본인 값**을 입력하고 **저장**하세요.\n'
     '서브넷 마스크 대신 **접두사 길이**를 물으면 `24`를 입력하세요.'),
)


def connection_values(prefix: str, ip: str | None = None) -> dict[str, str]:
    return {
        'IP 주소': ip or f'{prefix}.xxx',
        '서브넷 마스크': '255.255.255.0',
        '게이트웨이': f'{prefix}.1',
        '기본 설정 DNS': '8.8.8.8',
    }


def build_values_embed(prefix: str, ip: str | None = None) -> discord.Embed:
    return discord.Embed(
        description='\n'.join(
            f'{label}\n{copyable_value(label, value, ip)}'
            for label, value in connection_values(prefix, ip).items()),
        color=discord.Color.blue(),
    )


def copyable_value(label: str, value: str, ip: str | None) -> str:
    if label == 'IP 주소' and ip is None:
        return '사용할 IP 번호를 선택하세요.'
    return f'```\n{value}\n```'


def build_connect_embed(prefix: str, ip: str | None = None, step: int = 0) -> discord.Embed:
    title, filename, instruction = GUIDE_STEPS[step]
    embed = build_values_embed(prefix, ip)
    embed.title = f'🌐 유선 인터넷 연결 · {title}'
    embed.description = instruction
    for label, value in connection_values(prefix, ip).items():
        embed.add_field(name=label, value=copyable_value(label, value, ip), inline=False)
    if ip is None:
        embed.add_field(
            name='IP 번호 선택',
            value='아래에서 번호를 선택하거나, 등록한 번호로 `/howtoconnect ip:221`처럼 실행하세요.',
            inline=False,
        )
    embed.set_image(url=f'attachment://{filename}')
    embed.set_footer(text='사진은 아래 ① ② ③ 버튼으로 넘기세요.')
    return embed


class GuideHelpButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label='설정 방법 보기', row=3, style=discord.ButtonStyle.primary)

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.show_guide = True
        self.view.add_guide_controls()
        await interaction.response.edit_message(
            embed=self.view.embed(), attachments=[self.view.guide_file()], view=self.view)


class GuideStepButton(discord.ui.Button):
    def __init__(self, step: int):
        super().__init__(label=GUIDE_STEPS[step][0], row=3)
        self.step = step

    async def callback(self, interaction: discord.Interaction) -> None:
        self.view.guide_step = self.step
        self.view.refresh_guide_buttons()
        await interaction.response.edit_message(
            embed=self.view.embed(), attachments=[self.view.guide_file()], view=self.view)


class ConnectView(discord.ui.View):
    def __init__(self, prefix: str, ip: str | None = None, guide_step: int = 0, show_guide: bool = False):
        super().__init__(timeout=900)
        self.prefix = prefix
        self.ip = ip
        self.guide_step = guide_step
        self.show_guide = show_guide
        if show_guide:
            self.add_guide_controls()
        else:
            self.add_item(GuideHelpButton())

    def add_guide_controls(self) -> None:
        for item in list(self.children):
            if isinstance(item, (GuideHelpButton, GuideStepButton)):
                self.remove_item(item)
        for step in range(len(GUIDE_STEPS)):
            self.add_item(GuideStepButton(step))
        self.refresh_guide_buttons()

    def refresh_guide_buttons(self) -> None:
        for item in self.children:
            if isinstance(item, GuideStepButton):
                item.style = (discord.ButtonStyle.primary if item.step == self.guide_step
                              else discord.ButtonStyle.secondary)
                item.disabled = item.step == self.guide_step

    def guide_file(self) -> discord.File:
        return discord.File(GUIDE_ASSETS / GUIDE_STEPS[self.guide_step][1])

    def embed(self) -> discord.Embed:
        if not self.show_guide:
            return build_values_embed(self.prefix, self.ip)
        return build_connect_embed(self.prefix, self.ip, self.guide_step)

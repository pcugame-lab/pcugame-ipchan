from __future__ import annotations

from pathlib import Path

import discord

GUIDE_SOURCE = 'https://itservice.kangwon.ac.kr/itservice/bbs/784/detail.do?pstSn=56'
GUIDE_ASSETS = Path(__file__).parent / 'assets' / 'connect'
GUIDE_STEPS = (
    ('① 이더넷 열기', '01-ethernet.png',
     '랜선을 연결하고 `Win + I`를 누르세요.\n'
     '**네트워크 및 인터넷**에서 사진의 빨간 칸 **이더넷**을 누르세요.'),
    ('② IP 할당 편집', '02-ip-edit.png',
     '사진의 빨간 칸처럼 **IP 할당** 옆 **편집**을 누르세요.'),
    ('③ 값 입력', '03-ipv4.png',
     '사진처럼 **수동**을 선택하고 **IPv4**를 켜세요.\n'
     '아래 값을 같은 이름의 칸에 넣고 **저장**하세요.\n'
     '서브넷 마스크 대신 **접두사 길이**를 물으면 `24`를 입력하세요.'),
)


def connection_values(prefix: str, ip: str | None = None) -> dict[str, str]:
    return {
        'IP 주소': ip or f'{prefix}.xxx',
        '서브넷 마스크': '255.255.255.0',
        '게이트웨이': f'{prefix}.1',
        '기본 설정 DNS': '8.8.8.8',
    }


def build_connect_embed(prefix: str, ip: str | None = None, step: int = 0) -> discord.Embed:
    title, filename, instruction = GUIDE_STEPS[step]
    embed = discord.Embed(
        title=f'🌐 유선 인터넷 연결 · {title}',
        description=instruction,
        color=discord.Color.blue(),
    )
    for label, value in connection_values(prefix, ip).items():
        embed.add_field(name=label, value=f'`{value}`', inline=False)
    if ip is None:
        embed.add_field(
            name='IP 번호 선택',
            value='`xxx` 대신 사용할 번호가 필요합니다. 아래에서 선택하거나, 등록한 번호로 `/howtoconnect ip:221`처럼 실행하세요.',
            inline=False,
        )
    embed.add_field(name='화면 출처', value=f'[강원대학교 정보화본부]({GUIDE_SOURCE})', inline=False)
    embed.set_image(url=f'attachment://{filename}')
    embed.set_footer(text='사진은 아래 ① ② ③ 버튼으로 넘기세요. 항목 버튼을 누르면 복사할 값이 표시됩니다.')
    return embed


class ValueButton(discord.ui.Button):
    def __init__(self, label: str, value: str, needs_ip: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.secondary, row=0)
        self.value = value
        self.needs_ip = needs_ip

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.needs_ip:
            await interaction.response.send_message(
                '먼저 아래 목록에서 IP를 선택하거나 `/howtoconnect ip:221`처럼 본인 번호를 입력하세요.',
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f'```\n{self.value}\n```', ephemeral=True)


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
    def __init__(self, prefix: str, ip: str | None = None, guide_step: int = 0):
        super().__init__(timeout=900)
        self.prefix = prefix
        self.ip = ip
        self.guide_step = guide_step
        for label, value in connection_values(prefix, ip).items():
            self.add_item(ValueButton(label, value, needs_ip=label == 'IP 주소' and ip is None))
        self.add_item(ValueButton('접두사 길이', '24'))
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
        return build_connect_embed(self.prefix, self.ip, self.guide_step)

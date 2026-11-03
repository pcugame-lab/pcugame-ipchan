from __future__ import annotations

import discord

WINDOWS_HELP = 'https://support.microsoft.com/ko-kr/windows/experience/connectivity-networking/essential-network-settings-and-tasks-in-windows'


def connection_values(prefix: str, ip: str | None = None) -> dict[str, str]:
    return {
        'IP 주소': ip or f'{prefix}.xxx',
        '서브넷 마스크': '255.255.255.0',
        '게이트웨이': f'{prefix}.1',
        '기본 설정 DNS': '8.8.8.8',
    }


def build_connect_embed(prefix: str, ip: str | None = None) -> discord.Embed:
    embed = discord.Embed(
        title='🌐 Windows 유선 인터넷 연결 방법',
        description=(
            '**1. 랜선을 연결하고 설정 열기**\n'
            '`Win + I` → **네트워크 및 인터넷** → **이더넷**\n\n'
            '**2. IPv4를 수동으로 설정**\n'
            '**IP 할당** 옆 **편집** → **수동** → **IPv4 켬**\n'
            '아래 값을 같은 이름의 입력칸에 넣고 **저장**하세요.\n'
            'DNS 입력칸이 없으면 **DNS 서버 할당 → 편집 → 수동 → IPv4 켬**에서 입력하세요.'
        ),
        color=discord.Color.blue(),
    )
    for label, value in connection_values(prefix, ip).items():
        embed.add_field(name=label, value=f'`{value}`', inline=False)
    embed.add_field(
        name='서브넷 접두사 길이를 묻는 화면이라면',
        value='서브넷 마스크 대신 **서브넷 접두사 길이**가 나오면 `24`를 입력하세요.',
        inline=False,
    )
    embed.add_field(
        name='IP 주소의 xxx는 본인에게 배정된 번호',
        value=(
            ('본인 등록 IP를 표시했습니다. 다른 기기를 설정한다면 해당 기기의 IP를 지정하세요.\n' if ip else
             '`xxx`를 그대로 입력하지 마세요. `/status`로 확인하고 본인 IP를 `/register`로 등록하세요.\n')
            + '예: `/howtoconnect ip:221` → `' + prefix + '.221`\n'
            + '안내 조회만으로는 등록되지 않습니다. 추천 번호를 선택하면 본인 IP로 등록됩니다. Windows 설정은 직접 입력하세요.'
        ), inline=False,
    )
    embed.add_field(
        name='Windows 10 / 기존 IPv4 속성 창',
        value=(
            '`Win + R` → `ncpa.cpl` → **이더넷** 우클릭 → **속성** → '
            '**인터넷 프로토콜 버전 4(TCP/IPv4)** → **속성**\n'
            '**다음 IP 주소 사용**에 IP 주소·서브넷 마스크·**기본 게이트웨이**를, '
            '**다음 DNS 서버 주소 사용**의 **기본 설정 DNS 서버**에 `8.8.8.8`을 입력하세요.'
        ), inline=False,
    )
    embed.add_field(
        name='항목별 복사',
        value='아래 버튼을 누르면 값 하나만 표시됩니다. 코드 박스의 복사 기능이나 텍스트 선택으로 복사하세요.',
        inline=False,
    )
    embed.add_field(name='Windows 설정 안내', value=f'[Microsoft 공식 안내]({WINDOWS_HELP})', inline=False)
    embed.set_footer(text='Windows 버전에 따라 항목 이름과 위치가 조금 다를 수 있습니다.')
    return embed


class ValueButton(discord.ui.Button):
    def __init__(self, label: str, value: str, needs_ip: bool = False):
        super().__init__(label=label, style=discord.ButtonStyle.secondary)
        self.value = value
        self.needs_ip = needs_ip

    async def callback(self, interaction: discord.Interaction) -> None:
        if self.needs_ip:
            await interaction.response.send_message(
                'IP 주소의 `xxx`는 본인 번호로 바꿔야 합니다. '
                '`/howtoconnect ip:221`처럼 본인에게 배정된 IP 끝자리를 지정한 뒤 IP 주소 버튼을 눌러 주세요.',
                ephemeral=True,
            )
            return
        await interaction.response.send_message(f'```\n{self.value}\n```', ephemeral=True)


class ConnectView(discord.ui.View):
    def __init__(self, prefix: str, ip: str | None = None):
        super().__init__(timeout=900)
        for label, value in connection_values(prefix, ip).items():
            self.add_item(ValueButton(label, value, needs_ip=label == 'IP 주소' and ip is None))
        self.add_item(ValueButton('접두사 길이', '24'))

from __future__ import annotations

import logging
import discord
from app.connect import ConnectView, build_connect_embed
from app.security import check_all_permissions

logger = logging.getLogger(__name__)
MISSING_RANGE = '마지막 옥텟 정보가 입력되어 있지 않아서 추천은 불가능하다'


def available_ips(config, registry):
    if config.ip_last_octet_range is None:
        return []
    start, end = config.ip_last_octet_range
    return [f'{config.ip_prefix}.{n}' for n in range(start, end + 1)
            if n != 1 and registry.find_ip_owner(f'{config.ip_prefix}.{n}') is None]


def add_recommendation_info(embed, config, registry):
    if config.ip_last_octet_range is None:
        text = MISSING_RANGE
    else:
        count = len(available_ips(config, registry))
        start, end = config.ip_last_octet_range
        text = (f'끝자리 {start}~{end} 중 등록 데이터상 미등록 IP **{count}개**\n'
                '아래에서 번호를 선택하면 **본인 IP로 즉시 등록**됩니다.\n'
                '등록부 기준이며 실제 네트워크 사용 여부를 확인한 결과는 아닙니다.' if count else
                f'끝자리 {start}~{end} 범위에 등록 데이터상 비어 있는 IP가 없습니다.')
    embed.add_field(name='사용할 IP 추천', value=text, inline=False)


class RecommendSelect(discord.ui.Select):
    def __init__(self, addresses):
        super().__init__(placeholder='사용할 IP 선택 → 내 IP로 등록', row=1,
                         options=[discord.SelectOption(label=ip.rsplit('.', 1)[-1], value=ip,
                                                       description=ip) for ip in addresses])
        self.offered = set(addresses)

    async def callback(self, interaction):
        await self.view.claim(interaction, self.values[0], self.offered)


class RecommendView(ConnectView):
    def __init__(self, bot, owner_id, ip=None):
        super().__init__(bot.config.ip_prefix, ip)
        self.bot = bot
        self.owner_id = owner_id
        self.ip = ip
        self.page = 0
        self.addresses = available_ips(bot.config, bot.registry)
        self.refresh()

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('본인이 실행한 명령에서 IP를 선택해 주세요.', ephemeral=True)
            return False
        return True

    def refresh(self):
        for item in list(self.children):
            if isinstance(item, RecommendSelect):
                self.remove_item(item)
        self.page = min(self.page, max(0, (len(self.addresses) - 1) // 25))
        chunk = self.addresses[self.page * 25:(self.page + 1) * 25]
        if chunk:
            self.add_item(RecommendSelect(chunk))
        self.prev.disabled = self.page == 0
        self.next.disabled = (self.page + 1) * 25 >= len(self.addresses)
        if len(self.addresses) <= 25:
            for item in (self.prev, self.next):
                if item in self.children:
                    self.remove_item(item)

    def embed(self):
        embed = build_connect_embed(self.bot.config.ip_prefix, self.ip)
        add_recommendation_info(embed, self.bot.config, self.bot.registry)
        return embed

    @discord.ui.button(label='추천 이전', row=2, style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, button):
        self.page = max(0, self.page - 1)
        self.refresh()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    @discord.ui.button(label='추천 다음', row=2, style=discord.ButtonStyle.secondary)
    async def next(self, interaction, button):
        self.page += 1
        self.refresh()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def claim(self, interaction, address, offered):
        error, _ = check_all_permissions(interaction, self.bot.config.guilds)
        if error or interaction.user.id != self.owner_id:
            await interaction.response.send_message(error or '본인이 실행한 명령에서 선택해 주세요.', ephemeral=True)
            return
        # No awaits between availability validation and registry.register: all bot/web
        # writers run synchronously on the same event loop, including persistence.
        if address not in offered or address not in available_ips(self.bot.config, self.bot.registry):
            self.addresses = available_ips(self.bot.config, self.bot.registry)
            self.refresh()
            await interaction.response.edit_message(
                content='선택한 IP는 더 이상 등록할 수 없습니다. 남은 번호에서 다시 선택해 주세요.',
                embed=self.embed(), view=self)
            return
        user = interaction.user
        display = getattr(user, 'display_name', None) or getattr(user, 'global_name', None) or user.name
        try:
            success, message = self.bot.registry.register(
                user_id=user.id, username=str(user), display_name=display,
                address=address, person_name=display, source='manual')
        except Exception:
            logger.exception('추천 IP 등록 저장 실패: user_id=%s ip=%s', user.id, address)
            await interaction.response.send_message('등록을 저장하지 못했습니다. 관리자에게 문의해 주세요.', ephemeral=True)
            return
        if not success:
            await interaction.response.send_message(message, ephemeral=True)
            return
        logger.info('추천 IP 선택 등록: user_id=%s ip=%s', user.id, address)
        embed = build_connect_embed(self.bot.config.ip_prefix, address)
        embed.insert_field_at(0, name='✅ 내 IP로 등록 완료', value=f'`{address}`를 본인 IP로 등록했습니다. 아래 값으로 Windows를 설정하세요.', inline=False)
        await interaction.response.edit_message(content=None, embed=embed,
                                                view=ConnectView(self.bot.config.ip_prefix, address))
        self.stop()

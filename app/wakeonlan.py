from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
import time

import discord

from app.config import WakeTarget
from app.security import check_all_permissions

logger = logging.getLogger(__name__)


def send_magic_packet(target: WakeTarget, prefix: str) -> None:
    network = ipaddress.IPv4Network(f'{prefix}.0/24')
    if ipaddress.IPv4Address(target.ip) not in network:
        raise ValueError('허용 대역 밖의 대상입니다.')
    mac = bytes.fromhex(target.mac.replace(':', ''))
    if len(mac) != 6 or mac[0] & 1 or mac == bytes(6):
        raise ValueError('유효한 PC MAC 주소가 아닙니다.')
    packet = b'\xff' * 6 + mac * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sender:
        sender.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sender.settimeout(2)
        for _ in range(3):
            if sender.sendto(packet, (str(network.broadcast_address), 9)) != len(packet):
                raise OSError('Wake-on-LAN 패킷을 모두 보내지 못했습니다.')


class WakeCooldown(Exception):
    pass


class WakeService:
    def __init__(self):
        self.sent_at: dict[str, float] = {}

    async def wake(self, target: WakeTarget, prefix: str) -> None:
        now = time.monotonic()
        previous = self.sent_at.get(target.mac)
        if previous is not None and now - previous < 30:
            raise WakeCooldown('방금 켜기 요청을 보냈습니다. 30초 후 다시 시도하세요.')
        # Reserve before yielding so simultaneous interactions share the cooldown.
        self.sent_at[target.mac] = now
        try:
            await asyncio.to_thread(send_magic_packet, target, prefix)
        except Exception:
            self.sent_at.pop(target.mac, None)
            raise


class WakeSelect(discord.ui.Select):
    def __init__(self, targets: tuple[WakeTarget, ...]):
        super().__init__(
            placeholder='켤 PC를 선택하세요',
            options=[discord.SelectOption(
                label=f'{target.ip.rsplit(".", 1)[-1]} · {target.name}',
                value=target.ip, description=target.ip,
            ) for target in targets],
        )
        self.offered = {target.ip: target for target in targets}

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.view.wake(interaction, self.values[0], self.offered)


class WakeView(discord.ui.View):
    def __init__(self, bot, owner_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.owner_id = owner_id
        self.add_item(WakeSelect(bot.config.wol_targets))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('본인이 실행한 명령에서 PC를 선택해 주세요.', ephemeral=True)
            return False
        return True

    async def wake(self, interaction: discord.Interaction, address: str, offered: dict[str, WakeTarget]) -> None:
        error, _ = check_all_permissions(interaction, self.bot.config.guilds)
        if error or interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                error or '본인이 실행한 명령에서 PC를 선택해 주세요.', ephemeral=True)
            return
        current = {target.ip: target for target in self.bot.config.wol_targets}
        target = current.get(address)
        if target is None or offered.get(address) != target:
            await interaction.response.send_message('대상 PC 설정이 바뀌었습니다. `/wakeonlan`을 다시 실행하세요.', ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.wake_service.wake(target, self.bot.config.ip_prefix)
        except WakeCooldown as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception:
            logger.exception('Wake-on-LAN 전송 실패: actor_id=%s ip=%s', interaction.user.id, target.ip)
            await interaction.followup.send('❌ 켜기 요청을 보내지 못했습니다. 잠시 후 다시 시도하세요.', ephemeral=True)
            return
        logger.info('Wake-on-LAN 전송 완료: actor_id=%s ip=%s', interaction.user.id, target.ip)
        await interaction.followup.send(
            f'✅ `{target.ip}`에 켜기 요청을 보냈습니다. 잠시 후 PC에 접속해 보세요.', ephemeral=True)

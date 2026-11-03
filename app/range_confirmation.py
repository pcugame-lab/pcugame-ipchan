from __future__ import annotations

import discord

WARNING = '할당된 IP 범위 밖입니다... 진짜 괜찮아요?'


def outside_range(address: str, bounds: tuple[int, int] | None) -> bool:
    if bounds is None:
        return False
    return not bounds[0] <= int(address.rsplit('.', 1)[-1]) <= bounds[1]


def warning_text(address: str, bounds: tuple[int, int]) -> str:
    return f'⚠️ **{WARNING}**\n입력 IP: `{address}` · 할당된 끝자리 범위: `{bounds[0]}~{bounds[1]}`'


class RangeConfirmationView(discord.ui.View):
    def __init__(self, owner_id, continue_action):
        super().__init__(timeout=120)
        self.owner_id = owner_id
        self.continue_action = continue_action
        self.finished = False

    async def interaction_check(self, interaction):
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message('명령을 실행한 본인만 확인할 수 있습니다.', ephemeral=True)
            return False
        return True

    @discord.ui.button(label='네, 계속할게요', style=discord.ButtonStyle.danger)
    async def confirm(self, interaction, button):
        if not await self.interaction_check(interaction):
            return
        if self.finished:
            await interaction.response.send_message('이미 처리한 요청입니다.', ephemeral=True)
            return
        self.finished = True
        await self.continue_action(interaction)
        await interaction.edit_original_response(content='범위 밖 IP 사용을 확인했습니다.', view=None)
        self.stop()

    @discord.ui.button(label='취소', style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        if not await self.interaction_check(interaction):
            return
        if self.finished:
            await interaction.response.send_message('이미 처리한 요청입니다.', ephemeral=True)
            return
        self.finished = True
        await interaction.response.edit_message(content='취소했습니다.', view=None)
        self.stop()

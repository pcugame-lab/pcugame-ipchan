from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands

from app.config import Config
from app.data import IPRegistry
from app.formatter import StatusView, build_help_embed, build_status_pages
from app.security import check_all_permissions
from app.recommend import RecommendView
from app.range_confirmation import RangeConfirmationView, outside_range, warning_text
from app.tokens import TokenStore
from app.wakeonlan import WakeService, WakeView

logger = logging.getLogger(__name__)

_LABEL_MAX = 50


# ---------------------------------------------------------------------------
# 검증 헬퍼
# ---------------------------------------------------------------------------

def _expand_ip(ip: str, ip_prefix: str) -> str:
    """숫자만 입력된 경우 prefix를 붙여 완전한 IP로 변환."""
    s = ip.strip()
    if s.isdigit():
        return f"{ip_prefix}.{s}"
    return s


def _validate_ip(ip: str, ip_prefix: str) -> Optional[str]:
    """유효하면 None, 오류 시 오류 메시지 반환."""
    parts = ip.strip().split(".")
    if len(parts) != 4:
        return "올바른 IPv4 형식이 아닙니다. 예: `203.250.133.100`"
    expected = ip_prefix.split(".")
    for got, exp in zip(parts[:3], expected):
        if got != exp:
            return f"허용된 대역의 IP만 등록할 수 있습니다. (`{ip_prefix}.x`)"
    try:
        last = int(parts[3])
    except ValueError:
        return "마지막 옥텟이 숫자가 아닙니다."
    if not (1 <= last <= 254):
        return "마지막 옥텟은 1~254 사이여야 합니다."
    return None


def _validate_label(value: str, field: str) -> Optional[str]:
    v = value.strip()
    if not v:
        return f"{field}은(는) 빈 값일 수 없습니다."
    if len(v) > _LABEL_MAX:
        return f"{field}은(는) {_LABEL_MAX}자 이하여야 합니다."
    return None


# ---------------------------------------------------------------------------
# Claim 링크 버튼 뷰 (URL 버튼 — Discord 인터랙션 불필요)
# ---------------------------------------------------------------------------

class ClaimView(discord.ui.View):
    def __init__(self, claim_url: str) -> None:
        super().__init__(timeout=None)
        self.add_item(discord.ui.Button(
            label="현재 IP 자동 등록",
            style=discord.ButtonStyle.link,
            url=claim_url,
            emoji="🔗",
        ))


# ---------------------------------------------------------------------------
# Bot
# ---------------------------------------------------------------------------

class LabIPBot(discord.Client):
    def __init__(self, config: Config, registry: IPRegistry, token_store: TokenStore) -> None:
        intents = discord.Intents.default()
        super().__init__(intents=intents)

        self.config = config
        self.registry = registry
        self.token_store = token_store
        self.tree = app_commands.CommandTree(self)
        self.wake_service = WakeService()

        self._register_commands()

    # ------------------------------------------------------------------ #
    # 슬래시 커맨드 등록                                                   #
    # ------------------------------------------------------------------ #

    def _register_commands(self) -> None:
        for guild_cfg in self.config.guilds:
            guild_obj = discord.Object(id=guild_cfg.guild_id)

            @self.tree.command(
                name="register",
                description="IP를 등록합니다. ip 생략 시 자동 감지 링크를 발급합니다.",
                guild=guild_obj,
            )
            @app_commands.describe(
                ip="직접 입력할 IP 주소 (생략하면 자동 감지 링크 발급)",
                device="기기 이름 (예: 랩탑, 데스크탑)",
                person="사람 이름 (예: 홍길동)",
            )
            async def cmd_register(
                interaction: discord.Interaction,
                ip: Optional[str] = None,
                device: Optional[str] = None,
                person: Optional[str] = None,
            ) -> None:
                await self._handle_register(interaction, ip, device, person)

            @self.tree.command(
                name="release",
                description="등록된 특정 IP를 해제합니다.",
                guild=guild_obj,
            )
            @app_commands.describe(ip="해제할 IP 주소 또는 사람 이름")
            async def cmd_release(interaction: discord.Interaction, ip: str) -> None:
                await self._handle_release(interaction, ip)

            @self.tree.command(
                name="change",
                description="등록된 IP의 기기 이름 또는 사람 이름을 수정합니다.",
                guild=guild_obj,
            )
            @app_commands.describe(
                ip="수정할 IP 주소",
                device="새 기기 이름",
                person="새 사람 이름",
            )
            async def cmd_change(
                interaction: discord.Interaction,
                ip: str,
                device: Optional[str] = None,
                person: Optional[str] = None,
            ) -> None:
                await self._handle_change(interaction, ip, device, person)

            @self.tree.command(
                name="status",
                description="현재 등록된 모든 IP와 메타데이터를 표시합니다.",
                guild=guild_obj,
            )
            async def cmd_status(interaction: discord.Interaction) -> None:
                await self._handle_status(interaction)

            @self.tree.command(
                name="howtoconnect",
                description="Windows에서 유선 인터넷 IPv4를 설정하는 방법을 안내합니다.",
                guild=guild_obj,
            )
            @app_commands.describe(ip="설정할 본인 IP (예: 221). 생략하면 본인 등록 IP가 하나일 때 자동 표시")
            async def cmd_howtoconnect(interaction: discord.Interaction, ip: Optional[str] = None) -> None:
                await self._handle_howtoconnect(interaction, ip)

            @self.tree.command(name="recommend", description="미등록 IP를 추천받고 선택한 번호를 내 IP로 등록합니다.", guild=guild_obj)
            async def cmd_recommend(interaction: discord.Interaction) -> None:
                await self._handle_howtoconnect(interaction)

            @self.tree.command(name="wakeonlan", description="켤 PC를 선택해 원격으로 켜기 요청을 보냅니다.", guild=guild_obj)
            async def cmd_wakeonlan(interaction: discord.Interaction) -> None:
                await self._handle_wakeonlan(interaction)

            @self.tree.command(
                name="help",
                description="봇 사용법을 표시합니다.",
                guild=guild_obj,
            )
            async def cmd_help(interaction: discord.Interaction) -> None:
                await self._handle_help(interaction)

        logger.info(
            f"커맨드 등록 대상 길드 {len(self.config.guilds)}개: "
            + ", ".join(str(g.guild_id) for g in self.config.guilds)
        )

    # ------------------------------------------------------------------ #
    # Discord 이벤트                                                       #
    # ------------------------------------------------------------------ #

    async def setup_hook(self) -> None:
        for guild_cfg in self.config.guilds:
            guild_obj = discord.Object(id=guild_cfg.guild_id)
            synced = await self.tree.sync(guild=guild_obj)
            logger.info(f"슬래시 커맨드 동기화: {len(synced)}개 → guild={guild_cfg.guild_id}")

    async def on_ready(self) -> None:
        logger.info(f"봇 준비 완료: {self.user} (id={self.user.id if self.user else '?'})")
        logger.info(f"허용 IP 대역: {self.config.ip_prefix}.1 ~ {self.config.ip_prefix}.254")
        logger.info(f"웹서버 공개 URL: {self.config.web_base_url}")
        logger.info(f"현재 등록 수: {self.registry.count()}개")

    # ------------------------------------------------------------------ #
    # /register                                                            #
    # ------------------------------------------------------------------ #

    async def _handle_register(
        self,
        interaction: discord.Interaction,
        ip: Optional[str],
        device: Optional[str],
        person: Optional[str],
        _range_confirmed: bool = False,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            error_msg, _ = check_all_permissions(interaction, self.config.guilds)
            if error_msg:
                await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
                return

            device_label = device.strip() if device else ""
            person_name = person.strip() if person else ""

            # device/person 값이 들어온 경우만 길이 검증
            if device_label:
                err = _validate_label(device_label, "기기 이름")
                if err:
                    await interaction.followup.send(f"❌ {err}", ephemeral=True)
                    return
            if person_name:
                err = _validate_label(person_name, "사람 이름")
                if err:
                    await interaction.followup.send(f"❌ {err}", ephemeral=True)
                    return

            # 공통: Discord 표시 이름 — person 미입력 시 기본값으로 사용
            user = interaction.user
            display_name = (
                user.display_name if isinstance(user, discord.Member)
                else (user.global_name or user.name)
            )
            if not person_name:
                person_name = display_name

            # ── IP 직접 입력: 수동 등록 ──────────────────────────────────────
            if ip is not None:
                ip = _expand_ip(ip, self.config.ip_prefix)
                validation_error = _validate_ip(ip, self.config.ip_prefix)
                if validation_error:
                    await interaction.followup.send(f"❌ {validation_error}", ephemeral=True)
                    return

                if not _range_confirmed and outside_range(ip, self.config.ip_last_octet_range):
                    async def proceed(confirm_interaction):
                        await self._handle_register(confirm_interaction, ip, device, person, _range_confirmed=True)
                    await interaction.followup.send(
                        warning_text(ip, self.config.ip_last_octet_range),
                        view=RangeConfirmationView(interaction.user.id, proceed), ephemeral=True)
                    return

                owner = self.registry.find_ip_owner(ip)
                admin_override = self.config.is_admin(user.id) and owner is not None and owner.user_id != user.id
                target = owner if admin_override else None
                success, message = self.registry.register(
                    user_id=target.user_id if target else user.id,
                    username=target.username if target else str(user),
                    display_name=target.display_name if target else display_name,
                    address=ip,
                    device_label=device_label,
                    person_name=(person_name if person is not None else "") if admin_override else person_name,
                    source="manual",
                )
                if success:
                    logger.info("수동 등록: ip=%s actor_id=%s owner_id=%s admin_override=%s",
                                ip, user.id, target.user_id if target else user.id, admin_override)
                    if admin_override:
                        message += " (관리자 권한)"
                    await interaction.followup.send(f"✅ {message}", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ {message}", ephemeral=True)
                return

            # ── IP 생략: 자동 감지 링크 발급 ─────────────────────────────────
            token_str = self.token_store.create(
                user_id=user.id,
                discord_username=str(user),
                discord_display_name=display_name,
                device_label=device_label,
                person_name=person_name,
                ttl_seconds=self.config.token_ttl_seconds,
            )
            claim_url = f"{self.config.web_base_url}/ip/claim?token={token_str}"
            ttl_min = self.config.token_ttl_seconds // 60

            embed = discord.Embed(
                title="🔗 현재 IP 자동 등록",
                description=(
                    "아래 버튼을 눌러 현재 접속 중인 네트워크의 IP를 자동으로 등록하세요.\n"
                    f"링크는 **{ttl_min}분** 후 만료되며, 한 번만 사용할 수 있습니다."
                ),
                color=discord.Color.blurple(),
            )
            if device_label or person_name:
                embed.add_field(
                    name="저장될 정보",
                    value=(
                        f"기기: {device_label or '(미지정)'}\n"
                        f"사람: {person_name or '(미지정)'}"
                    ),
                    inline=False,
                )
            embed.set_footer(text="버튼 클릭 시 브라우저에서 현재 IP가 자동 감지됩니다.")

            view = ClaimView(claim_url)
            await interaction.followup.send(embed=embed, view=view, ephemeral=True)
            logger.info(f"Claim 링크 발급: user={user.id} ttl={self.config.token_ttl_seconds}s")

        except Exception:
            logger.exception("_handle_register 처리 중 예외 발생")
            await interaction.followup.send("❌ 내부 오류가 발생했습니다. 잠시 후 다시 시도하세요.", ephemeral=True)

    # ------------------------------------------------------------------ #
    # /release                                                             #
    # ------------------------------------------------------------------ #

    async def _handle_release(self, interaction: discord.Interaction, ip: str) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            error_msg, _ = check_all_permissions(interaction, self.config.guilds)
            if error_msg:
                await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
                return

            ip = _expand_ip(ip, self.config.ip_prefix)
            validation_error = _validate_ip(ip, self.config.ip_prefix)
            if validation_error and "." not in ip and not ip.strip().isdigit():
                success, message = self.registry.release_by_person(
                    ip.strip(), user_id=None if self.config.is_admin(interaction.user.id) else interaction.user.id)
                if success:
                    logger.info("이름으로 IP 해제: actor_id=%s name=%s", interaction.user.id, ip.strip())
                await interaction.followup.send(f"{'✅' if success else '❌'} {message}", ephemeral=True)
                return
            if validation_error:
                await interaction.followup.send(f"❌ {validation_error}", ephemeral=True)
                return

            user = interaction.user
            owner = self.registry.find_ip_owner(ip)
            admin_override = (
                self.config.is_admin(user.id)
                and owner is not None
                and owner.user_id != user.id
            )
            target_user_id = owner.user_id if admin_override else user.id
            if self.config.is_admin(user.id) and owner is None:
                await interaction.followup.send("❌ 등록되지 않은 IP입니다.", ephemeral=True)
                return
            success, message = self.registry.release(target_user_id, ip)
            if success:
                logger.info(
                    "IP 해제: ip=%s actor_id=%s owner_id=%s admin_override=%s",
                    ip, user.id, target_user_id, admin_override,
                )
                if admin_override:
                    message += " (관리자 권한)"
                await interaction.followup.send(f"✅ {message}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)

        except Exception:
            logger.exception("_handle_release 처리 중 예외 발생")
            await interaction.followup.send("❌ 내부 오류가 발생했습니다. 잠시 후 다시 시도하세요.", ephemeral=True)

    # ------------------------------------------------------------------ #
    # /change                                                              #
    # ------------------------------------------------------------------ #

    async def _handle_change(
        self,
        interaction: discord.Interaction,
        ip: str,
        device: Optional[str],
        person: Optional[str],
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            error_msg, _ = check_all_permissions(interaction, self.config.guilds)
            if error_msg:
                await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
                return

            if device is None and person is None:
                await interaction.followup.send(
                    "❌ `device` 또는 `person` 중 하나 이상 입력하세요.", ephemeral=True
                )
                return

            ip = _expand_ip(ip, self.config.ip_prefix)
            validation_error = _validate_ip(ip, self.config.ip_prefix)
            if validation_error:
                await interaction.followup.send(f"❌ {validation_error}", ephemeral=True)
                return

            device_label: Optional[str] = None
            person_name: Optional[str] = None

            if device is not None:
                device_label = device.strip()
                err = _validate_label(device_label, "기기 이름")
                if err:
                    await interaction.followup.send(f"❌ {err}", ephemeral=True)
                    return

            if person is not None:
                person_name = person.strip()
                err = _validate_label(person_name, "사람 이름")
                if err:
                    await interaction.followup.send(f"❌ {err}", ephemeral=True)
                    return

            user = interaction.user
            owner = self.registry.find_ip_owner(ip)
            admin_override = self.config.is_admin(user.id) and owner is not None and owner.user_id != user.id
            target_user_id = owner.user_id if admin_override else user.id
            success, message = self.registry.update_labels(
                user_id=target_user_id,
                address=ip,
                device_label=device_label,
                person_name=person_name,
            )
            if success:
                logger.info("레이블 변경: ip=%s actor_id=%s owner_id=%s admin_override=%s",
                            ip, user.id, target_user_id, admin_override)
                if admin_override:
                    message += " (관리자 권한)"
                await interaction.followup.send(f"✅ {message}", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ {message}", ephemeral=True)

        except Exception:
            logger.exception("_handle_change 처리 중 예외 발생")
            await interaction.followup.send("❌ 내부 오류가 발생했습니다. 잠시 후 다시 시도하세요.", ephemeral=True)

    # ------------------------------------------------------------------ #
    # /status                                                              #
    # ------------------------------------------------------------------ #

    async def _handle_status(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        try:
            error_msg, _ = check_all_permissions(interaction, self.config.guilds)
            if error_msg:
                await interaction.followup.send(f"❌ {error_msg}", ephemeral=True)
                return

            entries = self.registry.get_all_entries()
            pages = build_status_pages(entries, self.config.ip_prefix)
            mobile_pages = build_status_pages(entries, self.config.ip_prefix, mobile=True)
            view = StatusView(pages, mobile_pages)
            await interaction.followup.send(embed=pages[0], view=view, ephemeral=True)

        except Exception:
            logger.exception("_handle_status 처리 중 예외 발생")
            await interaction.followup.send("❌ 내부 오류가 발생했습니다. 잠시 후 다시 시도하세요.", ephemeral=True)

    # ------------------------------------------------------------------ #
    # /help                                                                #
    # ------------------------------------------------------------------ #

    async def _handle_howtoconnect(self, interaction: discord.Interaction, ip: Optional[str] = None, _range_confirmed: bool = False) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            error, _ = check_all_permissions(interaction, self.config.guilds)
            if error:
                await interaction.followup.send(f"❌ {error}", ephemeral=True)
                return
            if ip is not None:
                ip = _expand_ip(ip, self.config.ip_prefix)
                error = _validate_ip(ip, self.config.ip_prefix)
                if error:
                    await interaction.followup.send(f"❌ {error}", ephemeral=True)
                    return
            else:
                own_ips = self.registry.get_user_ips(interaction.user.id)
                ip = own_ips[0].address if len(own_ips) == 1 else None
            if ip is not None and not _range_confirmed and outside_range(ip, self.config.ip_last_octet_range):
                async def proceed(confirm_interaction):
                    await self._handle_howtoconnect(confirm_interaction, ip, _range_confirmed=True)
                await interaction.followup.send(
                    warning_text(ip, self.config.ip_last_octet_range),
                    view=RangeConfirmationView(interaction.user.id, proceed), ephemeral=True)
                return
            view = RecommendView(self, interaction.user.id, ip)
            await interaction.followup.send(embed=view.embed(), view=view, ephemeral=True)
        except Exception:
            logger.exception("_handle_howtoconnect 처리 중 예외 발생")
            await interaction.followup.send("❌ 안내를 불러오지 못했습니다. 잠시 후 다시 시도하세요.", ephemeral=True)

    async def _handle_wakeonlan(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        error, _ = check_all_permissions(interaction, self.config.guilds)
        if error:
            await interaction.followup.send(f'❌ {error}', ephemeral=True)
            return
        if not self.config.wol_targets:
            await interaction.followup.send('켤 PC가 설정되지 않았습니다. 관리자에게 문의하세요.', ephemeral=True)
            return
        embed = discord.Embed(title='💡 PC 켜기', description='켤 PC를 선택하세요.', color=discord.Color.blue())
        await interaction.followup.send(embed=embed, view=WakeView(self, interaction.user.id), ephemeral=True)

    async def _handle_help(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        try:
            embed = build_help_embed(self.config.ip_prefix)
            await interaction.followup.send(embed=embed, ephemeral=True)
        except Exception:
            logger.exception("_handle_help 처리 중 예외 발생")
            await interaction.followup.send("❌ 내부 오류가 발생했습니다. 잠시 후 다시 시도하세요.", ephemeral=True)

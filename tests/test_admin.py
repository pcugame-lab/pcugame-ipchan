import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.bot import LabIPBot
from app.config import load_config
from app.data import IPRegistry

ADMIN = 862217265512710154
ENV = {"DISCORD_TOKEN": "test", "GUILD_1_ID": "1", "GUILD_1_CHANNEL_ID": "2",
       "IP_PREFIX": "203.250.133", "ADMIN_USER_IDS": str(ADMIN)}

class ConfigTests(unittest.TestCase):
    def test_admin_parsing(self):
        for raw, expected in [("", frozenset()), (str(ADMIN), frozenset([ADMIN])),
                              (f" {ADMIN}, 123, {ADMIN} ", frozenset([ADMIN, 123]))]:
            with self.subTest(raw=raw), patch.dict(os.environ, dict(ENV, ADMIN_USER_IDS=raw), clear=True):
                self.assertEqual(load_config().admin_user_ids, expected)

    def test_bad_admin_ids_fail_closed(self):
        for raw in ["abc", "-1", "0", "1,", "1.5", str(2**64)]:
            with self.subTest(raw=raw), patch.dict(os.environ, dict(ENV, ADMIN_USER_IDS=raw), clear=True):
                with self.assertRaises(ValueError):
                    load_config()

class ReleaseTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name)/"state.json")
        self.registry = IPRegistry(self.path)
        self.registry.register(111, "owner", "Owner", "203.250.133.240")
        self.registry.register(111, "owner", "Owner", "203.250.133.241")
        with patch.dict(os.environ, ENV, clear=True):
            self.config = load_config()
        self.bot = LabIPBot(self.config, self.registry, None)

    async def asyncTearDown(self):
        await self.bot.close()
        self.tmp.cleanup()

    def interaction(self, user_id, guild=1, channel=2):
        return SimpleNamespace(user=SimpleNamespace(id=user_id), guild_id=guild, channel_id=channel,
                               response=SimpleNamespace(defer=AsyncMock()),
                               followup=SimpleNamespace(send=AsyncMock()))

    async def test_admin_can_release_other_owner_and_persist(self):
        i = self.interaction(ADMIN)
        with self.assertLogs("app.bot", level="INFO") as logs:
            await self.bot._handle_release(i, "240")
        self.assertIsNone(IPRegistry(self.path).find_ip_owner("203.250.133.240"))
        self.assertEqual(IPRegistry(self.path).find_ip_owner("203.250.133.241").user_id, 111)
        self.assertIn("actor_id="+str(ADMIN), logs.output[0])
        self.assertIn("owner_id=111", logs.output[0])
        self.assertIn("관리자 권한", i.followup.send.call_args.args[0])

    async def test_nonadmin_cannot_release_other_owner(self):
        i = self.interaction(222)
        before = Path(self.path).read_bytes()
        await self.bot._handle_release(i, "240")
        self.assertEqual(before, Path(self.path).read_bytes())
        self.assertTrue(i.followup.send.call_args.args[0].startswith("❌"))

    async def test_owner_can_release(self):
        i = self.interaction(111)
        await self.bot._handle_release(i, "203.250.133.240")
        self.assertIsNone(self.registry.find_ip_owner("203.250.133.240"))
        self.assertTrue(i.followup.send.call_args.args[0].startswith("✅"))

    async def test_admin_missing_ip_does_not_mutate(self):
        i = self.interaction(ADMIN)
        before = Path(self.path).read_bytes()
        await self.bot._handle_release(i, "242")
        self.assertEqual(before, Path(self.path).read_bytes())
        self.assertIn("등록되지 않은", i.followup.send.call_args.args[0])

    async def test_admin_still_subject_to_guild_channel_and_ip_validation(self):
        for guild, channel, ip in [(99,2,"240"), (1,99,"240"), (1,2,"192.168.1.240"), (1,2,"255")]:
            with self.subTest(guild=guild,channel=channel,ip=ip):
                i = self.interaction(ADMIN, guild, channel)
                before = Path(self.path).read_bytes()
                await self.bot._handle_release(i, ip)
                self.assertEqual(before, Path(self.path).read_bytes())
                self.assertTrue(i.followup.send.call_args.args[0].startswith("❌"))

    async def test_admin_still_subject_to_role_check(self):
        from dataclasses import replace
        from app.config import GuildConfig
        self.bot.config = replace(self.config, guilds=(GuildConfig(1,2,333),))
        i = self.interaction(ADMIN)
        await self.bot._handle_release(i, "240")
        self.assertEqual(self.registry.count(), 2)
        self.assertTrue(i.followup.send.call_args.args[0].startswith("❌"))

    async def test_admin_can_change_other_owner_and_persist(self):
        i = self.interaction(ADMIN)
        await self.bot._handle_change(i, "240", "수정 기기", "수정 이름")
        registry = IPRegistry(self.path)
        self.assertEqual(registry.find_ip_owner("203.250.133.240").user_id, 111)
        entry = registry.get_user_ips(111)[0]
        self.assertEqual((entry.device_label, entry.person_name), ("수정 기기", "수정 이름"))
        self.assertIn("관리자 권한", i.followup.send.call_args.args[0])

    async def test_nonadmin_cannot_change_other_owner(self):
        before = Path(self.path).read_bytes()
        i = self.interaction(222)
        await self.bot._handle_change(i, "240", "수정 기기", None)
        self.assertEqual(Path(self.path).read_bytes(), before)
        self.assertTrue(i.followup.send.call_args.args[0].startswith("❌"))

    async def test_admin_register_updates_without_taking_ownership(self):
        i = self.interaction(ADMIN)
        i.user.name = "admin"
        i.user.global_name = "Admin"
        await self.bot._handle_register(i, "240", "새 기기", None)
        registry = IPRegistry(self.path)
        owner = registry.find_ip_owner("203.250.133.240")
        self.assertEqual((owner.user_id, owner.display_name), (111, "Owner"))
        self.assertEqual(registry.get_user_ips(111)[0].device_label, "새 기기")
        self.assertEqual(registry.count(), 2)
        self.assertIn("관리자 권한", i.followup.send.call_args.args[0])

    async def test_admin_change_still_validates_input(self):
        for guild, channel, ip, device in [(99,2,"240","ok"), (1,99,"240","ok"),
                                          (1,2,"192.168.1.240","ok"), (1,2,"240","")]:
            i = self.interaction(ADMIN, guild, channel)
            before = Path(self.path).read_bytes()
            await self.bot._handle_change(i, ip, device, None)
            self.assertEqual(Path(self.path).read_bytes(), before)
            self.assertTrue(i.followup.send.call_args.args[0].startswith("❌"))

if __name__ == "__main__":
    unittest.main()


class NameReleaseTests(ReleaseTests):
    async def test_name_release_only_affects_own_ips(self):
        self.registry.register(222, 'other', 'Other', '203.250.133.242', person_name='Same')
        self.registry.update_labels(111, '203.250.133.240', person_name='Same')
        i = self.interaction(111)
        await self.bot._handle_release(i, 'Same')
        self.assertIsNone(self.registry.find_ip_owner('203.250.133.240'))
        self.assertEqual(self.registry.find_ip_owner('203.250.133.242').user_id, 222)

    async def test_admin_name_release(self):
        self.registry.update_labels(111, '203.250.133.240', person_name='Owner')
        i = self.interaction(ADMIN)
        await self.bot._handle_release(i, 'Owner')
        self.assertIsNone(self.registry.find_ip_owner('203.250.133.240'))

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.connect import ConnectView, build_connect_embed
from app.bot import LabIPBot
from app.config import load_config
from app.data import IPRegistry

class ConnectTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = IPRegistry(str(Path(self.tmp.name) / 'state.json'))
        with patch.dict(os.environ, {'DISCORD_TOKEN':'test', 'GUILD_1_ID':'1', 'GUILD_1_CHANNEL_ID':'2', 'IP_PREFIX':'203.250.133'}, clear=True):
            self.bot = LabIPBot(load_config(), self.registry, None)
        self.i = SimpleNamespace(user=SimpleNamespace(id=111), guild_id=1, channel_id=2,
                                 response=SimpleNamespace(defer=AsyncMock(), send_message=AsyncMock()),
                                 followup=SimpleNamespace(send=AsyncMock()))

    async def asyncTearDown(self):
        await self.bot.close()
        self.tmp.cleanup()

    async def test_command_and_guide(self):
        self.assertIsNotNone(self.bot.tree.get_command('howtoconnect', guild=SimpleNamespace(id=1)))
        await self.bot._handle_howtoconnect(self.i, '221')
        args = self.i.followup.send.call_args.kwargs
        self.assertTrue(args['ephemeral'])
        self.assertLess(len(args['embed']), 6000)
        self.assertEqual([f.value for f in args['embed'].fields[:4]],
                         ['`203.250.133.221`', '`255.255.255.0`', '`203.250.133.1`', '`8.8.8.8`'])
        self.assertEqual(self.registry.get_all_entries(), [])
        args['view'].stop()

    async def test_buttons_return_only_values(self):
        view = ConnectView('203.250.133', '203.250.133.221')
        for button, value in zip(view.children, ['203.250.133.221','255.255.255.0','203.250.133.1','8.8.8.8','24']):
            await button.callback(self.i)
            self.i.response.send_message.assert_awaited_with(f'```\n{value}\n```', ephemeral=True)
        view.stop()

    async def test_no_ip_does_not_offer_placeholder_to_copy(self):
        view = ConnectView('203.250.133')
        await view.children[0].callback(self.i)
        self.assertNotIn('```', self.i.response.send_message.call_args.args[0])
        view.stop()

    async def test_single_own_ip_selected(self):
        self.registry.register(111, 'owner', 'Owner', '203.250.133.240')
        await self.bot._handle_howtoconnect(self.i)
        args = self.i.followup.send.call_args.kwargs
        self.assertEqual(args['embed'].fields[0].value, '`203.250.133.240`')
        args['view'].stop()

    async def test_multiple_own_ips_not_arbitrarily_selected(self):
        for last in [240,241]:
            self.registry.register(111, 'owner', 'Owner', f'203.250.133.{last}')
        await self.bot._handle_howtoconnect(self.i)
        args = self.i.followup.send.call_args.kwargs
        self.assertEqual(args['embed'].fields[0].value, '`203.250.133.xxx`')
        args['view'].stop()

    async def test_invalid_ip_rejected(self):
        for ip in ['192.168.1.221', '255', 'hello', '0']:
            await self.bot._handle_howtoconnect(self.i, ip)
            self.assertTrue(self.i.followup.send.call_args.args[0].startswith('❌'))

    async def test_permissions_apply(self):
        self.i.guild_id = 99
        await self.bot._handle_howtoconnect(self.i)
        self.assertTrue(self.i.followup.send.call_args.args[0].startswith('❌'))

import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from app.connect import ConnectView, GuideHelpButton, GuideStepButton, build_connect_embed
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
        self.assertEqual(args['embed'].description,
            'IP 주소\n```\n203.250.133.221\n```\n'
            '서브넷 마스크\n```\n255.255.255.0\n```\n'
            '게이트웨이\n```\n203.250.133.1\n```\n'
            '기본 설정 DNS\n```\n8.8.8.8\n```\n'
            '대체 DNS\n```\n8.8.4.4\n```')
        self.assertEqual(self.registry.get_all_entries(), [])
        self.assertEqual(args['embed'].fields, [])
        self.assertFalse(args['embed'].title)
        self.assertFalse(args['embed'].image.url)
        self.assertNotIn('file', args)
        self.assertTrue(any(isinstance(c, GuideHelpButton) for c in args['view'].children))
        args['view'].stop()

    async def test_help_button_reveals_screenshots_only_on_request(self):
        self.i.response.edit_message = AsyncMock()
        view = ConnectView('203.250.133', '203.250.133.221')
        await next(c for c in view.children if isinstance(c, GuideHelpButton)).callback(self.i)
        args = self.i.response.edit_message.call_args.kwargs
        self.assertTrue(view.show_guide)
        self.assertIn('이더넷', args['embed'].description)
        self.assertEqual(args['embed'].image.url, f"attachment://{args['attachments'][0].filename}")
        self.assertNotIn('출처', str(args['embed'].to_dict()))
        self.assertEqual(sum(isinstance(c, GuideStepButton) for c in view.children), 3)
        args['attachments'][0].close()
        view.stop()

    async def test_photo_steps_replace_attachment_and_keep_ip(self):
        self.i.response.edit_message = AsyncMock()
        view = ConnectView('203.250.133', '203.250.133.221', show_guide=True)
        buttons = [item for item in view.children if isinstance(item, GuideStepButton)]
        for step in [1, 2, 0]:
            await buttons[step].callback(self.i)
            args = self.i.response.edit_message.call_args.kwargs
            photo = args['attachments'][0]
            self.assertEqual(args['embed'].image.url, f'attachment://{photo.filename}')
            self.assertTrue(photo.fp.read().startswith(b'\x89PNG\r\n\x1a\n'))
            self.assertEqual(args['embed'].fields[0].value, '```\n203.250.133.221\n```')
            self.assertEqual(args['embed'].fields[4].name, '대체 DNS')
            self.assertEqual(args['embed'].fields[4].value, '```\n8.8.4.4\n```')
            self.assertEqual([b.disabled for b in buttons], [n == step for n in range(3)])
            photo.close()
        view.stop()

    async def test_only_help_and_photo_navigation_buttons_remain(self):
        for show_guide, expected_type, count in [(False, GuideHelpButton, 1), (True, GuideStepButton, 3)]:
            view = ConnectView('203.250.133', '203.250.133.221', show_guide=show_guide)
            self.assertEqual(len(view.children), count)
            self.assertTrue(all(isinstance(c, expected_type) for c in view.children))
            view.stop()

    async def test_no_ip_shows_prefix_without_last_octet(self):
        view = ConnectView('203.250.133')
        self.assertIn('IP 주소\n```\n203.250.133.\n```', view.embed().description)
        self.assertNotIn('203.250.133.xxx', view.embed().description)
        self.assertEqual(view.embed().description.count('```'), 10)
        self.assertEqual(build_connect_embed('203.250.133').fields[0].value, '```\n203.250.133.\n```')
        view.stop()

    async def test_single_own_ip_selected(self):
        self.registry.register(111, 'owner', 'Owner', '203.250.133.240')
        await self.bot._handle_howtoconnect(self.i)
        args = self.i.followup.send.call_args.kwargs
        self.assertIn('IP 주소\n```\n203.250.133.240\n```', args['embed'].description)
        args['view'].stop()

    async def test_multiple_own_ips_not_arbitrarily_selected(self):
        for last in [240,241]:
            self.registry.register(111, 'owner', 'Owner', f'203.250.133.{last}')
        await self.bot._handle_howtoconnect(self.i)
        args = self.i.followup.send.call_args.kwargs
        self.assertIn('IP 주소\n```\n203.250.133.\n```', args['embed'].description)
        args['view'].stop()

    async def test_invalid_ip_rejected(self):
        for ip in ['192.168.1.221', '255', 'hello', '0']:
            await self.bot._handle_howtoconnect(self.i, ip)
            self.assertTrue(self.i.followup.send.call_args.args[0].startswith('❌'))

    async def test_permissions_apply(self):
        self.i.guild_id = 99
        await self.bot._handle_howtoconnect(self.i)
        self.assertTrue(self.i.followup.send.call_args.args[0].startswith('❌'))

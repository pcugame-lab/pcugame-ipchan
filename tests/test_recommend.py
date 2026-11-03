import os
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import patch, AsyncMock
import test_connect
from app.connect import GuideHelpButton, GuideStepButton
from app.config import _load_ip_last_octet_range
from app.data import IPRegistry
from app.recommend import RecommendView, RecommendSelect, available_ips, MISSING_RANGE

class RangeTests(unittest.TestCase):
    def test_optional_and_valid_range(self):
        for raw, expected in [('', None), ('  ', None), ('221-254', (221,254)), ('100-100', (100,100))]:
            with patch.dict(os.environ, {'IP_LAST_OCTET_RANGE':raw}):
                self.assertEqual(_load_ip_last_octet_range(), expected)
    def test_invalid_range_fails_closed(self):
        for raw in ['0-254', '1-255', '200-100', '221', 'a-b', '-1-20', '1-2-3']:
            with self.subTest(raw=raw), patch.dict(os.environ, {'IP_LAST_OCTET_RANGE':raw}):
                with self.assertRaises(ValueError):
                    _load_ip_last_octet_range()

class RecommendationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await test_connect.ConnectTests.asyncSetUp(self)
        self.i.response.edit_message = AsyncMock()
        self.i.user.name = 'test-user'
        self.i.user.display_name = '테스트 사용자'

    asyncTearDown = test_connect.ConnectTests.asyncTearDown

    def configure(self, start=221, end=254):
        self.bot.config = replace(self.bot.config, ip_last_octet_range=(start,end))

    def view(self):
        return RecommendView(self.bot, 111)

    async def show_help(self, view):
        await next(c for c in view.children if isinstance(c, GuideHelpButton)).callback(self.i)
        self.i.response.edit_message.call_args.kwargs['attachments'][0].close()

    async def test_missing_range_explained_and_no_selection(self):
        view = self.view()
        await self.show_help(view)
        self.assertIn(MISSING_RANGE, view.embed().fields[-1].value)
        self.assertFalse(any(isinstance(c, RecommendSelect) for c in view.children))
        view.stop()

    async def test_excludes_registered_and_gateway_and_paginates(self):
        self.configure(1,254)
        self.registry.register(222, 'other', 'Other', '203.250.133.221')
        self.assertNotIn('203.250.133.1', available_ips(self.bot.config,self.registry))
        self.assertNotIn('203.250.133.221', available_ips(self.bot.config,self.registry))
        view = self.view()
        select = next(c for c in view.children if isinstance(c, RecommendSelect))
        self.assertEqual(len(select.options),25)
        self.assertFalse(view.next.disabled)
        await view.next.callback(self.i)
        select2 = next(c for c in view.children if isinstance(c, RecommendSelect))
        self.assertTrue(select.offered.isdisjoint(select2.offered))
        view.stop()

    async def test_selection_registers_persists_and_returns_config(self):
        self.configure()
        view = self.view()
        address = '203.250.133.221'
        await view.claim(self.i, address, {address})
        saved = IPRegistry(str(Path(self.tmp.name)/'state.json'))
        self.assertEqual(saved.find_ip_owner(address).user_id,111)
        args = self.i.response.edit_message.call_args.kwargs
        self.assertIn(address,args['embed'].description)
        self.assertFalse(args['view'].show_guide)
        self.assertEqual(args['view'].guide_step, 0)
        self.assertEqual(args['embed'].description.count('```'), 8)
        self.assertEqual(args['attachments'], [])
        self.assertFalse(any(isinstance(c,RecommendSelect) for c in args['view'].children))
        args['view'].stop()

    async def test_photo_navigation_keeps_recommendations_without_registering(self):
        self.configure()
        view = self.view()
        await self.show_help(view)
        button = next(c for c in view.children if isinstance(c, GuideStepButton) and c.step == 1)
        await button.callback(self.i)
        args = self.i.response.edit_message.call_args.kwargs
        self.assertIn('내 IP로 등록', args['embed'].fields[-1].value)
        self.assertTrue(any(isinstance(c, RecommendSelect) for c in view.children))
        self.assertEqual(self.registry.count(), 0)
        args['attachments'][0].close()
        view.stop()

    async def test_selecting_ip_with_help_open_keeps_input_photo(self):
        self.configure()
        view = self.view()
        await self.show_help(view)
        address = '203.250.133.221'
        await view.claim(self.i, address, {address})
        args = self.i.response.edit_message.call_args.kwargs
        self.assertTrue(args['view'].show_guide)
        self.assertEqual(args['view'].guide_step, 2)
        self.assertEqual(args['embed'].fields[0].value, f'```\n{address}\n```')
        self.assertEqual(args['embed'].image.url, f"attachment://{args['attachments'][0].filename}")
        args['attachments'][0].close()
        args['view'].stop()

    async def test_concurrent_claim_cannot_take_another_owner(self):
        self.configure()
        view = self.view()
        address='203.250.133.221'
        self.registry.register(222,'other','Other',address)
        await view.claim(self.i,address,{address})
        self.assertEqual(self.registry.find_ip_owner(address).user_id,222)
        self.assertIn('다시 선택', self.i.response.edit_message.call_args.kwargs['content'])
        view.stop()

    async def test_unoffered_outside_range_and_permissions_rejected(self):
        self.configure()
        view = self.view()
        for address, offered in [('203.250.133.222',set()), ('203.250.133.100',{'203.250.133.100'})]:
            await view.claim(self.i,address,offered)
        self.i.guild_id=99
        await view.claim(self.i,'203.250.133.221',{'203.250.133.221'})
        self.assertEqual(self.registry.count(),0)
        view.stop()

    async def test_empty_range_has_no_select(self):
        self.configure(221,221)
        self.registry.register(222,'other','Other','203.250.133.221')
        view=self.view()
        await self.show_help(view)
        self.assertIn('비어 있는 IP가 없습니다',view.embed().fields[-1].value)
        self.assertFalse(any(isinstance(c,RecommendSelect) for c in view.children))
        view.stop()

    async def test_other_user_cannot_register(self):
        self.configure()
        view=self.view()
        self.i.user.id=222
        await view.claim(self.i,'203.250.133.221',{'203.250.133.221'})
        self.assertEqual(self.registry.count(),0)
        view.stop()

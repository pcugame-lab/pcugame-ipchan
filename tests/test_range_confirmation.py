import re
from dataclasses import replace
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch
from aiohttp.test_utils import TestClient, TestServer
import test_connect
from app.range_confirmation import RangeConfirmationView, outside_range, WARNING
from app.tokens import TokenStore
from app.webserver import create_web_app

class RangeConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await test_connect.ConnectTests.asyncSetUp(self)
        self.bot.config=replace(self.bot.config, ip_last_octet_range=(221,254))
        self.i.user.name='owner'
        self.i.user.global_name='Owner'
        self.i.response.edit_message=AsyncMock()
        self.i.edit_original_response=AsyncMock()
    asyncTearDown=test_connect.ConnectTests.asyncTearDown

    async def test_manual_outside_requires_confirmation_then_persists(self):
        await self.bot._handle_register(self.i,'220',None,None)
        self.assertEqual(self.registry.count(),0)
        self.assertIn(WARNING,self.i.followup.send.call_args.args[0])
        view=self.i.followup.send.call_args.kwargs['view']
        self.assertIsInstance(view,RangeConfirmationView)
        await view.confirm.callback(self.i)
        self.assertEqual(self.registry.find_ip_owner('203.250.133.220').user_id,111)
        await view.confirm.callback(self.i)
        self.assertEqual(self.registry.count(),1)

    async def test_cancel_does_not_register(self):
        await self.bot._handle_register(self.i,'220',None,None)
        view=self.i.followup.send.call_args.kwargs['view']
        await view.cancel.callback(self.i)
        self.assertEqual(self.registry.count(),0)

    async def test_range_edges_no_prompt(self):
        for last in ['221','254']:
            await self.bot._handle_register(self.i,last,None,None)
            self.assertTrue(self.i.followup.send.call_args.args[0].startswith('✅'))
        self.assertEqual(self.registry.count(),2)
        self.assertFalse(outside_range('203.250.133.220',None))

    async def test_permission_rechecked_after_prompt(self):
        await self.bot._handle_register(self.i,'220',None,None)
        view=self.i.followup.send.call_args.kwargs['view']
        self.i.guild_id=99
        await view.confirm.callback(self.i)
        self.assertEqual(self.registry.count(),0)

    async def test_owner_rechecked_after_prompt(self):
        await self.bot._handle_register(self.i,'220',None,None)
        view=self.i.followup.send.call_args.kwargs['view']
        self.registry.register(222,'other','Other','203.250.133.220')
        await view.confirm.callback(self.i)
        self.assertEqual(self.registry.find_ip_owner('203.250.133.220').user_id,222)
        self.assertTrue(self.i.followup.send.call_args.args[0].startswith('❌'))

    async def test_other_user_cannot_confirm(self):
        await self.bot._handle_register(self.i,'220',None,None)
        view=self.i.followup.send.call_args.kwargs['view']
        self.i.user.id=222
        await view.confirm.callback(self.i)
        self.assertEqual(self.registry.count(),0)
        view.stop()

    async def test_connect_explicit_outside_requires_confirmation_without_registration(self):
        await self.bot._handle_howtoconnect(self.i,'220')
        view=self.i.followup.send.call_args.kwargs['view']
        self.assertIsInstance(view,RangeConfirmationView)
        await view.confirm.callback(self.i)
        args=self.i.followup.send.call_args.kwargs
        self.assertEqual(args['embed'].description.splitlines()[0], 'IP 주소: `203.250.133.220`')
        self.assertEqual(self.registry.count(),0)
        args['view'].stop()

class WebConfirmationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await test_connect.ConnectTests.asyncSetUp(self)
        self.store=TokenStore(str(Path(self.tmp.name)/'tokens.json'))
        self.client=TestClient(TestServer(create_web_app(self.registry,self.store,'203.250.133',ip_last_octet_range=(221,254))))
        await self.client.start_server()
        self.ip_patch = patch('app.webserver._client_ip', return_value='203.250.133.220')
        self.client_ip = self.ip_patch.start()
        self.addCleanup(self.ip_patch.stop)
    async def asyncTearDown(self):
        await self.client.close()
        await test_connect.ConnectTests.asyncTearDown(self)
    def token(self):
        return self.store.create(111,'owner','Owner','','Owner')
    async def prompt(self):
        token=self.token()
        response=await self.client.get('/ip/claim?token='+token)
        self.assertEqual(response.status,200)
        self.assertTrue(self.store.peek(token))
        self.assertEqual(self.registry.count(),0)
        response=await self.client.post('/ip/claim',data={'token':token})
        html=await response.text()
        self.assertIn(WARNING,html)
        self.assertEqual(self.registry.count(),0)
        return re.search(r'name="token" value="([^"]+)"',html).group(1)
    async def test_web_confirmation_post_and_single_use(self):
        url=await self.prompt()
        response=await self.client.post('/ip/claim',data={'token':url})
        self.assertEqual(response.status,200)
        self.assertEqual(self.registry.find_ip_owner('203.250.133.220').user_id,111)
        self.assertEqual((await self.client.post('/ip/claim',data={'token':url})).status,400)
    async def test_query_flag_does_not_skip_confirmation(self):
        response=await self.client.post('/ip/claim?confirmed=1',data={'token':self.token()})
        self.assertIn(WARNING,await response.text())
        self.assertEqual(self.registry.count(),0)
    async def test_confirmation_bound_to_same_ip(self):
        url=await self.prompt()
        self.client_ip.return_value='203.250.133.219'
        response=await self.client.post('/ip/claim',data={'token':url})
        self.assertEqual(response.status,400)
        self.assertEqual(self.registry.count(),0)
    async def test_within_range_keeps_existing_registration_flow(self):
        self.client_ip.return_value='203.250.133.221'
        response=await self.client.post('/ip/claim',data={'token':self.token()})
        self.assertEqual(response.status,200)
        self.assertEqual(self.registry.find_ip_owner('203.250.133.221').user_id,111)

    async def test_forwarded_headers_are_not_trusted(self):
        self.ip_patch.stop()
        response=await self.client.post('/ip/claim',data={'token':self.token()},
                                        headers={'X-Real-IP':'203.250.133.221','X-Forwarded-For':'203.250.133.221'})
        self.assertEqual(response.status,403)
        self.assertEqual(self.registry.count(),0)

    async def test_html_labels_are_escaped(self):
        self.client_ip.return_value='203.250.133.221'
        token=self.store.create(111,'owner','Owner','<script>alert(1)</script>','<img src=x onerror=alert(1)>')
        response=await self.client.post('/ip/claim',data={'token':token})
        html=await response.text()
        self.assertNotIn('<script>',html)
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<img',html)
        self.assertEqual(response.headers['X-Frame-Options'],'DENY')

    async def test_rate_limit_preserved(self):
        from app.webserver import RateLimiter
        self.client.app['rate_limiter']=RateLimiter(60,1)
        await self.client.post('/ip/claim',data={'token':'invalid'})
        response=await self.client.post('/ip/claim',data={'token':self.token()})
        self.assertEqual(response.status,429)
        self.assertEqual(self.registry.count(),0)

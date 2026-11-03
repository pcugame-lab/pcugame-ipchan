import asyncio
import json
import os
import socket
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import test_connect
from app.config import WakeTarget, _load_wol_targets
from app.wakeonlan import WakeCooldown, WakeSelect, WakeService, WakeView, send_magic_packet


TARGET = WakeTarget('203.250.133.223', '58:11:22:46:4c:e9', '테스트 PC')


class WakeConfigTests(unittest.TestCase):
    def test_disabled_and_valid_targets(self):
        with patch.dict(os.environ, {'WOL_TARGETS': ''}):
            self.assertEqual(_load_wol_targets('203.250.133'), ())
        raw = json.dumps([{'ip': '223', 'mac': '58-11-22-46-4C-E9', 'name': '테스트 PC'}])
        with patch.dict(os.environ, {'WOL_TARGETS': raw}):
            self.assertEqual(_load_wol_targets('203.250.133'), (TARGET,))

    def test_invalid_configuration_rejected(self):
        row = {'ip': '223', 'mac': TARGET.mac}
        cases = ['not json', '{}', '[{}]', json.dumps([row] * 26), json.dumps([row, row])]
        for changes in [
            {'ip': '192.168.1.223'}, {'ip': '0'}, {'ip': '255'},
            {'mac': 'bad'}, {'mac': 'ff:ff:ff:ff:ff:ff'}, {'mac': '00:00:00:00:00:00'},
            {'mac': '01:11:22:33:44:55'}, {'name': 'x' * 81}, {'name': 'PC\nname'},
        ]:
            cases.append(json.dumps([{**row, **changes}]))
        for raw in cases:
            with self.subTest(raw=raw), patch.dict(os.environ, {'WOL_TARGETS': raw}):
                with self.assertRaisesRegex(ValueError, 'WOL_TARGETS'):
                    _load_wol_targets('203.250.133')


class PacketTests(unittest.TestCase):
    def test_packet_and_broadcast_destination(self):
        with patch('app.wakeonlan.socket.socket') as factory:
            sender = factory.return_value.__enter__.return_value
            sender.sendto.return_value = 102
            send_magic_packet(TARGET, '203.250.133')
        factory.assert_called_once_with(socket.AF_INET, socket.SOCK_DGRAM)
        sender.setsockopt.assert_called_once_with(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        self.assertEqual(sender.sendto.call_count, 3)
        packet, destination = sender.sendto.call_args.args
        self.assertEqual(destination, ('203.250.133.255', 9))
        self.assertEqual(packet, b'\xff' * 6 + bytes.fromhex('581122464ce9') * 16)

    def test_partial_send_is_failure(self):
        with patch('app.wakeonlan.socket.socket') as factory:
            factory.return_value.__enter__.return_value.sendto.return_value = 0
            with self.assertRaises(OSError):
                send_magic_packet(TARGET, '203.250.133')

    def test_outside_subnet_cannot_send(self):
        with patch('app.wakeonlan.socket.socket') as factory:
            with self.assertRaises(ValueError):
                send_magic_packet(replace(TARGET, ip='192.168.1.223'), '203.250.133')
            factory.assert_not_called()


class WakeServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_cooldown_shared_and_failed_send_can_retry(self):
        service = WakeService()
        with patch('app.wakeonlan.send_magic_packet', side_effect=OSError('network')):
            with self.assertRaises(OSError):
                await service.wake(TARGET, '203.250.133')
        with patch('app.wakeonlan.send_magic_packet') as send:
            await service.wake(TARGET, '203.250.133')
            with self.assertRaises(WakeCooldown):
                await service.wake(TARGET, '203.250.133')
            send.assert_called_once_with(TARGET, '203.250.133')

    async def test_simultaneous_requests_only_send_once(self):
        service = WakeService()
        started, finish = asyncio.Event(), asyncio.Event()

        async def delayed_send(*args):
            started.set()
            await finish.wait()

        with patch('app.wakeonlan.asyncio.to_thread', side_effect=delayed_send) as send:
            first = asyncio.create_task(service.wake(TARGET, '203.250.133'))
            await started.wait()
            try:
                with self.assertRaises(WakeCooldown):
                    await service.wake(TARGET, '203.250.133')
            finally:
                finish.set()
                await first
            self.assertEqual(send.call_count, 1)


class WakeCommandTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await test_connect.ConnectTests.asyncSetUp(self)
        self.bot.config = replace(self.bot.config, wol_targets=(TARGET,))
        self.bot.wake_service.wake = AsyncMock()

    asyncTearDown = test_connect.ConnectTests.asyncTearDown

    async def test_command_shows_dropdown_without_sending(self):
        self.assertIsNotNone(self.bot.tree.get_command('wakeonlan', guild=type('Guild', (), {'id': 1})()))
        await self.bot._handle_wakeonlan(self.i)
        args = self.i.followup.send.call_args.kwargs
        self.assertTrue(args['ephemeral'])
        self.assertIsInstance(args['view'], WakeView)
        select = args['view'].children[0]
        self.assertIsInstance(select, WakeSelect)
        self.assertEqual([option.value for option in select.options], [TARGET.ip])
        self.assertIn('223', select.options[0].label)
        self.bot.wake_service.wake.assert_not_awaited()
        args['view'].stop()

    async def test_select_sends_without_registering_or_claiming_power_on(self):
        view = WakeView(self.bot, 111)
        await view.wake(self.i, TARGET.ip, {TARGET.ip: TARGET})
        self.bot.wake_service.wake.assert_awaited_once_with(TARGET, '203.250.133')
        self.assertEqual(self.registry.count(), 0)
        self.assertIn('요청을 보냈습니다', self.i.followup.send.call_args.args[0])
        view.stop()

    async def test_rechecks_owner_permissions_and_current_configuration(self):
        view = WakeView(self.bot, 111)
        self.i.user.id = 222
        await view.wake(self.i, TARGET.ip, {TARGET.ip: TARGET})
        self.i.user.id = 111
        self.i.guild_id = 99
        await view.wake(self.i, TARGET.ip, {TARGET.ip: TARGET})
        self.i.guild_id = 1
        self.i.channel_id = 99
        await view.wake(self.i, TARGET.ip, {TARGET.ip: TARGET})
        self.i.channel_id = 2
        await view.wake(self.i, TARGET.ip, {})
        await view.wake(self.i, '203.250.133.224', {TARGET.ip: TARGET})
        self.bot.config = replace(self.bot.config, wol_targets=(replace(TARGET, mac='02:11:22:33:44:55'),))
        await view.wake(self.i, TARGET.ip, {TARGET.ip: TARGET})
        self.bot.wake_service.wake.assert_not_awaited()
        view.stop()

    async def test_disabled_or_wrong_channel_has_no_dropdown(self):
        self.bot.config = replace(self.bot.config, wol_targets=())
        await self.bot._handle_wakeonlan(self.i)
        self.assertNotIn('view', self.i.followup.send.call_args.kwargs)
        self.bot.config = replace(self.bot.config, wol_targets=(TARGET,))
        self.i.channel_id = 99
        await self.bot._handle_wakeonlan(self.i)
        self.assertNotIn('view', self.i.followup.send.call_args.kwargs)
        self.bot.wake_service.wake.assert_not_awaited()

    async def test_send_failure_and_cooldown_are_reported(self):
        view = WakeView(self.bot, 111)
        for failure, expected in [(WakeCooldown('30초 후 다시 시도하세요.'), '30초'), (OSError('offline'), '보내지 못했습니다')]:
            self.bot.wake_service.wake.side_effect = failure
            await view.wake(self.i, TARGET.ip, {TARGET.ip: TARGET})
            self.assertIn(expected, self.i.followup.send.call_args.args[0])
        view.stop()

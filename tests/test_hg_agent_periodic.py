#!/usr/bin/env python
# -*- coding: utf-8 -*-

import collections
import os
import signal
import socket
import textwrap
import threading
import unittest

import httmock
import mock
import requests
import yaml

from pyfakefs import fake_filesystem_unittest
from hg_agent_periodic import periodic


# NB: we print exception messages to allow visual inspection that we're failing
# the right thing.
class TestConfigSchema(unittest.TestCase):

    def test_barestring(self):
        y = yaml.load('bare string')
        with self.assertRaises(periodic.ValidationError) as cm:
            periodic.validate_agent_config(y)
        print cm.exception.message

    def test_ok(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        periodic.validate_agent_config(y)

    def test_ok_proxy(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            https_proxy: "http://10.10.1.10:1080"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        periodic.validate_agent_config(y)

    def test_unknown_key(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            something: "whatever"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        with self.assertRaises(periodic.ValidationError) as cm:
            periodic.validate_agent_config(y)
        print cm.exception.message

    def test_missing_required_key(self):
        cfg = '''
        '''
        y = yaml.load(textwrap.dedent(cfg))
        with self.assertRaises(periodic.ValidationError) as cm:
            periodic.validate_agent_config(y)
        print cm.exception.message

    def test_bad_api_key(self):
        cfg = '''
            api_key: "not a uuidv4"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        with self.assertRaises(periodic.ValidationError) as cm:
            periodic.validate_agent_config(y)
        print cm.exception.message

    def test_bad_endpoint(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            endpoint: "not a hostname"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        with self.assertRaises(periodic.ValidationError) as cm:
            periodic.validate_agent_config(y)
        print cm.exception.message

    def test_bad_endpoint_url(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            endpoint_url: "not a URL"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        with self.assertRaises(periodic.ValidationError) as cm:
            periodic.validate_agent_config(y)
        print cm.exception.message

    def test_bad_proxy(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            https_proxy: "not a proxy URI"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        with self.assertRaises(periodic.ValidationError) as cm:
            periodic.validate_agent_config(y)
        print cm.exception.message

    def test_spelling(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            ednpoint: "a.carbon.endpoint"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        with self.assertRaises(periodic.ValidationError) as cm:
            periodic.validate_agent_config(y)
        print cm.exception.message


class TestDiamondConfigGen(unittest.TestCase):

    def test_gen(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        periodic.validate_agent_config(y)
        diamond = periodic.gen_diamond_config(y)
        lines = diamond.split('\n')
        self.assertIn('host = localhost', lines)
        self.assertIn(
            'path_prefix = hg_agent',
            lines)

    def test_custom_prefix(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            custom_prefix: "no_2_hg_agent"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        periodic.validate_agent_config(y)
        diamond = periodic.gen_diamond_config(y)
        lines = diamond.split('\n')
        self.assertIn(
            'path_prefix = no_2_hg_agent',
            lines)

    def test_hostname_method(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            hostname_method: "fqdn"
        '''
        y = yaml.load(textwrap.dedent(cfg))
        periodic.validate_agent_config(y)
        diamond = periodic.gen_diamond_config(y)
        lines = diamond.split('\n')
        self.assertIn('hostname_method = fqdn', lines)

    def test_single_collector_deactivation(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            CPUCollector: False
        '''
        y = yaml.load(textwrap.dedent(cfg))
        periodic.validate_agent_config(y)
        diamond = periodic.gen_diamond_config(y)
        lines = diamond.split('\n')
        for i, line in enumerate(lines):
            if "CPUCollector" in line:
                collectorEnabled = lines[i+1]
                self.assertEqual('enabled = False', collectorEnabled)

    def test_multiple_collector_deactivation(self):
        cfg = '''
            api_key: "00000000-0000-0000-0000-000000000000"
            CPUCollector: False
            DiskSpaceCollector: False
            DiskUsageCollector: False
            LoadAverageCollector: False
            MemoryCollector: False
            NetworkCollector: False
            SockstatCollector: False
            VMStatCollector: False
            SelfCollector: False
        '''
        collectors = (
            'CPUCollector',
            'DiskSpaceCollector',
            'DiskUsageCollector',
            'LoadAverageCollector',
            'MemoryCollector',
            'NetworkCollector',
            'SockstatCollector',
            'VMStatCollector',
            'SelfCollector')
        y = yaml.load(textwrap.dedent(cfg))
        periodic.validate_agent_config(y)
        diamond = periodic.gen_diamond_config(y)
        lines = diamond.split('\n')
        for i, line in enumerate(lines):
            for collector in collectors:
                if collector in line:
                    collectorEnabled = lines[i+1]
                    self.assertEqual('enabled = False', collectorEnabled)

    def test_collectors_activated_and_deactivated(self):
        cfg = 'api_key: "00000000-0000-0000-0000-000000000000"'
        collectorstates = {
            'CPUCollector': 'True',
            'DiskSpaceCollector': 'False',
            'DiskUsageCollector': 'True',
            'LoadAverageCollector': 'False',
            'MemoryCollector': 'False',
            'NetworkCollector': 'True',
            'SockstatCollector': 'False',
            'VMStatCollector': 'True',
            'SelfCollector': 'False',
        }
        for c in collectorstates:
            cfg += ("\n%s: %s\n" % (c, collectorstates[c]))
        y = yaml.load(textwrap.dedent(cfg))
        periodic.validate_agent_config(y)
        diamond = periodic.gen_diamond_config(y)
        lines = diamond.split('\n')
        for i, line in enumerate(lines):
            for collector in collectorstates:
                if collector in line:
                    collectorEnabled = lines[i+1]
                    self.assertEqual(
                        'enabled = %s' % collectorstates[collector],
                        collectorEnabled)

    def test_generated_configs_differ(self):
        cfg1 = textwrap.dedent('''A line,
                                  a line we should ignore,
                                  another line''')
        cfg2 = textwrap.dedent('''A line,
                                  a line we should ignore and not worry about,
                                  another line''')
        cfg3 = textwrap.dedent('''Some line,
                                  a line we should ignore,
                                  Some other line''')

        self.assertFalse(
            periodic.generated_configs_differ(cfg1, cfg2,
                                              ignore='ignore'))
        self.assertTrue(
            periodic.generated_configs_differ(cfg1, cfg3,
                                              ignore='ignore'))


ConfigArgs = collections.namedtuple('ConfigArgs', ['config', 'diamond_config'])


class TestConfigOnce(fake_filesystem_unittest.TestCase):

    def setUp(self):
        self.setUpPyfakefs()
        periodic.remember_config({})

    @mock.patch('hg_agent_periodic.periodic.logging')
    @mock.patch('hg_agent_periodic.periodic.validate_agent_config')
    def test_config_load_error(self, mock_validate, mock_logging):
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        mock_logging.error.assert_called()
        # If load fails, we never reach validate
        mock_validate.assert_not_called()

    @mock.patch('hg_agent_periodic.periodic.logging')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_invalid(self, mock_gen, mock_logging):
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                               invalid_key: "test"
                           '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))

        # If validation fails, we never reach gen.
        mock_logging.error.assert_called()
        mock_gen.assert_not_called()

    @mock.patch('hg_agent_periodic.periodic.restart_process')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_new_diamond(self, mock_gen, mock_restart):

        # As jinja2 uses the filesystem, we need to mock this out here (but
        # note its functionality is tested in TestDiamondConfigGen above).
        mock_gen.return_value = 'a fake diamond config\n'

        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                           '''))

        self.assertFalse(os.path.exists('/diamond.cfg'))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        self.assertTrue(os.path.exists('/diamond.cfg'))
        mock_restart.assert_called_once_with(mock.ANY, 'diamond')

    @mock.patch('hg_agent_periodic.periodic.restart_process')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_diamond_unchanged(self, mock_gen, mock_restart):

        old_diamond = 'a fake diamond config\n'
        mock_gen.return_value = old_diamond
        self.fs.CreateFile('/diamond.cfg', contents=old_diamond)

        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                           '''))

        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        mock_restart.assert_not_called()

    @mock.patch('hg_agent_periodic.periodic.restart_process')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_no_endpoint_url(self, mock_gen, mock_restart):
        '''The forwarder is not restarted without `endpoint_url`'''
        mock_gen.return_value = 'a fake diamond config\n'
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                           '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        mock_restart.assert_called_once_with(mock.ANY, 'diamond')

    @mock.patch('hg_agent_periodic.periodic.restart_process')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_unchanged_endpoint_url(self, mock_gen, mock_restart):
        '''The forwarder is not restarted with unchanged `endpoint_url`'''
        mock_gen.return_value = 'a fake diamond config\n'
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                               endpoint_url: "https://my-endpoint"
                           '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        mock_restart.assert_called_once_with(mock.ANY, 'diamond')

    @mock.patch('hg_agent_periodic.periodic.restart_process')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_changed_endpoint_url(self, mock_gen, mock_restart):
        '''The forwarder/receiver are restarted with changed `endpoint_url`'''
        mock_gen.return_value = 'a fake diamond config\n'
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                               endpoint_url: "https://my-endpoint"
                           '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        config = self.fs.get_object('/hg-agent.cfg')
        config.set_contents(textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                               endpoint_url: "https://other-endpoint"
                            '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        mock_restart.assert_any_call(mock.ANY, 'forwarder')
        mock_restart.assert_any_call(mock.ANY, 'receiver')

    @mock.patch('hg_agent_periodic.periodic.restart_process')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_unchanged_api_key(self, mock_gen, mock_restart):
        '''The forwarder is not restarted with unchanged `api_key`'''
        mock_gen.return_value = 'a fake diamond config\n'
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                           '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        mock_restart.assert_called_once_with(mock.ANY, 'diamond')

    @mock.patch('hg_agent_periodic.periodic.restart_process')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_changed_api_key(self, mock_gen, mock_restart):
        '''The forwarder/receiver are restarted with changed `api_key`'''
        mock_gen.return_value = 'a fake diamond config\n'
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                           '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        config = self.fs.get_object('/hg-agent.cfg')
        config.set_contents(textwrap.dedent('''
                               api_key: "10000000-0000-0000-0000-000000000001"
                            '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        mock_restart.assert_any_call(mock.ANY, 'forwarder')
        mock_restart.assert_any_call(mock.ANY, 'receiver')

    @mock.patch('hg_agent_periodic.periodic.restart_process')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_new_endpoint_url(self, mock_gen, mock_restart):
        '''The forwarder is restarted with an entirely new `endpoint_url`'''
        mock_gen.return_value = 'a fake diamond config\n'
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                           '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        config = self.fs.get_object('/hg-agent.cfg')
        config.set_contents(textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                               endpoint_url: "https://my-endpoint"
                            '''))
        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        mock_restart.assert_any_call(mock.ANY, 'forwarder')

    @mock.patch('hg_agent_periodic.periodic.logging')
    @mock.patch('hg_agent_periodic.periodic.restart_process')
    @mock.patch('hg_agent_periodic.periodic.gen_diamond_config')
    def test_config_write_except(self, mock_gen, mock_restart, mock_logging):
        mock_gen.return_value = 'a fake diamond config\n'
        mock_restart.side_effect = Exception('test')

        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                           '''))

        periodic.config_once(ConfigArgs('/hg-agent.cfg', '/diamond.cfg'))
        mock_logging.exception.assert_called()


HeartbeatArgs = collections.namedtuple('HeartbeatArgs',
                                       ['config', 'agent_version',
                                        'periodic_logfile', 'heartbeat'])


# httmock setup
@httmock.urlmatch(netloc=r'^heartbeat_ok.*$')
def heartbeat_ok_mock(url, request):
    return 'OK'


@httmock.urlmatch(netloc=r'^heartbeat_timeout.*$')
def heartbeat_timeout_mock(url, request):
    raise requests.exceptions.Timeout('Connection timed out.')


@httmock.urlmatch(netloc=r'^heartbeat_authfail.*$')
def heartbeat_authfail_mock(url, request):
    return httmock.response(401)


@httmock.urlmatch(netloc=r'^heartbeat_unhandled.*$')
def heartbeat_unhandled_mock(url, request):
    raise requests.exceptions.RequestException('test')


class TestHeartbeatOnce(fake_filesystem_unittest.TestCase):

    def setUp(self):
        self.setUpPyfakefs()

    def test_get_primary_ip(self):
        a = periodic.get_primary_ip()
        try:
            socket.inet_aton(a)
        except socket.error:
            self.fail('address from get_primary_ip does not parse '
                      'properly: %s' % a)

    def test_get_version(self):
        self.fs.CreateFile('/version', contents='0.1\n')
        result = periodic.get_version('/nonexistent')
        self.assertEqual(None, result)
        result = periodic.get_version('/version')
        self.assertEqual('0.1', result)

    def test_collect_logs(self):
        data = ['line %.02d' % i for i in range(20)]
        self.fs.CreateFile('/test.log', contents='\n'.join(data) + '\n')

        result = periodic.collect_logs('/nonexistent.log')
        self.assertEqual([], result)

        result = periodic.collect_logs('/test.log')
        self.assertEqual(data[10:], result)

    @mock.patch('hg_agent_periodic.periodic.logging')
    @mock.patch('hg_agent_periodic.periodic.validate_agent_config')
    def test_config_load_error(self, mock_validate, mock_logging):
        args = HeartbeatArgs('/hg-agent.cfg', '/version', '/test.log',
                             'endpoint')
        periodic.heartbeat_once(args)
        mock_logging.error.assert_called()
        # If load fails, we never reach validate
        mock_validate.assert_not_called()

    @mock.patch('hg_agent_periodic.periodic.logging')
    @mock.patch('hg_agent_periodic.periodic.get_version')
    def test_config_invalid(self, mock_version, mock_logging):
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                               invalid_key: "test"
                           '''))
        args = HeartbeatArgs('/hg-agent.cfg', '/version', '/test.log',
                             'endpoint')
        periodic.heartbeat_once(args)

        # If validation fails, we never reach version.
        mock_logging.error.assert_called()
        mock_version.assert_not_called()

    @mock.patch('hg_agent_periodic.periodic.logging')
    @mock.patch('hg_agent_periodic.periodic.collect_logs')
    def test_version_invalid(self, mock_collect, mock_logging):
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                           '''))
        args = HeartbeatArgs('/hg-agent.cfg', '/version', '/test.log',
                             'endpoint')
        periodic.heartbeat_once(args)

        # If version fails, we never reach collect_logs.
        mock_logging.error.assert_called()
        mock_collect.assert_not_called()

    @mock.patch('hg_agent_periodic.periodic.send_heartbeat')
    @mock.patch('hg_agent_periodic.periodic.platform')
    def test_heartbeat(self, mock_platform, mock_send):
        self.fs.CreateFile('/hg-agent.cfg',
                           contents=textwrap.dedent('''
                               api_key: "00000000-0000-0000-0000-000000000000"
                           '''))
        self.fs.CreateFile('/version', contents='0.1\n')
        data = ['line %.02d' % i for i in range(20)]
        self.fs.CreateFile('/test.log', contents='\n'.join(data) + '\n')
        args = HeartbeatArgs('/hg-agent.cfg', '/version', '/test.log',
                             'endpoint')
        periodic.heartbeat_once(args)
        mock_platform.platform.assert_called()
        mock_send.assert_called()

    @mock.patch('hg_agent_periodic.periodic.logging')
    def test_send_ok(self, mock_logging):
        endpoint = 'https://heartbeat_ok.hg.com/beat'
        with httmock.HTTMock(heartbeat_ok_mock):
            periodic.send_heartbeat(endpoint, '{"fake": "json"}')
        mock_logging.error.assert_not_called()

    @mock.patch('hg_agent_periodic.periodic.logging')
    def test_send_timeout(self, mock_logging):
        endpoint = 'https://heartbeat_timeout.hg.com/beat'
        with httmock.HTTMock(heartbeat_timeout_mock):
            periodic.send_heartbeat(endpoint, '{"fake": "json"}')
        mock_logging.error.assert_called()

    @mock.patch('hg_agent_periodic.periodic.logging')
    def test_send_auth_fail(self, mock_logging):
        endpoint = 'https://heartbeat_authfail.hg.com/beat'
        with httmock.HTTMock(heartbeat_authfail_mock):
            periodic.send_heartbeat(endpoint, '{"fake": "json"}')
        mock_logging.error.assert_called()

    @mock.patch('hg_agent_periodic.periodic.logging')
    def test_send_unhandled(self, mock_logging):
        endpoint = 'https://heartbeat_unhandled.hg.com/beat'
        with httmock.HTTMock(heartbeat_unhandled_mock):
            periodic.send_heartbeat(endpoint, '{"fake": "json"}')
        mock_logging.error.assert_called()

    @mock.patch('hg_agent_periodic.periodic.requests')
    def test_send_proxied(self, mock_requests):
        mock_response = mock.MagicMock(requests.Response)
        mock_requests.put.return_value = mock_response
        periodic.send_heartbeat('endpoint', '{"fake": "json"}')
        mock_requests.put.assert_called_once_with(mock.ANY,
                                                  json=mock.ANY,
                                                  timeout=mock.ANY)

        mock_requests.reset_mock()
        periodic.send_heartbeat('endpoint', '{"fake": "json"}',
                                proxies={'https': 'dummy'})
        mock_requests.put.assert_called_once_with(mock.ANY,
                                                  json=mock.ANY,
                                                  timeout=mock.ANY,
                                                  proxies={'https': 'dummy'})


class TestMiscFunctions(unittest.TestCase):

    def test_get_args(self):
        args = periodic.get_args([])
        self.assertFalse(args.debug)
        self.assertTrue(args.config_interval > 0)
        self.assertTrue(args.heartbeat_interval > 0)

    def test_create_shutdown_event(self):
        s = periodic.create_shutdown_event()
        self.assertFalse(s.is_set())
        os.kill(os.getpid(), signal.SIGTERM)
        self.assertTrue(s.is_set())

    @mock.patch('hg_agent_periodic.periodic.time.time')
    @mock.patch('hg_agent_periodic.periodic.time.sleep')
    @mock.patch('hg_agent_periodic.periodic.logging')
    def test_periodic_task(self, mock_logger, mock_sleep, mock_time):
        # We mock out some period of 6 seconds.
        mock_time.side_effect = [10.0, 11.0, 12.0, 13.0, 14.0, 15.0, 16.0]

        # Gives our mock `func` a `__name__` attribute for logging.
        def dummy():
            pass
        func = mock.Mock(spec=dummy)

        # Expect to call this once at the start + twice in 5s at 2s intervals.
        # To test the exception path, have the last call throw.
        func.side_effect = [True, True, Exception('test')]

        # Loop 6 times before shutdown.
        shutdown = mock.create_autospec(threading.Event())
        shutdown.is_set.side_effect = 5 * [False] + [True]

        periodic.periodic_task(func, None, 2, shutdown)
        mock_logger.exception.assert_called()
        self.assertEqual(func.call_count, 3)

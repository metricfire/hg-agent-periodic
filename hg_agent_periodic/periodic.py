# hg-agent-periodic
#
# A "sidecar" for `hg-agent`, managing user (re)configuration and other
# periodic tasks.

import argparse
import datetime
import logging
import os
import platform
import requests
import signal
import socket
import threading
import time
import uuid

import diamond.collector
import jinja2
import jsonschema
import tailer
import yaml

from supervisor import supervisorctl


class ValidationError(Exception):
    pass


class LoadFileError(Exception):
    pass


def load_file(name):
    '''Load a file from disk or raise a `LoadFileError` exception.'''
    try:
        with open(name) as f:
            data = f.read()
        return data
    except (OSError, IOError) as e:
        raise LoadFileError(str(e))


# JSON schema for `hg-agent` configuration
schema = {
    'type': 'object',
    'description': 'hg-agent configuration',
    'properties': {
        'api_key': {
            'type': 'string',
            'description': 'The user\'s HG API key'
        },
        'endpoint': {
            'type': 'string',
            'format': 'hostname',
            'description': 'Carbon endpoint for Diamond to send metrics to'
        },
        'https_proxy': {
            'type': 'string',
            'format': 'uri',
            'description': 'An HTTPS proxy to use for `heartbeat` messages'
        },
        'endpoint_url': {
            'type': 'string',
            'format': 'uri',
            'description': 'HTTP API endpoint for metric forwarding to HG'
        },
        'tcp_port': {
            'type': 'integer',
            'description': "Port for TCP Metric Receiver to listen on"
        },
        'udp_port': {
            'type': 'integer',
            'description': "Port for UDP Metric Receiver to listen on"
        },
        'spool_rotatesize': {
            'type': 'integer',
            'description': "Max bytes for a spool file before\
                            rotation for the metric receivers"
        },
        'max_spool_count': {
            'type': 'integer',
            'description': 'Max number of spool files to keep on disk'
        },
        'max_batch_size': {
            'type': 'integer',
            'description': 'Max number of metrics to forward in a batch'
        },
        'batch_timeout': {
            'type': 'integer',
            'description': 'Max time to flush the current metric batch'
        },
        'mongodb': {
            'type': 'object',
            'description': 'MongoDB collector configuration',
            'properties': {
                'enabled': {'type': 'boolean'},
                'host': {'type': 'string'},
                'port': {'type': 'integer'},
                'user': {'type': 'string'},
                'passwd': {'type': 'string'},
                'databases': {'type': 'string'},
                'ignore_collections': {'type': 'string'},
                'collection_sample_rate': {'type': 'integer'},
                'network_timeout': {'type': 'integer'},
                'simple': {'type': 'boolean'},
                'translate_collections': {'type': 'boolean'},
                'ssl': {'type': 'boolean'},
                'replica': {'type': 'boolean'},
                'replset_node_name': {'type': 'string'},
            },
        },
        'custom_prefix': {
            'type': 'string',
            'description': 'A custom prefix for metrics, instead of "hg_agent"'
        },
        'hostname_method': {
            'type': 'string',
            'description': 'Method to use for hostnames, per Diamond config'
        },
        'heartbeat_url': {
            'type': 'string',
            'format': 'uri',
            'description': 'Endpoint for Hosted Graphite heartbeat service'
        },
        'CPUCollector': {
            'type': 'boolean',
            'description': 'enable/disable CPU Collector'
        },
        'DiskSpaceCollector': {
            'type': 'boolean',
            'description': 'enable/disable DiskSpaceCollector'
        },
        'DiskUsageCollector': {
            'type': 'boolean',
            'description': 'enable/disable Disk Usage Collector'
        },
        'LoadAverageCollector': {
            'type': 'boolean',
            'description': 'enable/disable DiskSpaceCollector'
        },
        'MemoryCollector': {
            'type': 'boolean',
            'description': 'enable/disable Memory Collector'
        },
        'NetworkCollector': {
            'type': 'boolean',
            'description': 'enable/disable Memory Collector'
        },
        'SockstatCollector': {
            'type': 'boolean',
            'description': 'enable/disable Sockstat Collector'
        },
        'VMStatCollector': {
            'type': 'boolean',
            'description': 'enable/disable VMStat Collector'
        },
        'SelfCollector': {
            'type': 'boolean',
            'description': 'enable/disable Self Collector'
        }
    },
    'required': ['api_key'],
    'additionalProperties': False
}


def validate_agent_config(data):
    '''Validate a config against the config schema.
    Follows jsonschema's slightly strange convention of just passing
    'silently' (i.e. return None) if validation succeeds.
    '''
    try:
        jsonschema.validate(data, schema,
                            format_checker=jsonschema.FormatChecker())
    except jsonschema.ValidationError as e:
        raise ValidationError(e.message)

    try:
        uuid.UUID(data['api_key'], version=4)
    except ValueError as e:
        raise ValidationError('api_key: %s' % e)


def gen_diamond_config(context):
    '''Generate a `diamond` config from a `hg-agent` config.
    Uses templates/diamond.conf'''
    env = jinja2.Environment(loader=jinja2.PackageLoader('hg_agent_periodic',
                                                         'templates'),
                             lstrip_blocks=True)

    def isoformat(value):
        return value.isoformat()
    env.filters['isoformat'] = isoformat

    # Hack to work around PyInstaller's trouble with using pkg_resources,
    # which breaks jinja2's `get_template` method.
    # Cf. https://github.com/pyinstaller/pyinstaller/issues/1898
    package_dir, _ = os.path.split(__file__)
    template_path = os.path.join(package_dir, 'templates', 'diamond.conf')
    with open(template_path) as f:
        template_data = f.read()

    template = env.from_string(template_data)
    context['now'] = datetime.datetime.utcnow()
    return template.render(context)


def generated_configs_differ(new, old, ignore='Generated'):
    '''Compare `new` with `old`, eliding lines including `ignore`.'''
    new_lines = [line for line in new.split('\n') if ignore not in line]
    old_lines = [line for line in old.split('\n') if ignore not in line]
    return new_lines != old_lines


def restart_process(args, process):
    '''Restart a process under Supervisor.'''

    # NB: this prints out the usual supervisor stop/start to stdout, but
    # that's a small price to pay for the simplicity of just invoking
    # supervisorctl here; otherwise we'd need to replicate a lot of its
    # `Controller` class code.

    # One downside is that this is "fire and forget": this code does not
    # raise any useful errors for us if things goes wrong. Still, logs
    # from stdout should have data, and we need to rely on supervisord
    # working correctly in either case.
    options = supervisorctl.ClientOptions()
    options.realize(['--configuration', args.supervisor_config])
    controller = supervisorctl.Controller(options)
    controller.onecmd('restart %s' % process)


def load_config(source, filename):
    '''Return, parsed and validated, the config dict from `filename` or `None`.
    Log stating `source` of the error if there's a problem.'''
    try:
        data = load_file(filename)
        agent_config = yaml.load(data)
        validate_agent_config(agent_config)
    except LoadFileError as e:
        logging.error('%s loading %s: %s', source, filename, e)
        return None
    except ValidationError as e:
        logging.error('%s in %s: %s', source, filename, e)
        return None
    return agent_config


# Keep track of config values that may change between iterations of
# `config_once` (requiring action). We could make `config_once` a callable
# object & track it there, but this is somewhat simpler for now.
old_config = {}


def remember_config(new):
    '''Update the module-global config with `new`'''
    old_config.clear()
    old_config.update(new)


def config_changed(cfg1, cfg2, key):
    return cfg1.get(key) != cfg2.get(key)


def config_once(args):
    '''Load config, gen diamond config, and restart diamond if changed.'''
    agent_config = load_config('config', args.config)
    if agent_config is None:
        return

    if old_config:
        if (config_changed(old_config, agent_config, 'endpoint_url') or
                config_changed(old_config, agent_config, 'api_key')):
            logging.info('Forwarder/receiver configuration changed, '
                         'restarting.')
            restart_process(args, 'forwarder')
            restart_process(args, 'receiver')

    new_diamond = gen_diamond_config(agent_config)
    try:
        old_diamond = load_file(args.diamond_config)
    except LoadFileError:
        old_diamond = ''

    if generated_configs_differ(new_diamond, old_diamond):
        logging.info('Diamond configuration changed, restarting.')
        try:
            with open(args.diamond_config, 'w') as f:
                f.write(new_diamond)
            restart_process(args, 'diamond')
        except BaseException:
            logging.exception('Writing & restarting: %s', args.diamond_config)
    else:
        logging.info('No change in Diamond configuration')

    remember_config(agent_config)


def get_primary_ip():
    '''Get "primary" IP.

    This is the IP the machine uses to talk to the 'net. As such, it could be
    a local NAT address or whatever, but given that we use it primarily as an
    identifier, it should still be meaningful to the user.

    This hack is from http://stackoverflow.com/questions/166506.
    '''
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(('8.8.8.8', 53))
    ip, port = s.getsockname()
    return ip


def get_version(filename):
    '''Get the version from a `hg-agent` version file.'''
    try:
        data = load_file(filename)
        return data.strip()
    except LoadFileError as e:
        logging.error('loading %s: %s', filename, e)
        return None


def collect_logs(name):
    '''Grab the last 10 lines of logs from a logfile.

    Initially that will be this process, using the logs produced by
    supervisord, but we may add e.g. diamond's later, hence this more
    generic function.
    '''
    try:
        with open(name) as f:
            lines = tailer.tail(f, 10)
    except (OSError, IOError) as e:
        logging.error('collect_logs for %s: %s', name, e)
        lines = []

    return lines


def send_heartbeat(endpoint, data, proxies=None):
    '''Send metadata to the `heartbeat` service.'''
    try:
        # Use proxies *explicitly* here only if configured; this should allow
        # setting proxies by environment variable (`HTTPS_PROXY`) to also work.
        if proxies:
            r = requests.put(endpoint, json=data, timeout=10, proxies=proxies)
        else:
            r = requests.put(endpoint, json=data, timeout=10)
        r.raise_for_status()
    except requests.exceptions.Timeout:
        logging.error('heartbeat timed out to %s', endpoint)
    except requests.exceptions.HTTPError as e:
        logging.error('heartbeat HTTP error to %s: %s', endpoint, e)
    except requests.exceptions.RequestException as e:
        logging.error('heartbeat unhandled exception to %s: %s', endpoint, e)


def heartbeat_once(args):
    '''Send heartbeat metadata to Hosted Graphite.'''
    agent_config = load_config('heartbeat', args.config)
    if agent_config is None:
        return

    version = get_version(args.agent_version)
    if version is None:
        return

    logs = collect_logs(args.periodic_logfile)
    messages = '\n'.join(logs)

    hostname_method = agent_config.get('hostname_method', 'smart')

    beat_data = {
        'key': agent_config['api_key'],
        'timestamp': int(time.time()),
        'version': version,
        'hostname': diamond.collector.get_hostname({}, method=hostname_method),
        'ip': get_primary_ip(),
        'platform': platform.platform(),
        'ok': 'ERROR' not in messages,
        'messages': messages
    }

    https_proxy = agent_config.get('https_proxy')
    if https_proxy:
        proxies = {'https': https_proxy}
    else:
        proxies = None

    heartbeat_url = agent_config.get('heartbeat_url', args.heartbeat)
    send_heartbeat(heartbeat_url, beat_data, proxies=proxies)


def periodic_task(func, args, interval, shutdown):
    '''Run `func(args)` every `interval` seconds.'''

    next_run = 0
    while not shutdown.is_set():
        now = time.time()
        if now >= next_run:
            try:
                func(args)
            except BaseException:
                logging.exception('Unhandled exception in %s', func.__name__)
            next_run = now + interval
        time.sleep(1)


def init_log(name, debug):
    '''Configure logging.'''
    logger = logging.getLogger()
    if debug:
        logger.setLevel(logging.DEBUG)
    else:
        logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s ' + name + '[%(process)d] %(levelname)s %(message)s'))
    logger.addHandler(handler)


def create_shutdown_event():
    '''Setup signal handlers and return a threading.Event.'''
    shutdown = threading.Event()

    def sighandler(number, frame):
        if number == signal.SIGINT or number == signal.SIGTERM:
            shutdown.set()

    signal.signal(signal.SIGINT, sighandler)
    signal.signal(signal.SIGTERM, sighandler)
    return shutdown


def get_args(argv=None):
    '''Parse out and returns script args.'''
    description = 'Periodic tasks script for the Hosted Graphite agent.'
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Use debug logging.')
    parser.add_argument('--config', default='/etc/opt/hg-agent/hg-agent.conf',
                        help='Path to overall hg-agent config.')
    parser.add_argument('--agent-version', default='/opt/hg-agent/version',
                        help='Path to hg-agent version file.')
    parser.add_argument('--supervisor-config',
                        default='/etc/opt/hg-agent/supervisor.conf',
                        help='Path to supervisor config.')
    parser.add_argument('--diamond-config',
                        default='/var/opt/hg-agent/diamond.conf',
                        help='Path to managed diamond config.')
    parser.add_argument('--heartbeat',
                        default='https://heartbeat.hostedgraphite.com/beat',
                        help='URI for Hosted Graphite heartbeat service.')
    parser.add_argument('--periodic-logfile',
                        default='/var/log/hg-agent/periodic.log',
                        help='Path to logs of this process (via supervisord).')
    parser.add_argument('--config-interval', type=int, default=10,
                        help='Seconds between config check & update.')
    parser.add_argument('--heartbeat-interval', type=int, default=60,
                        help='Seconds between heartbeats.')
    args = parser.parse_args(args=argv)
    return args


def main():
    args = get_args()
    init_log('hg-agent-periodic', args.debug)

    shutdown = create_shutdown_event()

    config = threading.Thread(
        target=periodic_task,
        name='hg-agent-periodic.config_manager',
        args=(config_once, args, args.config_interval, shutdown))

    heartbeat = threading.Thread(
        target=periodic_task,
        name='hg-agent-periodic.heartbeat_manager',
        args=(heartbeat_once, args, args.heartbeat_interval, shutdown))

    threads = [config, heartbeat]

    for t in threads:
        t.start()

    while not shutdown.is_set():
        time.sleep(5)

    logging.debug('Caught shutdown event')

    for t in threads:
        while t.is_alive():
            t.join(timeout=0.1)

    logging.info('Shutting down.')


if __name__ == '__main__':
    main()

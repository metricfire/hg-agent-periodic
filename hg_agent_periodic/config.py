# hg-agent-config
#
# Generate config for `hg-agent`.
# Support script for initial install.

import argparse
import logging
import yaml

from hg_agent_periodic import periodic


def get_args(argv=None):
    '''Parse out and returns script args.'''
    description = 'Generate config for `hg-agent`.'
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Use debug logging.')
    parser.add_argument('--config', default='/etc/opt/hg-agent/hg-agent.conf',
                        help='Path to hg-agent config.')
    parser.add_argument('--api-key',
                        default='00000000-0000-0000-0000-000000000000',
                        help='Hosted Graphite API key.')
    parser.add_argument('--endpoint',
                        default='localhost',
                        help='HG Agent local Graphite endpoint.')
    parser.add_argument('--endpoint-url',
                        default='',
                        help='Hosted Graphite sink API endpoint.')
    parser.add_argument('--heartbeat-url',
                        default='',
                        help='Hosted Graphite heartbeat metadata endpoint.')
    args = parser.parse_args(args=argv)
    return args


def main():
    args = get_args()
    periodic.init_log('hg-agent-config', args.debug)

    try:
        agent_config = {
            'api_key': args.api_key,
        }
        if args.endpoint_url:
            agent_config['endpoint_url'] = args.endpoint_url
        if args.heartbeat_url:
            agent_config['heartbeat_url'] = args.heartbeat_url

        periodic.validate_agent_config(agent_config)
        data = yaml.dump(agent_config, default_flow_style=False)
        with open(args.config, 'w') as f:
            f.write(data)
    except periodic.ValidationError as e:
        logging.error('generating %s: %s', args.config, e)
    except (OSError, IOError) as e:
        logging.error('writing %s: %s', args.config, e)
    except Exception:
        logging.exception('unhandled exception')


if __name__ == '__main__':
    main()

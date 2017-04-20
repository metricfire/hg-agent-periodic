# hg-agent-diamond-config
#
# Generate `diamond` config from `hg-agent` config.
# Support script for initial install.

import argparse
import logging
import yaml

from hg_agent_periodic import periodic


def get_args(argv=None):
    '''Parse out and returns script args.'''
    description = 'Generate diamond config for `hg-agent`.'
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Use debug logging.')
    parser.add_argument('--config', default='/etc/opt/hg-agent/hg-agent.conf',
                        help='Path to overall hg-agent config.')
    parser.add_argument('--diamond-config',
                        default='/var/opt/hg-agent/diamond.conf',
                        help='Path to managed diamond config.')
    args = parser.parse_args(args=argv)
    return args


def main():
    args = get_args()
    periodic.init_log('hg-agent-diamond-config', args.debug)

    try:
        data = periodic.load_file(args.config)
        agent_config = yaml.load(data)
        periodic.validate_agent_config(agent_config)
        new_diamond = periodic.gen_diamond_config(agent_config)
        with open(args.diamond_config, 'w') as f:
            f.write(new_diamond)
    except periodic.LoadFileError as e:
        logging.error('config loading %s: %s', args.config, e)
    except periodic.ValidationError as e:
        logging.error('config in %s: %s', args.config, e)
    except (OSError, IOError) as e:
        logging.error('writing %s: %s', args.diamond_config, e)
    except:
        logging.exception('unhandled exception')


if __name__ == '__main__':
    main()

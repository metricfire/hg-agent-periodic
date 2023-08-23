#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

requirements = [
    'Jinja2<=3.0.3',
    'jsonschema==3.2.0',
    'requests<=2.27.1',
    'rfc3987<=1.3.8',  # For 'uri' format validation in jsonschema
    'supervisor<=4.2.4',
    'tailer<=0.4.1',
    'PyYAML<=6.0.1',
    'diamond @ git+ssh://git@github.com/hostedgraphite/Diamond.git@master',
]

setup(
    name='hg-agent-periodic',
    version='2.0.0',
    description='Periodic tasks script for the Hosted Graphite agent.',
    long_description='Periodic tasks script for the Hosted Graphite agent.',
    author='Metricfire',
    author_email='maintainer@metricfire.com',
    url='https://github.com/metricfire/hg-agent-periodic',
    packages=find_packages(),
    package_data={'hg_agent_periodic': ['templates/*']},
    scripts=[
        'bin/hg-agent-periodic',
        'bin/hg-agent-config',
        'bin/hg-agent-diamond-config',
    ],
    install_requires=requirements,
    test_suite='tests',
    include_package_data=True,
    zip_safe=False,
    keywords='hg-agent-periodic',
    classifiers=[],
)

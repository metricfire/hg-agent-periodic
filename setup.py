#!/usr/bin/env python
# -*- coding: utf-8 -*-

from setuptools import setup, find_packages

requirements = [
    'diamond==4.0.451',
    'jinja2==2.10.1',
    'jsonschema==2.6.0',
    'requests==2.22.0',
    'rfc3987==1.3.7',  # For 'uri' format validation in jsonschema
    'supervisor==3.3.1',
    'tailer==0.4.1',
    'PyYAML==5.4',
    'wheel',
]

test_requirements = [
    'httmock',
    'pyfakefs',
    'coverage',
    'mock',
]

dependency_links = [
]

setup(
    name='hg-agent-periodic',
    version='1.1.0',
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
    dependency_links=dependency_links,
    tests_require=test_requirements,
    test_suite='tests',
    include_package_data=True,
    zip_safe=False,
    keywords='hg-agent-periodic',
    classifiers=[
    ],
)

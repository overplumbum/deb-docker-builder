#!/usr/bin/env python2.7
import argparse
import os
import re
from subprocess import call, check_output, check_call, list2cmdline, PIPE
import sys


class Tool(object):
    @staticmethod
    def version(txt, limit=2):
        return tuple(map(int, txt.split('.')[:limit]))

    @staticmethod
    def panic(msg, *args, **kw):
        if len(args) or len(kw):
            msg = msg.format(*args, **kw)
        sys.stderr.write(msg + '\n')
        sys.exit(1)

    @staticmethod
    def log(msg, *args, **kw):
        if len(args) or len(kw):
            msg = msg.format(*args, **kw)
        print(msg)

    @staticmethod
    def build_deps():
        with open('debian/control') as fp:
            content = fp.read()
        m = re.search(r'\nBuild-Depends:(.*?)\n[a-zA-Z0-9\-_]+:', content, re.S)
        if m is None:
            Tool.log('no build dependencies found')
            return []
        build_deps_raw = re.split(r'(?:\s*,\s*)+', m.group(1))
        result = []
        for dep in build_deps_raw:
            if dep == '':
                continue
            m = re.match(r'^\s*([a-zA-Z0-9_\-.]+)\s*(?:[(][^\)]+[)])?\s*$', dep)
            if m is None:
                Tool.panic('failed to parse build dependencies entry: "{}"', dep)
            pkg = m.group(1)
            result.append(pkg)
        return result

    def generate_dockerfile(self):
        if os.path.exists('Dockerfile'):
            self.panic('Dockerfile already exists, can\'t continue')
        if os.path.exists('.dockerignore'):
            self.panic('.dockerignore already exists, can\'t continue')

        lines = [
            'FROM ' + self.base_image,
            'RUN sed -i -e "s/archive.ubuntu.com/mirror.yandex.ru/g" /etc/apt/sources.list',
            'RUN apt-get update -qq && export DEBIAN_FRONTEND=noninteractive && apt-get upgrade -qq && apt-get install -qq devscripts debhelper',
            'RUN apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -qyV {}'.format(
                ' '.join(sorted(self.build_deps()))
            ),
            'ADD . /root/source',
            'VOLUME ["/results"]',
        ]
        with open('Dockerfile', 'w') as fp:
            fp.write('\n'.join(lines) + '\n')
        if os.path.exists('.gitignore'):
            ignore_base = open('.gitignore').read().strip().splitlines()
        else:
            ignore_base = []
        ignore_base.append('.git')
        with open('.dockerignore', 'w') as fp:
            fp.write('\n'.join(ignore_base))
            fp.write('\n')

    def build_cmd(self):
        build_cmd = [
            'cd /root/source',
        ]
        if self.pre_deb_build:
            build_cmd.append(self.pre_deb_build)
        build_cmd += [
            'cp -f /bin/true /usr/bin/debsign',
            'debuild --no-lintian -b',
            'cp -v ../*_*.changes ../*_*.deb /results/',
        ]
        return build_cmd

    def __init__(self):
        parser = argparse.ArgumentParser()
        # parser.add_argument(
        #     '--docker-pre-add',
        #     help='docker command to be added to Dockerfile just before deps intallation'
        #          ' (you can add custom apt repos here)'
        # )  # todo multiple
        # parser.add_argument(
        #     '--docker-post-add',
        #     help='docker command to be added to Dockerfile end'
        #          ' (you can add custom apt repos here)'
        # )  # todo multiple
        parser.add_argument(
            '--pre-deb-build',
            help='optional script to run just before debuild'
                 ' (you can update changelog via dch)'
        )
        parser.add_argument(
            '--results-dir',
            help='where to put resulting *.deb & *.changes files',
            default='./results/',
        )
        parser.add_argument(
            '--base-image',
            help='base container image',
            default='debian:jessie',
        )
        args = parser.parse_args()

        self.base_image = args.base_image
        self.pre_deb_build = args.pre_deb_build
        self.results_dir = args.results_dir

    def run(self):
        container_tag = image_tag = 'demo'

        # build env preparation
        self.generate_dockerfile()
        try:
            check_call(('docker', 'build', '-t', image_tag, '.'))
        finally:
            os.remove('Dockerfile')
            if os.path.exists('.dockerignore'):
                os.remove('.dockerignore')

        if 0 == call(('docker', 'rm', '-f', container_tag), stderr=PIPE):
            self.log('container "{}" from previous build removed', container_tag)

        # debian package build
        check_call((
            'docker', 'run',
            '--name', container_tag,
            '--volume', '/results',
            image_tag,
            'sh', '-c', ' && '.join(self.build_cmd()),
        ))
        if not os.path.exists(self.results_dir):
            os.makedirs(self.results_dir)

        # build results extraction
        check_call(
            list2cmdline((
                'docker', 'run',
                '--rm',
                '--workdir', '/results/',
                '--volumes-from', container_tag,
                'busybox',
                'sh', '-c', 'tar -c *.deb *.changes',
            )) + ' | ' + list2cmdline((
                'tar', '-C', self.results_dir, '-xv'
            )), shell=True)

        check_call(('docker', 'rm', '-f', container_tag))
        self.log('all done, results are in {}', self.results_dir)


if __name__ == '__main__':
    Tool().run()

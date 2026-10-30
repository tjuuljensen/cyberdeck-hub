#!/usr/bin/env python3
"""Read-only root checks of firewall access inside the live web mount namespace."""
import argparse
import json
import os
import re
import socket
import subprocess
import sys


HELPER = '/usr/local/lib/cyberdeck/admin-helper.py'


def run(*args):
    result = subprocess.run(args, text=True, capture_output=True, timeout=30, check=False)
    if result.returncode:
        raise RuntimeError(f'{args[0]} failed: {result.stderr.strip() or result.stdout.strip()}')
    return result.stdout.strip()


def verify(expected_host):
    if os.geteuid() != 0:
        raise RuntimeError('Runtime verification must run as root.')
    if (not re.fullmatch(r'[a-z][a-z0-9-]{0,61}[a-z0-9]|[a-z]', expected_host)
            or socket.gethostname().split('.')[0] != expected_host):
        raise RuntimeError('Runtime verification hostname does not match the expected host.')
    pid = run('systemctl', 'show', '--property=MainPID', '--value', 'cyberdeck-web.service')
    if not pid.isdecimal() or int(pid) <= 0:
        raise RuntimeError('The web service has no running main process.')
    # Use the actual service mount namespace, including ProtectSystem=strict,
    # rather than testing only the service account outside its sandbox.
    command = ('nsenter', '--target', pid, '--mount', '--',
               'runuser', '-u', 'cyberdeck', '--', 'sudo', '-n')
    status = json.loads(run(*command, HELPER, 'firewall-status'))
    for action in ('firewall-enable', 'firewall-disable'):
        # sudo -l checks authorization without executing either change action.
        run(*command, '-l', '--', HELPER, action)
    if not isinstance(status, dict) or any(type(status.get(key)) is not bool
                                          for key in ('available', 'enabled', 'active')):
        raise RuntimeError('Firewall status has an invalid response.')
    if status['enabled']:
        if not status['available'] or not status['active']:
            raise RuntimeError('The enabled firewall is unavailable or has no active rules: ' + str(status))
        run('systemctl', 'is-enabled', '--quiet', 'cyberdeck-firewall.service')
        run('systemctl', 'is-active', '--quiet', 'cyberdeck-firewall.service')
    elif status['active']:
        raise RuntimeError('Firewall rules are active although the module is disabled.')
    return status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-host', required=True)
    args = parser.parse_args()
    try:
        print('Web service firewall access verified: ' + json.dumps(verify(args.expected_host)))
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

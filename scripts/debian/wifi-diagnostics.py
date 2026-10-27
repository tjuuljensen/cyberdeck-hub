#!/usr/bin/env python3
"""Inspect wireless adapter visibility and offer an opt-in Debian firmware install."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys


def run(args: list[str], *, timeout: int = 20) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(args, check=False, text=True, capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as exc:
        return subprocess.CompletedProcess(args, 1, '', str(exc))


def pci_devices() -> list[dict[str, str | None]]:
    if not shutil.which('lspci'):
        return []
    output = run(['lspci', '-D', '-nnk']).stdout
    devices = []
    current: dict[str, str | None] | None = None
    wireless_class = False
    for line in output.splitlines():
        if line and not line[0].isspace():
            if current and (wireless_class or re.search(r'wireless|wi-fi|802\.11', current['description'] or '', re.I)):
                devices.append(current)
            match = re.match(r'^(\S+)\s+[^:]+:\s*(.*)$', line)
            current = {'address': match.group(1) if match else None,
                       'description': match.group(2) if match else line, 'driver': None}
            wireless_class = bool(re.search(r'network controller\s*\[0280\]', line, re.I))
        elif current:
            match = re.match(r'\s*Kernel driver in use:\s*(\S+)', line)
            if match:
                current['driver'] = match.group(1)
    if current and (wireless_class or re.search(r'wireless|wi-fi|802\.11', current['description'] or '', re.I)):
        devices.append(current)
    return devices


def interfaces() -> list[tuple[str, str]]:
    result = []
    for entry in sorted(Path('/sys/class/net').glob('*')):
        if entry.name == 'lo':
            continue
        if (entry / 'wireless').exists() or (entry / 'phy80211').exists():
            driver = None
            try:
                driver = (entry / 'device' / 'driver').resolve().name
            except (OSError, RuntimeError):
                pass
            result.append((entry.name, driver or 'unknown'))
    return result


def firmware_errors() -> list[str]:
    result = run(['dmesg', '--color=never'])
    if result.returncode:
        return []
    lines = [line.strip() for line in result.stdout.splitlines()
             if re.search(r'firmware.*(failed|missing|not found)|failed to load.*firmware', line, re.I)]
    return lines[-8:]


def usb_devices() -> list[str]:
    if not shutil.which('lsusb'):
        return []
    result = run(['lsusb'])
    return result.stdout.splitlines()


def inspect() -> tuple[list[dict[str, str | None]], list[tuple[str, str]], list[str]]:
    return pci_devices(), interfaces(), firmware_errors()


def install_firmware() -> int:
    if platform.system() != 'Linux' or not Path('/etc/debian_version').is_file():
        print('Firmware installation is supported here only on Debian-based Linux.', file=sys.stderr)
        return 2
    if os.geteuid() != 0:
        print('Run this option with sudo so apt can install packages.', file=sys.stderr)
        return 2
    if not shutil.which('apt-get'):
        print('apt-get was not found; install the matching firmware package for your distribution.', file=sys.stderr)
        return 2
    print('Installing Debian firmware-linux. apt will show the packages and ask before continuing.')
    update = run(['apt-get', 'update'], timeout=600)
    if update.stdout:
        print(update.stdout, end='')
    if update.stderr:
        print(update.stderr, file=sys.stderr, end='')
    if update.returncode:
        print('Package index update failed. Check network access and Debian non-free-firmware sources.', file=sys.stderr)
        return update.returncode
    install = run(['apt-get', 'install', 'firmware-linux'], timeout=1800)
    if install.stdout:
        print(install.stdout, end='')
    if install.stderr:
        print(install.stderr, file=sys.stderr, end='')
    return install.returncode


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-firmware', action='store_true',
                        help='on Debian, update apt indexes and interactively install firmware-linux')
    args = parser.parse_args(argv)
    if args.install_firmware:
        return install_firmware()

    print('Wireless adapter diagnostics')
    print(f'Host: {platform.system()} {platform.release()}')
    if not shutil.which('lspci'):
        print('PCI inventory: lspci is unavailable (install pciutils for PCI identification).')
    devices, wifi_interfaces, errors = inspect()
    print('\nPCI wireless/network controllers:')
    if devices:
        for device in devices:
            print(f"  {device['address'] or 'unknown'}: {device['description']}")
            print(f"    Kernel driver: {device['driver'] or 'not bound'}")
    else:
        print('  None reported by lspci.')
    print('\nUSB devices (inspect vendor/model for an unrecognized Wi-Fi adapter):')
    usb = usb_devices()
    if usb:
        for line in usb:
            print(f'  {line}')
    elif not shutil.which('lsusb'):
        print('  lsusb is unavailable (install usbutils for USB identification).')
    else:
        print('  None reported.')
    print('\nKernel wireless interfaces:')
    if wifi_interfaces:
        for name, driver in wifi_interfaces:
            print(f'  {name} (driver: {driver})')
    else:
        print('  None found in /sys/class/net.')
    nmcli = shutil.which('nmcli')
    if nmcli:
        result = run([nmcli, '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status'])
        wifi_rows = [line for line in result.stdout.splitlines() if ':wifi:' in line]
        print('\nNetworkManager Wi-Fi devices:')
        print('\n'.join(f'  {line}' for line in wifi_rows) if wifi_rows else '  None reported.')
    else:
        print('\nNetworkManager: nmcli is unavailable.')
    print('\nFirmware errors in kernel log:')
    if errors:
        for line in errors:
            print(f'  {line}')
    else:
        print('  None found (or kernel log access is restricted). Try sudo for dmesg access.')
    if not wifi_interfaces:
        print('\nNext steps: check that the adapter is seated/connected; identify USB devices with lsusb;')
        print('check firmware errors with sudo dmesg | grep -i firmware; then install the matching')
        print('vendor firmware package or driver for the adapter chipset. lspci alone cannot identify USB Wi-Fi.')
    elif not nmcli or not any(':wifi:' in line for line in run([nmcli, '-t', '-f', 'DEVICE,TYPE,STATE', 'device', 'status']).stdout.splitlines()):
        print('\nThe kernel exposes Wi-Fi, but NetworkManager does not. Check that NetworkManager is running')
        print('and that the interface is not blocked: run rfkill list and nmcli device status.')
    print('\nFor Debian, an optional broad firmware package install is available with:')
    print('  sudo python3 scripts/debian/wifi-diagnostics.py --install-firmware')
    print('This does not replace chipset-specific driver installation; reboot may be needed afterward.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

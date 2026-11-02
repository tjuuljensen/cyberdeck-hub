# Guided Debian USB bootstrap

This guide prepares custom Debian 13 installer media that includes the Cyberdeck Hub source kit and first-boot setup. It does not write a USB device automatically. Debian installation still asks you to choose the target disk and confirm partitioning. Back up anything you need before installing.

## Windows guided path

Use Windows PowerShell 5.1 or later, Python 3, and Rufus. From a clean checkout of this repository, run:

```powershell
.\scripts\debian\prepare-usb-windows.ps1
```

The script downloads the current Debian 13 amd64 netinst image and its official SHA-512 list when they are not supplied, verifies the image, builds a Cyberdeck install kit from this checkout, and prepares a Rufus overlay. Review `cyberdeck-media-manifest.json` in the output directory. It records the source revision, source-tree cleanliness, Debian image checksum, and install-kit checksum.

In Rufus, select the verified Debian ISO, choose **ISO Image mode** if prompted, then use **Ctrl** while clicking **SELECT** to choose `cyberdeck-preseed-overlay.zip`. Check the selected USB device carefully and approve Rufus's erase/write prompt. The preparation script does not erase media.

To use a previously downloaded ISO and matching Debian checksum list:

```powershell
.\scripts\debian\prepare-usb-windows.ps1 `
  -IsoPath 'D:\ISO\debian-13.x.y-amd64-netinst.iso' `
  -ChecksumsPath 'D:\ISO\SHA512SUMS' `
  -OutputDirectory 'D:\Cyberdeck USB'
```

See `Get-Help .\scripts\debian\prepare-usb-windows.ps1 -Full` for all parameters. Existing generated output is not overwritten unless `-Overwrite` is supplied and its manifest is valid.

## Linux media path

The Linux ISO builder requires `xorriso` and Python 3. Provide an official Debian 13 amd64 netinst ISO and the matching `SHA512SUMS` file:

```sh
bash scripts/debian/create-usb-linux.sh \
  --iso /path/to/debian-13.x.y-amd64-netinst.iso \
  --checksums /path/to/SHA512SUMS \
  --output-dir /path/to/cyberdeck-media
```

This prepares and verifies a custom ISO but does not write a disk. To write it, add `--write --device /dev/sdX` with the whole removable USB device. The script rejects partitions, mounted devices, and the disk backing the running root filesystem, then requires the exact typed confirmation `ERASE /dev/sdX`.

## Install Debian and run Hub setup

Boot the target computer from the USB. Debian's installer asks for language and keyboard, then guides you through country, target disk/partitioning, administrator account, and password. The preseed suggests hostname `cyberdeck` and username `operator`; do not use `cyberdeck` as the login account because that name is reserved for the Hub service. No disk or password is preselected.

After Debian reboots, sign in on the local console and accept the Cyberdeck setup prompt. It previews the Hub install and requires typing `APPLY` before making host changes. Online setup installs CyberChef automatically and leaves its service disabled. Setup can be retried from SSH with:

```sh
sudo /usr/local/sbin/cyberdeck-firstboot-install --retry
```

The staged kit remains under `/var/lib/cyberdeck-bootstrap` for recovery and
retry. Each retry refreshes the extracted installer source from the staged
archive, so replacing the archive with a newer kit does not leave an older
extracted installer in use. For a later update to an already installed Hub,
follow the complete source-kit preview and apply workflow in the [manual Debian
install guide](debian-install.md); patching only the web application does not
update the privileged helper or sudoers allowlist. After setup, create the Hub
administrator account in a browser. Open `http://cyberdeck.local/` for
certificate guidance; compare the CA fingerprint shown by the server before
trusting the certificate. If `.local` does not resolve, use the server IP on
the same network. Once the CA is trusted, open `https://cyberdeck.local/`.

## Start with an existing Debian 13 install

If Debian 13 is already installed, skip the USB and Debian Installer sections and begin at [Prepare a source kit](debian-install.md#prepare-a-source-kit). That path builds/transfers a source kit, previews host changes, and applies the Hub installer. It does not install Debian or repartition disks.

## Failure and recovery

- If the ISO checksum does not match Debian's checksum list, discard the image and download it again. Do not write it to USB.
- If the USB does not boot, record whether the system uses UEFI or legacy BIOS and rebuild the media from a verified ISO.
- If first-boot setup is skipped or interrupted, retry it with the command above. Keep the staged kit until setup and service checks succeed.
- First-boot setup checks that the staged installer grants the firewall status and change actions before it offers to apply. If it reports a missing action, rebuild the media or source kit from the current repository and retry; do not hand-edit the installed sudoers file.
- If install reports a deployment recovery ID, retain it and preview rollback before executing rollback.
- After install, verify `cyberdeck-web.service` and `cyberdeck-kiwix.service`; follow the manual guide for backup and disconnected restore procedures.

The media builder performs source and package preparation checks. A successful build does not prove Debian Installer boot, USB write, first-boot behavior, hardware support, offline startup, client access, or recovery. Record those observations separately on disposable and physical targets.

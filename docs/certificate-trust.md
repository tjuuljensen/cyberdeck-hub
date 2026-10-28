# Cyberdeck HTTPS certificate setup and removal

Cyberdeck uses HTTPS for the Hub, PDFs, and Kiwix pages. The server uses a
certificate signed by a private, local Cyberdeck certificate authority (CA).
This keeps traffic encrypted and lets modern phone browsers open PDFs and other
secure content without an internet connection or a public domain name. A public
certificate authority generally cannot validate a private `.local` hostname
while the Cyberdeck is offline.

The trade-off is that phones and computers do not trust this CA by default. You
must install the public CA certificate on each client device. This grants that
device's trust store permission to accept certificates issued by this CA, so
only install it for a Cyberdeck you control and after checking its fingerprint.
The private signing key stays on the server and must never be copied to a client.

## First connection

1. Connect the device to the same trusted local network as Cyberdeck. If using
   the standard Cyberdeck hotspot, connect to that Wi-Fi network first.
2. Open `http://cyberdeck.local/` in a browser. If `.local` does not resolve,
   use the server IP printed by the installer. On the standard hotspot, the
   address is `http://10.42.0.1/`.
3. Follow the certificate setup page and download the public CA certificate.
   The direct downloads are `http://cyberdeck.local/trust/ca.cer` and
   `http://cyberdeck.local/trust/ca.crt`; replace the hostname with the server
   IP if needed.
4. Compare the page's SHA-256 fingerprint with the fingerprint obtained on the
   Cyberdeck itself or from another trusted channel. On the server, run:

   ```sh
   sudo openssl x509 -noout -fingerprint -sha256 -in /etc/cyberdeck/tls/ca.crt
   ```

   A fingerprint shown on the same untrusted HTTP connection does not by itself
   prove that the downloaded file is genuine. Do not install the CA if the
   fingerprints differ or cannot be verified to your satisfaction.
5. Install the certificate as a trusted **root CA** using the instructions for
   the device below. The server's private key is never part of this download.
6. Open `https://cyberdeck.local/` (or the server's HTTPS IP/name shown by the
   installer). Create the administrator account on the trusted HTTPS page.

The HTTP page exists only to bootstrap certificate trust and redirect other
requests to HTTPS. HTTP is not encrypted or authenticated: anyone able to
intercept local network traffic could read or alter it. Do not enter passwords
or use Admin over HTTP. If your browser forces HTTPS before the CA is installed,
use the server IP for the first HTTP visit, or transfer the public certificate
through USB or another trusted device.

Repeat the installation for each device. A hostname change renews the server
certificate while keeping the same local CA, so devices that already trust the
CA normally do not need to install it again.

## Install on a device

### iPhone and iPad

1. Open the HTTP certificate setup page in **Safari** and download the `.cer`
   certificate. Safari makes the downloaded configuration profile available
   from Settings.
2. Open **Settings > General > VPN & Device Management** and tap **Profile
   Downloaded** (or the downloaded Cyberdeck profile), then tap **Install**.
3. Installing the profile alone does not enable website trust. Open **Settings
   > General > About > Certificate Trust Settings** and enable full trust for
   **Cyberdeck Local Library CA**.
4. Return to Safari and open the HTTPS Hub address.

Apple may remove a downloaded profile if it is not installed promptly. iOS and
iPadOS menu names can vary by release. See Apple's instructions for [installing
a downloaded profile](https://support.apple.com/en-us/102400) and [trusting a
manually installed root certificate](https://support.apple.com/en-us/102390).

### Windows

1. Download the `.cer` file and verify its fingerprint.
2. Open the file and choose **Install Certificate**.
3. Choose **Current User** unless you intentionally need to trust the CA for
   every account on this computer. Choose **Place all certificates in the
   following store**, select **Trusted Root Certification Authorities**, and
   complete the import.
4. Close and reopen the browser, then visit the HTTPS Hub address.

If Windows shows a trust warning during import, confirm the certificate name
and fingerprint before proceeding. Windows documentation describes the
[Trusted Root Certification Authorities store](https://learn.microsoft.com/en-us/windows-hardware/drivers/install/trusted-root-certification-authorities-certificate-store).

### Debian and other Linux distributions using `update-ca-certificates`

Download the `.crt` file, verify its fingerprint, and copy it to the local CA
directory:

```sh
sudo install -m 0644 cyberdeck-local-ca.crt \
  /usr/local/share/ca-certificates/cyberdeck-local-ca.crt
sudo update-ca-certificates
```

Restart the browser and open the HTTPS Hub address. Some browsers, including
some Firefox configurations, use a separate certificate store; if Firefox
still reports an untrusted CA, import the public CA certificate into Firefox's
certificate authorities or configure Firefox to use the operating system
trust store.

### Android

1. Download the certificate and verify its fingerprint. If Android does not
   recognize the `.cer` file, download the `.crt` version instead.
2. Open **Settings > Security & privacy > More security settings > Encryption &
   credentials > Install a certificate > CA certificate**. Select the downloaded
   file and confirm the device warning. Manufacturer menus vary; some use
   **Security > Install from device storage**.
3. Reopen the browser and visit the HTTPS Hub address.

Android may require a screen lock before installing a CA. Some applications do
not accept user-installed CAs, even when Android and the browser trust them;
open the Hub in a browser if another application still reports a certificate
error. See [Google's certificate instructions](https://support.google.com/pixelphone/answer/2844832).

## Troubleshooting

- **The browser still warns about the CA:** confirm the certificate was
  installed as a root CA, restart the browser, and check the device's date and
  time. On iPhone, enable full trust after installing the profile.
- **The hostname does not match:** use the exact HTTPS hostname printed by the
  installer. A server certificate is issued for the configured Cyberdeck
  hostname; changing it may require a refreshed server certificate.
- **Firefox alone reports an error:** Firefox may use its own certificate
  store. Import the CA there or enable its operating-system certificate trust
  integration.
- **An Android app reports an error:** use a browser. An app can choose not to
  trust user-installed CAs.
- **The Hub works but PDFs do not open:** confirm the address begins with
  `https://` and that the browser trusts the CA. Modern browser security rules
  can limit document viewing and downloads from plain HTTP pages.

## Remove trust when decommissioning a Cyberdeck

Remove **Cyberdeck Local Library CA** from every phone, computer, and browser
that trusted it. Removing the Hub server alone does not remove copies installed
on client devices. The steps below remove only the Cyberdeck CA; do not clear or
delete other certificates you recognize as belonging to your operating system,
workplace, VPN, or Wi-Fi.

- **iPhone/iPad:** open **Settings > General > VPN & Device Management**, select
  the Cyberdeck certificate profile, and choose **Remove Profile**. If the CA
  was installed another way, also check **Settings > General > About >
  Certificate Trust Settings** and turn off its full trust.
- **Windows:** open `certmgr.msc`, find **Cyberdeck Local Library CA** under
  **Trusted Root Certification Authorities > Certificates** for the account
  where it was installed, and delete that certificate. If it was installed for
  the whole computer, use the Local Computer certificate store instead.
- **Debian/Linux:** remove only the file added for Cyberdeck, then refresh the
  trust store:

  ```sh
  sudo rm /usr/local/share/ca-certificates/cyberdeck-local-ca.crt
  sudo update-ca-certificates
  ```

- **Android:** open **Settings > Security & privacy > More security settings >
  Encryption & credentials > User credentials** (or the manufacturer's
  equivalent) and remove **Cyberdeck Local Library CA**.
- **Firefox or another browser with its own trust store:** remove the Cyberdeck
  CA from that browser's certificate authorities as well.

If the Cyberdeck server is being retired, remove its private CA key from the
server and from any backups that are being destroyed. The key is normally at
`/etc/cyberdeck/tls/ca.key`; do not publish or copy it as part of decommissioning.
Retain or destroy backups according to the owner's data-retention policy.


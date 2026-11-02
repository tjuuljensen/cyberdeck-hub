# Survival Cyberdeck Hub tutorial

This guide helps you build a small, useful reference library for a household or
local group. It is about preparing information for offline access, not about
predicting emergencies or replacing official instructions, emergency services,
medical advice, or practical training.

## Start with what people will need offline

Build the collection around your location, household, and likely disruptions.
Start with a few short, high-value references; a small checked library is more
useful than a large collection no one can navigate.

| Topic | Useful offline material | Review notes |
| --- | --- | --- |
| Official preparedness guidance | Current national and local authority guides for power, water, food, communications, severe weather, evacuation, and public warnings. | Keep the issuing authority, region, publication date, and review date visible. Guidance varies by country and changes over time. |
| First aid and health | Current, reputable first-aid guidance; local emergency numbers; a short list of nearby emergency facilities if useful. | First aid guidance can change. Use it as a reference, not a substitute for calling emergency services or taking a course. Do not store private patient records in a library shared over the LAN. |
| Local maps | Printable maps of the neighborhood, nearby roads, trails, public facilities, and places relevant to your household or group. | Include the area, scale, source, and map date. A map is not live navigation and may omit closures or current hazards. Keep a paper copy for power or device failure. |
| Practical household references | Food and water planning, sanitation, safe heating, battery and radio use, charging, and simple repair or maintenance guides relevant to your equipment. | Prefer official safety instructions and manuals for the exact model you own. Review safety-critical material regularly. |
| Offline general knowledge | Selected Wikipedia or other reference ZIM archives served by Kiwix. Choose the language and size that fit your users and disk. | ZIM libraries are snapshots, not live websites. Record the edition or download date and refresh them deliberately. |
| Everyday life and morale | Recipes using ingredients you actually keep, printable games, activity sheets, and local language or learning material. | Keep these lightweight and useful. Store game rules or printable sheets as PDFs; the Hub is not a general executable game launcher. |

For a Danish collection, start with the current [Styrelsen for
Samfundssikkerhed home-preparedness guidance](https://samsik.dk/forberedt/faq/)
and applicable municipality guidance. For first aid, prefer a current source
such as the Danish Red Cross's [four main first-aid
principles](https://www.rodekors.dk/skole/temaer/foerstehjaelp/de-fire-hovedpunkter)
and current health-authority advice. For another country, use its own civil
protection, health, weather, and local-government sources instead.

## Decide whether something should be stored or linked

- **Documents** are for PDF, DOCX, and packaged HTML material stored on the Hub.
  Upload a permitted copy, not just the webpage URL. Add a useful title and
  keep the source and edition information with the item.
- **Kiwix libraries** are `.zim` files. Add the archive through **Admin > Kiwix
  libraries**. The Hub serves the archive; readers search inside it with the
  Kiwix interface.
- **Online Source cards** open a live external website. They do not save or
  mirror the website, so the link is useful only when the client has internet
  access and that service is reachable.
- **RSS cards** show recent feed items when the Hub can reach the feed. They
  are not push notifications, emergency alerts, or offline copies of the
  linked articles. A cached view may be old; check its retrieval time and the
  publisher's page.

Online Source and RSS cards are pointers to live services. Do not count them
as part of your offline reference set. If you configure official news or police
feeds, use them as supplemental information; they do not replace official
alert channels. See [Online Source and RSS cards](online-crisis-links.md).

## A simple curation workflow

1. **Choose a small audience and area.** Decide whose needs the library serves
   and what geographic area it covers. A household library can include local
   details that a general public collection should omit.
2. **Choose a few priority topics.** Start with official preparedness, first
   aid, local maps, household-specific equipment, and one or two reference
   archives. Add recipes and games after the essentials.
3. **Check the source and the right to store it.** Prefer the issuing
   authority, the publisher, or an authorized download. Check the license or
   terms before copying or sharing. A document being freely readable online
   does not automatically mean you may redistribute it.
4. **Check the edition and fitness.** Confirm the country, language, region,
   publication date, equipment model, and safety instructions. Avoid advice
   that conflicts with current authority guidance. A hardware service manual
   for a different model can be misleading.
5. **Add one item and preview it.** Use **Admin > Documents** for PDFs or
   **Admin > Kiwix libraries** for ZIM archives. Keep a source, version/date,
   language, and relevant region in the title or catalogue details.
6. **Test without internet.** Disconnect the client from the internet while
   keeping it connected to Cyberdeck. Open each important document and ZIM.
   Confirm that the material itself is present and readable; a working link
   while online is not an offline test.
7. **Back up and review.** Export configuration for catalogue metadata and
   source links, selecting local files or cached PDF copies when needed. Review
   the [recovery limitations](../runbooks/debian-install.md#backup-and-restore)
   before relying on the Debian backup command.
   Schedule a review date for official, medical, map, and equipment guidance.
   Replace stale files only after the new copy has been checked.

## What not to upload

- Do not upload books, e-books, manuals, or other material unless its license
  allows you to store it and share it with everyone who can access the Hub.
  Buying a copy or being able to read it online does not automatically grant
  permission to redistribute it. Prefer openly licensed or public-domain
  material when you need a reusable shared copy.
- Do not upload hardware-specific service manuals unless that exact equipment
  is used by the household or group and the rights allow sharing the manual.
  Instructions for a different model can be misleading.
- Do not treat an old PDF as current just because it is stored locally. Remove
  or clearly mark superseded guidance, especially for first aid, public
  warnings, evacuation, and equipment safety.
- Do not put passwords, recovery codes, private keys, identity documents,
  financial records, or detailed personal health information in the shared
  library. Anyone who can reach the Hub can read the shared documents.
- Do not rely on the Hub as the only copy of essential directions. Devices,
  disks, batteries, Wi-Fi, and the Hub itself can fail. Keep a short paper
  fallback and a tested backup.
- Do not assume that a URL, RSS entry, or imported profile means its content
  has been downloaded. Check acquisition status and test offline.

## Optional tools and storage choices

### External USB disk

Use an external disk when the internal disk is too small for your PDF and ZIM
collection, or to hold a separate recovery backup. In Admin, open **Management
> Storage** to inspect disks and choose a supported action. Adoption registers
a disk without erasing it. Initializing creates an ext4 filesystem and erases
all data on that disk. An existing ext4 filesystem can be mounted without
formatting. Moving the library data root copies the Hub's data and restarts Hub
and Kiwix; make a verified backup and stop active imports/downloads first. The
Admin preview shows the source, destination, and required space before you
confirm.

Keep the disk attached while it is used as the library data disk. Do not unplug
it while Hub or Kiwix is running. A disk that stores the only library copy is
not a backup; use a second physical disk for backup and verify a restore before
relying on it. See the [Debian install guide's backup and restore
section](../runbooks/debian-install.md#backup-and-restore).

### CyberChef

CyberChef is an optional local browser tool for transforming or inspecting
data, such as decoding text, parsing formats, or calculating hashes. It is not
an emergency information source and does not replace security review. The
installer can stage a pinned copy while online; the service stays disabled
until enabled in **Admin > CyberChef**. Staging uses disk space, and enabling
starts another service. Once staged, the local tool does not need a public
CyberChef website to be available. Treat data entered into any browser tool as
sensitive and use it only on a trusted device and network.

## Keep the collection useful

Set a review reminder rather than trying to update everything continuously.
For each priority item, record who will check it and when. On review, confirm
the publisher, date, region, and whether the official version has changed. Test
the Hub after updates, keep the previous checked copy until the replacement is
usable, and note which items are snapshots. A deliberate update is safer than
silently replacing emergency material with an unreviewed download.


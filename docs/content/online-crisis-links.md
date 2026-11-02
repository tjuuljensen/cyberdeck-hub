# Online Source and RSS cards

Cyberdeck Hub supports configurable Online Source and RSS cards. New installs
start with neither type preloaded. In **Admin > Cards**, create a card of the
appropriate type, then manage its entries under **All Online Sources** or
**All RSS Feeds**. Use Subject cards to group Documents and Kiwix libraries.

Online Source entries link to live websites. RSS entries read configured public
HTTPS feeds and show recent headlines with links and publication times. Both
card types support editable text and translations and can be selected during
configuration import/export.

## Connectivity and caching

The home page uses connectivity checks to show these cards as available online.
When offline, each card's display preference determines whether it is hidden
or shown as inactive. The check is a reachability hint, not a guarantee that
every configured website or feed is available. An Online Source link does not
save a website, and an RSS feed does not save its linked articles.

RSS fetching limits response size and item count and caches results briefly.
An unavailable feed may show a labelled cached result; check retrieval and
publication times. RSS cards do not send push notifications or serve as an
emergency alert channel.

## Maintain the entries

Use the publisher's current website or feed URL, give each entry a clear title,
and identify country or language where relevant. Check links after publisher
changes and during profile review. Delete entries that no longer serve the
collection. Keep essential reference material as verified local Documents or
ZIM libraries and test it without internet access.

Existing installations may retain earlier example links and police feeds.
Review those saved entries in Admin; they are not mandatory defaults for a new
installation. For choosing offline material, see the [content tutorial](survival-cyberdeck-hub-tutorial.md).

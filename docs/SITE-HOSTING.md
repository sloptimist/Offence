# Hosting the Offence introduction

Serve the contents of `site/` at `https://offence.ai/`:

- `index.html`: public introduction, static buyer and provider guides, structured data and social metadata.
- `offence-cartridge.png`: cartridge preview image for X and Open Graph.
- `robots.txt`: allows all crawlers, including search, AI and training crawlers.
- `sitemap.xml`: identifies the canonical page.

Place these files at the domain root. The image must be available at
`https://offence.ai/offence-cartridge.png`. Serve the page and image publicly with
successful responses and the appropriate content types. Server or CDN bot rules,
login requirements and `X-Robots-Tag` headers must not contradict the public crawl policy.
Only the contents of `site/` belong in the public document root.

Both instruction sets are in the original HTML and visible without JavaScript.
JavaScript adds the buyer/provider switch and animation pause control.
No personal account, analytics service or external asset is included.

The canonical URL, social image URLs, JSON-LD and sitemap use `https://offence.ai/`.
Update those together if the public origin changes. After uploading, verify the
page, image, robots file and sitemap return successful public responses, then
inspect the link preview in X's post composer. Crawling permissions and metadata
do not guarantee indexing or a particular platform presentation; cached cards may
continue to show an older image.

The editable social artwork is `assets/offence-social.svg`. Regenerate it and the
1200 x 600 PNG from the page's pixel artwork using
`scripts/render-social-card.py` with CairoSVG installed. On a Homebrew Mac, Cairo
may need `DYLD_FALLBACK_LIBRARY_PATH=/opt/homebrew/lib`.

## Optional API routing on the website domain

`deploy/pages-offence-api.conf` is a template, not a ready-to-install configuration.
Set its listener, static document root and private upstream for your own installation.
It serves static content at `/` and proxies `/v1/` and `/health` to the node.
No wallet keys or local operator records belong in the static document root.

For Start9 Pages, a separate main-volume `nginx/conf.d/` include can keep custom
routing apart from generated configuration. Inspect your installed version before
using this approach and recheck it on upgrades. Validate nginx before reloading,
compare the homepage and verify signed gossip through the new public origin.

Only after the new route works should you update the node's advertised address,
its peers' seed addresses and approved origins. Retire any old public host binding.
Changing a hostname does not erase historical DNS, certificates or retained peer
records; preserving node identity keeps old and new signed records linkable.

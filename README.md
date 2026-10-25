# Duo Ready

A daily-updated tracker of which App Store apps are ready for **iPhone Duo**, Apple's first foldable iPhone (launched 23 October 2026).

Live site: **https://francesqwo.github.io/duo-ready/**

## What "ready" means here

Apple puts a **Made for iPhone Duo** badge on an app's product page once the developer submits iPhone Duo screenshots in App Store Connect. Those screenshots are the only assets sized `1398×2034 / 2034×1398` (outer display) and `2007×2853 / 2853×2007` (inner display), and in the App Store catalog they land in the `customScreenshotsByType.cassatt` slot.

So the tracker reads the public catalog record for each app and checks for that slot. Presence = Duo-ready, the machine-readable counterpart of the badge.

**Caveat:** absence is not proof an app is broken on Duo — an app can be recompiled with the iOS 27.1 SDK and simply not have uploaded Duo screenshots yet. And from April 2027 Apple requires Duo screenshots for new submissions, so the "not yet" set will shrink to nothing as a signal.

## What gets scanned

- US App Store **top-free 100** and **top-paid 100** (Apple marketing RSS)
- Apple's editorial collections *Great Apps and Games on iPhone Duo* and *Great Games on iPhone Duo*

Roughly 220–250 unique apps per run, one catalog request each, ~0.3 s apart.

## Layout

```
scraper/scan.py        # the whole pipeline: charts + editorial + catalog probe
docs/index.html        # static site (GitHub Pages, branch source: main /docs)
docs/app.js            # filtering/rendering, no dependencies, no build step
docs/styles.css
docs/data/apps.json    # generated: one record per app
docs/data/meta.json    # generated: run metadata + new-today list
.github/workflows/scan.yml   # daily refresh + commit
```

## Run locally

```bash
python3 scraper/scan.py            # writes docs/data/*.json
python3 -m http.server -d docs 8000
# open http://localhost:8000
```

No dependencies, Python 3.10+.

## Data shape

```json
{
  "generatedAt": "2026-10-25T16:20:00Z",
  "totals": { "tracked": 231, "duoReady": 44, "checked": 231 },
  "apps": [
    {
      "id": "989178902",
      "name": "Timepage: Calendar Planner",
      "seller": "Bonobo",
      "genre": "Productivity",
      "icon": "https://is1-ssl.mzstatic.com/.../96x96bb.png",
      "url": "https://apps.apple.com/us/app/...",
      "duo": true,
      "duoShots": ["2853x2007"],
      "latestRelease": "2026-10-25",
      "notesMentionDuo": true,
      "firstSeenDuo": "2026-10-25",
      "sources": ["featured"]
    }
  ]
}
```

`firstSeenDuo` is carried forward between runs, so "New" badges on the site mean *first observed by this tracker*, not necessarily the app's release day.

## Adding a source

- **More charts:** tweak `chart_ids()` calls in `scraper/scan.py` (Apple's RSS supports `top-free`, `top-paid`, `top-grossing`).
- **More editorial lists:** append story URLs to `STORIES`.
- **A watchlist:** add app ids and merge them into `universe` in `main()`.

## Disclaimer

Unofficial, not affiliated with Apple. Data comes from undocumented App Store endpoints and can break without notice. Apple, iPhone and App Store are trademarks of Apple Inc.

## License

MIT — see [LICENSE](LICENSE).

Vibecoded with [Hermes Agent](https://hermes-agent.nousresearch.com).

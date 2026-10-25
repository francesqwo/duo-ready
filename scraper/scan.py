#!/usr/bin/env python3
"""Scan the App Store for apps that are ready for iPhone Duo.

Universe scanned per run:
  * US top-free 100   (marketing RSS)
  * US top-paid 100   (marketing RSS)
  * Apple's editorial Duo collections (story pages, SSR JSON)

Duo readiness is detected from the App Store catalog record: Apple stores
iPhone Duo screenshots in the `customScreenshotsByType.cassatt` slot
(1398x2034 outer / 2853x2007 inner). Submitting those screenshots is what makes
the "Made for iPhone Duo" badge appear, so the slot is a reliable proxy.

Output: docs/data/apps.json (+ docs/data/meta.json)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "data"
STATE = OUT / "apps.json"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
      "(KHTML, like Gecko) Version/18.0 Safari/605.1.15")

STORIES = [
    "https://apps.apple.com/us/iphone/story/id6820639500",  # Great Apps and Games on iPhone Duo
    "https://apps.apple.com/us/story/id6820647409",          # Great Games on iPhone Duo
]

DUO_SLOT = "cassatt"


def get(url: str, tries: int = 4, timeout: int = 30):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503) and attempt < tries - 1:
                time.sleep(5 * (attempt + 1))
                continue
            raise
        except (urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def get_text(url: str, tries: int = 4) -> str:
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            if attempt < tries - 1:
                time.sleep(4 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def chart_ids(kind: str, limit: int = 100, country: str = "us") -> list[str]:
    url = f"https://rss.marketingtools.apple.com/api/v2/{country}/apps/{kind}/{limit}/apps.json"
    try:
        feed = get(url)["feed"]["results"]
        return [str(a["id"]) for a in feed]
    except Exception as exc:  # chart hiccup must not kill the run
        print(f"  ! chart {kind} failed: {exc}", file=sys.stderr)
        return []


def story_apps(url: str) -> list[str]:
    """Apple editorial collections: pull Lockup entries out of the SSR JSON."""
    html = get_text(url)
    m = re.search(r'<script type="application/json" id="serialized-server-data">(.*?)</script>', html, re.S)
    if not m:
        return []
    blob = m.group(1)
    # unescape the HTML entities JSON ships with
    blob = (blob.replace("&quot;", '"').replace("&amp;", "&")
                .replace("&lt;", "<").replace("&gt;", ">").replace("&#39;", "'"))
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        ids = re.findall(r'"adamId":\s*"?(\d{6,})"?', blob)
        return list(dict.fromkeys(ids))

    found: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            if node.get("$kind") == "Lockup" and node.get("adamId"):
                found.append(str(node["adamId"]))
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return list(dict.fromkeys(found))


def icon_url(template: str | None) -> str | None:
    if not template:
        return None
    return template.replace("{w}x{h}{c}.{f}", "96x96bb.png")


def app_record(app_id: str, country: str = "us") -> dict:
    url = (f"https://apps.apple.com/api/apps/v1/catalog/{country}/apps/{app_id}"
           "?platform=web&additionalPlatforms=iphone%2Cipad"
           "&extend=customScreenshotsByType%2CiconArtwork%2CversionHistory&l=en-US")
    data = get(url)["data"][0]
    attrs = data["attributes"]
    ios = attrs.get("platformAttributes", {}).get("ios", {})
    shots = (ios.get("customAttributes", {}).get("default", {})
             .get("default", {}).get("customScreenshotsByType", {}))
    versions = ios.get("versionHistory") or []
    latest = None
    if versions:
        latest = max(versions, key=lambda v: v.get("releaseDate") or "")
    notes = (latest or {}).get("releaseNotes") or ""
    return {
        "id": str(app_id),
        "name": attrs.get("name"),
        "seller": attrs.get("artistName"),
        "genre": attrs.get("genreDisplayName"),
        "icon": icon_url((ios.get("iconArtwork") or {}).get("url")),
        "url": attrs.get("url"),
        "duo": DUO_SLOT in shots,
        "duoShots": sorted({f"{s.get('width')}x{s.get('height')}" for s in shots.get(DUO_SLOT, [])}),
        "latestRelease": (latest or {}).get("releaseDate"),
        "notesMentionDuo": "duo" in notes.lower(),
    }


def load_previous() -> dict:
    if not STATE.exists():
        return {}
    try:
        data = json.loads(STATE.read_text())
        return {a["id"]: a for a in data.get("apps", [])}
    except Exception:
        return {}


def main() -> int:
    previous = load_previous()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    universe: dict[str, set[str]] = {}
    for kind in ("top-free", "top-paid"):
        for app_id in chart_ids(kind):
            universe.setdefault(app_id, set()).add("chart-" + kind.split("-")[1])
        print(f"  {kind}: {len([1 for v in universe.values() if 'chart-' + kind.split('-')[1] in v])} ids")
        time.sleep(0.4)

    for story in STORIES:
        try:
            ids = story_apps(story)
        except Exception as exc:
            print(f"  ! story failed ({story}): {exc}", file=sys.stderr)
            ids = []
        for app_id in ids:
            universe.setdefault(app_id, set()).add("featured")
        print(f"  featured {story.rsplit('/', 1)[-1]}: {len(ids)} ids")

    print(f"universe: {len(universe)} unique apps")
    apps: list[dict] = []
    errors = 0

    for index, (app_id, sources) in enumerate(sorted(universe.items()), 1):
        try:
            record = app_record(app_id)
        except Exception as exc:
            errors += 1
            print(f"  ! {app_id}: {exc}", file=sys.stderr)
            stale = previous.get(app_id)
            if stale:
                stale = dict(stale)
                stale["sources"] = sorted(sources)
                apps.append(stale)
            time.sleep(1.5)
            continue

        previous_record = previous.get(app_id, {})
        if record["duo"]:
            first_seen = previous_record.get("firstSeenDuo") or today
        else:
            first_seen = None
        record["firstSeenDuo"] = first_seen
        record["sources"] = sorted(sources)
        apps.append(record)
        if index % 25 == 0:
            print(f"  scanned {index}/{len(universe)} (duo so far: {sum(1 for a in apps if a.get('duo'))})")
        time.sleep(0.3)

    apps.sort(key=lambda a: (not a.get("duo"), (a.get("name") or "").lower()))
    ready = [a for a in apps if a.get("duo")]
    newly = [a for a in ready if a.get("firstSeenDuo") == today and a["id"] not in previous]

    OUT.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totals": {
            "tracked": len(apps),
            "duoReady": len(ready),
            "checked": len(apps) - errors,
        },
        "apps": apps,
    }
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    tmp.replace(STATE)

    meta = {
        "generatedAt": payload["generatedAt"],
        "totals": payload["totals"],
        "newToday": [{"id": a["id"], "name": a["name"]} for a in newly],
        "errors": errors,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"done: {len(ready)}/{len(apps)} duo-ready, {len(newly)} new today, {errors} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())

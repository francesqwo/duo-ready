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
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

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

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": UA, "Accept": "application/json"})

# Apple's storefront proxy throttles bursts hard (a few requests/second, then
# 429 for a while — data-centre IPs get it worse). Pace gently, do not chase a
# 429 for long, and let the next scheduled run fill whatever was skipped.
MIN_INTERVAL = float(os.environ.get("MIN_INTERVAL", "1.2"))
BUDGET_SECONDS = int(os.environ.get("BUDGET_SECONDS", "540"))
STARTED = time.time()
_last_request = 0.0


def _throttle():
    global _last_request
    wait = MIN_INTERVAL - (time.time() - _last_request)
    if wait > 0:
        time.sleep(wait + random.uniform(0, 0.3))
    _last_request = time.time()


def get_json(url: str, tries: int = 3):
    for attempt in range(tries):
        _throttle()
        try:
            response = SESSION.get(url, timeout=15)
            if response.status_code == 429 and attempt < tries - 1:
                pause = 8 * (attempt + 1)
                print(f"    429, waiting {pause}s", file=sys.stderr, flush=True)
                time.sleep(pause)
                continue
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError):
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def get_text(url: str, tries: int = 3) -> str:
    for attempt in range(tries):
        try:
            response = SESSION.get(url, timeout=20)
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            if attempt < tries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            raise
    raise RuntimeError("unreachable")


def chart_ids(kind: str, limit: int = 100, country: str = "us") -> list[str]:
    url = f"https://rss.marketingtools.apple.com/api/v2/{country}/apps/{kind}/{limit}/apps.json"
    try:
        return [str(a["id"]) for a in get_json(url)["feed"]["results"]]
    except Exception as exc:  # a chart hiccup must not kill the run
        print(f"  ! chart {kind} failed: {exc}", file=sys.stderr, flush=True)
        return []


def story_apps(url: str) -> list[str]:
    """Apple editorial collections: pull Lockup entries out of the SSR JSON."""
    html = get_text(url)
    match = re.search(r'<script type="application/json" id="serialized-server-data">(.*?)</script>', html, re.S)
    if not match:
        return []
    blob = match.group(1)
    try:
        data = json.loads(blob)
    except json.JSONDecodeError:
        return list(dict.fromkeys(re.findall(r'"adamId":\s*"?(\d{6,})"?', blob)))

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
    attrs = get_json(url)["data"][0]["attributes"]
    ios = attrs.get("platformAttributes", {}).get("ios", {})
    shots = (ios.get("customAttributes", {}).get("default", {})
             .get("default", {}).get("customScreenshotsByType", {}))
    versions = ios.get("versionHistory") or []
    latest = max(versions, key=lambda v: v.get("releaseDate") or "") if versions else {}
    notes = latest.get("releaseNotes") or ""
    return {
        "id": str(app_id),
        "name": attrs.get("name"),
        "seller": attrs.get("artistName"),
        "genre": attrs.get("genreDisplayName"),
        "icon": icon_url((ios.get("iconArtwork") or {}).get("url")),
        "url": attrs.get("url"),
        "duo": DUO_SLOT in shots,
        "duoShots": sorted({f"{s.get('width')}x{s.get('height')}" for s in shots.get(DUO_SLOT, [])}),
        "latestRelease": latest.get("releaseDate"),
        "checkedAt": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "notesMentionDuo": "duo" in notes.lower(),
    }


def load_previous() -> dict:
    if not STATE.exists():
        return {}
    try:
        return {a["id"]: a for a in json.loads(STATE.read_text()).get("apps", [])}
    except Exception:
        return {}


def write_payload(apps: list[dict], errors: int) -> dict:
    ready = [a for a in apps if a.get("duo")]
    payload = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "totals": {"tracked": len(apps), "duoReady": len(ready), "checked": len(apps) - errors},
        "apps": apps,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1))
    tmp.replace(STATE)
    return payload


def main() -> int:
    previous = load_previous()
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    universe: dict[str, set[str]] = {}
    for kind, tag in (("top-free", "chart-free"), ("top-paid", "chart-paid")):
        ids = chart_ids(kind)
        for app_id in ids:
            universe.setdefault(app_id, set()).add(tag)
        print(f"  {tag}: {len(ids)} ids", flush=True)
        time.sleep(0.3)

    for story in STORIES:
        try:
            ids = story_apps(story)
        except Exception as exc:
            print(f"  ! story failed ({story}): {exc}", file=sys.stderr, flush=True)
            ids = []
        for app_id in ids:
            universe.setdefault(app_id, set()).add("featured")
        print(f"  featured {story.rsplit('/', 1)[-1]}: {len(ids)} ids", flush=True)

    total = len(universe)
    print(f"universe: {total} unique apps", flush=True)
    apps: list[dict] = []
    errors = 0

    resume = os.environ.get("RESUME") == "1"
    stopped_early = False
    for index, (app_id, sources) in enumerate(sorted(universe.items()), 1):
        if time.time() - STARTED > BUDGET_SECONDS:
            stopped_early = True
            print(f"  budget of {BUDGET_SECONDS}s reached at {index - 1}/{total} — "
                  "committing what we have; the next run continues", flush=True)
            break
        cached = previous.get(app_id)
        if resume and cached and cached.get("checkedAt") == today:
            cached = dict(cached)
            cached["sources"] = sorted(sources)
            apps.append(cached)
            continue
        try:
            record = app_record(app_id)
        except Exception as exc:
            errors += 1
            print(f"  ! {app_id}: {exc}", file=sys.stderr, flush=True)
            stale = previous.get(app_id)
            if stale:
                stale = dict(stale)
                stale["sources"] = sorted(sources)
                apps.append(stale)
            time.sleep(1)
            continue

        record["firstSeenDuo"] = (previous.get(app_id, {}).get("firstSeenDuo") or today) if record["duo"] else None
        record["sources"] = sorted(sources)
        apps.append(record)

        if index % 10 == 0:
            elapsed = int(time.time() - STARTED)
            print(f"  {index}/{total} · duo {sum(1 for a in apps if a.get('duo'))} · "
                  f"errors {errors} · {elapsed}s", flush=True)
        if index % 25 == 0:
            apps.sort(key=lambda a: (not a.get("duo"), (a.get("name") or "").lower()))
            write_payload(apps, errors)

    # carry over anything we did not get to this run (budget stop / persistent 429)
    processed = {a["id"] for a in apps}
    for app_id, sources in sorted(universe.items()):
        if app_id not in processed and app_id in previous:
            stale = dict(previous[app_id])
            stale["sources"] = sorted(sources)
            apps.append(stale)

    apps.sort(key=lambda a: (not a.get("duo"), (a.get("name") or "").lower()))
    payload = write_payload(apps, errors)
    newly = [a for a in payload["apps"] if a.get("duo") and a.get("firstSeenDuo") == today and a["id"] not in previous]

    OUT.mkdir(parents=True, exist_ok=True)
    meta = {
        "generatedAt": payload["generatedAt"],
        "totals": payload["totals"],
        "newToday": [{"id": a["id"], "name": a["name"]} for a in newly],
        "errors": errors,
    }
    (OUT / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))
    print(f"done: {payload['totals']['duoReady']}/{len(apps)} duo-ready, {len(newly)} new today, {errors} errors", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

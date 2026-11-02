#!/usr/bin/env python3
"""Sync authoritative trail data into the Mapbox datasets/tilesets behind cvilletrails.com.

Pipeline for one trail (configured in sources.json):

  1. fetch     authoritative source (Google My Maps KML/KMZ, or a local file)
  2. convert   KML -> GeoJSON features, filtered to the configured geometry types,
               with deterministic ids so unchanged features are left alone
  3. diff      against the current Mapbox dataset (a backup is always written)
  4. --apply   write the changes to the dataset (PUT new features, DELETE stale ones)
  5. --publish re-export the dataset into the tileset the map style reads from

Without --apply/--publish it is a dry run: nothing on Mapbox changes.

Needs MAPBOX_TOKEN (a secret sk. token with datasets:read/write and uploads:write).
Standard library only.

Examples:
  python3 sync/trailsync.py rivanna-trail                       # dry run from Google My Maps
  python3 sync/trailsync.py rivanna-trail --kml-file map.kml    # dry run from a downloaded file
  python3 sync/trailsync.py rivanna-trail --apply --publish     # update dataset + live tileset
"""

import argparse
import datetime as dt
import hashlib
import html
import io
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
API = "https://api.mapbox.com"
KML_NS = "{http://www.opengis.net/kml/2.2}"


# ---------------------------------------------------------------- HTTP helpers

def http(method, url, body=None, raw=False):
    data = None
    headers = {"User-Agent": "cvilletrails-sync/1.0"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                payload = r.read()
                if raw:
                    return payload
                return json.loads(payload) if payload else None
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and attempt < 3:
                time.sleep(2 ** (attempt + 1))
                continue
            msg = e.read().decode(errors="replace")[:500]
            safe_url = re.sub(r"access_token=[^&]+", "access_token=***", url)
            raise SystemExit(f"HTTP {e.code} on {method} {safe_url}: {msg}")


def mb(path, token, **params):
    params["access_token"] = token
    return f"{API}{path}?{urllib.parse.urlencode(params)}"


# ---------------------------------------------------------------- source fetch

def fetch_kml(source, kml_file=None):
    if kml_file:
        with open(kml_file, "rb") as f:
            blob = f.read()
        origin = "file:" + os.path.basename(kml_file)
    elif source["type"] == "google_mymaps":
        if not source.get("mid"):
            raise SystemExit("sources.json has no Google My Maps `mid` for this trail; "
                             "fill it in or pass --kml-file.")
        origin = f"https://www.google.com/maps/d/kml?mid={source['mid']}&forcekml=1"
        blob = http("GET", origin, raw=True)
    else:
        raise SystemExit(f"Unsupported source type: {source['type']}")
    if blob[:2] == b"PK":  # KMZ
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            name = next(n for n in z.namelist() if n.lower().endswith(".kml"))
            blob = z.read(name)
    return blob, origin


# ---------------------------------------------------------------- KML -> GeoJSON

def _coords(text):
    pts = []
    for tok in text.split():
        parts = tok.split(",")
        if len(parts) >= 2:
            pts.append([round(float(parts[0]), 6), round(float(parts[1]), 6)])
    return pts


def _strip_html(s):
    s = re.sub(r"<br\s*/?>", "\n", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return html.unescape(s).strip()


def _geoms(el):
    """Yield GeoJSON geometries for a Placemark, flattening MultiGeometry."""
    for child in el:
        tag = child.tag.replace(KML_NS, "")
        if tag == "Point":
            c = _coords(child.findtext(f"{KML_NS}coordinates", ""))
            if c:
                yield {"type": "Point", "coordinates": c[0]}
        elif tag == "LineString":
            c = _coords(child.findtext(f"{KML_NS}coordinates", ""))
            if len(c) >= 2:
                yield {"type": "LineString", "coordinates": c}
        elif tag == "Polygon":
            rings = []
            outer = child.find(f"{KML_NS}outerBoundaryIs/{KML_NS}LinearRing/{KML_NS}coordinates")
            if outer is not None:
                rings.append(_coords(outer.text or ""))
            for inner in child.findall(f"{KML_NS}innerBoundaryIs/{KML_NS}LinearRing/{KML_NS}coordinates"):
                rings.append(_coords(inner.text or ""))
            if rings and rings[0]:
                yield {"type": "Polygon", "coordinates": rings}
        elif tag == "MultiGeometry":
            yield from _geoms(child)


def feature_id(geom, props):
    """Deterministic id: any change to geometry or properties yields a new id."""
    key = json.dumps([geom, props], sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(key.encode()).hexdigest()[:32]


def _clean(s):
    return re.sub(r"\s+", " ", (s or "").replace("\xa0", " ")).strip()


def _line_colors(root):
    """Map styleUrl -> '#rrggbb' line color (KML stores aabbggrr)."""
    colors = {}
    for st in root.iter(f"{KML_NS}Style"):
        c = st.findtext(f"{KML_NS}LineStyle/{KML_NS}color")
        if c and len(c) == 8:
            colors["#" + st.get("id", "")] = "#" + c[6:8] + c[4:6] + c[2:4]
    for sm in root.iter(f"{KML_NS}StyleMap"):
        for pair in sm.findall(f"{KML_NS}Pair"):
            if pair.findtext(f"{KML_NS}key") == "normal":
                target = pair.findtext(f"{KML_NS}styleUrl")
                if target in colors:
                    colors["#" + sm.get("id", "")] = colors[target]
    return colors


def kml_to_features(blob, geometry_types, origin):
    root = ET.fromstring(blob)
    colors = _line_colors(root)
    feats = []

    def walk(el, folder):
        for child in el:
            tag = child.tag.replace(KML_NS, "")
            if tag in ("Document", "Folder"):
                name = child.findtext(f"{KML_NS}name") if tag == "Folder" else None
                walk(child, _clean(name) or folder)
            elif tag == "Placemark":
                props = {"section": _clean(child.findtext(f"{KML_NS}name"))}
                desc = _strip_html(child.findtext(f"{KML_NS}description"))
                desc = re.sub(r"^description:\s*", "", desc)
                if desc:
                    props["description"] = desc
                if folder:
                    props["layer"] = folder
                color = colors.get(child.findtext(f"{KML_NS}styleUrl") or "")
                for d in child.findall(f"{KML_NS}ExtendedData/{KML_NS}Data"):
                    k = d.get("name")
                    v = (d.findtext(f"{KML_NS}value") or "").strip()
                    if k and v and k not in props:
                        props[k] = v
                for g in _geoms(child):
                    if geometry_types and g["type"] not in geometry_types:
                        continue
                    p = dict(props, source=origin.split("&")[0])
                    if color and g["type"] != "Point":
                        p["stroke"] = color
                    feats.append({"type": "Feature", "geometry": g, "properties": p})

    walk(root, None)
    return feats


def apply_rules(feats, trail):
    """Drop excluded layers, classify with the first matching rule, drop excluded categories.

    Rule: {"if": {"section"|"layer"|"description": regex, "stroke": "#rrggbb"}, "set": {...}}
    """
    skip_layers = [re.compile(r) for r in trail.get("exclude_layers", [])]
    skip_cats = set(trail.get("exclude_categories", []))
    out, seen, dropped = [], set(), {}
    for f in feats:
        p = f["properties"]
        if any(r.search(p.get("layer", "")) for r in skip_layers):
            dropped["layer: " + p.get("layer", "")] = dropped.get("layer: " + p.get("layer", ""), 0) + 1
            continue
        for rule in trail.get("rules", []):
            cond = rule.get("if", {})
            if all((p.get(k, "").lower() == v.lower()) if k == "stroke"
                   else re.search(v, p.get(k, "")) for k, v in cond.items()):
                p.update(rule.get("set", {}))
                break
        if p.get("category") in skip_cats:
            dropped["category: " + p["category"]] = dropped.get("category: " + p["category"], 0) + 1
            continue
        f["id"] = feature_id(f["geometry"], p)
        if f["id"] in seen:  # My Maps sometimes emits exact duplicates
            continue
        seen.add(f["id"])
        out.append(f)
    return out, dropped


# ---------------------------------------------------------------- Mapbox dataset

def dataset_features(user, dataset, token):
    feats, start = [], None
    while True:
        # The features endpoint sits behind a CDN with max-age=300; bust it so a run
        # right after --apply diffs against the real dataset, not a stale copy.
        params = {"limit": 100, "nocache": int(time.time() * 1000)}
        if start:
            params["start"] = start
        page = http("GET", mb(f"/datasets/v1/{user}/{dataset}/features", token, **params))
        batch = page.get("features", [])
        feats.extend(batch)
        if len(batch) < 100:
            return feats
        start = batch[-1]["id"]


def line_km(features):
    def hav(a, b):
        R = 6371.0088
        la1, la2 = math.radians(a[1]), math.radians(b[1])
        dla, dlo = la2 - la1, math.radians(b[0] - a[0])
        h = math.sin(dla / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin(dlo / 2) ** 2
        return 2 * R * math.asin(math.sqrt(h))
    total = 0.0
    for f in features:
        g = f.get("geometry") or {}
        lines = [g["coordinates"]] if g.get("type") == "LineString" else \
            g["coordinates"] if g.get("type") == "MultiLineString" else []
        for line in lines:
            total += sum(hav(line[i], line[i + 1]) for i in range(len(line) - 1))
    return total


def write_geojson(path, features):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, indent=1)
        f.write("\n")


def publish_tileset(user, cfg, token):
    body = {"url": f"mapbox://datasets/{user}/{cfg['dataset']}",
            "tileset": cfg["tileset"], "name": cfg["tileset_name"]}
    up = http("POST", mb(f"/uploads/v1/{user}", token), body)
    print(f"  upload {up['id']} queued -> {cfg['tileset']}")
    while not up.get("complete"):
        if up.get("error"):
            raise SystemExit(f"  upload failed: {up['error']}")
        time.sleep(5)
        up = http("GET", mb(f"/uploads/v1/{user}/{up['id']}", token))
        print(f"  progress {up.get('progress', 0):.0%}")
    if up.get("error"):
        raise SystemExit(f"  upload failed: {up['error']}")
    print("  tileset published")


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("trail", help="trail key from sources.json")
    ap.add_argument("--kml-file", help="use a local KML/KMZ instead of downloading the source")
    ap.add_argument("--apply", action="store_true", help="write changes to the Mapbox dataset")
    ap.add_argument("--publish", action="store_true", help="re-export the dataset to the live tileset")
    ap.add_argument("--force", action="store_true",
                    help="apply even if the source has under half the current trail length")
    ap.add_argument("--config", default=os.path.join(HERE, "sources.json"))
    args = ap.parse_args()

    token = os.environ.get("MAPBOX_TOKEN")
    if not token:
        raise SystemExit("MAPBOX_TOKEN is not set")
    conf = json.load(open(args.config))
    user = conf["mapbox_user"]
    trail = conf["trails"].get(args.trail) or sys.exit(f"Unknown trail {args.trail!r}")
    mcfg = trail["mapbox"]
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    print(f"[1/5] fetching source for {trail['name']}")
    blob, origin = fetch_kml(trail["source"], args.kml_file)

    print("[2/5] converting KML")
    new = kml_to_features(blob, trail.get("geometry_types"), origin)
    new, dropped = apply_rules(new, trail)
    for why, n in sorted(dropped.items()):
        print(f"      skipped {n} feature(s) by {why}")
    cats = {}
    for f in new:
        c = f["properties"].get("category", "(none)")
        cats.setdefault(c, []).append(f)
    for c, fs in sorted(cats.items()):
        print(f"      {c:12s} {len(fs):3d} features {line_km(fs):6.1f} km")
    if not new:
        raise SystemExit("Source produced no features; refusing to continue.")

    print(f"[3/5] reading Mapbox dataset {mcfg['dataset']}")
    old = dataset_features(user, mcfg["dataset"], token)
    backup = os.path.join(HERE, "backups", f"{args.trail}-{stamp}.geojson")
    write_geojson(backup, old)

    old_ids = {f["id"] for f in old}
    new_ids = {f["id"] for f in new}
    adds = [f for f in new if f["id"] not in old_ids]
    dels = [i for i in old_ids if i not in new_ids]
    print(f"      current: {len(old)} features, {line_km(old):.1f} km of line")
    print(f"      source:  {len(new)} features, {line_km(new):.1f} km of line")
    print(f"      diff:    +{len(adds)} new/changed, -{len(dels)} removed, "
          f"{len(new_ids & old_ids)} unchanged")
    print(f"      backup:  {os.path.relpath(backup)}")
    preview = os.path.join(HERE, "backups", f"{args.trail}-{stamp}.source.geojson")
    write_geojson(preview, new)
    print(f"      source preview: {os.path.relpath(preview)}")

    old_km, new_km = line_km(old), line_km(new)
    if args.apply and old_km and new_km < 0.5 * old_km and not args.force:
        raise SystemExit(f"Source has {new_km:.1f} km vs {old_km:.1f} km on Mapbox (<50%). "
                         "Inspect the preview, then rerun with --force if this is intended.")

    if args.apply:
        print("[4/5] applying to dataset")
        for n, f in enumerate(adds, 1):
            http("PUT", mb(f"/datasets/v1/{user}/{mcfg['dataset']}/features/{f['id']}", token), f)
            print(f"\r      put {n}/{len(adds)}", end="")
        print()
        for n, fid in enumerate(dels, 1):
            http("DELETE", mb(f"/datasets/v1/{user}/{mcfg['dataset']}/features/{fid}", token))
            print(f"\r      delete {n}/{len(dels)}", end="")
        print()
        write_geojson(os.path.join(HERE, "data", f"{args.trail}.geojson"),
                      sorted(new, key=lambda f: f["id"]))
        print(f"      snapshot: sync/data/{args.trail}.geojson (commit it to record the change)")
    else:
        print("[4/5] dry run: dataset not changed (use --apply)")

    if args.publish:
        print("[5/5] publishing tileset")
        publish_tileset(user, mcfg, token)
    else:
        print("[5/5] tileset not published (use --publish)")


if __name__ == "__main__":
    main()

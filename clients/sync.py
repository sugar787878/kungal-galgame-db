#!/usr/bin/env python3
"""Sync the Kungal galgame database from GitHub, verify, and query it.

Standard library only (Python 3.8+).

    python sync.py --dest ./kungal_data                 # fetch/update db
    python sync.py --dest ./kungal_data --covers        # + download covers zip
    python sync.py --dest ./kungal_data --query 恋爱    # search names
    python sync.py --dest ./kungal_data --id 1047       # one work

Update flow: read latest.json -> compare local .version -> download to .tmp ->
verify sha256 -> os.replace (atomic). Safe to run while another process reads.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
import urllib.request

DEFAULT_BASE = "https://raw.githubusercontent.com/sugar787878/kungal-galgame-db/main/"
UA = "kungal-db-sync/1.0"


def fetch(url, dest=None, timeout=120):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        if dest is None:
            return r.read()
        tmp = dest + ".tmp"
        h = hashlib.sha256()
        with open(tmp, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                h.update(chunk)
                f.write(chunk)
        return tmp, h.hexdigest()


def sha256_file(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sync(dest, base=DEFAULT_BASE, with_covers=False, force=False):
    os.makedirs(dest, exist_ok=True)
    meta_path = os.path.join(dest, "latest.json")
    meta = json.loads(fetch(base + "data/latest.json").decode("utf-8"))
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    version = meta["version"]
    ver_path = os.path.join(dest, ".version")
    local = open(ver_path).read().strip() if os.path.exists(ver_path) else ""
    need = force or local != version

    jobs = [("kungal_galgame.db", meta["files"]["kungal_galgame.db"])]
    if with_covers and "covers" in meta.get("release_assets", {}):
        asset = meta["release_assets"]["covers"]
        url = "https://github.com/sugar787878/kungal-galgame-db/releases/download/v%s/%s" % (
            version, asset["name"])
        jobs.append((asset["name"], {"path": None, "url": url, "sha256": asset["sha256"]}))

    for name, info in jobs:
        target = os.path.join(dest, name)
        if not need and os.path.exists(target):
            print("[skip] %s (version %s)" % (name, version))
            continue
        url = info.get("url") or (base + info["path"])
        print("[get ] %s <- %s" % (name, url))
        tmp, digest = fetch(url, target)
        if digest != info["sha256"]:
            os.remove(tmp)
            raise SystemExit("sha256 mismatch for %s: %s != %s" % (name, digest, info["sha256"]))
        os.replace(tmp, target)
        print("[ok  ] %s  %d bytes" % (name, os.path.getsize(target)))

    with open(ver_path, "w") as f:
        f.write(version + "\n")
    print("db ready: %s (version %s, %d works)"
          % (os.path.join(dest, "kungal_galgame.db"), version, meta["counts"]["works"]))
    return os.path.join(dest, "kungal_galgame.db")


def connect(db_path):
    con = sqlite3.connect("file:%s?mode=ro" % db_path.replace("\\", "/"), uri=True)
    con.row_factory = sqlite3.Row
    return con


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default="./kungal_data")
    ap.add_argument("--base", default=DEFAULT_BASE, help="raw base url (override for mirrors)")
    ap.add_argument("--covers", action="store_true", help="also download the covers zip")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--query", default=None, help="search display_name/name_zh/name_ja")
    ap.add_argument("--id", default=None, help="print one work as json")
    ap.add_argument("--limit", type=int, default=10)
    args = ap.parse_args()

    db = sync(args.dest, args.base, args.covers, args.force)
    if not (args.query or args.id):
        return
    con = connect(db)
    if args.id:
        row = con.execute("SELECT * FROM works WHERE id = ?", (args.id,)).fetchone()
        print(json.dumps(dict(row) if row else None, ensure_ascii=False, indent=2))
        return
    like = "%" + args.query + "%"
    rows = con.execute(
        "SELECT id, display_name, name_zh, release_date, cover_url FROM works "
        "WHERE display_name LIKE ? OR name_zh LIKE ? OR name_ja LIKE ? "
        "ORDER BY in_resource_lib DESC, view_count DESC LIMIT ?",
        (like, like, like, args.limit)).fetchall()
    for r in rows:
        print("%-7s %-40s %-24s %-10s %s"
              % (r["id"], r["display_name"], r["name_zh"] or "", r["release_date"] or "",
                 r["cover_url"]))


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Rebuild every derived artifact from data/kungal_galgame.db.

Used by .github/workflows/refresh.yml after the crawlers run, and usable locally:

    python scripts/build_dataset.py --db data/kungal_galgame.db
    python scripts/build_dataset.py --db data/kungal_galgame.db --covers-zip /tmp/covers.zip

Produces:
    data/works.csv, data/resource_library.csv, data/works.jsonl
    data/schema.sql, data/covers_manifest.csv (only when covers/ exists)
    data/latest.json      (version + sha256, covers asset carried over)
    docs/index.html       (Pages gallery, remote cover urls)
    dist/kungal_galgame_db_<version>.zip
"""
import argparse
import csv
import hashlib
import json
import os
import sqlite3
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from export_kungal import write_csv, write_jsonl, write_xlsx, write_gallery, rows  # noqa: E402

RAW_BASE = "https://raw.githubusercontent.com/sugar787878/kungal-galgame-db/main/"


def sha256(path, chunk=1 << 20):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def dump_schema(conn, path):
    lines = [sql.strip() + ";" for (sql,) in conn.execute(
        "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'")]
    with open(path, "w", encoding="utf-8") as f:
        f.write("-- Kungal galgame database schema (generated)\n" + "\n\n".join(lines) + "\n")


def covers_manifest(conn, path, covers_dir):
    if not covers_dir or not os.path.isdir(covers_dir):
        print("[manifest] covers dir absent, keep existing manifest")
        return
    out_rows = conn.execute(
        "SELECT id, cover_url, cover_hash, cover_width, cover_height FROM works "
        "WHERE cover_url IS NOT NULL AND cover_url<>'' ORDER BY id").fetchall()
    n = total = 0
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(["id", "filename", "cover_url", "cover_hash", "width", "height", "sha256", "bytes"])
        for wid, url, h, cw, ch in out_rows:
            p = os.path.join(covers_dir, "%s.webp" % wid)
            if not os.path.exists(p):
                w.writerow([wid, "", url, h, cw, ch, "", ""])
                continue
            size = os.path.getsize(p)
            w.writerow([wid, "covers/%s.webp" % wid, url, h, cw, ch, sha256(p), size])
            n += 1
            total += size
    print("[manifest] %d covers, %.1f MB" % (n, total / 1e6))


def build_zip(path, files):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for src, arc in files:
            z.write(src, arc)
    print("[zip] %s %.1f MB" % (os.path.basename(path), os.path.getsize(path) / 1e6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(ROOT, "data", "kungal_galgame.db"))
    ap.add_argument("--version", default=time.strftime("%Y.%m.%d", time.gmtime()))
    ap.add_argument("--covers-dir", default=os.path.join(ROOT, "covers"))
    ap.add_argument("--covers-zip", default=None)
    ap.add_argument("--skip-xlsx", action="store_true")
    args = ap.parse_args()

    data = os.path.join(ROOT, "data")
    docs = os.path.join(ROOT, "docs")
    os.makedirs(data, exist_ok=True)
    os.makedirs(docs, exist_ok=True)
    os.makedirs(os.path.join(ROOT, "dist"), exist_ok=True)

    conn = sqlite3.connect(args.db)
    works = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    res = conn.execute("SELECT COUNT(*) FROM works WHERE in_resource_lib=1").fetchone()[0]
    with_cover = conn.execute(
        "SELECT COUNT(*) FROM works WHERE cover_url IS NOT NULL AND cover_url<>''").fetchone()[0]

    write_csv(os.path.join(data, "works.csv"), rows(conn))
    write_csv(os.path.join(data, "resource_library.csv"), rows(conn, "in_resource_lib=1"))
    write_jsonl(os.path.join(data, "works.jsonl"), rows(conn))
    if not args.skip_xlsx:
        write_xlsx(os.path.join(ROOT, "dist", "kungal_galgame.xlsx"), conn)
    dump_schema(conn, os.path.join(data, "schema.sql"))
    covers_manifest(conn, os.path.join(data, "covers_manifest.csv"), args.covers_dir)
    write_gallery(os.path.join(docs, "index.html"), conn)

    # latest.json: keep the covers asset from the previous manifest unless a new zip is shipped
    latest_path = os.path.join(data, "latest.json")
    old = {}
    if os.path.exists(latest_path):
        try:
            old = json.load(open(latest_path, encoding="utf-8"))
        except Exception:
            old = {}

    files = {}
    for name in ("kungal_galgame.db", "works.csv", "resource_library.csv",
                 "works.jsonl", "covers_manifest.csv"):
        p = os.path.join(data, name)
        files[name] = {"path": "data/" + name, "bytes": os.path.getsize(p), "sha256": sha256(p)}

    doc = {
        "schema_version": 1,
        "version": args.version,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": "https://www.kungal.com",
        "repo": "sugar787878/kungal-galgame-db",
        "raw_base": RAW_BASE,
        "counts": {"works": works, "resource_library": res, "with_cover": with_cover},
        "files": files,
        "release_assets": {},
    }
    if args.covers_zip and os.path.exists(args.covers_zip):
        name = os.path.basename(args.covers_zip)
        doc["release_assets"]["covers"] = {
            "name": name,
            "bytes": os.path.getsize(args.covers_zip),
            "sha256": sha256(args.covers_zip),
            "url": ("https://github.com/sugar787878/kungal-galgame-db/releases/download/v%s/%s"
                    % (args.version, name)),
        }
    elif old.get("release_assets", {}).get("covers"):
        covers = dict(old["release_assets"]["covers"])
        if not covers.get("url"):
            tag = old.get("version", args.version)
            covers["url"] = ("https://github.com/sugar787878/kungal-galgame-db/releases/download/v%s/%s"
                             % (tag, covers["name"]))
        doc["release_assets"]["covers"] = covers
    doc["release"] = ("https://github.com/sugar787878/kungal-galgame-db/releases/tag/v" + args.version)

    with open(latest_path, "w", encoding="utf-8") as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("[latest] version %s, %d works, %d covers" % (args.version, works, with_cover))
    conn.close()

    zip_path = os.path.join(ROOT, "dist", "kungal_galgame_db_%s.zip" % args.version)
    parts = [(os.path.join(data, "kungal_galgame.db"), "kungal_galgame.db"),
             (os.path.join(data, "works.csv"), "kungal_works_all.csv"),
             (os.path.join(data, "resource_library.csv"), "kungal_resource_library.csv"),
             (os.path.join(data, "works.jsonl"), "kungal_works.jsonl"),
             (os.path.join(data, "covers_manifest.csv"), "covers/covers_index.csv"),
             (os.path.join(data, "schema.sql"), "schema.sql"),
             (os.path.join(ROOT, "README.md"), "README.md"),
             (os.path.join(ROOT, "DATA-NOTICE.md"), "DATA-NOTICE.md"),
             (os.path.join(docs, "index.html"), "kungal_gallery.html")]
    if not args.skip_xlsx:
        parts.append((os.path.join(ROOT, "dist", "kungal_galgame.xlsx"), "kungal_galgame.xlsx"))
    build_zip(zip_path, [p for p in parts if os.path.exists(p[0])])
    print("done")


if __name__ == "__main__":
    main()

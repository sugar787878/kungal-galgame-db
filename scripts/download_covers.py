"""Download Kungal cover images into covers/<id>.webp using the crawled SQLite DB."""
import argparse
import csv
import os
import sqlite3
import sys
import threading
import time
import urllib.request

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")


def download(url, dest, retries=4, timeout=40):
    if os.path.exists(dest) and os.path.getsize(dest) > 0:
        return "skip"
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "image/webp,image/*"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
            if not data:
                raise RuntimeError("empty body")
            tmp = dest + ".part"
            with open(tmp, "wb") as f:
                f.write(data)
            os.replace(tmp, dest)
            return "ok"
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(repr(last))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "kungal_galgame.db"))
    ap.add_argument("--outdir", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "covers"))
    ap.add_argument("--set", default="resource", choices=["resource", "all"])
    ap.add_argument("--workers", type=int, default=12)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    conn = sqlite3.connect(args.db)
    where = "in_resource_lib=1" if args.set == "resource" else "1=1"
    q = ("SELECT id, cover_url, cover_hash FROM works WHERE %s AND cover_url IS NOT NULL"
         " ORDER BY in_resource_lib DESC, id ASC" % where)
    if args.limit:
        q += " LIMIT %d" % args.limit
    items = list(conn.execute(q))
    print("to download:", len(items), flush=True)

    index_path = os.path.join(args.outdir, "covers_index.csv")
    existing = set()
    if os.path.exists(index_path):
        with open(index_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                existing.add(row["id"])

    lock = threading.Lock()
    queue = list(items)
    stats = {"ok": 0, "skip": 0, "fail": 0, "bytes": 0}
    fails = []

    def worker():
        while True:
            with lock:
                if not queue:
                    return
                wid, url, h = queue.pop(0)
            dest = os.path.join(args.outdir, "%s.webp" % wid)
            try:
                st = download(url, dest)
                with lock:
                    if st == "ok":
                        stats["ok"] += 1
                        stats["bytes"] += os.path.getsize(dest)
                    else:
                        stats["skip"] += 1
                    if stats["ok"] % 200 == 0 and stats["ok"]:
                        print("  ok=%d skip=%d fail=%d %.1f MB"
                              % (stats["ok"], stats["skip"], stats["fail"],
                                 stats["bytes"] / 1e6), flush=True)
            except Exception as e:  # noqa: BLE001
                with lock:
                    stats["fail"] += 1
                    fails.append((wid, repr(e)))

    threads = [threading.Thread(target=worker, daemon=True) for _ in range(args.workers)]
    t0 = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with open(index_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "filename", "cover_url", "cover_hash"])
        for wid, url, h in items:
            fn = "%s.webp" % wid
            if os.path.exists(os.path.join(args.outdir, fn)):
                w.writerow([wid, fn, url, h])

    print("done in %.1fs: ok=%d skip=%d fail=%d total=%.1f MB"
          % (time.time() - t0, stats["ok"], stats["skip"], stats["fail"], stats["bytes"] / 1e6))
    if fails:
        print("failures:", fails[:10])


if __name__ == "__main__":
    main()

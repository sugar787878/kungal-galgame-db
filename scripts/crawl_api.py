"""Crawl Kungal JSON API /api/v1/{library-works,works} with sort / year / tag partitions.

The page-number collection caps at 10,000 items (page<=100 with limit=100), so we
union several sort windows plus release-year windows to reach the whole catalog.
"""
import argparse
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from crawl_kungal import UA, DDL, flatten, now

API = "https://www.kungal.com/api/v1"
SORTS = ["popularity_desc", "released_asc", "released_desc", "updated_desc"]

STATE_DDL = """
CREATE TABLE IF NOT EXISTS api_state (
    endpoint TEXT, sort TEXT, page INTEGER, ok INTEGER, n_items INTEGER, total INTEGER,
    fetched_at TEXT, PRIMARY KEY (endpoint, sort, page)
);
"""


class ApiCrawler:
    def __init__(self, db, workers=4, delay=0.34, retries=5):
        self.db = db
        self.workers = workers
        self.delay = delay
        self.retries = retries
        self.lock = threading.Lock()
        self.pace_lock = threading.Lock()
        self.next_slot = 0.0
        self.block_until = 0.0
        self.done = 0
        self.rows = 0
        self.failed = []

    def pace(self):
        with self.pace_lock:
            start = max(time.time(), self.next_slot, self.block_until)
            self.next_slot = start + self.delay
        wait = start - time.time()
        if wait > 0:
            time.sleep(wait)

    def block(self, s):
        with self.pace_lock:
            self.block_until = max(self.block_until, time.time() + s)

    def get_json(self, path):
        last = None
        for attempt in range(self.retries):
            try:
                self.pace()
                req = urllib.request.Request(API + path, headers={
                    "User-Agent": UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    return json.loads(r.read().decode("utf-8", "replace"))
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 429:
                    self.block(20 + 10 * attempt)
                elif e.code == 400:
                    raise
                else:
                    self.block(5 * (attempt + 1))
            except Exception as e:  # noqa: BLE001
                last = e
                self.block(3 * (attempt + 1))
        raise RuntimeError("%s failed: %r" % (path, last))

    def store(self, endpoint, key, page, body):
        items = body.get("items") or []
        fetched = now()
        rows = [flatten(it, "galgame" if endpoint == "works" else "gallib", fetched) for it in items]
        conn = sqlite3.connect(self.db, timeout=60)
        try:
            if rows:
                cols = list(rows[0].keys())
                updates = ",".join("%s=excluded.%s" % (c, c) for c in cols
                                   if c not in ("id", "in_resource_lib", "in_gallib"))
                sql = ("INSERT INTO works (%s) VALUES (%s) ON CONFLICT(id) DO UPDATE SET %s,"
                       " in_resource_lib=MAX(works.in_resource_lib, excluded.in_resource_lib),"
                       " in_gallib=MAX(works.in_gallib, excluded.in_gallib)"
                       % (",".join(cols), ",".join("?" for _ in cols), updates))
                conn.executemany(sql, [[r[c] for c in cols] for r in rows])
            conn.execute("REPLACE INTO api_state(endpoint,sort,page,ok,n_items,total,fetched_at)"
                         " VALUES(?,?,?,?,?,?,?)",
                         (endpoint, key, page, 1, len(rows), body.get("total"), fetched))
            conn.commit()
        finally:
            conn.close()
        with self.lock:
            self.done += 1
            self.rows += len(rows)
            if self.done % 60 == 0:
                print("[api] %d tasks, %d rows" % (self.done, self.rows), flush=True)

    def worker(self, queue):
        while True:
            with self.lock:
                if not queue:
                    return
                endpoint, key, page, qs = queue.pop(0)
            try:
                body = self.get_json("/%s?page=%d&limit=100%s" % (endpoint, page, qs))
                self.store(endpoint, key, page, body)
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.failed.append((endpoint, key, page, repr(e)))
                print("[api] FAIL %s %s p%s: %r" % (endpoint, key, page, e), flush=True)

    def run(self, tasks):
        queue = list(tasks)
        threads = [threading.Thread(target=self.worker, args=(queue,), daemon=True)
                   for _ in range(self.workers)]
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print("[api] done %d tasks, %d rows in %.1fs, failures=%d"
              % (self.done, self.rows, time.time() - t0, len(self.failed)), flush=True)
        return self.failed


def probe_total(path, qs):
    req = urllib.request.Request(API + path + qs, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode()).get("total") or 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "kungal_galgame.db"))
    ap.add_argument("--sorts", default=None)
    ap.add_argument("--years", default=None, help="e.g. 1980-2032")
    ap.add_argument("--tags", default=None, help="comma list of tag_ids")
    ap.add_argument("--companies", default=None, help="comma list of company_ids")
    ap.add_argument("--max-page", type=int, default=100)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--delay", type=float, default=0.34)
    ap.add_argument("--include-works", action="store_true")
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--include-nsfw", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    db.executescript(DDL)
    db.execute(STATE_DDL)
    db.commit()

    def build(endpoint, key, qs, max_page=None):
        t = probe_total("/" + endpoint, "?page=1&limit=1" + qs)
        pages = min(max_page or args.max_page, max(1, (t + 99) // 100))
        return [(endpoint, key, p, qs) for p in range(1, pages + 1)]

    tasks = []
    nsfw_qs = "&include_nsfw=true" if args.include_nsfw else ""
    if args.sorts:
        for sort in [s for s in args.sorts.split(",") if s]:
            tasks += [("library-works", sort + nsfw_qs, p, "&sort=" + sort + nsfw_qs)
                      for p in range(1, args.max_page + 1)]
    if args.years:
        a, b = map(int, args.years.split("-"))
        for y in range(a, b + 1):
            tasks += build("library-works", "year:%d%s" % (y, nsfw_qs),
                           "&released_from=%d&released_to=%d%s" % (y, y, nsfw_qs))
    if args.tags:
        for tag in args.tags.split(","):
            tag = tag.strip()
            if tag:
                tasks += build("library-works", "tag:%s%s" % (tag, nsfw_qs),
                               "&tag_ids=%s%s" % (tag, nsfw_qs), max_page=100)
    if args.companies:
        for cid in args.companies.split(","):
            cid = cid.strip()
            if cid:
                tasks += build("library-works", "company:%s%s" % (cid, nsfw_qs),
                               "&company_id=%s%s" % (cid, nsfw_qs), max_page=100)
    if args.include_works:
        tasks += build("works", "works", "", max_page=100)

    if args.resume:
        done = {(a, b, c) for a, b, c in db.execute(
            "SELECT endpoint,sort,page FROM api_state WHERE ok=1")}
        tasks = [t for t in tasks if (t[0], t[1], t[2]) not in done]
    print("tasks:", len(tasks), flush=True)
    db.close()

    c = ApiCrawler(args.db, workers=args.workers, delay=args.delay)
    failed = c.run(tasks)
    if failed:
        print("FAILED:", failed[:8])
        sys.exit(4)


if __name__ == "__main__":
    main()

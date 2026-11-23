"""Crawl Kungal release-calendar by month -> works with name + cover.

https://www.kungal.com/galgame-calendar?month=YYYY-MM returns every work released
in that month (SSR payload key: api:release-calendar:<month>:...).
"""
import argparse
import json
import os
import sqlite3
import sys
import threading
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_nuxt import extract_payload, decode
from crawl_kungal import UA, DDL, flatten, now

BASE = "https://www.kungal.com/galgame-calendar?month={}"

MIGRATIONS = [
    "ALTER TABLE works ADD COLUMN in_calendar INTEGER DEFAULT 0",
    """CREATE TABLE IF NOT EXISTS calendar_state (
        month TEXT PRIMARY KEY, ok INTEGER, n_items INTEGER, fetched_at TEXT)""",
]


def months_between(start, end):
    y, m = start
    ey, em = end
    out = []
    while (y, m) <= (ey, em):
        out.append("%04d-%02d" % (y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


class CalCrawler:
    def __init__(self, db, workers=3, delay=0.35, retries=6):
        self.db = db
        self.workers = workers
        self.delay = delay
        self.retries = retries
        self.lock = threading.Lock()
        self.pace_lock = threading.Lock()
        self.next_slot = 0.0
        self.block_until = 0.0
        self.failed = []
        self.done = 0
        self.rows = 0

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

    def fetch(self, month):
        last = None
        for attempt in range(self.retries):
            try:
                self.pace()
                req = urllib.request.Request(BASE.format(month), headers={
                    "User-Agent": UA, "Accept": "text/html",
                    "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8"})
                with urllib.request.urlopen(req, timeout=60) as r:
                    html = r.read().decode("utf-8", "replace")
                data = decode(extract_payload(html)).get("data") or {}
                for k, v in data.items():
                    if k.startswith("api:release-calendar"):
                        body = v.get("data", v)
                        if isinstance(body, dict) and body.get("ok") is False:
                            raise RuntimeError("problem: %s" % json.dumps(body.get("problem"))[:200])
                        return body
                raise RuntimeError("no calendar key")
            except Exception as e:  # noqa: BLE001
                last = e
                self.block(min(90, 8 * (attempt + 1)))
        raise RuntimeError("month %s failed: %r" % (month, last))

    def store(self, month, body):
        items = body.get("items") or []
        fetched = now()
        conn = sqlite3.connect(self.db, timeout=60)
        try:
            conn.execute("PRAGMA journal_mode=WAL")
            rows = [flatten(it, "gallib", fetched) for it in items]
            if rows:
                cols = list(rows[0].keys())
                updates = ",".join("%s=excluded.%s" % (c, c) for c in cols
                                   if c not in ("id", "in_resource_lib", "in_gallib"))
                sql = ("INSERT INTO works (%s) VALUES (%s) ON CONFLICT(id) DO UPDATE SET %s,"
                       " in_resource_lib=MAX(works.in_resource_lib, excluded.in_resource_lib),"
                       " in_gallib=MAX(works.in_gallib, excluded.in_gallib), in_calendar=1"
                       % (",".join(cols), ",".join("?" for _ in cols), updates))
                conn.executemany(sql, [[r[c] for c in cols] for r in rows])
            conn.execute("REPLACE INTO calendar_state(month,ok,n_items,fetched_at) VALUES(?,?,?,?)",
                         (month, 1, len(rows), fetched))
            conn.commit()
        finally:
            conn.close()
        with self.lock:
            self.done += 1
            self.rows += len(items)
            if self.done % 40 == 0:
                print("[calendar] %d months, %d item-rows" % (self.done, self.rows), flush=True)

    def worker(self, queue):
        while True:
            with self.lock:
                if not queue:
                    return
                month = queue.pop(0)
            try:
                self.store(month, self.fetch(month))
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.failed.append((month, repr(e)))
                print("[calendar] FAIL %s: %r" % (month, e), flush=True)

    def run(self, months):
        queue = list(months)
        threads = [threading.Thread(target=self.worker, args=(queue,), daemon=True)
                   for _ in range(self.workers)]
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print("[calendar] done %d months, %d rows in %.1fs, failures=%d"
              % (self.done, self.rows, time.time() - t0, len(self.failed)), flush=True)
        return self.failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "kungal_galgame.db"))
    ap.add_argument("--start", default="1960-01")
    ap.add_argument("--end", default="2032-12")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--delay", type=float, default=0.35)
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    db.executescript(DDL)
    for m in MIGRATIONS:
        try:
            db.execute(m)
        except sqlite3.OperationalError:
            pass
    db.commit()

    sy, sm = map(int, args.start.split("-"))
    ey, em = map(int, args.end.split("-"))
    months = months_between((sy, sm), (ey, em))
    if args.resume:
        done = {r[0] for r in db.execute("SELECT month FROM calendar_state WHERE ok=1")}
        months = [m for m in months if m not in done]
    print("months to fetch:", len(months), flush=True)
    db.close()

    c = CalCrawler(args.db, workers=args.workers, delay=args.delay)
    failed = c.run(months)
    if failed:
        print("FAILED:", failed[:10])
        sys.exit(3)


if __name__ == "__main__":
    main()

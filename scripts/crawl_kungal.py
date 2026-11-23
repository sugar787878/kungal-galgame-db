"""
Kungal (www.kungal.com) galgame works crawler — rate-limit friendly.

Datasets:
  galgame : https://www.kungal.com/galgame?page=N   -> resource library
  gallib  : https://www.kungal.com/gallib?page=N    -> full galgame info database

SSR payload: api:works / api:library-works -> { object, items[], total, total_relation }
"""
import argparse
import gzip
import io
import json
import os
import random
import re
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import zlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from parse_nuxt import extract_payload, decode

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

BASES = {
    "galgame": "https://www.kungal.com/galgame?page={}",
    "gallib": "https://www.kungal.com/gallib?page={}",
}
PREFIX = {"galgame": "api:works", "gallib": "api:library-works"}

DDL = """
CREATE TABLE IF NOT EXISTS works (
    id TEXT PRIMARY KEY,
    display_name TEXT, name_ja TEXT, name_zh TEXT, name_en TEXT, name_latin TEXT,
    cover_url TEXT, cover_hash TEXT, cover_width INTEGER, cover_height INTEGER,
    cover_sexual TEXT, cover_sfw_url TEXT, banner_url TEXT,
    release_date TEXT, release_date_precision TEXT,
    maker_id TEXT, maker_name TEXT,
    is_nsfw INTEGER, is_published INTEGER,
    view_count INTEGER, like_count INTEGER, rating_score REAL, rating_count INTEGER,
    resource_platforms TEXT, resource_languages TEXT, resource_updated_at TEXT,
    in_resource_lib INTEGER DEFAULT 0, in_gallib INTEGER DEFAULT 0,
    detail_url TEXT, fetched_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_works_name ON works(display_name);
CREATE INDEX IF NOT EXISTS idx_works_date ON works(release_date);
CREATE TABLE IF NOT EXISTS crawl_state (
    dataset TEXT, page INTEGER, ok INTEGER, n_items INTEGER, total INTEGER,
    fetched_at TEXT, PRIMARY KEY (dataset, page)
);
"""


def now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def localized_name(localized, lang):
    if not isinstance(localized, dict):
        return None
    v = localized.get(lang)
    if isinstance(v, dict):
        return v.get("value")
    return v if isinstance(v, str) else None


def flatten(item, dataset, fetched):
    cover = item.get("cover") or {}
    cover_sfw = item.get("cover_sfw") or {}
    banner = item.get("banner") or {}
    maker = item.get("maker") or {}
    loc = item.get("localized") or {}
    wid = str(item.get("id"))
    return {
        "id": wid,
        "display_name": item.get("display_name"),
        "name_ja": localized_name(loc, "ja"),
        "name_zh": localized_name(loc, "zh-Hans"),
        "name_en": localized_name(loc, "en"),
        "name_latin": item.get("latin"),
        "cover_url": cover.get("url"),
        "cover_hash": cover.get("hash"),
        "cover_width": cover.get("width"),
        "cover_height": cover.get("height"),
        "cover_sexual": cover.get("sexual"),
        "cover_sfw_url": cover_sfw.get("url"),
        "banner_url": banner.get("url"),
        "release_date": item.get("release_date"),
        "release_date_precision": item.get("release_date_precision"),
        "maker_id": str(maker.get("id")) if maker.get("id") is not None else None,
        "maker_name": maker.get("display_name"),
        "is_nsfw": 1 if item.get("is_nsfw") else 0,
        "is_published": 1 if item.get("is_published") else 0,
        "view_count": item.get("view_count"),
        "like_count": item.get("like_count"),
        "rating_score": item.get("rating_score"),
        "rating_count": item.get("rating_count"),
        "resource_platforms": json.dumps(item.get("resource_platforms") or [], ensure_ascii=False),
        "resource_languages": json.dumps(item.get("resource_languages") or [], ensure_ascii=False),
        "resource_updated_at": item.get("resource_updated_at"),
        "in_resource_lib": 1 if dataset == "galgame" else 0,
        "in_gallib": 1 if dataset == "gallib" else 0,
        "detail_url": "https://www.kungal.com/galgame/%s" % wid,
        "fetched_at": fetched,
    }


class Crawler:
    def __init__(self, db_path, dataset, workers=2, retries=6, timeout=60, delay=0.6):
        self.db_path = db_path
        self.dataset = dataset
        self.workers = workers
        self.retries = retries
        self.timeout = timeout
        self.delay = delay
        self.lock = threading.Lock()
        self.pace_lock = threading.Lock()
        self.next_slot = 0.0
        self.global_block_until = 0.0
        self.done = 0
        self.rows = 0
        self.failed = []
        self.consecutive_throttle = 0

    # ---------- infra ----------
    def db(self):
        conn = sqlite3.connect(self.db_path, timeout=60)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def pace(self):
        with self.pace_lock:
            t = time.time()
            start = max(t, self.next_slot, self.global_block_until)
            self.next_slot = start + self.delay
        wait = start - time.time()
        if wait > 0:
            time.sleep(wait)

    def block_all(self, seconds):
        with self.pace_lock:
            self.global_block_until = max(self.global_block_until, time.time() + seconds)
        print("  [throttle] global pause %.0fs" % seconds, flush=True)

    def get(self, url):
        self.pace()
        req = urllib.request.Request(url, headers={
            "User-Agent": UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9,ja;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate",
            "Cache-Control": "no-cache",
        })
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            raw = r.read()
            enc = (r.headers.get("Content-Encoding") or "").lower()
        if enc == "gzip":
            raw = gzip.decompress(raw)
        elif enc == "deflate":
            raw = zlib.decompress(raw, -zlib.MAX_WBITS)
        return raw.decode("utf-8", "replace")

    # ---------- fetch ----------
    def fetch_page(self, page):
        url = BASES[self.dataset].format(page)
        last = None
        for attempt in range(self.retries):
            try:
                html = self.get(url)
                data = decode(extract_payload(html)).get("data") or {}
                for k, v in data.items():
                    if k.startswith(PREFIX[self.dataset]):
                        body = v.get("data", v) if isinstance(v, dict) else v
                        items = body.get("items")
                        if not items:
                            raise RuntimeError("empty items (throttle?)")
                        return body
                m = re.search(r"<title>(.*?)</title>", html, re.S)
                raise RuntimeError("no payload key; title=%r" % (m.group(1) if m else "?"))
            except urllib.error.HTTPError as e:
                last = e
                if e.code == 429:
                    wait = min(120, 20 * (attempt + 1)) + random.random() * 5
                    self.block_all(wait)
                    continue
                if 500 <= e.code < 600:
                    time.sleep(5 * (attempt + 1))
                    continue
                time.sleep(2 * (attempt + 1))
            except Exception as e:  # noqa: BLE001
                last = e
                # throttle-looking failure -> back off hard
                self.block_all(min(90, 10 * (attempt + 1)) + random.random() * 5)
        raise RuntimeError("page %s failed: %r" % (page, last))

    # ---------- store ----------
    def store(self, page, body):
        items = body.get("items") or []
        fetched = now()
        rows = [flatten(it, self.dataset, fetched) for it in items]
        conn = self.db()
        try:
            if rows:
                cols = list(rows[0].keys())
                placeholders = ",".join("?" for _ in cols)
                updates = ",".join("%s=excluded.%s" % (c, c) for c in cols
                                   if c not in ("id", "in_resource_lib", "in_gallib"))
                sql = ("INSERT INTO works (%s) VALUES (%s) ON CONFLICT(id) DO UPDATE SET %s,"
                       " in_resource_lib=MAX(works.in_resource_lib, excluded.in_resource_lib),"
                       " in_gallib=MAX(works.in_gallib, excluded.in_gallib)"
                       % (",".join(cols), placeholders, updates))
                conn.executemany(sql, [[r[c] for c in cols] for r in rows])
            conn.execute("INSERT OR REPLACE INTO crawl_state(dataset,page,ok,n_items,total,fetched_at)"
                         " VALUES(?,?,?,?,?,?)",
                         (self.dataset, page, 1, len(rows), body.get("total"), fetched))
            conn.commit()
        finally:
            conn.close()
        with self.lock:
            self.rows += len(rows)
            self.done += 1
            if self.done % 50 == 0:
                print("[%s] %d pages, %d rows" % (self.dataset, self.done, self.rows), flush=True)

    def worker(self, queue):
        while True:
            with self.lock:
                if not queue:
                    return
                page = queue.pop(0)
            try:
                self.store(page, self.fetch_page(page))
            except Exception as e:  # noqa: BLE001
                with self.lock:
                    self.failed.append((page, repr(e)))
                print("[%s] FAIL page %s: %r" % (self.dataset, page, e), flush=True)

    def run(self, pages):
        queue = list(pages)
        threads = [threading.Thread(target=self.worker, args=(queue,), daemon=True)
                   for _ in range(max(1, min(self.workers, len(queue))))]
        t0 = time.time()
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        print("[%s] finished %d pages, %d rows in %.1fs, %d failures"
              % (self.dataset, self.done, self.rows, time.time() - t0, len(self.failed)), flush=True)
        return self.failed


def parse_pages(spec):
    out = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            out.extend(range(int(a), int(b) + 1))
        else:
            out.append(int(part))
    return sorted(set(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default="galgame", choices=["galgame", "gallib"])
    ap.add_argument("--pages", default=None)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--delay", type=float, default=0.6)
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "kungal_galgame.db"))
    ap.add_argument("--resume", action="store_true", help="skip pages already ok in crawl_state")
    ap.add_argument("--max-pages", type=int, default=None)
    args = ap.parse_args()

    db = sqlite3.connect(args.db)
    db.executescript(DDL)
    db.commit()

    c = Crawler(args.db, args.dataset, workers=args.workers, delay=args.delay)
    if args.pages:
        pages = parse_pages(args.pages)
    else:
        body = c.fetch_page(1)
        total = body.get("total") or 0
        last = max(1, (total + 23) // 24)
        print("total=%s -> pages 1..%s" % (total, last), flush=True)
        c.store(1, body)
        pages = list(range(2, last + 1))

    if args.resume:
        done = {r[0] for r in db.execute(
            "SELECT page FROM crawl_state WHERE dataset=? AND ok=1", (args.dataset,))}
        before = len(pages)
        pages = [p for p in pages if p not in done]
        print("resume: %d pages already done, %d to fetch" % (before - len(pages), len(pages)))
    if args.max_pages:
        pages = pages[:args.max_pages]
    db.close()

    failed = c.run(pages)
    if failed:
        print("FAILED %d pages, first 10: %s" % (len(failed), failed[:10]))
        sys.exit(2)


if __name__ == "__main__":
    main()

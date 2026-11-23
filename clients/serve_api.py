#!/usr/bin/env python3
"""Serve the Kungal galgame database as a read-only HTTP API.

    pip install fastapi uvicorn
    python serve_api.py --db data/kungal_galgame.db --covers covers --port 8000

    GET /health
    GET /latest.json                     版本与校验清单（若有 data/latest.json）
    GET /works?q=恋爱&page=1&size=20      模糊搜索（display_name / name_zh / name_ja）
    GET /works/{id}                      单部作品
    GET /covers/{id}.webp                本地封面（需要 covers/ 目录或 zip 解压结果）
"""
import argparse
import json
import os
import sqlite3

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse

app = FastAPI(title="Kungal Galgame DB", version="2026.11.23")
DB_PATH = "data/kungal_galgame.db"
COVERS_DIR = "covers"

COLUMNS = ["id", "display_name", "name_zh", "name_ja", "name_en", "name_latin",
           "cover_url", "cover_width", "cover_height", "cover_sexual", "banner_url",
           "release_date", "maker_id", "maker_name", "rating_score", "rating_count",
           "view_count", "like_count", "resource_platforms", "resource_languages",
           "resource_updated_at", "in_resource_lib", "in_gallib", "is_nsfw",
           "detail_url", "fetched_at"]


def con():
    c = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"), uri=True,
                        check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


@app.get("/health")
def health():
    c = con()
    n = c.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    c.close()
    return {"ok": True, "works": n}


@app.get("/latest.json")
def latest():
    path = os.path.join(os.path.dirname(DB_PATH), "latest.json")
    if not os.path.exists(path):
        raise HTTPException(404, "latest.json not found")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.get("/works")
def works(q: str = "", page: int = Query(1, ge=1), size: int = Query(20, ge=1, le=200),
          resource_only: bool = False):
    offset = (page - 1) * size
    where, args = [], []
    if q:
        like = "%" + q.replace("%", r"\%").replace("_", r"\_") + "%"
        where.append("(display_name LIKE ? ESCAPE '\\' OR name_zh LIKE ? ESCAPE '\\'"
                     " OR name_ja LIKE ? ESCAPE '\\')")
        args += [like, like, like]
    if resource_only:
        where.append("in_resource_lib = 1")
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    c = con()
    total = c.execute("SELECT COUNT(*) FROM works " + clause, args).fetchone()[0]
    rows = c.execute("SELECT %s FROM works %s ORDER BY in_resource_lib DESC, view_count DESC"
                     " LIMIT ? OFFSET ?" % (",".join(COLUMNS), clause),
                     args + [size, offset]).fetchall()
    c.close()
    return {"page": page, "size": size, "total": total,
            "items": [dict(r) for r in rows]}


@app.get("/works/{wid}")
def work(wid: str):
    c = con()
    row = c.execute("SELECT * FROM works WHERE id = ?", (wid,)).fetchone()
    c.close()
    if not row:
        raise HTTPException(404, "work not found")
    return dict(row)


@app.get("/covers/{filename}")
def cover(filename: str):
    if not filename.endswith(".webp") or "/" in filename or "\\" in filename:
        raise HTTPException(400, "bad filename")
    path = os.path.join(COVERS_DIR, filename)
    if not os.path.exists(path):
        raise HTTPException(404, "cover not found")
    return FileResponse(path, media_type="image/webp",
                        headers={"Cache-Control": "public, max-age=86400"})


def main():
    global DB_PATH, COVERS_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="data/kungal_galgame.db")
    ap.add_argument("--covers", default="covers")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    DB_PATH, COVERS_DIR = args.db, args.covers
    import uvicorn
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()

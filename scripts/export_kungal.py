"""Export the crawled Kungal works table to CSV / XLSX / JSONL / HTML gallery."""
import argparse
import csv
import json
import os
import sqlite3
import sys

COLS = [
    ("id", "Kungal ID"),
    ("display_name", "名称"),
    ("name_zh", "中文名"),
    ("name_ja", "日文名"),
    ("name_en", "英文名"),
    ("name_latin", "罗马字"),
    ("cover_url", "封面URL"),
    ("cover_width", "封面宽"),
    ("cover_height", "封面高"),
    ("banner_url", "Banner URL"),
    ("release_date", "发售日"),
    ("maker_name", "制作会社"),
    ("rating_score", "评分"),
    ("rating_count", "评分人数"),
    ("view_count", "浏览量"),
    ("like_count", "点赞"),
    ("is_nsfw", "NSFW"),
    ("resource_platforms", "平台"),
    ("resource_languages", "资源语言"),
    ("resource_updated_at", "资源更新时间"),
    ("in_resource_lib", "在资源库"),
    ("in_gallib", "在资料库"),
    ("detail_url", "详情页"),
]


def rows(conn, where="1=1", order="in_resource_lib DESC, id ASC"):
    cur = conn.execute("SELECT %s FROM works WHERE %s ORDER BY %s"
                       % (",".join(c for c, _ in COLS), where, order))
    for r in cur:
        yield dict(zip([c for c, _ in COLS], r))


def write_csv(path, data):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([h for _, h in COLS])
        for row in data:
            w.writerow([row.get(c) if row.get(c) is not None else "" for c, _ in COLS])
    print("wrote", path, os.path.getsize(path), "bytes")


def write_jsonl(path, data):
    n = 0
    with open(path, "w", encoding="utf-8") as f:
        for row in data:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
            n += 1
    print("wrote", path, n, "rows")


def write_xlsx(path, conn, limit=None):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    sheets = [
        ("资源库(有资源)", "in_resource_lib=1", None),
        ("全部作品", "1=1", limit),
    ]
    first = True
    for title, where, lim in sheets:
        ws = wb.active if first else wb.create_sheet()
        first = False
        ws.title = title
        headers = [h for _, h in COLS]
        ws.append(headers)
        head_fill = PatternFill("solid", fgColor="1F4E79")
        for c in ws[1]:
            c.font = Font(bold=True, color="FFFFFF")
            c.fill = head_fill
            c.alignment = Alignment(horizontal="center", vertical="center")
        q = "SELECT %s FROM works WHERE %s ORDER BY in_resource_lib DESC, id ASC%s" % (
            ",".join(c for c, _ in COLS), where, (" LIMIT %d" % lim) if lim else "")
        for r in conn.execute(q):
            ws.append([x if x is not None else "" for x in r])
        widths = {"名称": 38, "中文名": 30, "日文名": 38, "封面URL": 60, "Banner URL": 50,
                  "详情页": 42, "制作会社": 24, "资源更新时间": 22, "英文名": 30,
                  "罗马字": 24, "平台": 18, "资源语言": 18}
        for i, h in enumerate(headers, 1):
            ws.column_dimensions[get_column_letter(i)].width = widths.get(h, 12)
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = "A1:%s%d" % (get_column_letter(len(headers)), ws.max_row)
    wb.save(path)
    print("wrote", path, os.path.getsize(path), "bytes")


def write_gallery(path, conn, limit=None):
    q = ("SELECT id, display_name, name_zh, name_ja, cover_url, release_date, maker_name,"
         " rating_score, is_nsfw FROM works WHERE in_resource_lib=1 ORDER BY id ASC")
    if limit:
        q += " LIMIT %d" % limit
    covers_dir = os.path.join(os.path.dirname(os.path.abspath(path)), "covers")
    cards = []
    for r in conn.execute(q):
        wid, name, zh, ja, cover, date, maker, score, nsfw = r
        local = os.path.join(covers_dir, "%s.webp" % wid)
        if os.path.exists(local):
            cover = "covers/%s.webp" % wid
        cards.append({
            "id": wid, "name": name or "", "zh": zh or "", "ja": ja or "",
            "cover": cover or "", "date": (date or "")[:10], "maker": maker or "",
            "score": score, "nsfw": int(nsfw or 0),
        })
    payload = json.dumps(cards, ensure_ascii=False)
    html = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<title>Kungal 资源库封面浏览</title>
<style>
:root{color-scheme:dark}
body{margin:0;background:#0f1115;color:#e7e9ee;font:14px/1.5 "Segoe UI",system-ui,sans-serif}
header{position:sticky;top:0;z-index:9;background:#161a22cc;backdrop-filter:blur(10px);
 padding:12px 20px;border-bottom:1px solid #262c38;display:flex;gap:14px;align-items:center;flex-wrap:wrap}
h1{font-size:16px;margin:0;font-weight:600}
input{background:#0b0e13;border:1px solid #2c3444;color:#e7e9ee;border-radius:8px;padding:8px 12px;width:280px;outline:none}
input:focus{border-color:#4a90ff}
.stat{color:#8b95a7;font-size:12px}
#grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(168px,1fr));gap:14px;padding:18px}
.card{background:#161a22;border:1px solid #232a36;border-radius:12px;overflow:hidden;
 transition:transform .16s ease,border-color .16s ease}
.card:hover{transform:translateY(-3px);border-color:#3d6ad1}
.thumb{aspect-ratio:3/4;background:#0b0e13;display:flex;align-items:center;justify-content:center}
.thumb img{width:100%;height:100%;object-fit:cover}
.meta{padding:8px 10px}
.name{font-size:12.5px;line-height:1.35;height:34px;overflow:hidden}
.sub{font-size:11px;color:#7c8698;margin-top:4px;display:flex;justify-content:space-between;gap:6px}
.badge{color:#ffb545}
</style></head><body>
<header><h1>🐳 Kungal 资源库 · 封面浏览</h1>
<input id="q" placeholder="搜索名称 / 会社 / ID（支持中文日文）">
<span class="stat" id="stat"></span></header>
<div id="grid"></div>
<script>
const DATA = __DATA__;
const grid = document.getElementById('grid');
const stat = document.getElementById('stat');
const q = document.getElementById('q');
function render(list){
  stat.textContent = list.length + ' / ' + DATA.length + ' 部';
  const frag = document.createDocumentFragment();
  for (const w of list){
    const d = document.createElement('div'); d.className='card';
    const score = (w.score===null||w.score===undefined) ? '—' : w.score.toFixed(1);
    const img = w.cover ? '<img loading="lazy" src="'+w.cover+'" alt="" onerror="this.style.display=\\'none\\'">' : '';
    d.innerHTML = '<div class="thumb">'+img+'</div>'+
      '<div class="meta"><div class="name">'+w.name.replace(/</g,'&lt;')+'</div>'+
      '<div class="sub"><span>'+(w.date||'—')+'</span><span class="badge">★ '+score+'</span></div></div>';
    d.title = [w.zh,w.ja,w.maker,'#'+w.id].filter(Boolean).join(' | ');
    frag.appendChild(d);
  }
  grid.replaceChildren(frag);
}
q.addEventListener('input', ()=>{
  const k = q.value.trim().toLowerCase();
  if(!k){render(DATA);return;}
  render(DATA.filter(w => (w.name+' '+w.zh+' '+w.ja+' '+w.maker+' '+w.id).toLowerCase().includes(k)));
});
render(DATA);
</script></body></html>"""
    html = html.replace("__DATA__", payload)
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    print("wrote", path, os.path.getsize(path), "bytes")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                 "kungal_galgame.db"))
    ap.add_argument("--outdir", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--xlsx-limit", type=int, default=None)
    args = ap.parse_args()

    conn = sqlite3.connect(args.db)
    total = conn.execute("SELECT COUNT(*) FROM works").fetchone()[0]
    res = conn.execute("SELECT COUNT(*) FROM works WHERE in_resource_lib=1").fetchone()[0]
    print("total works:", total, "| resource library:", res)

    export_path = os.path.join(args.outdir, "kungal_works_all.csv")
    write_csv(export_path, rows(conn))
    write_csv(os.path.join(args.outdir, "kungal_resource_library.csv"),
              rows(conn, "in_resource_lib=1"))
    write_jsonl(os.path.join(args.outdir, "kungal_works.jsonl"), rows(conn))
    write_xlsx(os.path.join(args.outdir, "kungal_galgame.xlsx"), conn, args.xlsx_limit)
    write_gallery(os.path.join(args.outdir, "kungal_gallery.html"), conn)


if __name__ == "__main__":
    main()

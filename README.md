# Kungal Galgame 作品库（可拉取的 SQLite / CSV / JSONL 数据）

[www.kungal.com](https://www.kungal.com) 全站 Galgame 作品元数据 + 封面索引，面向「其他软件直接拉取」而整理：一个 SQLite 文件、两份 CSV、一份 JSONL、一份封面清单、一个版本清单 `latest.json`。抓取快照：**2026-11-23**。

| 数据 | 数量 |
|---|---|
| 全部作品（`works` 表） | **34,807** |
| 资源资料库（有补丁/资源下载，`in_resource_lib=1`） | **4,995** |
| 有封面地址的作品 | 31,728 |
| 本地封面镜像（release 资产） | 4,932 张 `.webp`，≈ 394 MB |
| 封面全部来自 | `image.kungal.iloveren.link`（`cover_url` 字段） |

> 文档站（GitHub Pages）：https://sugar787878.github.io/kungal-galgame-db/ — 4,995 部资源库封面的可视化浏览页。

## 一、怎么拉（三种方式，按场景选）

### 方式 A：直接下文件（推荐，零依赖）

```
https://raw.githubusercontent.com/sugar787878/kungal-galgame-db/main/data/kungal_galgame.db
https://raw.githubusercontent.com/sugar787878/kungal-galgame-db/main/data/works.csv
https://raw.githubusercontent.com/sugar787878/kungal-galgame-db/main/data/resource_library.csv
https://raw.githubusercontent.com/sugar787878/kungal-galgame-db/main/data/works.jsonl
https://raw.githubusercontent.com/sugar787878/kungal-galgame-db/main/data/covers_manifest.csv
```

- `kungal_galgame.db` — SQLite（22.9 MB），`works` 表 34,807 行、31 列，带索引，可直接 `SELECT`
- `works.csv` — UTF-8 BOM，Excel 双击可用
- `resource_library.csv` — 只看「有资源」的 4,995 部
- `works.jsonl` — 一行一条 JSON，适合灌 ES/向量库/流式处理
- `covers_manifest.csv` — `id, filename, cover_url, cover_hash, width, height, sha256, bytes`，逐张封面可校验

### 方式 B：版本清单 + 增量同步（软件内自动更新）

先读 [`data/latest.json`](data/latest.json)：

```json
{
  "schema_version": 1,
  "version": "2026.11.23",
  "generated_at": "2026-11-23T12:13:44Z",
  "counts": { "works": 34807, "resource_library": 4995, "with_cover": 31728, "covers_local": 4932 },
  "files": {
    "kungal_galgame.db": { "path": "data/kungal_galgame.db", "bytes": 23953408, "sha256": "…" }
  }
}
```

流程：比对本地 `version` → 不同则下载 → 校验 `sha256` → 下载到 `.tmp` 再原子 `rename` 替换 → 重开只读连接。参考实现见 [`clients/sync.py`](clients/sync.py) 与 [`clients/sync.mjs`](clients/sync.mjs)。

### 方式 C：Release 资产（含封面原图）

[Latest release](https://github.com/sugar787878/kungal-galgame-db/releases/latest) 提供：

| 资产 | 内容 |
|---|---|
| `kungal_galgame_db_2026-11-23.zip` | 库 + Excel + CSV + JSONL + 浏览页 + 脚本（24.8 MB） |
| `kungal_covers_2026-11-23.zip` | 4,932 张封面 `.webp`，文件名 = 作品 id（394 MB） |

## 二、封面怎么取

优先级从省事到自持：

1. **直接用 `cover_url`**（数据库字段）：CDN 直链，无需鉴权，程序里按需加载即可，仓库零体积。
2. **本地镜像**：下 release 的 `kungal_covers_*.zip` 解压到 `covers/`，路径规则 `covers/{id}.webp`；`covers_manifest.csv` 里有每张的 `sha256`。
3. **自己回源**：`scripts/download_covers.py` 按 `cover_url` 重新下载，支持断点续传（已存在即跳过）。

## 三、结构

```
data/
  kungal_galgame.db      SQLite 主库（works 表 + 抓取状态表）
  works.csv              全量 34,807 行
  resource_library.csv   资源库 4,995 行
  works.jsonl            一行一条 JSON
  covers_manifest.csv    封面清单（含 sha256）
  schema.sql             建表语句
  latest.json            版本 / 校验清单（自动更新入口）
clients/
  sync.py                拉取+校验+替换（Python，标准库）
  sync.mjs               同上（Node 18+，零依赖）
  serve_api.py           把库包成只读 HTTP API（FastAPI）
  queries.sql            常用查询示例
scripts/                 抓取与导出脚本（可重跑）
docs/index.html          封面浏览页（GitHub Pages）
```

## 四、字段

| 字段 | 含义 |
|---|---|
| `id` | Kungal 作品 id，详情页 `https://www.kungal.com/galgame/{id}` |
| `display_name` / `name_zh` / `name_ja` / `name_en` / `name_latin` | 显示名与中/日/英/罗马字名 |
| `cover_url` / `cover_hash` / `cover_width` / `cover_height` / `cover_sexual` / `cover_sfw_url` | 封面直链与元信息（`safe` / `suggestive`） |
| `banner_url` | 横幅图直链 |
| `release_date` / `release_date_precision` | 发售日 |
| `maker_id` / `maker_name` | 制作会社 |
| `rating_score` / `rating_count` | 站内评分、人数 |
| `view_count` / `like_count` | 热度 |
| `resource_platforms` / `resource_languages` | 资源平台（`win`/`and`/…）、语言（`zh-cn`/`ja-jp`/…），JSON 数组字符串 |
| `resource_updated_at` | 资源更新时间 |
| `in_resource_lib` / `in_gallib` | 是否在资源库 / 全量资料库 |
| `is_nsfw` / `is_published` | 分级、上架状态 |
| `detail_url` / `fetched_at` | 详情页、抓取时间 |

完整 DDL 见 [`data/schema.sql`](data/schema.sql)。

## 五、快速开始

```python
import sqlite3
con = sqlite3.connect("file:kungal_galgame.db?mode=ro", uri=True)
con.row_factory = sqlite3.Row
for r in con.execute("""SELECT id, display_name, name_zh, cover_url FROM works
                        WHERE in_resource_lib=1 ORDER BY view_count DESC LIMIT 5"""):
    print(r["id"], r["display_name"], r["cover_url"])
```

```js
import Database from 'better-sqlite3';
const db = new Database('kungal_galgame.db', { readonly: true });
console.log(db.prepare('SELECT id, display_name FROM works WHERE id = ?').get('1047'));
```

包成 HTTP 服务（给 Flutter / 小程序 / 前端用）：

```bash
pip install fastapi uvicorn
python clients/serve_api.py --db data/kungal_galgame.db --port 8000
# GET /works?q=恋爱&page=1&size=20
# GET /works/1047
# GET /covers/1047.webp   （若本地有 covers/ 目录）
```

## 六、更新

- 快照版本号写在 `latest.json` 的 `version`（当前 `2026.11.23`）。
- 重新抓取：`scripts/` 下脚本按 README 顺序跑，再用 `scripts/export_kungal.py` 导出。
- 站点每日新增作品，建议每 1–4 周重跑一次；`--resume` 会跳过已抓页。

## 七、已知边界

- 全量库站点自报 36,920 部，本库 34,807 部（**94.3%**）；缺的 2,113 部是无发售日的残缺条目，受站点分页 10,000 条上限所限抓不到。
- 匿名视图不含 R18（`is_nsfw` 全为 0）；带 `include_nsfw=true` 时站点总数为 82,235。
- 中文名覆盖 59%、站内评分覆盖 3.8%——站点本身如此，不是抓取缺失。

## 八、数据来源与使用

数据抓取自 [kungal.com](https://www.kungal.com)（开源社区项目 [KunMoe](https://github.com/KunMoe)），作品元数据为事实性信息；封面图片版权归各游戏公司/画师所有。使用前请读 [DATA-NOTICE.md](DATA-NOTICE.md)。

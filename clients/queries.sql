-- Kungal galgame DB — 常用查询示例（SQLite）
-- 打开方式： sqlite3 -readonly kungal_galgame.db

-- 1) 随机抽 10 部有资源的作品
SELECT id, display_name, name_zh, cover_url
FROM works
WHERE in_resource_lib = 1
ORDER BY RANDOM() LIMIT 10;

-- 2) 按名字搜索（中文/日文/英文任一命中）
SELECT id, display_name, name_zh, release_date, maker_name, cover_url
FROM works
WHERE display_name LIKE '%恋爱%' OR name_zh LIKE '%恋爱%' OR name_ja LIKE '%恋爱%'
ORDER BY in_resource_lib DESC, view_count DESC
LIMIT 20;

-- 3) 某年发售 + 有评分，按评分排序
SELECT display_name, name_zh, release_date, rating_score, rating_count
FROM works
WHERE release_date LIKE '2025-%' AND rating_score IS NOT NULL
ORDER BY rating_score DESC, rating_count DESC
LIMIT 50;

-- 4) 会社作品数排行
SELECT maker_name, COUNT(*) AS works
FROM works
WHERE maker_name <> '' AND maker_name IS NOT NULL
GROUP BY maker_name
ORDER BY works DESC
LIMIT 30;

-- 5) 有中文资源、且支持 Windows 的作品
SELECT id, display_name, name_zh, resource_languages
FROM works
WHERE in_resource_lib = 1
  AND resource_languages LIKE '%zh-cn%'
  AND resource_platforms LIKE '%win%'
ORDER BY view_count DESC
LIMIT 50;

-- 6) 只差封面的条目（无 cover_url）
SELECT id, display_name FROM works
WHERE cover_url IS NULL OR cover_url = ''
LIMIT 20;

-- 7) 按年代统计入库量
SELECT CAST(substr(release_date, 1, 4) / 10 AS INT) * 10 AS decade, COUNT(*) AS n
FROM works
WHERE release_date <> ''
GROUP BY decade
ORDER BY decade;

-- 8) 资源库与全量库的交集/差集
SELECT
  SUM(in_resource_lib = 1 AND in_gallib = 1) AS both_libs,
  SUM(in_resource_lib = 1 AND in_gallib = 0) AS resource_only,
  SUM(in_resource_lib = 0 AND in_gallib = 1) AS gallib_only
FROM works;

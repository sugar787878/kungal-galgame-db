#!/usr/bin/env node
/**
 * Sync the Kungal galgame database from GitHub (Node 18+, zero dependencies).
 *
 *   node sync.mjs --dest ./kungal_data
 *   node sync.mjs --dest ./kungal_data --covers
 *
 * Read the resulting file with better-sqlite3 / node:sqlite:
 *   const db = new Database('./kungal_data/kungal_galgame.db', { readonly: true });
 */
import { createHash } from 'node:crypto';
import { createWriteStream } from 'node:fs';
import { mkdir, open, readFile, rename, rm, writeFile, stat } from 'node:fs/promises';
import { pipeline } from 'node:stream/promises';
import path from 'node:path';

const BASE = 'https://raw.githubusercontent.com/sugar787878/kungal-galgame-db/main/';
const UA = 'kungal-db-sync/1.0';

const args = process.argv.slice(2);
const opt = (name, def) => {
  const i = args.indexOf('--' + name);
  return i >= 0 ? args[i + 1] : def;
};
const flag = (name) => args.includes('--' + name);
const dest = opt('dest', './kungal_data');
const withCovers = flag('covers');

async function getJson(url) {
  const res = await fetch(url, { headers: { 'user-agent': UA } });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  return res.json();
}

async function sha256(file) {
  const h = createHash('sha256');
  const fh = await open(file, 'r');
  try {
    for await (const chunk of fh.createReadStream()) h.update(chunk);
  } finally {
    await fh.close();
  }
  return h.digest('hex');
}

async function download(url, target) {
  const res = await fetch(url, { headers: { 'user-agent': UA } });
  if (!res.ok) throw new Error(`${url} -> ${res.status}`);
  const tmp = target + '.tmp';
  await pipeline(res.body, createWriteStream(tmp));
  return tmp;
}

const meta = await getJson(BASE + 'data/latest.json');
await mkdir(dest, { recursive: true });
await writeFile(path.join(dest, 'latest.json'), JSON.stringify(meta, null, 2));

const versionFile = path.join(dest, '.version');
let local = '';
try { local = (await readFile(versionFile, 'utf8')).trim(); } catch {}
const need = local !== meta.version;

const jobs = [['kungal_galgame.db', meta.files['kungal_galgame.db']]];
if (withCovers && meta.release_assets?.covers) {
  const a = meta.release_assets.covers;
  jobs.push([a.name, {
    url: `https://github.com/sugar787878/kungal-galgame-db/releases/download/v${meta.version}/${a.name}`,
    sha256: a.sha256,
  }]);
}

for (const [name, info] of jobs) {
  const target = path.join(dest, name);
  if (!need) {
    try { await stat(target); console.log(`[skip] ${name} (version ${meta.version})`); continue; } catch {}
  }
  const url = info.url || BASE + info.path;
  console.log(`[get ] ${name} <- ${url}`);
  const tmp = await download(url, target);
  const digest = await sha256(tmp);
  if (digest !== info.sha256) {
    await rm(tmp, { force: true });
    throw new Error(`sha256 mismatch for ${name}: ${digest} != ${info.sha256}`);
  }
  await rename(tmp, target);
  console.log(`[ok  ] ${name}  ${(await stat(target)).size} bytes`);
}

await writeFile(versionFile, meta.version + '\n');
console.log(`db ready: ${path.join(dest, 'kungal_galgame.db')} (version ${meta.version}, ${meta.counts.works} works)`);

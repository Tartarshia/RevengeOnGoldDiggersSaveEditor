'use strict';

const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const APP_ID = 3350200;
const GAME_DIR = process.env.ROGD_GAME_DIR ||
  'C:\\Program Files (x86)\\Steam\\steamapps\\common\\RevengeOnGoldDiggers';
const modulePath = path.join(GAME_DIR, 'resources', 'app', 'node_modules', 'steamworks.js');

function finish(payload, code = 0) {
  process.stdout.write(`ROGD_RESULT=${JSON.stringify(payload)}\n`);
  process.exit(code);
}

function sha256(data) {
  return crypto.createHash('sha256').update(data).digest('hex').toUpperCase();
}

try {
  const steamworks = require(modulePath);
  const client = steamworks.init(APP_ID);
  const [command, ...args] = process.argv.slice(2);

  if (command === 'status') {
    const ids = args.length ? args : Array.from({ length: 39 }, (_, i) => `a${String(i + 1).padStart(2, '0')}`);
    const status = {};
    for (const id of ids) {
      if (!/^a\d{2}$/.test(id)) throw new Error(`无效成就 ID：${id}`);
      status[id] = Boolean(client.achievement.isActivated(id));
    }
    finish({ ok: true, status });
  }

  if (command === 'unlock') {
    const id = args[0];
    if (!/^a\d{2}$/.test(id || '')) throw new Error(`无效成就 ID：${id}`);
    const before = Boolean(client.achievement.isActivated(id));
    if (!before) client.achievement.activate(id);
    const after = Boolean(client.achievement.isActivated(id));
    finish({ ok: after, id, before, after, error: after ? undefined : 'Steam 未确认成就已解锁' }, after ? 0 : 2);
  }

  if (command === 'cloud-write') {
    const [remoteName, localPath] = args;
    if (!['archive.save', 'setting.save'].includes(remoteName)) {
      throw new Error(`不允许写入的 Cloud 文件：${remoteName}`);
    }
    const source = fs.readFileSync(localPath);
    const wrote = client.cloud.writeFile(remoteName, source);
    if (wrote === false) throw new Error('Steam Cloud writeFile 返回 false');
    const readBack = Buffer.from(client.cloud.readFile(remoteName));
    const expected = sha256(source);
    const actual = sha256(readBack);
    finish({ ok: expected === actual, name: remoteName, size: readBack.length, sha256: actual,
      error: expected === actual ? undefined : 'Steam Cloud 哈希复读不一致' }, expected === actual ? 0 : 3);
  }

  throw new Error(`未知命令：${command || '(empty)'}`);
} catch (error) {
  finish({ ok: false, error: String(error && error.stack || error) }, 1);
}

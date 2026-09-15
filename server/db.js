const fs = require('fs');
const path = require('path');

const DATA_DIR = path.join(__dirname, '..', 'data');
const DB_FILE = path.join(DATA_DIR, 'db.json');

function ensureReady() {
  if (!fs.existsSync(DATA_DIR)) fs.mkdirSync(DATA_DIR, { recursive: true });
  if (!fs.existsSync(DB_FILE)) fs.writeFileSync(DB_FILE, JSON.stringify({ projects: {} }, null, 2));
}

function load() {
  ensureReady();
  return JSON.parse(fs.readFileSync(DB_FILE, 'utf-8'));
}

function save(data) {
  const tmp = DB_FILE + '.tmp';
  fs.writeFileSync(tmp, JSON.stringify(data, null, 2));
  fs.renameSync(tmp, DB_FILE);
}

// 동시 쓰기 충돌을 막기 위한 아주 단순한 순차 큐 (단일 프로세스 로컬 앱 용도)
// 개별 mutate가 실패해도 체인 자체는 계속 이어지도록 별도로 복구한다.
let writeChain = Promise.resolve();
function mutate(fn) {
  const result = writeChain.then(() => {
    const data = load();
    const r = fn(data);
    save(data);
    return r;
  });
  writeChain = result.catch(() => {});
  return result;
}

function getAll() {
  return load().projects;
}

function getProject(id) {
  return load().projects[id] || null;
}

module.exports = { load, save, mutate, getAll, getProject, DATA_DIR };

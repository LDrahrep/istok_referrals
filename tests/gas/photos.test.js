// Тесты GAS-скрипта gas/photos.gs на фейках Apps Script. Запуск: node --test tests/gas
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(path.join(__dirname, '..', '..', 'gas', 'photos.gs'), 'utf8');
const HEADER = ['№', 'Имя', 'Фамилия', 'file_id', 'Фото'];

function makeEnv(rows, { onDownload } = {}) {
  const grid = [HEADER.slice(), ...rows.map((r) => r.slice())];
  const notes = {};
  const files = [];
  const range = (r, c, nr = 1, nc = 1) => ({
    getValue: () => grid[r - 1][c - 1],
    setValue: (v) => { grid[r - 1][c - 1] = v; },
    setNote: (n) => { notes[`${r}:${c}`] = n; },
    getValues: () => grid.slice(r - 1, r - 1 + nr).map((row) => row.slice(c - 1, c - 1 + nc)),
  });
  const sheet = {
    getDataRange: () => ({ getValues: () => grid.map((row) => row.slice()) }),
    getRange: range,
    getLastRow: () => grid.length,
  };
  const iterator = (list) => { let i = 0; return { hasNext: () => i < list.length, next: () => list[i++] }; };
  const folder = {
    searchFiles: (q) => {
      const needle = q.match(/title contains "(.*)"/)[1];
      return iterator(files.filter((f) => f.name.includes(needle)).map((f) => ({ getUrl: () => f.url })));
    },
    createFile: (blob) => {
      const file = { name: blob.name, url: `https://drive/${blob.fileId}` };
      files.push(file);
      return { getUrl: () => file.url };
    },
  };
  const context = {
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => ({ BOT_TOKEN: 'T', FOLDER_ID: 'F' })[k] }) },
    DriveApp: { getFolderById: () => folder },
    SpreadsheetApp: { getActive: () => ({ getSheetByName: () => sheet }) },
    UrlFetchApp: {
      fetch: (url) => {
        const getFile = url.match(/getFile\?file_id=(.*)$/);
        if (getFile) {
          const id = decodeURIComponent(getFile[1]);
          return { getContentText: () => JSON.stringify({ ok: true, result: { file_path: `photos/${id}.jpg` } }) };
        }
        const id = url.match(/photos\/(.*)\.jpg$/)[1];
        if (onDownload) onDownload(id, grid);
        return {
          getResponseCode: () => 200,
          getBlob: () => ({ fileId: id, setName(name) { this.name = name; return this; } }),
        };
      },
    },
    ScriptApp: {},
  };
  vm.createContext(context);
  vm.runInContext(SOURCE, context);
  return { context, grid, files, notes };
}

test('ссылка на фото пишется в строку своей заявки, даже если лист отсортировали во время загрузки', () => {
  let sorted = false;
  const env = makeEnv(
    [['R-000010', 'Aziz', 'Karimov', 'file-10', ''], ['R-000011', 'Olga', 'Ivanova', 'file-11', '']],
    {
      onDownload: (id, grid) => {
        if (!sorted) { sorted = true; grid.splice(1, 2, grid[2], grid[1]); }  // HR сортирует по убыванию
      },
    },
  );
  env.context.uploadPhotos();
  const photoOf = (number) => env.grid.find((row) => row[0] === number)[4];
  assert.strictEqual(photoOf('R-000010'), 'https://drive/file-10');
  assert.strictEqual(photoOf('R-000011'), 'https://drive/file-11');
});

test('уже загруженный файл не загружается повторно', () => {
  const env = makeEnv([['R-000010', 'Aziz', 'Karimov', 'file-10', '']]);
  env.files.push({ name: 'R-000010 Aziz Karimov.jpg', url: 'https://drive/old' });
  env.context.uploadPhotos();
  assert.strictEqual(env.grid[1][4], 'https://drive/old');
  assert.strictEqual(env.files.length, 1);
});

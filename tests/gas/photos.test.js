// Тесты GAS-скрипта gas/photos.gs на фейках Apps Script. Запуск: node --test tests/gas/photos.test.js
const test = require('node:test');
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(path.join(__dirname, '..', '..', 'gas', 'photos.gs'), 'utf8');
const HEADER = ['№', 'Имя', 'Фамилия', 'file_id', 'Фото'];
const PHOTO = 4;

const imageFormula = (id, sep = ',') =>
  `=HYPERLINK("https://drive.google.com/file/d/${id}/view"${sep} ` +
  `IMAGE("https://drive.google.com/uc?export=view&id=${id}"))`;

function makeEnv(rows, { onDownload, locale = 'en_US' } = {}) {
  const grid = [HEADER.slice(), ...rows.map((r) => r.slice())];
  // Как Google Sheets: разделитель аргументов формулы зависит от локали таблицы
  // (в ru_RU — «;», в en_US — «,»); формула с чужим разделителем показывает #ERROR!.
  const wrongSep = locale === 'ru_RU' ? '", IMAGE(' : '"; IMAGE(';
  let flushes = 0;
  const notes = {};
  const heights = {};
  const sharing = {};
  const files = [];
  const isFormula = (v) => String(v).startsWith('=');
  // у формулы с IMAGE нет текстового значения; формула с чужим разделителем — #ERROR!
  const display = (v) => (isFormula(v) ? (String(v).includes(wrongSep) ? '#ERROR!' : '') : v);
  const driveFile = (f) => ({
    getId: () => f.id,
    getUrl: () => `https://drive.google.com/file/d/${f.id}/view`,
    setSharing: (access, permission) => { sharing[f.id] = `${access}/${permission}`; },
  });
  const range = (r, c, nr = 1, nc = 1) => ({
    getValue: () => display(grid[r - 1][c - 1]),
    getDisplayValue: () => String(display(grid[r - 1][c - 1])),
    setValue: (v) => { grid[r - 1][c - 1] = v; },
    setFormula: (f) => { grid[r - 1][c - 1] = f; },
    setNote: (n) => { notes[`${r}:${c}`] = n; },
    getValues: () => grid.slice(r - 1, r - 1 + nr).map((row) => row.slice(c - 1, c - 1 + nc).map(display)),
  });
  const sheet = {
    getDataRange: () => ({
      getValues: () => grid.map((row) => row.map(display)),
      getFormulas: () => grid.map((row) => row.map((v) => (isFormula(v) ? v : ''))),
    }),
    getRange: range,
    getLastRow: () => grid.length,
    setRowHeight: (r, h) => { heights[r] = h; },
  };
  const iterator = (list) => { let i = 0; return { hasNext: () => i < list.length, next: () => list[i++] }; };
  const folder = {
    searchFiles: (q) => {
      const needle = q.match(/title contains "(.*)"/)[1];
      return iterator(files.filter((f) => f.name.includes(needle)).map(driveFile));
    },
    createFile: (blob) => {
      const file = { id: `drive-${blob.fileId}`, name: blob.name };
      files.push(file);
      return driveFile(file);
    },
  };
  const context = {
    LockService: { getScriptLock: () => ({ tryLock: () => true, releaseLock: () => {} }) },
    PropertiesService: { getScriptProperties: () => ({ getProperty: (k) => ({ BOT_TOKEN: 'T', FOLDER_ID: 'F' })[k] }) },
    DriveApp: {
      getFolderById: () => folder,
      getFileById: (id) => driveFile({ id }),
      Access: { ANYONE_WITH_LINK: 'ANYONE_WITH_LINK' },
      Permission: { VIEW: 'VIEW' },
    },
    SpreadsheetApp: { getActive: () => ({ getSheetByName: () => sheet }), flush: () => { flushes++; } },
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
  return { context, grid, files, notes, heights, sharing };
}

test('фото загружается и в «Фото» появляется картинка со ссылкой, доступной по ссылке', () => {
  const env = makeEnv([['R-000010', 'Aziz', 'Karimov', 'file-10', '']]);
  env.context.uploadPhotos();
  assert.strictEqual(env.grid[1][PHOTO], imageFormula('drive-file-10'));
  assert.strictEqual(env.sharing['drive-file-10'], 'ANYONE_WITH_LINK/VIEW');
  assert.strictEqual(env.heights[2], 120);
  assert.strictEqual(env.files[0].name, 'R-000010 Aziz Karimov.jpg');
});

test('картинка пишется в строку своей заявки, даже если лист отсортировали во время загрузки', () => {
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
  const photoOf = (number) => env.grid.find((row) => row[0] === number)[PHOTO];
  assert.strictEqual(photoOf('R-000010'), imageFormula('drive-file-10'));
  assert.strictEqual(photoOf('R-000011'), imageFormula('drive-file-11'));
});

test('уже загруженный файл не загружается повторно', () => {
  const env = makeEnv([['R-000010', 'Aziz', 'Karimov', 'file-10', '']]);
  env.files.push({ id: 'old', name: 'R-000010 Aziz Karimov.jpg' });
  env.context.uploadPhotos();
  assert.strictEqual(env.grid[1][PHOTO], imageFormula('old'));
  assert.strictEqual(env.files.length, 1);
});

test('обычная ссылка на файл (строку восстановил бот) превращается в картинку без повторной загрузки', () => {
  const env = makeEnv([['R-000010', 'Aziz', 'Karimov', 'file-10', 'https://drive.google.com/file/d/abc123/view']]);
  env.context.uploadPhotos();
  assert.strictEqual(env.grid[1][PHOTO], imageFormula('abc123'));
  assert.strictEqual(env.sharing.abc123, 'ANYONE_WITH_LINK/VIEW');
  assert.strictEqual(env.files.length, 0);
});

test('ячейка с картинкой и чужой текст не трогаются', () => {
  const env = makeEnv([
    ['R-000010', 'Aziz', 'Karimov', 'file-10', imageFormula('done')],
    ['R-000011', 'Olga', 'Ivanova', 'file-11', 'фото у HR на почте'],
  ]);
  env.context.uploadPhotos();
  assert.strictEqual(env.grid[1][PHOTO], imageFormula('done'));
  assert.strictEqual(env.grid[2][PHOTO], 'фото у HR на почте');
  assert.strictEqual(env.files.length, 0);
});


test('в русской локали картинка пишется через «;» и не показывает #ERROR!', () => {
  const env = makeEnv([['R-000010', 'Aziz', 'Karimov', 'file-10', '']], { locale: 'ru_RU' });
  env.context.uploadPhotos();
  assert.strictEqual(env.grid[1][PHOTO], imageFormula('drive-file-10', ';'));
});

test('сломанная формула (#ERROR! из-за разделителя) чинится без повторной загрузки', () => {
  const broken = imageFormula('abc123', ',');
  const env = makeEnv([['R-000010', 'Aziz', 'Karimov', 'file-10', broken]], { locale: 'ru_RU' });
  env.context.uploadPhotos();
  assert.strictEqual(env.grid[1][PHOTO], imageFormula('abc123', ';'));
  assert.strictEqual(env.sharing.abc123, 'ANYONE_WITH_LINK/VIEW');
  assert.strictEqual(env.files.length, 0);
});

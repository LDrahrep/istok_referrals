/**
 * Istok Referrals — загрузка фото ворка из Telegram на Google Диск.
 *
 * Работает от аккаунта владельца таблицы. Раз в 5 минут ищет строки листа «Заявки»,
 * где заполнен file_id, а «Фото» пусто, скачивает файл через Telegram Bot API,
 * кладёт в папку FOLDER_ID и пишет ссылку в «Фото». Бот эту колонку не трогает.
 *
 * Настройка: Script Properties → BOT_TOKEN, FOLDER_ID; один раз запустить installTrigger().
 */
var SHEET_NAME = 'Заявки';
var MAX_ROWS_PER_RUN = 30;

function uploadPhotos() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) return;  // предыдущий запуск ещё идёт
  try {
    var props = PropertiesService.getScriptProperties();
    var token = props.getProperty('BOT_TOKEN');
    var folder = DriveApp.getFolderById(props.getProperty('FOLDER_ID'));
    var sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
    var values = sheet.getDataRange().getValues();
    var head = values[0].map(function (h) { return String(h).trim(); });
    var col = {
      id: head.indexOf('№'),
      first: head.indexOf('Имя'),
      last: head.indexOf('Фамилия'),
      fileId: head.indexOf('file_id'),
      photo: head.indexOf('Фото')
    };
    if (col.id < 0 || col.fileId < 0 || col.photo < 0) {
      throw new Error('В листе «' + SHEET_NAME + '» нет заголовков №, file_id или Фото');
    }

    var processed = 0;
    for (var r = 1; r < values.length && processed < MAX_ROWS_PER_RUN; r++) {
      var row = values[r];
      var number = String(row[col.id]).trim();
      var fileId = String(row[col.fileId]).trim();
      if (!number || !fileId || String(row[col.photo]).trim()) continue;
      var url = null, error = null;
      try {
        var baseName = number + ' ' + String(row[col.first]).trim() + ' ' + String(row[col.last]).trim();
        url = uploadOne_(token, folder, fileId, number, baseName);
      } catch (e) {
        error = e.message;
      }
      processed++;
      // Пока шла загрузка, лист могли отсортировать или вставить строки — ищем строку заново по №.
      var target = rowOf_(sheet, col.id, number, r + 1);
      if (target < 0) continue;  // строку удалили во время загрузки: следующий запуск разберётся
      var cell = sheet.getRange(target, col.photo + 1);
      if (url) {
        cell.setValue(url);
        cell.setNote('');
      } else {
        cell.setNote('Ошибка загрузки ' + new Date().toISOString() + ': ' + error);
      }
    }
  } finally {
    lock.releaseLock();
  }
}

function rowOf_(sheet, idCol, number, hint) {
  if (hint <= sheet.getLastRow() && String(sheet.getRange(hint, idCol + 1).getValue()).trim() === number) return hint;
  var ids = sheet.getRange(1, idCol + 1, sheet.getLastRow(), 1).getValues();
  for (var i = 1; i < ids.length; i++) {
    if (String(ids[i][0]).trim() === number) return i + 1;
  }
  return -1;
}

function uploadOne_(token, folder, fileId, number, baseName) {
  // Файл уже загружен прошлым запуском, который упал до записи ссылки, — не создаём дубль.
  var existing = folder.searchFiles('title contains "' + number + ' "');
  if (existing.hasNext()) return existing.next().getUrl();

  var info = JSON.parse(UrlFetchApp.fetch(
    'https://api.telegram.org/bot' + token + '/getFile?file_id=' + encodeURIComponent(fileId),
    { muteHttpExceptions: true }
  ).getContentText());
  if (!info.ok) throw new Error(info.description || 'getFile не удался');

  var path = info.result.file_path;
  var dot = path.lastIndexOf('.');
  var name = baseName + (dot >= 0 ? path.substring(dot) : '.jpg');
  var response = UrlFetchApp.fetch('https://api.telegram.org/file/bot' + token + '/' + path,
                                   { muteHttpExceptions: true });
  if (response.getResponseCode() !== 200) {
    throw new Error('скачивание файла: HTTP ' + response.getResponseCode());
  }
  return folder.createFile(response.getBlob().setName(name)).getUrl();
}

function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'uploadPhotos') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('uploadPhotos').timeBased().everyMinutes(5).create();
}

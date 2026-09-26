/**
 * Istok Referrals — загрузка фото ворка из Telegram на Google Диск.
 *
 * Работает от аккаунта владельца таблицы. Раз в 5 минут ищет строки листа «Заявки»,
 * где заполнен file_id, а «Фото» пусто, скачивает файл через Telegram Bot API,
 * кладёт в папку FOLDER_ID, открывает доступ «все, у кого есть ссылка — просмотр»
 * и пишет в «Фото» формулу HYPERLINK(ссылка, IMAGE(…)): в ячейке видно превью, клик открывает файл.
 * Если в «Фото» лежит обычная ссылка на файл (строку восстановил бот), превращает её в картинку.
 * Бот эту колонку не трогает, а ссылку на файл читает из формулы.
 *
 * Настройка: Script Properties → BOT_TOKEN, FOLDER_ID; один раз запустить installTrigger().
 */
var SHEET_NAME = 'Заявки';
var MAX_ROWS_PER_RUN = 30;
var PHOTO_ROW_HEIGHT = 120;
var DRIVE_FILE_ID_RE = /drive\.google\.com\/(?:file\/d\/|uc\?[^"]*id=|open\?id=)([\w-]+)/;

function uploadPhotos() {
  var lock = LockService.getScriptLock();
  if (!lock.tryLock(0)) return;  // предыдущий запуск ещё идёт
  try {
    var props = PropertiesService.getScriptProperties();
    var token = props.getProperty('BOT_TOKEN');
    var folder = DriveApp.getFolderById(props.getProperty('FOLDER_ID'));
    var sheet = SpreadsheetApp.getActive().getSheetByName(SHEET_NAME);
    var range = sheet.getDataRange();
    var values = range.getValues();
    var formulas = range.getFormulas();
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
      if (!number || formulas[r][col.photo]) continue;  // картинка уже стоит
      var photoText = String(row[col.photo]).trim();
      var fileId = String(row[col.fileId]).trim();

      var driveId = null, error = null;
      if (photoText) {
        var match = photoText.match(DRIVE_FILE_ID_RE);
        if (!match) continue;  // в ячейке что-то своё от HR — не трогаем
        driveId = match[1];
      } else if (!fileId) {
        continue;
      }
      try {
        if (driveId) {
          shareByLink_(DriveApp.getFileById(driveId));
        } else {
          var baseName = number + ' ' + String(row[col.first]).trim() + ' ' + String(row[col.last]).trim();
          driveId = uploadOne_(token, folder, fileId, number, baseName);
        }
      } catch (e) {
        error = e.message;
      }
      processed++;
      // Пока шла загрузка, лист могли отсортировать или вставить строки — ищем строку заново по №.
      var target = rowOf_(sheet, col.id, number, r + 1);
      if (target < 0) continue;  // строку удалили во время загрузки: следующий запуск разберётся
      var cell = sheet.getRange(target, col.photo + 1);
      if (error) {
        cell.setNote('Ошибка загрузки ' + new Date().toISOString() + ': ' + error);
        continue;
      }
      cell.setFormula(imageFormula_(driveId));
      cell.setNote('');
      sheet.setRowHeight(target, PHOTO_ROW_HEIGHT);
    }
  } finally {
    lock.releaseLock();
  }
}

function imageFormula_(driveId) {
  return '=HYPERLINK("https://drive.google.com/file/d/' + driveId + '/view", ' +
         'IMAGE("https://drive.google.com/uc?export=view&id=' + driveId + '"))';
}

function shareByLink_(file) {
  // IMAGE() загружает картинку анонимно, поэтому файлу нужен доступ по ссылке.
  file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
  return file;
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
  // Файл уже загружен прошлым запуском, который упал до записи в ячейку, — не создаём дубль.
  var existing = folder.searchFiles('title contains "' + number + ' "');
  if (existing.hasNext()) return shareByLink_(existing.next()).getId();

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
  return shareByLink_(folder.createFile(response.getBlob().setName(name))).getId();
}

function installTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'uploadPhotos') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('uploadPhotos').timeBased().everyMinutes(5).create();
}

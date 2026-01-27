# Telegram Signal Filter (GUI)

Локальное Windows-приложение на tkinter для фильтрации сигналов из Telegram и пересылки в выбранный канал/чат.

## Требования
- Python 3.10+

## Установка
```bash
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Запуск
```bash
python app.py
```

## Как пользоваться
1) Нажмите **Request code** и введите телефон — код придёт в Telegram (часто в чат “Telegram”, а не по SMS).
2) Нажмите **Login** и введите код (и 2FA пароль если потребуется).
3) Нажмите **Load chats** — приложение загрузит список ваших диалогов.
4) Выберите **Source chat** (где читаем сообщения).
5) Выберите **Notify chat** (куда отправлять). Можно нажать кнопку "Use default notify id 3727425191".
6) Установите **Min distance** (по умолчанию 1.5) и при необходимости включите **Ignore forwarded**.
7) Нажмите **Start monitoring**.

## Что фильтруется
Ищется формат вида:
```
✅ ↑ #FOLKSUSDT: 1.123% (49627$) 15:01:09.394
```
Извлекается расстояние (distance) после `#...USDT:` и перед `%`.
Сравнение по модулю: сигнал проходит, если `abs(distance) >= Min distance`.

## Скриншоты графиков
Если в сообщении есть ссылка на график (http/https, предпочтительно `crypto.netmotion.ru/shotdetectgraph`), приложение делает скриншот через Playwright и отправляет его вместе с текстом.
Если ссылка не найдена или скриншот не получился — отправляется только текст.

## Формат уведомления
- Заголовок: `⚡️ FILTERED SIGNAL (>= X%)`
- Coin
- Distance (со знаком)
- AbsDistance
- Source (title + chat_id)
- Local time
- Link (если есть username) или `chat_id=... msg_id=...`
- Полный оригинальный текст сообщения ниже

## Конфиг
`config.json` создаётся автоматически при первом запуске.
Хранит:
- `api_id`, `api_hash`
- `source_chat_id`, `notify_chat_id`
- `min_distance`, `ignore_forwarded`
- `enable_graph_screenshot`, `screenshot_timeout_ms`, `screenshot_wait_ms`, `screenshot_viewport`, `screenshot_full_page`

Как включить/выключить скриншоты:
- В `config.json` установите `enable_graph_screenshot` = true/false
- Либо добавьте `ENABLE_GRAPH_SCREENSHOT` = 1/0 (оба варианта поддерживаются)

Сессия Telegram хранится в `session.session` внутри папки проекта.
Логи пишутся в `logs/app.log`.
Скриншоты сохраняются в `screenshots/`.
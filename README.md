# SerwisWin Survey Bot

Telegram-бот для сбора голосовых и текстовых ответов сотрудников на вопросы опросника. Голосовые сообщения расшифровываются через whisper.cpp, ответы сохраняются в SQLite. Администраторы могут выгрузить все ответы в CSV.

## Функции

- Приём голосовых сообщений в Telegram, расшифровка через whisper.cpp (автоопределение языка)
- Приём текстовых ответов
- Автоматическое распознавание номера вопроса из сообщения
- Если номер не распознан — бот попросит уточнить цифрой
- Разделение по ролям: колл-центр, мастера
- `/stats` — статистика ответов (только для админов)
- `/export` — выгрузка всех ответов в CSV (только для админов)

## Быстрый старт (One-command deploy)

Всё, что нужно для установки на чистый сервер — одна команда:

```bash
./deploy/setup.sh <IP_СЕРВЕРА> <BOT_TOKEN> <ADMIN_IDS>
```

Пример:
```bash
./deploy/setup.sh 1.2.3.4 ВАШ_ТОКЕН_БОТА АДМИН_ID
```

Что произойдёт автоматически:
1. Установится Ansible (если нет)
2. Склонируется репозиторий на сервер
3. Установятся Python, ffmpeg, whisper-cli
4. Скачается модель распознавания речи (465 МБ)
5. Создастся `.env` с токеном и админами
6. Запустится systemd-сервис — бот будет работать 24/7

Подробнее см. [`deploy/README.md`](deploy/README.md).

## Подключение к серверу (SSH)

```bash
ssh root@<IP_СЕРВЕРА>
```

Пароль выдаётся хостингом после создания сервера.

## Управление ботом (на сервере)

```bash
# Проверить статус
systemctl status survey-bot

# Посмотреть логи в реальном времени
journalctl -u survey-bot -f

# Перезапустить
systemctl restart survey-bot

# Остановить
systemctl stop survey-bot
```

## Watchdog (мониторинг)

Каждые 5 минут проверяет, что бот жив, диск не забит, RAM в норме, Telegram API доступен. Если проблема — пишет в journald.

**Установка вручную (без Ansible):**
```bash
# Скопировать файлы уже на сервере
# watchdog.sh должен лежать в /opt/survey-bot/deploy/watchdog.sh

# Создать сервис
cat > /etc/systemd/system/survey-bot-watchdog.service <<'SERVICEEOF'
[Unit]
Description=Survey Bot Watchdog Check
After=network.target

[Service]
Type=oneshot
ExecStart=/opt/survey-bot/deploy/watchdog.sh
Environment=ADMIN_IDS=294356300,271032976
SERVICEEOF

# Создать таймер (каждые 5 минут)
cat > /etc/systemd/system/survey-bot-watchdog.timer <<'TIMEREOF'
[Unit]
Description=Run Survey Bot watchdog every 5 minutes
Requires=survey-bot-watchdog.service

[Timer]
OnCalendar=*:0/5
Persistent=true

[Install]
WantedBy=timers.target
TIMEREOF

systemctl daemon-reload
systemctl enable --now survey-bot-watchdog.timer
```

**Проверка:**
```bash
systemctl list-timers --no-pager | grep watchdog
journalctl -u survey-bot-watchdog -n 10
```

Также watchdog автоматически настраивается через Ansible (см. `deploy/playbook.yml`).

## Локальный запуск (для разработки)

## Команды бота

| Команда | Доступ | Описание |
|---|---|---|
| `/start` | Все | Приветствие, выбор роли |
| `/questions` | Все | Показать мои вопросы |
| `/stats` | Админы | Статистика ответов |
| `/export` | Админы | Выгрузить CSV |
| `/about` | Все | О боте |

## Структура проекта

```
.
├── bot.py              # Telegram-бот
├── config.py           # Конфигурация
├── database.py         # Работа с SQLite
├── survey_data.py      # Вопросы опросника
├── transcriber.py      # Транскрибация через whisper-cpp
├── requirements.txt    # Зависимости Python
├── .env                # Токен и админы (не в git)
├── .gitignore
├── models/             # Модели whisper (скачать отдельно)
└── audio/              # Голосовые сообщения (создаётся автоматически)
```

## Данные

- База SQLite: `survey.db`
- Голосовые файлы: `audio/`
- Выгрузка: команда `/export` в Telegram

## Тестирование транскрибации (whisper)

Транскрибация через whisper-cli — внешний бинарник, доступный только на сервере. Юнит-тестами не покрывается.

**Smoke-тест (запускать на сервере после деплоя):**
```bash
bash tests/test_whisper.sh
```

Проверяет:
1. whisper-cli установлен
2. Модель `ggml-small.bin` на месте
3. Базовое распознавание (sine wave — проверяет что не падает)
4. Если есть тестовые аудиофайлы — прогоняет их через `-l auto`

**Тестовые аудио для языков** (опционально):
Положить .wav файлы в `/opt/survey-bot/test_audio_samples/`:
- `ru.wav` — русский
- `pl.wav` — польский
- `uk.wav` — украинский
- `cs.wav` — чешский
- `de.wav` — немецкий

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

## Установка на сервер

### 1. Требования

- Python 3.10+
- ffmpeg
- whisper-cpp (https://github.com/ggerganov/whisper.cpp)

```bash
# Ubuntu/Debian
sudo apt install ffmpeg

# macOS
brew install ffmpeg whisper-cpp
```

### 2. Клонировать и установить

```bash
git clone <repo-url>
cd serwiswin-survey-bot
pip3 install -r requirements.txt
```

### 3. Скачать модель whisper

```bash
mkdir -p models
wget -O models/ggml-small.bin https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-small.bin
```

Можно использовать `ggml-base.bin` (быстрее, чуть хуже качество) или `ggml-large-v3.bin` (лучше качество, медленнее).

### 4. Настроить .env

```bash
cp .env.example .env
```

Отредактировать `.env`:

```
BOT_TOKEN=токен_от_BotFather
ADMIN_IDS=ваш_telegram_id,ид_коллеги
```

Где взять свой Telegram ID: написать боту [@userinfobot](https://t.me/userinfobot).

### 5. Запустить

```bash
python3 bot.py
```

### 6. Настроить systemd (для автозапуска на сервере)

Создать файл `/etc/systemd/system/survey-bot.service`:

```ini
[Unit]
Description=SerwisWin Survey Bot
After=network.target

[Service]
User=your_user
WorkingDirectory=/path/to/serwiswin-survey-bot
ExecStart=/usr/bin/python3 /path/to/serwiswin-survey-bot/bot.py
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable survey-bot
sudo systemctl start survey-bot
```

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

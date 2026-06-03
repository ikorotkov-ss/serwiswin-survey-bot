# Развёртывание бота на сервер

## Что это

Полностью автоматическое развёртывание Telegram-бота на **чистом сервере Ubuntu 22.04/24.04 LTS**.

После запуска одной команды сервер сам:
- Установит Python, ffmpeg, whisper
- Скачает модель распознавания речи
- Скопирует код бота
- Настроит автозапуск (systemd)
- Настроит ежедневный бэкап базы данных

## Требования к серверу

| Параметр | Минимум | Рекомендуется |
|----------|---------|---------------|
| CPU | 1 ядро | 2 ядра |
| RAM | 1 GB | 2 GB |
| Диск | 10 GB SSD | 20 GB SSD |
| ОС | Ubuntu 22.04 или 24.04 LTS | 22.04 LTS |

Дата-центр выбирайте **Франкфурт** (Европа) — для доступа к Telegram.

## Полная инструкция для новичка

### Шаг 1. Получить токен бота

1. Напишите в Telegram [@BotFather](https://t.me/BotFather)
2. Отправьте команду: `/newbot`
3. Введите имя: `SerwisWin Survey Bot`
4. Введите username: `serwiswin_survey_bot` (или любой свободный)
5. BotFather пришлёт токен — скопируйте его (вида `ВАШ_ТОКЕН_БОТА`)

### Шаг 2. Узнать свой Telegram ID

1. Напишите боту [@userinfobot](https://t.me/userinfobot)
2. Он пришлёт ваш ID (число, например `294356300`)
3. Если нужно добавить коллегу — через запятую, например: `АДМИН_ID`

### Шаг 3. Создать сервер (VPS)

1. Зайдите в личный кабинет хостинга
2. Закажите VPS/VDS с Ubuntu 22.04 или 24.04 LTS
3. Дождитесь создания (обычно 20-30 минут)
4. Скопируйте **IP-адрес** и **пароль root**

### Шаг 4. Одна команда для развёртывания

На своём компьютере (Mac / Linux) выполните:

```bash
# Клонировать репозиторий (если ещё нет)
git clone https://github.com/ikorotkov-ss/serwiswin-survey-bot.git
cd serwiswin-survey-bot

# Запустить развёртывание
./deploy/setup.sh <IP_СЕРВЕРА> <BOT_TOKEN> <ADMIN_IDS>
```

Пример:
```bash
./deploy/setup.sh 123.123.123.123 ВАШ_ТОКЕН_БОТА АДМИН_ID
```

### Шаг 5. Проверить

```bash
# Подключиться к серверу
ssh root@<IP_СЕРВЕРА>

# Проверить, что бот работает
systemctl status survey-bot
# Должно быть: Active: active (running)

# Посмотреть последние логи
journalctl -u survey-bot --no-pager -n 20
```

После этого напишите своему боту в Telegram команду `/start` — он должен ответить.

## Команды Ansible (для DevOps)

### Установка

```bash
cd deploy/
ansible-playbook -i inventory.ini playbook.yml \
    --extra-vars "bot_token=TOKEN admin_ids=ID1,ID2"
```

### Переменные

| Переменная | Обязательно | Описание |
|-----------|-------------|----------|
| `bot_token` | да | Токен от BotFather |
| `admin_ids` | да | ID админов через запятую |
| `repo_url` | нет | URL репозитория (по умолчанию GitHub) |

### Inventory

```ini
[bot]
1.2.3.4 ansible_user=root
```

## Структура deploy/

```
deploy/
├── setup.sh               # One-command deploy (для новичков)
├── playbook.yml            # Ansible playbook
├── survey-bot.service.j2  # systemd unit (шаблон)
├── inventory.example      # Пример inventory
└── README.md              # Этот файл
```

## Бэкапы

База данных бэкапится ежедневно в 4:03 в папку `/opt/survey-bot/backups/`.
Настроено автоматически через cron.

# Pre-Deploy Checklist

## Перед тем как показать руководству / запустить в продакшн

### 1. Проверка кода
- [ ] `python3 -c "import py_compile"` на всех `.py` файлах — нет синтаксических ошибок
- [ ] Все импорты загружаются без `ModuleNotFoundError`
- [ ] `.env.example` — без реальных токенов, только шаблон
- [ ] `.gitignore` закрывает: `.env`, `survey.db`, `inventory.ini`, `audio/`, `models/`, `__pycache__/`
- [ ] Нет захардкоженных IP, паролей, токенов в коде
- [ ] **Pre-push hook установлен:** `git config core.hooksPath .githooks` (проверяет секреты перед пушем)

### 2. Проверка сервера
- [ ] `systemctl status survey-bot` — `active (running)` и `enabled`
- [ ] `journalctl -u survey-bot -n 30` — нет ошибок, трейсбеков, исключений
- [ ] `curl -s -o /dev/null -w "%{http_code}" https://api.telegram.org` — ответ 200/302
- [ ] `python3 -c "from config import BOT_TOKEN, ADMIN_IDS, DB_PATH; print('OK')"` — конфиг загружается
- [ ] Если используется полный режим: `whisper-cli -m /path/to/model -f /dev/null --help` — whisper работает
- [ ] Если используется лёгкий режим: голосовые сохраняются в `audio/`, а whisper не запускается во время опроса

### 3. Проверка DATA_DIR (разделение кода и данных)
- [ ] `systemctl show survey-bot -p Environment` — содержит `DATA_DIR=/var/lib/survey-bot`
- [ ] `ls /var/lib/survey-bot/survey.db` — БД в правильном месте
- [ ] `ls /opt/survey-bot/survey.db` — **НЕ существует** (если есть — удалить!)
- [ ] Права: `surveybot:surveybot` на `/var/lib/survey-bot/` и `/opt/survey-bot/`

### 4. Сеть и безопасность
- [ ] Telegram API доступен с сервера (проверить через curl)
- [ ] Порт 25 (почта) не открыт (на сервере 1gb.ru по умолчанию закрыт — хорошо)
- [ ] `.env` имеет права `0600`
- [ ] Пароль root — не дефолтный

### 5. Бэкапы
- [ ] `systemctl list-timers` или `crontab -l` — есть ежедневный бэкап БД
- [ ] `ls /var/lib/survey-bot/backups/` — папка существует

### 6. Память и ресурсы
- [ ] `free -h` — RAM не переполнена
- [ ] `df -h /` — диск не забит (аудио + БД; в полном режиме ещё модель 466MB)
- [ ] `ps aux | grep survey-bot` — процесс не жрёт CPU

### 7. Мониторинг и алерты
- [ ] Бот прислал startup-уведомление (если перезапускался)
- [ ] `systemctl status survey-bot-watchdog.timer` — активен
- [ ] `journalctl -u survey-bot-watchdog -n 10` — нет ошибок ("All checks passed")
- [ ] `/health` в Telegram → отвечает статусом сервера
- [ ] `ls {{ data_dir }}/logs/` — logs пишутся

---

## Типичные ошибки (из опыта)

| Ошибка | Причина | Решение |
|--------|---------|---------|
| Бот не отвечает | Нет доступа к Telegram API из РФ | Дата-центр Frankfurt, не Москва |
| whisper-cli: libwhisper.so.1 not found | Сборка с динамическими библиотеками | cmake .. -DBUILD_SHARED_LIBS=OFF |
| SQLite в папке с кодом | Не задан DATA_DIR | Установить DATA_DIR env var |
| git clone не работает на сервере | Нет SSH-ключа на GitHub | Копировать через scp ИЛИ настроить deploy key |
| Web SSH тормозит/зависает | Браузерная консоль | Использовать нативный SSH-клиент |
| Ansible не подключается по паролю | Нет sshpass | `brew install sshpass` (Mac) или настроить SSH-ключи |

---

## Быстрая команда для проверки сервера

```bash
ssh root@<IP> 'bash -s' <<'EOF'
echo "=== SYSTEM ==="
echo "Uptime: $(uptime -p)"
echo "Disk: $(df -h / | tail -1 | awk "{print \$3 \" / \" \$2 \" (\" \$5 \")\"}")"
echo "RAM: $(free -h | grep Mem | awk "{print \$3 \" / \" \$2}")"
echo ""
echo "=== BOT ==="
systemctl is-active survey-bot && echo "ACTIVE ✅" || echo "DEAD ❌"
echo "Log errors:"
journalctl -u survey-bot --no-pager -n 30 | grep -iE "error|traceback|exception" || echo "  None ✅"
echo ""
echo "=== NET ==="
curl -s -o /dev/null -w "Telegram API: HTTP %{http_code}" --connect-timeout 5 https://api.telegram.org
EOF
```

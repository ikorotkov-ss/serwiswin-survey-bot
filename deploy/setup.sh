#!/usr/bin/env bash
set -euo pipefail

# ===== SerwisWin Survey Bot — одно командное развёртывание =====
# Использование:
#   1. Создать сервер Ubuntu 22.04 (VPS/VDS), получить IP и пароль root
#   2. Запустить:  ./setup.sh <IP_сервера> <BOT_TOKEN> <ADMIN_IDS>
#
# Пример:
#   ./setup.sh 123.123.123.123 ВАШ_ТОКЕН_БОТА АДМИН_ID

if [ $# -lt 3 ]; then
    echo "Использование: $0 <IP_SERVERA> <BOT_TOKEN> <ADMIN_IDS>"
    echo ""
    echo "Пример:"
    echo "  $0 1.2.3.4 ВАШ_ТОКЕН_БОТА АДМИН_ID"
    echo ""
    echo "ADMIN_IDS — через запятую, без пробелов"
    exit 1
fi

SERVER_IP="$1"
BOT_TOKEN="$2"
ADMIN_IDS="$3"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PLAYBOOK="$SCRIPT_DIR/playbook.yml"

echo "===== 1. Проверяю Ansible... ====="
if ! command -v ansible-playbook &> /dev/null; then
    echo "Ansible не найден. Устанавливаю..."
    if [[ "$OSTYPE" == "darwin"* ]]; then
        # Mac
        brew install ansible
    else
        # Linux
        sudo apt update && sudo apt install -y ansible
    fi
fi

echo ""
echo "===== 2. Копирую inventory... ====="
INVENTORY=$(mktemp)
cat > "$INVENTORY" <<EOF
[bot]
$SERVER_IP ansible_user=root
EOF

echo ""
echo "===== 3. Запускаю развёртывание на $SERVER_IP... ====="
echo "     Это займёт 5-10 минут (скачивается whisper модель 465MB)"
echo ""

ansible-playbook -i "$INVENTORY" "$PLAYBOOK" \
    --extra-vars "bot_token=$BOT_TOKEN admin_ids=$ADMIN_IDS"

rm -f "$INVENTORY"

echo ""
echo "===== Готово! ====="
echo ""
echo "Подключиться к серверу:        ssh root@$SERVER_IP"
echo "Посмотреть логи бота:          journalctl -u survey-bot -f"
echo "Проверить статус:              systemctl status survey-bot"
echo "Перезапустить бота:            systemctl restart survey-bot"
echo "Проверить напоминания:         systemctl list-timers --no-pager | grep survey"
echo ""
echo "Бот работает 24/7 и перезапускается при падениях."

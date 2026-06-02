import os
import csv
import io
from pathlib import Path
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

from config import BOT_TOKEN, AUDIO_DIR, ADMIN_IDS
from database import init_db, load_questions, save_response, get_stats, get_all_responses, get_question
from survey_data import questions, format_questions
from transcriber import transcribe, parse_question_number


# Ensure audio directory exists
AUDIO_DIR.mkdir(exist_ok=True)

# On startup: init DB and load questions
init_db()
load_questions(questions)

# ─── Roles ────────────────────────────────────────────────────────────

ROLES = {
    "sales": "Колл-центр / Продавцы",
    "masters": "Мастера (выездные + реновация)",
}


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 Всем привет!\n\n"
        "Я подготовил опросник, чтобы собрать реальные истории и фразы клиентов. "
        "Это нужно для нашей рекламы и видео — чтобы тексты были живыми, а не выдуманными.\n\n"
        "Вы с клиентами общаетесь каждый день, лучше всех знаете, что они говорят, "
        "из-за чего переживают, за что благодарят. Поделитесь этим.\n\n"
        "📲 **Как отвечать:**\n"
        "Читаете вопрос, вспоминаете 2-3 конкретных случая, "
        "записываете голосовое в Telegram или пишете текстом.\n\n"
        "Важно не обобщать, а рассказывать как было. Вместо «клиентам дорого» — опишите случай, "
        "когда клиент конкретно так сказал. Страх, радость, злость, недоверие — всё пригодится.\n\n"
        "📝 **По формату:** отвечайте по порядку. В начале каждого голосового или текста "
        "называйте номер вопроса. Например: «Вопрос 5. Когда клиенты отказываются, они чаще всего говорят...»\n\n"
        "Выберите свою роль, чтобы я показал ваши вопросы:"
    )

    keyboard = [
        [InlineKeyboardButton("📞 Колл-центр / Продавцы", callback_data="role_sales")],
        [InlineKeyboardButton("🔧 Мастера", callback_data="role_masters")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(text, reply_markup=reply_markup)


async def role_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    role = query.data.replace("role_", "")
    role_name = ROLES.get(role, role)
    context.user_data["role"] = role

    questions_text = format_questions(role)

    msg = (
        f"Вы выбрали: **{role_name}**\n\n"
        f"Вот ваши вопросы. Отвечайте по порядку, называя номер вопроса в начале каждого сообщения.\n\n"
        f"{questions_text}"
    )
    await query.edit_message_text(msg, parse_mode="Markdown")


async def questions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = context.user_data.get("role")
    if not role:
        await start(update, context)
        return

    role_name = ROLES.get(role, role)
    questions_text = format_questions(role)
    await update.message.reply_text(
        f"Ваши вопросы ({role_name}):\n\n{questions_text}"
    )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming voice messages — download, transcribe, save."""
    voice = update.message.voice
    user = update.effective_user

    # Download the voice file
    file = await voice.get_file()
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    ogg_path = AUDIO_DIR / f"{user.id}_{timestamp}.ogg"
    await file.download_to_drive(ogg_path)

    await update.message.reply_text("🎧 Получил голосовое, расшифровываю...")

    # Transcribe
    text = transcribe(str(ogg_path))

    if not text:
        await update.message.reply_text(
            "❌ Не удалось расшифровать. Попробуйте записать ещё раз или напишите текстом."
        )
        return

    # Extract question number
    question_number = parse_question_number(text)

    # Save to DB
    save_response(
        user_id=user.id,
        username=user.username or user.full_name,
        question_number=question_number,
        raw_text=text,
        audio_path=str(ogg_path),
    )

    if question_number:
        await update.message.reply_text(
            f"✅ Вопрос {question_number} принят. Спасибо!\n\n"
            f"📝 Расшифровка: {text[:200]}{'...' if len(text) > 200 else ''}"
        )
    else:
        await update.message.reply_text(
            f"✅ Голосовое сохранено. Спасибо!\n\n"
            f"📝 Расшифровка: {text[:200]}{'...' if len(text) > 200 else ''}\n\n"
            f"👇 Напишите номер вопроса, на который вы ответили (просто цифру 1, 2, 3...). "
            f"Если хотите начать новый ответ — просто отправьте голосовое или текст с номером вопроса в начале."
        )
        # Save user context so we can match next text message to this transcribed audio
        context.user_data["pending_question"] = {"audio_path": str(ogg_path), "transcript": text}


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages as written answers."""
    text = update.message.text.strip()
    user = update.effective_user

    # Skip commands
    if text.startswith("/"):
        return

    # Check if user is clarifying a question number after a voice message
    pending = context.user_data.get("pending_question")
    if pending and text.isdigit():
        number = int(text)
        if 1 <= number <= 45:
            # Update the last response with the correct question number
            question_number = number
            # Re-save the pending voice response with the correct number
            save_response(
                user_id=user.id,
                username=user.username or user.full_name,
                question_number=question_number,
                raw_text=pending["transcript"],
                audio_path=pending["audio_path"],
            )
            context.user_data.pop("pending_question", None)
            await update.message.reply_text(
                f"✅ Понял, это был ответ на вопрос {number}. Спасибо!"
            )
            return

    question_number = parse_question_number(text)

    save_response(
        user_id=user.id,
        username=user.username or user.full_name,
        question_number=question_number,
        raw_text=text,
    )

    if question_number:
        await update.message.reply_text(f"✅ Вопрос {question_number} принят. Спасибо!")
    else:
        await update.message.reply_text(
            f"✅ Принято. Спасибо!\n"
            f"💡 В следующий раз напишите номер вопроса в начале, например: «Вопрос 5. ...»"
        )


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "SerwisWin Survey Bot\n\n"
        "Помощник для сбора инсайтов от сотрудников. Принимает голосовые и текстовые "
        "ответы на вопросы опросника, расшифровывает их и сохраняет для анализа.\n\n"
        "Создан для улучшения рекламы и контента SerwisWin."
    )
    await update.message.reply_text(text)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда только для администраторов.")
        return
    stats = get_stats()

    lines = [
        f"📊 **Статистика опросника**\n",
        f"Участников: {stats['total_users']}",
        f"Всего ответов: {stats['total_responses']}",
        "",
        "**По вопросам:**",
    ]

    for q in stats["per_question"]:
        icon = "✅" if q["count"] > 0 else "⬜"
        lines.append(f"{icon} Вопрос {q['number']}: {q['count']} ответов")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def export_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда только для администраторов.")
        return
    """Export all responses as CSV."""
    responses = get_all_responses()

    if not responses:
        await update.message.reply_text("Пока нет ни одного ответа.")
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "User ID", "Username", "Вопрос №", "Текст вопроса", "Ответ (транскрипт)", "Дата"])

    for r in responses:
        writer.writerow([
            r["id"], r["user_id"], r["username"],
            r["question_number"], r["question_text"],
            r["raw_text"], r["created_at"],
        ])

    csv_bytes = output.getvalue().encode("utf-8-sig")

    await update.message.reply_document(
        document=io.BytesIO(csv_bytes),
        filename=f"survey_responses_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        caption=f"📥 Все ответы ({len(responses)} шт.)",
    )


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("questions", questions_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CallbackQueryHandler(role_callback, pattern="^role_"))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    print("Бот запущен...")
    app.run_polling()


if __name__ == "__main__":
    main()

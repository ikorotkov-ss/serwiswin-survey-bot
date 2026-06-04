import os
import csv
import io
import traceback
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
from database import (
    init_db, db_migrate, load_questions, save_response, get_stats, get_all_responses, get_question,
    get_or_create_user, update_user_role, update_user_block, update_user_activity,
    mark_user_finished, get_skipped_questions, get_user_responses, get_user_progress,
    mark_skipped,
)
from survey_data import (
    questions, format_questions, get_blocks_for_role,
    get_questions_in_block, is_optional, get_block_welcome,
)
from transcriber import transcribe, parse_question_number
from monitor import log_info, log_error, startup_alert, health_check, send_pending_alerts, send_immediate_alert


# Ensure audio directory exists
AUDIO_DIR.mkdir(exist_ok=True)

# On startup: init DB, migrate, load questions
init_db()
db_migrate()
load_questions(questions)
log_info("Database initialized, questions loaded")

# ─── Roles ────────────────────────────────────────────────────────────

ROLES = {
    "sales": "Колл-центр / Продавцы",
    "masters": "Мастера (выездные + реновация)",
}

# ─── Helpers ──────────────────────────────────────────────────────────


def _build_progress_bar(progress: dict, width: int = 12) -> str:
    """Build progress display string with mandatory + optional counts."""
    mandatory = progress["mandatory_answered"]
    total_mandatory = progress["total_mandatory"]

    if total_mandatory > 0:
        pct = int(mandatory / total_mandatory * 100)
        filled = round(pct / 100 * width)
        bar = "█" * filled + "░" * (width - filled)
        parts = [f"📊 Прогресс: {bar} {mandatory}/{total_mandatory} обязательных"]
    else:
        parts = []

    if progress["total_optional"] > 0:
        parts.append(f"{progress['optional_answered']}/{progress['total_optional']} опциональных")

    return " + ".join(parts)


async def _send_or_edit(update_or_query, text, **kwargs):
    """Send a new message or edit existing one depending on context."""
    if isinstance(update_or_query, str):
        # Raw chat_id string — shouldn't happen, here for safety
        return None
    if hasattr(update_or_query, "edit_message_text"):
        try:
            return await update_or_query.edit_message_text(text, **kwargs)
        except Exception:
            pass
    # Fallback: reply to the message
    return await update_or_query.reply_text(text, **kwargs)


async def _send_question(update_or_query, context, question_number: int):
    """Send a single question with action buttons."""
    question = get_question(question_number)
    if not question:
        return

    opt_tag = " (опционально)" if is_optional(question_number) else ""
    text = (
        f"**Вопрос {question_number}**{opt_tag}\n\n"
        f"{question['text']}\n\n"
        f"Ответьте голосом или текстом."
    )

    keyboard = [
        [InlineKeyboardButton("🎙 Ответить голосом", callback_data=f"instr_voice_{question_number}")],
        [InlineKeyboardButton("✏️ Написать текст", callback_data=f"instr_text_{question_number}")],
        [InlineKeyboardButton("⏭ Пропустить", callback_data=f"skip_{question_number}")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    context.user_data["current_question"] = question_number

    if hasattr(update_or_query, "edit_message_text"):
        try:
            return await update_or_query.edit_message_text(
                text, reply_markup=reply_markup, parse_mode="Markdown"
            )
        except Exception:
            pass
    return await update_or_query.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")


async def _get_user_id(obj):
    """Extract user_id from Update, CallbackQuery, Message, or User object."""
    if hasattr(obj, "effective_user") and obj.effective_user:
        return obj.effective_user.id
    if hasattr(obj, "from_user") and obj.from_user:
        return obj.from_user.id
    if hasattr(obj, "chat") and obj.chat:
        return obj.chat.id
    if hasattr(obj, "id"):
        return obj.id
    return None


async def _show_progress_and_next(update_or_query, context):
    """After answer/skip: show progress bar, determine next action."""
    user_id = await _get_user_id(update_or_query)
    if not user_id:
        return
    role = context.user_data.get("role")
    if not role:
        return

    blocks = get_blocks_for_role(role)
    current_block_idx = context.user_data.get("current_block", 0)
    current_block = blocks[current_block_idx]
    block_questions = get_questions_in_block(current_block, role)
    block_qnums = [q["number"] for q in block_questions]

    # Progress
    progress = get_user_progress(user_id, role)
    progress_text = _build_progress_bar(progress)
    await _send_or_edit(update_or_query, progress_text)

    # If answering skipped questions mode
    if context.user_data.get("answering_skipped"):
        skipped = get_skipped_questions(user_id)
        if skipped:
            await update_or_query.reply_text(
                f"Следующий пропущенный вопрос:"
            ) if hasattr(update_or_query, "reply_text") else await context.bot.send_message(chat_id=user_id, text="Следующий пропущенный вопрос:")
            await _send_question(update_or_query, context, skipped[0])
            return
        context.user_data["answering_skipped"] = False

    # Check if current block is complete
    user_responses = get_user_responses(user_id)
    answered_or_skipped = {r["question_number"] for r in user_responses}

    block_complete = all(q in answered_or_skipped for q in block_qnums)

    if not block_complete:
        for qnum in block_qnums:
            if qnum not in answered_or_skipped:
                await _send_question(update_or_query, context, qnum)
                return

    # Block is complete; check for skipped in this block
    all_skipped = get_skipped_questions(user_id)
    skipped_in_block = [q for q in block_qnums if q in all_skipped]

    if skipped_in_block:
        keyboard = [
            [InlineKeyboardButton("✅ Давай ответим", callback_data="retry_skipped")],
            [InlineKeyboardButton("❌ К следующему блоку", callback_data="next_block")],
        ]
        await update_or_query.reply_text(
            f"Блок «{current_block}» завершён!\n"
            f"У тебя осталось {len(skipped_in_block)} пропущенных вопросов. "
            f"Хочешь ответить на них сейчас?",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    # No skipped, move to next block or finish
    next_block_idx = current_block_idx + 1
    if next_block_idx < len(blocks):
        update_user_block(user_id, next_block_idx)
        context.user_data["current_block"] = next_block_idx
        await update_or_query.reply_text("✅ Блок завершён! Переходим к следующему.")
    else:
        # All blocks done → check for global skipped
        all_skipped = get_skipped_questions(user_id)
        if all_skipped:
            keyboard = [
                [InlineKeyboardButton("✅ Вернуться к пропущенным", callback_data="retry_skipped")],
                [InlineKeyboardButton("🏁 Завершить опрос", callback_data="finish_survey")],
            ]
            await update_or_query.reply_text(
                f"Ты прошёл все блоки! Осталось {len(all_skipped)} пропущенных вопросов. "
                f"Вернёмся к ним?",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
        else:
            await _send_final_message(update_or_query)


async def _send_block_welcome_and_first_question(chat_or_msg, context, block_index: int, user_id: int | None = None):
    """Send block welcome message, then first question."""
    role = context.user_data.get("role")
    if not role:
        return
    blocks = get_blocks_for_role(role)
    block_name = blocks[block_index]

    if user_id is None:
        user_id = chat_or_msg.effective_user.id if hasattr(chat_or_msg, "effective_user") else chat_or_msg.chat.id

    welcome = get_block_welcome(block_name)
    await chat_or_msg.reply_text(welcome)

    block_questions = get_questions_in_block(block_name, role)
    user_responses = get_user_responses(user_id)
    answered = {r["question_number"] for r in user_responses}

    first_q = None
    for q in block_questions:
        if q["number"] not in answered:
            first_q = q["number"]
            break

    if first_q:
        await _send_question(chat_or_msg, context, first_q)


async def _send_final_message(update_or_query):
    user_id = await _get_user_id(update_or_query)
    if not user_id:
        return
    mark_user_finished(user_id)
    msg = (
        "🎉 Спасибо! Ты ответил на все вопросы.\n\n"
        "Твои ответы очень помогут нашей рекламе и контенту. Если вспомнишь "
        "ещё что-то — просто напиши номер вопроса и ответ, я приму.\n\n"
        "Хорошего дня!"
    )
    await update_or_query.reply_text(msg)


# ─── Handlers ─────────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    get_or_create_user(user.id, user.username or user.full_name)

    text = (
        "👋 Всем привет!\n\n"
        "Я подготовил опросник, чтобы собрать реальные истории и фразы клиентов. "
        "Это нужно для нашей рекламы и видео — чтобы тексты были живыми, а не выдуманными.\n\n"
        "Вы с клиентами общаетесь каждый день, лучше всех знаете, что они говорят, "
        "из-за чего переживают, за что благодарят. Поделитесь этим.\n\n"
        "📲 **Как отвечать:**\n"
        "Читаете вопрос, вспоминаете 2-3 конкретных случая, "
        "записываете голосовое или пишете текстом. На всё уйдёт 20-30 минут.\n\n"
        "📝 **По формату:** называйте номер вопроса в начале каждого сообщения. "
        "Например: «Вопрос 5. Когда клиенты отказываются, они чаще всего говорят...» "
        "Потом переходите к следующему. Так мы ничего не потеряем.\n\n"
        "**Важно** не обобщать, а рассказывать как было. Вместо «клиентам дорого» — опишите случай, "
        "когда клиент конкретно так сказал. Страх, радость, злость, недоверие — всё пригодится.\n\n"
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
    user = update.effective_user

    # Save role in DB and context
    update_user_role(user.id, role)
    update_user_block(user.id, 0)
    update_user_activity(user.id)
    context.user_data["role"] = role
    context.user_data["current_block"] = 0
    context.user_data["answering_skipped"] = False

    await query.edit_message_text(f"Вы выбрали: **{role_name}**", parse_mode="Markdown")

    # Re-entry: just continue from current block, skip mentions only after block
    roles_before = get_or_create_user(user.id, user.username or user.full_name)
    if roles_before.get("current_block", 0) == 0:
        await query.message.reply_text("С возвращением! Продолжим с того же места.")
    await _send_block_welcome_and_first_question(query.message, context, 0, user_id=user.id)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all inline keyboard callbacks."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    # Instruction buttons — send as new message, don't replace the question
    if data.startswith("instr_voice_") or data.startswith("instr_text_"):
        qnum = data.replace("instr_voice_", "").replace("instr_text_", "")
        instr = (
            "🎙 Отправь голосовое сообщение с ответом.\n"
            f"Начни с «Вопрос {qnum}» — так я пойму, на какой вопрос ты отвечаешь."
        ) if "voice" in data else (
            "✏️ Напиши текстовый ответ.\n"
            f"Начни с «Вопрос {qnum}» — так я пойму, на какой вопрос ты отвечаешь."
        )
        # Send as new message so the question stays visible
        await query.message.reply_text(instr)
        return

    # Skip question
    if data.startswith("skip_"):
        qnum = int(data.replace("skip_", ""))
        mark_skipped(user.id, qnum)
        update_user_activity(user.id)
        await query.edit_message_text(f"✅ Вопрос {qnum} пропущен.")
        await _show_progress_and_next(query, context)
        return

    # Retry skipped questions
    if data == "retry_skipped":
        skipped = get_skipped_questions(user.id)
        if skipped:
            context.user_data["answering_skipped"] = True
            await query.edit_message_text(
                f"Осталось ответить на {len(skipped)} вопросов. Поехали!"
            )
            await _send_question(query.message, context, skipped[0])
        else:
            await query.edit_message_text("Пропущенных вопросов больше нет!")
        return

    # Next block
    if data == "next_block":
        context.user_data["answering_skipped"] = False
        next_block = context.user_data.get("current_block", 0) + 1
        role = context.user_data.get("role")
        blocks = get_blocks_for_role(role)
        if next_block < len(blocks):
            update_user_block(user.id, next_block)
            context.user_data["current_block"] = next_block
            await query.edit_message_text("Переходим к следующему блоку.")
            await _send_block_welcome_and_first_question(query.message, context, next_block, user_id=user.id)
        else:
            await _send_final_message(query)
        return

    # Continue with current block (decline skipped on re-entry)
    if data == "continue_current":
        role = context.user_data.get("role")
        current_block_idx = context.user_data.get("current_block", 0)
        await query.edit_message_text("Хорошо, продолжим с текущего блока.")
        await _send_block_welcome_and_first_question(query.message, context, current_block_idx, user_id=user.id)
        return

    # Finish survey (decline skipped after all blocks)
    if data == "finish_survey":
        await _send_final_message(query)
        return


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
    user = update.effective_user

    # Require role selection first
    if not context.user_data.get("role"):
        await update.message.reply_text(
            "Сначала выберите роль, чтобы я знал, какие вопросы вам задавать.\n"
            "Напишите /start для выбора роли."
        )
        return

    voice = update.message.voice

    try:
        file = await voice.get_file()
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ogg_path = AUDIO_DIR / f"{user.id}_{timestamp}.ogg"
        await file.download_to_drive(ogg_path)
    except Exception as e:
        log_error("voice_download", e, {"user_id": user.id})
        await update.message.reply_text("❌ Не удалось загрузить голосовое. Попробуйте ещё раз.")
        return

    await update.message.reply_text("🎧 Получил голосовое, расшифровываю...")

    text = transcribe(str(ogg_path))

    if not text:
        await update.message.reply_text(
            "❌ Не удалось расшифровать. Попробуйте записать ещё раз или напишите текстом."
        )
        return

    question_number = parse_question_number(text)

    save_response(
        user_id=user.id,
        username=user.username or user.full_name,
        question_number=question_number,
        raw_text=text,
        audio_path=str(ogg_path),
        status="answered",
    )
    update_user_activity(user.id)

    if question_number:
        await update.message.reply_text(
            f"✅ Вопрос {question_number} принят. Спасибо!\n\n"
            f"📝 Расшифровка: {text[:200]}{'...' if len(text) > 200 else ''}"
        )
        await _show_progress_and_next(update.message, context)
    else:
        await update.message.reply_text(
            f"✅ Голосовое сохранено. Спасибо!\n\n"
            f"📝 Расшифровка: {text[:200]}{'...' if len(text) > 200 else ''}\n\n"
            f"👇 Напишите номер вопроса, на который вы ответили (просто цифру 1, 2, 3...). "
            f"Если хотите начать новый ответ — просто отправьте голосовое или текст с номером вопроса в начале."
        )
        context.user_data["pending_question"] = {"audio_path": str(ogg_path), "transcript": text}


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages as written answers."""
    text = update.message.text.strip()
    user = update.effective_user

    # Log user ID for admin identification
    if text == "/myid":
        await update.message.reply_text(f"Твой Telegram ID: `{user.id}`", parse_mode="Markdown")
        return

    # Skip commands
    if text.startswith("/"):
        return

    # Require role selection first
    if not context.user_data.get("role"):
        await update.message.reply_text(
            "Сначала выберите роль, чтобы я знал, какие вопросы вам задавать.\n"
            "Напишите /start для выбора роли."
        )
        return

    # Check if user is clarifying a question number after a voice message
    pending = context.user_data.get("pending_question")
    if pending and text.isdigit():
        number = int(text)
        if 1 <= number <= 45:
            save_response(
                user_id=user.id,
                username=user.username or user.full_name,
                question_number=number,
                raw_text=pending["transcript"],
                audio_path=pending["audio_path"],
                status="answered",
            )
            update_user_activity(user.id)
            context.user_data.pop("pending_question", None)
            await update.message.reply_text(
                f"✅ Понял, это был ответ на вопрос {number}. Спасибо!"
            )
            await _show_progress_and_next(update.message, context)
            return

    question_number = parse_question_number(text)

    save_response(
        user_id=user.id,
        username=user.username or user.full_name,
        question_number=question_number,
        raw_text=text,
        status="answered",
    )
    update_user_activity(user.id)

    if question_number:
        await update.message.reply_text(f"✅ Вопрос {question_number} принят. Спасибо!")
        await _show_progress_and_next(update.message, context)
    else:
        await update.message.reply_text(
            f"✅ Принято. Спасибо!\n"
            f"💡 В следующий раз напишите номер вопроса в начале, например: «Вопрос 5. ...»"
        )


async def error_handler(update: Update | None, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler — catches all unhandled exceptions."""
    log_error("unhandled_exception", context.error, {
        "update_id": update.update_id if update else None,
        "user_id": update.effective_user.id if update and update.effective_user else None,
    })
    if update and update.effective_chat:
        try:
            await update.effective_chat.send_message(
                "❌ Что-то пошло не так. Нажмите /start чтобы продолжить опрос."
            )
        except Exception:
            pass
    # Only admins get the full traceback
    try:
        if update and update.effective_user and _is_admin(update.effective_user.id):
            await update.effective_user.send_message(
                f"❌ Ошибка:\n```\n{''.join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))[:3000]}```",
                parse_mode="Markdown",
            )
    except Exception:
        pass


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command: show system health."""
    if not _is_admin(update.effective_user.id):
        await update.message.reply_text("Эта команда только для администраторов.")
        return

    h = health_check()
    msg = (
        f"Бот работает.\n\n"
        f"Статус: {'OK' if h['status'] == 'ok' else 'Проблемы'}\n"
        f"Данные: {h['data_dir']}\n"
        f"БД: {'есть' if h['database']['exists'] else 'нет'} ({h['database']['size_mb']} MB)\n\n"
        f"Диск: {h['disk']['used_gb']} / {h['disk']['total_gb']} GB ({h['disk']['percent_used']}%)\n"
        f"Свободно: {h['disk']['free_gb']} GB\n"
    )
    await update.message.reply_text(msg, parse_mode="Markdown")


async def about_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "SerwisWin Survey Bot\n\n"
        "Помощник для сбора инсайтов от сотрудников. Принимает голосовые и текстовые "
        "ответы на вопросы опросника, расшифровывает их и сохраняет для анализа.\n\n"
        "Создан для улучшения рекламы и контента SerwisWin."
    )
    await update.message.reply_text(text)


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


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("questions", questions_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("health", health_command))

    app.add_handler(CallbackQueryHandler(role_callback, pattern="^role_"))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(skip_|retry_skipped|next_block|finish_survey|instr_voice_|instr_text_)"))

    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    log_info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()

import os
import csv
import io
import traceback
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
    init_db, db_migrate, load_questions, save_response, get_stats, get_all_responses,
    get_or_create_user, update_user_role, update_user_block, update_user_activity,
    mark_user_finished, get_user_responses, get_current_block, mark_voice_pending,
)
from survey_data import (
    questions, format_questions, get_blocks_for_role,
    get_questions_in_block, is_optional, get_block_welcome,
    BLOCK_ORDER,
)
from transcriber import parse_question_number
from monitor import log_info, log_error, health_check


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

# Block where renovation question should be asked (for masters)
RENOVATION_PROMPT_BLOCK = "Мастера (выезд)"

# ─── Helpers ──────────────────────────────────────────────────────────


def _get_block_part_indices(block_name: str, role: str) -> list[list[int]]:
    """Return list of question number lists, each up to 8 questions."""
    qs = get_questions_in_block(block_name, role)
    result = []
    chunk_size = 8
    for i in range(0, len(qs), chunk_size):
        result.append([q["number"] for q in qs[i:i + chunk_size]])
    return result


async def _ensure_role(context, user_id: int) -> str | None:
    """Get role from context or DB. Returns role or None."""
    role = context.user_data.get("role")
    if not role:
        user_data = get_or_create_user(user_id, None)
        role = user_data.get("role")
        if role:
            block_idx = user_data.get("current_block", 0)
            context.user_data["role"] = role
            context.user_data["current_block"] = block_idx
    return role


async def _get_user_id(obj):
    """Extract user_id from Update, Message, or User object."""
    if hasattr(obj, "effective_user") and obj.effective_user:
        return obj.effective_user.id
    if hasattr(obj, "from_user") and obj.from_user:
        return obj.from_user.id
    if hasattr(obj, "chat") and obj.chat:
        return obj.chat.id
    if hasattr(obj, "id"):
        return obj.id
    return None


async def _send_block_intro(chat_or_msg, context, block_index: int, user_id: int):
    """Show welcome + only the first (or next unanswered) part of a block."""
    role = context.user_data.get("role")
    if not role:
        return
    blocks = get_blocks_for_role(role)
    block_name = blocks[block_index]
    total_blocks = len(blocks)
    parts = _get_block_part_indices(block_name, role)

    # Find the part the user is currently on
    target_part = _get_current_part_idx(user_id, block_name, role)

    # Welcome message only for part 0
    if target_part == 0:
        welcome = get_block_welcome(block_name)
        await chat_or_msg.reply_text(welcome)

    # Get answered question numbers
    user_responses = get_user_responses(user_id)
    answered_nums = set()
    for r in user_responses:
        if r.get("status") == "answered" and r.get("question_number"):
            answered_nums.add(r["question_number"])

    # Show only the current part
    q_numbers = parts[target_part]
    lines = []
    if target_part == 0:
        lines.append(f"📋 **Блок {block_index + 1} из {total_blocks}: {block_name}**\n")
    else:
        lines.append(f"📋 **{block_name} (часть {target_part + 1})**\n")

    for qnum in q_numbers:
        q = get_question_data(qnum)
        if not q:
            continue
        opt_tag = " (опц.)" if is_optional(qnum) else ""
        prefix = "✅" if qnum in answered_nums else f"{qnum}."
        lines.append(f"{prefix} {q['text']}{opt_tag}")

    lines.extend([
        "",
        "📲 **Как отвечать:**",
        "Начинай с номера вопроса — например: «Вопрос 5. ...»",
        "Можно голосом или текстом.",
    ])
    await chat_or_msg.reply_text("\n".join(lines))


def get_question_data(qnum: int) -> dict | None:
    """Get question dict by number from survey_data."""
    for q in questions:
        if q["number"] == qnum:
            return q
    return None


def _get_current_part_idx(user_id: int, block_name: str, role: str) -> int:
    """Find which part of a block the user is currently on."""
    parts = _get_block_part_indices(block_name, role)
    user_responses = get_user_responses(user_id)
    for part_idx, part_qnums in enumerate(parts):
        # Check if all questions in this part are answered
        for qnum in part_qnums:
            answered = any(
                r.get("status") == "answered" and r.get("question_number") == qnum
                for r in user_responses
            )
            if not answered:
                return part_idx
    return len(parts) - 1  # All parts done, stay on last


def _is_part_fully_answered(user_id: int, block_name: str, role: str) -> bool:
    """Check if current part of a block is fully answered."""
    parts = _get_block_part_indices(block_name, role)
    current_part = _get_current_part_idx(user_id, block_name, role)
    part_qnums = set(parts[current_part])
    user_responses = get_user_responses(user_id)
    answered = set()
    for r in user_responses:
        if r.get("status") == "answered" and r.get("question_number") in part_qnums:
            answered.add(r["question_number"])
    return part_qnums.issubset(answered)


def _is_block_fully_answered(user_id: int, block_name: str, role: str) -> bool:
    """Check if ALL questions in a block have at least one answered response."""
    qs = get_questions_in_block(block_name, role)
    all_qnums = {q["number"] for q in qs}
    user_responses = get_user_responses(user_id)
    answered = set()
    for r in user_responses:
        if r.get("status") == "answered" and r.get("question_number") in all_qnums:
            answered.add(r["question_number"])
    return all_qnums.issubset(answered)


def _count_block_answered(user_id: int, block_name: str, role: str) -> int:
    """Count how many unique questions have been answered in a block."""
    qs = get_questions_in_block(block_name, role)
    all_qnums = {q["number"] for q in qs}
    user_responses = get_user_responses(user_id)
    answered = set()
    for r in user_responses:
        if r.get("status") == "answered" and r.get("question_number") in all_qnums:
            answered.add(r["question_number"])
    return len(answered)


def _count_voice_pending(user_id: int, block_name: str, role: str) -> int:
    """Count voice_saved responses without a question number, in this block's question range."""
    qs = get_questions_in_block(block_name, role)
    all_qnums = {q["number"] for q in qs}
    user_responses = get_user_responses(user_id)
    return sum(1 for r in user_responses
               if r.get("status") == "voice_saved" and r.get("question_number") is None)


def _is_same_block_question(qnum: int, block_name: str, role: str) -> bool:
    """Check if a question number belongs to the current block."""
    qs = get_questions_in_block(block_name, role)
    return any(q["number"] == qnum for q in qs)


async def _show_after_answer(chat_or_msg, context, user_id: int, last_qnum: int | None = None):
    """After saving an answer: show buttons and check block status."""
    role = context.user_data.get("role")
    if not role:
        return
    current_block_idx = context.user_data.get("current_block", 0)
    blocks = get_blocks_for_role(role)
    block_name = blocks[current_block_idx]

    # Check if we should show the renovation prompt after "Мастера (выезд)"
    if role == "masters" and block_name == RENOVATION_PROMPT_BLOCK:
        if _is_block_fully_answered(user_id, block_name, role):
            # Check if user already answered the renovation question
            skip_renov = context.user_data.get("skip_renovation")
            if skip_renov is None:
                keyboard = [
                    [InlineKeyboardButton("✅ Да, делаю реновацию", callback_data="renovation_yes")],
                    [InlineKeyboardButton("❌ Нет, не моё", callback_data="renovation_no")],
                ]
                await chat_or_msg.reply_text(
                    "✅ Все вопросы блока «Мастера (выезд)» отвечены!\n\n"
                    "У нас есть блок про реновацию деревянных окон (вопросы 26-31). "
                    "Ты занимаешься реновацией окон?",
                    reply_markup=InlineKeyboardMarkup(keyboard),
                )
                return

    # Determine part and block completion
    part_done = _is_part_fully_answered(user_id, block_name, role)
    block_done = _is_block_fully_answered(user_id, block_name, role) if part_done else False

    voice_pending = _count_voice_pending(user_id, block_name, role)

    # Build buttons
    buttons = []
    if last_qnum and _is_same_block_question(last_qnum, block_name, role):
        buttons.append([InlineKeyboardButton(f"📝 Дополнить вопрос {last_qnum}",
                        callback_data=f"append_{last_qnum}")])

    if voice_pending > 0:
        await chat_or_msg.reply_text(
            f"📌 У тебя {voice_pending} голосовое без номера вопроса. "
            "Напиши номер вопроса, на который оно было."
        )

    if block_done and voice_pending == 0:
        if current_block_idx + 1 < len(blocks):
            next_block_name = blocks[current_block_idx + 1]
            buttons.append([InlineKeyboardButton(
                f"➡️ К следующему блоку: {next_block_name}",
                callback_data="next_block",
            )])
        else:
            buttons.append([InlineKeyboardButton(
                "🏁 Завершить опрос",
                callback_data="finish_survey",
            )])
    elif part_done and not block_done and voice_pending == 0:
        buttons.append([InlineKeyboardButton(
            "➡️ Следующие вопросы блока",
            callback_data="next_part",
        )])

    if buttons:
        # Check which buttons are shown to pick the right text
        has_append = any(b[0].callback_data.startswith("append_") for b in buttons)
        has_next = any(b[0].callback_data in ("next_part", "next_block", "finish_survey") for b in buttons)

        if has_append and not has_next:
            text = "Ты можешь дополнить ответ или продолжить отвечать на вопросы."
        elif has_append and has_next:
            text = "Все вопросы этой части отвечены! Можешь дополнить или перейти дальше."
        elif has_next:
            text = "Все вопросы этой части отвечены! Переходи дальше."
        else:
            text = "Выбери действие:"

        await chat_or_msg.reply_text(text, reply_markup=InlineKeyboardMarkup(buttons))


async def _show_status(chat_or_msg, user_id: int, context):
    """Show detailed status of current block."""
    role = context.user_data.get("role")
    if not role:
        await chat_or_msg.reply_text("Сначала выбери роль через /start.")
        return

    blocks = get_blocks_for_role(role)
    current_block_idx = context.user_data.get("current_block", 0)
    block_name = blocks[current_block_idx]
    qs = get_questions_in_block(block_name, role)
    total = len(qs)
    answered = _count_block_answered(user_id, block_name, role)
    pending_voice = _count_voice_pending(user_id, block_name, role)

    user_responses = get_user_responses(user_id)
    answered_nums = set()
    for r in user_responses:
        if r.get("status") == "answered" and r.get("question_number") and \
           _is_same_block_question(r["question_number"], block_name, role):
            answered_nums.add(r["question_number"])

    lines = [
        f"📋 **Блок {current_block_idx + 1} из {len(blocks)}: {block_name}**",
        f"Отвечено {answered} из {total}\n",
    ]

    for q in qs:
        opt_tag = " (опц.)" if is_optional(q["number"]) else ""
        prefix = "✅" if q["number"] in answered_nums else f"⬜"
        lines.append(f"{prefix} Вопрос {q['number']}. {q['text']}{opt_tag}")

    if pending_voice > 0:
        lines.extend([
            "",
            f"📌 {pending_voice} голосовое без номера — напиши номер вопроса для него.",
        ])

    await chat_or_msg.reply_text("\n".join(lines))


# ─── Handlers ─────────────────────────────────────────────────────────


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_data = get_or_create_user(user.id, user.username or user.full_name)

    # Already finished
    if user_data.get("finished"):
        await update.message.reply_text(
            "🎉 Спасибо! Ты уже прошёл опрос.\n\n"
            "Если хочешь посмотреть свои вопросы — напиши /questions.\n"
            "Хорошего дня!"
        )
        return

    # Has role — resume from current block
    if user_data.get("role"):
        role = user_data["role"]
        block_idx = user_data.get("current_block", 0)
        context.user_data["role"] = role
        context.user_data["current_block"] = block_idx

        await _send_block_intro(update.message, context, block_idx, user.id)
        await _show_after_answer(update.message, context, user.id)
        return

    # No role — show welcome
    text = (
        "👋 Всем привет!\n\n"
        "Я подготовил опросник, чтобы собрать реальные истории и фразы "
        "из работы с клиентами. Это для нашей рекламы и соцсетей — нужно, "
        "чтобы тексты были живыми, а не выдуманными.\n\n"
        "Вы с клиентами общаетесь каждый день и лучше всех знаете, "
        "что они говорят, из-за чего переживают, за что благодарят. "
        "Поделитесь этим.\n\n"
        "📲 **Как отвечать:**\n"
        "Читаешь вопрос, вспоминаешь 2-3 конкретных случая — "
        "записываешь голосовое или пишешь текстом.\n\n"
        "📝 **Главное правило:** называй номер вопроса в начале ответа.\n"
        "Пример: «Вопрос 5. Когда клиенты отказываются, они говорят...»\n\n"
        "**Важно:** не обобщай, а рассказывай как было. "
        "Вместо «клиентам дорого» — опиши случай, когда клиент "
        "конкретно так сказал.\n\n"
        "На всё уйдёт 20-30 минут. Выбери свою роль:"
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

    update_user_role(user.id, role)
    update_user_block(user.id, 0)
    update_user_activity(user.id)
    context.user_data["role"] = role
    context.user_data["current_block"] = 0

    await query.edit_message_text(f"Ты выбрал: **{role_name}**", parse_mode="Markdown")

    await _send_block_intro(query.message, context, 0, user.id)


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle voice messages — save .ogg and ask for question number."""
    user = update.effective_user
    role = await _ensure_role(context, user.id)
    if not role:
        await update.message.reply_text(
            "Сначала выбери роль через /start."
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
        await update.message.reply_text("❌ Не удалось загрузить голосовое. Попробуй ещё раз.")
        return

    row_id = mark_voice_pending(
        user_id=user.id,
        username=user.username or user.full_name,
        audio_path=str(ogg_path),
    )
    context.user_data["pending_voice_id"] = row_id
    update_user_activity(user.id)

    await update.message.reply_text(
        "✅ Голосовое принято!\n"
        "Напиши номер вопроса, на который ответил."
    )


async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle text messages — answer, question number mapping, or command."""
    text = update.message.text.strip()
    user = update.effective_user

    # Commands
    if text == "/myid":
        await update.message.reply_text(f"Твой Telegram ID: `{user.id}`", parse_mode="Markdown")
        return
    if text.startswith("/"):
        return

    role = await _ensure_role(context, user.id)
    if not role:
        await update.message.reply_text(
            "Сначала выбери роль через /start."
        )
        return

    # Try to parse question number from text
    question_number = parse_question_number(text)

    # If there is a pending voice, try to bind this text as its question number
    pending_id = context.user_data.get("pending_voice_id")
    if pending_id:
        if question_number:
            # Update the pending voice response with the question number
            from database import get_connection
            conn = get_connection()
            cur = conn.cursor()
            cur.execute(
                "UPDATE responses SET question_number = ?, status = 'answered' WHERE id = ?",
                (question_number, pending_id),
            )
            conn.commit()
            conn.close()
            context.user_data.pop("pending_voice_id", None)

            await update.message.reply_text(
                f"✅ Вопрос {question_number} принят. Спасибо!"
            )
            await _show_after_answer(update.message, context, user.id, question_number)
            return
        else:
            # Text without number — could be the number itself written as just "5"
            if text.isdigit():
                num = int(text)
                if 1 <= num <= 45:
                    from database import get_connection
                    conn = get_connection()
                    cur = conn.cursor()
                    cur.execute(
                        "UPDATE responses SET question_number = ?, status = 'answered' WHERE id = ?",
                        (num, pending_id),
                    )
                    conn.commit()
                    conn.close()
                    context.user_data.pop("pending_voice_id", None)

                    await update.message.reply_text(
                        f"✅ Вопрос {num} принят. Спасибо!"
                    )
                    await _show_after_answer(update.message, context, user.id, num)
                    return

            # Text without number, no pending voice matched
            await update.message.reply_text(
                "Я не вижу номер вопроса.\n"
                "Напиши номер вопроса, на который ответил — просто цифру (1, 2, 3...)."
            )
            return

    # Normal text answer (no pending voice)
    if question_number:
        save_response(
            user_id=user.id,
            username=user.username or user.full_name,
            question_number=question_number,
            raw_text=text,
            status="answered",
        )
        update_user_activity(user.id)

        await update.message.reply_text(
            f"✅ Вопрос {question_number} принят. Спасибо!"
        )
        await _show_after_answer(update.message, context, user.id, question_number)
    else:
        await update.message.reply_text(
            "✅ Принято. Спасибо!\n"
            "💡 В следующий раз напиши номер вопроса в начале — "
            "например: «Вопрос 5. ...»"
        )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline keyboard callbacks: append, next block, renovation, finish."""
    query = update.callback_query
    await query.answer()
    data = query.data
    user = update.effective_user

    # Append to question N
    if data.startswith("append_"):
        qnum = int(data.replace("append_", ""))
        context.user_data["append_question"] = qnum
        await query.edit_message_text(
            f"📝 Жду дополнение к вопросу {qnum}.\n"
            "Отправь голосовое или текст."
        )
        return

    # Renovation yes
    if data == "renovation_yes":
        context.user_data["skip_renovation"] = False
        role = context.user_data.get("role")
        blocks = get_blocks_for_role(role)
        # Find renovation block index
        ren_idx = blocks.index("Реновация окон")
        update_user_block(user.id, ren_idx)
        context.user_data["current_block"] = ren_idx
        await query.edit_message_text("Отлично! Показываю блок по реновации окон.")
        await _send_block_intro(query.message, context, ren_idx, user.id)
        return

    # Renovation no
    if data == "renovation_no":
        context.user_data["skip_renovation"] = True
        role = context.user_data.get("role")
        blocks = get_blocks_for_role(role)
        # Skip to final block
        final_idx = blocks.index("Финальный")
        update_user_block(user.id, final_idx)
        context.user_data["current_block"] = final_idx
        await query.edit_message_text("Понял! Переходим к финальному блоку.")
        await _send_block_intro(query.message, context, final_idx, user.id)
        return

    # Next part within same block
    if data == "next_part":
        user_id = update.effective_user.id
        role = context.user_data.get("role")
        current_block_idx = context.user_data.get("current_block", 0)
        await _send_block_intro(query.message, context, current_block_idx, user_id)
        return

    # Next block
    if data == "next_block":
        role = context.user_data.get("role")
        current_block_idx = context.user_data.get("current_block", 0)
        blocks = get_blocks_for_role(role)
        next_block_idx = current_block_idx + 1

        if next_block_idx < len(blocks):
            next_name = blocks[next_block_idx]

            # If next is renovation and user is masters who said no, skip to final
            if (role == "masters" and next_name == "Реновация окон"
                    and context.user_data.get("skip_renovation")):
                # Move directly to final
                final_idx = blocks.index("Финальный")
                update_user_block(user.id, final_idx)
                context.user_data["current_block"] = final_idx
                await query.edit_message_text("✅ Блок завершён! Переходим к финальному блоку.")
                await _send_block_intro(query.message, context, final_idx, user.id)
                return

            update_user_block(user.id, next_block_idx)
            context.user_data["current_block"] = next_block_idx
            await query.edit_message_text(
                f"✅ Блок «{blocks[current_block_idx]}» завершён! "
                f"Переходим к следующему."
            )
            await _send_block_intro(query.message, context, next_block_idx, user.id)
        else:
            await _send_final_message(query)
        return

    # Finish survey
    if data == "finish_survey":
        await _send_final_message(query)
        return


async def _send_final_message(chat_or_msg):
    """Send final congratulations and mark user as finished."""
    user_id = await _get_user_id(chat_or_msg)
    if not user_id:
        return
    mark_user_finished(user_id)
    msg = (
        "🎉 Спасибо! Ты ответил на все вопросы.\n\n"
        "Твои ответы очень помогут нашей рекламе и контенту. "
        "Если вспомнишь ещё что-то — просто напиши номер вопроса "
        "и ответ, я приму.\n\n"
        "Хорошего дня!"
    )
    await chat_or_msg.reply_text(msg)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show detailed progress for current block."""
    user = update.effective_user
    role = await _ensure_role(context, user.id)
    if not role:
        await update.message.reply_text("Сначала выбери роль через /start.")
        return

    await _show_status(update.message, user.id, context)


async def questions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    role = context.user_data.get("role")
    if not role:
        await start(update, context)
        return

    role_name = ROLES.get(role, role)
    questions_text = format_questions(role)
    await update.message.reply_text(
        f"Твои вопросы ({role_name}):\n\n{questions_text}"
    )


async def error_handler(update: Update | None, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler."""
    log_error("unhandled_exception", context.error, {
        "update_id": update.update_id if update else None,
        "user_id": update.effective_user.id if update and update.effective_user else None,
    })
    if update and update.effective_chat:
        try:
            await update.effective_chat.send_message(
                "❌ Что-то пошло не так. Нажми /start чтобы продолжить."
            )
        except Exception:
            pass
    try:
        if update and update.effective_user and _is_admin(update.effective_user.id):
            await update.effective_user.send_message(
                f"❌ Ошибка:\n```\n{''.join(traceback.format_exception(type(context.error), context.error, context.error.__traceback__))[:3000]}```",
                parse_mode="Markdown",
            )
    except Exception:
        pass


async def health_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        "Помощник для сбора инсайтов от сотрудников. "
        "Принимает голосовые и текстовые ответы на вопросы опросника "
        "и сохраняет их для анализа.\n\n"
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
    responses = get_all_responses()

    if not responses:
        await update.message.reply_text("Пока нет ни одного ответа.")
        return

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "ID", "User ID", "Username", "Вопрос №", "Текст вопроса",
        "Текст ответа", "Путь к аудио", "Статус", "Дата",
    ])

    for r in responses:
        writer.writerow([
            r["id"], r["user_id"], r["username"],
            r["question_number"], r["question_text"],
            r["raw_text"], r["audio_path"], r["status"], r["created_at"],
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
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("questions", questions_command))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("export", export_command))
    app.add_handler(CommandHandler("about", about_command))
    app.add_handler(CommandHandler("health", health_command))

    app.add_handler(CallbackQueryHandler(role_callback, pattern="^role_"))
    app.add_handler(CallbackQueryHandler(button_handler, pattern="^(append_|next_block|finish_survey|renovation_)"))

    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.add_error_handler(error_handler)

    log_info("Bot starting...")
    app.run_polling()


if __name__ == "__main__":
    main()

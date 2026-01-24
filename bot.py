import json
import os
import re
import subprocess
import sys
import time
from typing import Dict, Optional, Tuple

# =====================
# Автоустановка библиотек (если нет)
# =====================
def install_package(package: str) -> None:
    subprocess.check_call([sys.executable, "-m", "pip", "install", package])

try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ChatMemberStatus
    from telegram.error import TelegramError, BadRequest
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        CallbackQueryHandler,
    )
except ImportError:
    install_package("python-telegram-bot==20.8")
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.constants import ChatMemberStatus
    from telegram.error import TelegramError, BadRequest
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        CallbackQueryHandler,
    )

try:
    import requests
except ImportError:
    install_package("requests")
    import requests


# =====================
# НАСТРОЙКИ
# =====================
# Рекомендуется задавать через переменные окружения (Replit Secrets / Environment Variables):
# BOT_TOKEN, CHAT_ID, POLL_INTERVAL, STATE_FILE
BOT_TOKEN = os.getenv("BOT_TOKEN", "PASTE_YOUR_BOT_TOKEN_HERE")
CHAT_ID = os.getenv("CHAT_ID", "@Russian_Demon_Life")

# Как часто обновлять (сек)
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "120"))

# Файл состояния (чтобы помнить message_id после перезапуска)
STATE_FILE = os.getenv("STATE_FILE", "bot_state.json")

# Если никого нет
EMPTY_TEXT = "По стримам насрано 😎"

# Заголовок поста
HEADER_TEXT = "Сейчас в эфире:\n\n"

# =====================
# СПИСОК КАНАЛОВ (ключ = как хочешь видеть в анонсе)
# =====================
CHANNELS: Dict[str, str] = {
    "Гусь": "UCOSbywsX9qgHc2No-Z4Z8CQ",
    "Нижняя полка": "UCyt77ruZOLVRztdcP-YQgbA",
    "Селюк": "UCw2d-PgHpthfpHRGX9vpPLQ",
    "Костик Сопляк": "UCz_-kouNzyug_2k0cIE1aig",
    "КамераСиевана": "UCIBiR242nRb3BV4Vf3h-0ZA",
    "Вьетнамские приключения": "UCOHaUXZer0z9soGdgkginag",
    "Бертолет": "UCDxns5jCJ09P4zCe_Kpyblg",
    "Саша Урина": "UCTXx6sWPILhFFGeOcmhPDIQ",
    "Олегон": "UCGyJh69PKkg49a4kJeTGSgQ",
    "Ната+куколд": "UC8s6wVMVWDEmCwmVx6NuoRw",
    "Володя Пинг-понг": "UCQvXQhIzcHy2qaCFmKnO6kw",
    "Лил селюк": "UCgFzPho3IRnsyRdgeiqRCRA",
    "Средний клоп": "UCCcEQ8Wwy8XliMS-vyXEyzw",
    "Школа сук": "UCxuWNVixWyudDP0j0SChQnw",
    "Вьетнам запасной": "UC2Gi2LMRSPQoW_KLObbzmyw",
    "Гулливер": "UCYYvf2FsWtLgF2Py42NAqNQ",
    "Бродяга": "UCfW_cHDEs6EAN8LsUkYX3nQ",
    "Горбатый питекс": "UCT6AyDBCK6m4tojoRs9eM5w",
    "Чвидарас": "UCCZUcXLbDHpnOxi2L2wXoMA",
    "Бартез": "UCDhMI7crLkBOFXZUBgd6FMw",
    "Галкин": "UC2Gx3FbGQoT8dl9FS0QJemQ",
}


# =====================
# Состояние
# =====================
def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(state: dict) -> None:
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Не смог сохранить state:", e)


# =====================
# Проверка live без YouTube API (через /live страницу)
# =====================
UA = {
    "User-Agent": "Mozilla/5.0 (compatible; TelegramLiveBot/1.1; +https://example.com)"
}

_VIDEO_ID_RE = re.compile(r'"videoId":"([a-zA-Z0-9_-]{11})"')


def get_live_video_url(channel_id: str) -> Optional[str]:
    """
    Возвращает URL живого стрима, если сейчас реально идёт LIVE.
    Если не в эфире — None.
    """
    try:
        url = f"https://www.youtube.com/channel/{channel_id}/live"
        r = requests.get(url, headers=UA, timeout=15, allow_redirects=True)
        r.raise_for_status()
        html = r.text

        # Важно: отличаем реальный эфир от "просто страница"
        if '"isLiveNow":true' not in html:
            return None

        m = _VIDEO_ID_RE.search(html)
        if not m:
            return None

        video_id = m.group(1)
        return f"https://youtu.be/{video_id}"

    except Exception as e:
        print(f"Ошибка при проверке LIVE для {channel_id}: {e}")
        return None


# =====================
# Генерация текста поста
# (ВАЖНО: используем только имя из CHANNELS)
# =====================
def build_post_text() -> Tuple[str, int]:
    live_items = []

    for display_name, channel_id in sorted(CHANNELS.items(), key=lambda x: x[0].lower()):
        live_url = get_live_video_url(channel_id)
        if live_url:
            live_items.append((display_name, live_url))

    if not live_items:
        return EMPTY_TEXT, 0

    text = HEADER_TEXT
    for display_name, live_url in live_items:
        text += f"🔴 {display_name}:\n{live_url}\n\n"

    return text.strip(), len(live_items)


# =====================
# Кнопки
# =====================
def main_keyboard(is_admin_hint: bool = True) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("🔄 Обновить (в личке)", callback_data="refresh_dm")],
        [InlineKeyboardButton("📣 Обновить пост в канале", callback_data="refresh_channel")],
    ]
    return InlineKeyboardMarkup(rows)


# =====================
# Telegram helpers
# =====================
async def is_channel_admin(bot, chat_id: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except TelegramError:
        return False


async def ensure_announcement_message(bot) -> Optional[int]:
    """
    Возвращает message_id объявления. Если нет — создаёт новое сообщение.
    """
    state = load_state()
    msg_id = state.get("announcement_message_id")

    if msg_id:
        return msg_id

    text, _ = build_post_text()
    msg = await bot.send_message(chat_id=CHAT_ID, text=text, disable_web_page_preview=True)
    state["announcement_message_id"] = msg.message_id
    save_state(state)
    return msg.message_id


async def update_channel_post(context: ContextTypes.DEFAULT_TYPE) -> None:
    """
    Обновляет (редактирует) одно фиксированное сообщение в канале.
    """
    bot = context.bot
    post_text, active_count = build_post_text()

    msg_id = await ensure_announcement_message(bot)
    if not msg_id:
        return

    try:
        await bot.edit_message_text(
            chat_id=CHAT_ID,
            message_id=msg_id,
            text=post_text,
            disable_web_page_preview=True,
        )
        print(f"[{time.strftime('%H:%M:%S')}] Обновил пост в канале. В эфире: {active_count}")
    except BadRequest as e:
        # Часто бывает "message is not modified" — это нормально
        if "message is not modified" in str(e).lower():
            return
        print("BadRequest при edit:", e)
    except TelegramError as e:
        print("TelegramError при edit:", e)


# =====================
# Команды
# =====================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post_text, _ = build_post_text()
    await update.message.reply_text(
        text=post_text,
        reply_markup=main_keyboard(),
        disable_web_page_preview=True,
    )


async def update_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_channel_admin(context.bot, CHAT_ID, update.effective_user.id):
        await update.message.reply_text("🚫 Только админы канала могут использовать /update")
        return
    await update.message.reply_text("⏳ Обновляю пост в канале...")
    await update_channel_post(context)
    await update.message.reply_text("✅ Готово.")


async def reset_post_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    На случай, если удалили сообщение в канале руками или бот потерял message_id.
    Команда сбрасывает state и создаёт пост заново при следующем обновлении.
    """
    if not await is_channel_admin(context.bot, CHAT_ID, update.effective_user.id):
        await update.message.reply_text("🚫 Только админы канала могут использовать /reset_post")
        return
    state = load_state()
    state.pop("announcement_message_id", None)
    save_state(state)
    await update.message.reply_text("♻️ Сбросил message_id. Следующее обновление создаст новый пост.")


# =====================
# Кнопки: обработчик
# =====================
async def on_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    post_text, _ = build_post_text()

    if query.data == "refresh_dm":
        # Только обновляем сообщение в личке
        try:
            await query.edit_message_text(
                text=post_text,
                reply_markup=main_keyboard(),
                disable_web_page_preview=True,
            )
        except BadRequest as e:
            if "message is not modified" in str(e).lower():
                return
            raise
        return

    if query.data == "refresh_channel":
        user_id = query.from_user.id
        if await is_channel_admin(context.bot, CHAT_ID, user_id):
            await update_channel_post(context)
            # И обновим сообщение в личке, чтобы пользователь видел актуальное
            post_text2, _ = build_post_text()
            await query.edit_message_text(
                text=post_text2,
                reply_markup=main_keyboard(),
                disable_web_page_preview=True,
            )
        else:
            await query.edit_message_text(
                text=post_text + "\n\n🚫 Пост в канале может обновлять только админ.",
                reply_markup=main_keyboard(),
                disable_web_page_preview=True,
            )
        return


# =====================
# Запуск
# =====================
def main():
    if not BOT_TOKEN or BOT_TOKEN == "PASTE_YOUR_BOT_TOKEN_HERE":
        print("❌ Укажи BOT_TOKEN в переменной окружения BOT_TOKEN (Replit Secrets) или в коде.")
        return

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("update", update_command))
    app.add_handler(CommandHandler("reset_post", reset_post_command))

    # Кнопки
    app.add_handler(CallbackQueryHandler(on_buttons, pattern="^(refresh_dm|refresh_channel)$"))

    # автообновление поста в канале
    app.job_queue.run_repeating(update_channel_post, interval=POLL_INTERVAL, first=5)

    print(f"🔴 БОТ ЗАПУЩЕН! Интервал обновления: {POLL_INTERVAL} сек. Чат: {CHAT_ID}")
    app.run_polling()


if __name__ == "__main__":
    main()

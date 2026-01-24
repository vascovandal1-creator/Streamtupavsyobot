# -*- coding: utf-8 -*-
"""
Telegram bot: мониторинг YouTube LIVE по channelId.

Требования (как ты просил):
✅ СНАЧАЛА проверяем каналы, и только потом формируем пост.
✅ Если есть эфиры → пост: "Сейчас в эфире:" + ссылки с ТВОИМИ названиями (ключи словаря).
✅ Если эфиров НЕТ → пост: "по стримам насрано"
✅ Автообновление поста каждые 15 минут (редактирование одного поста).
✅ Ротация: через 60 минут старый пост удаляется, на 61-й минуте создаётся новый.
✅ Кнопка "🔄 Обновить" для ручного обновления.
✅ Команды: /start, /now, /refresh, /reset_post
✅ Токен НЕ в коде: берём из ENV. Поддерживаем Bothost-имена переменных.

ENV:
- BOT_TOKEN / TELEGRAM_BOT_TOKEN / BOT_API_TOKEN / TOKEN  (любая подойдёт)
- CHAT_ID / TELEGRAM_CHANNEL_ID / CHANNEL_ID (куда постить). По умолчанию: @Russian_Demon_Life
- YT_API_KEY / YOUTUBE_API_KEY (YouTube Data API v3 key) — сильно рекомендую. Если нет, будет fallback через HTML.
"""

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError, BadRequest
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# =====================
# 1) ТВОИ КАНАЛЫ (НЕ УБИРАЮ)
# =====================
YOUTUBE_CHANNELS: Dict[str, str] = {
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
    "Галкин": "UC2Gx3FbGQoT8dl9FS0QJemQ"
}

# =====================
# 2) ENV / НАСТРОЙКИ
# =====================
def _first_env(*names: str, default: str = "") -> str:
    for n in names:
        v = os.getenv(n, "")
        if v and v.strip():
            return v.strip()
    return default

from secrets_local import BOT_TOKEN, YT_API_KEY
CHAT_ID = "@Russian_Demon_Life"
# Если вдруг захочешь сменить канал без правки кода — поставь ENV CHAT_ID_OVERRIDE=1 и ENV CHAT_ID
if os.getenv("CHAT_ID_OVERRIDE", "").strip() == "1":
    CHAT_ID = _first_env("CHAT_ID", "TELEGRAM_CHANNEL_ID", "CHANNEL_ID", default=CHAT_ID)


# обновление каждые 15 минут
UPDATE_EVERY = 15 * 60

# ротация поста
DELETE_AFTER = 60 * 60   # 60 минут
NEW_AFTER = 61 * 60      # 61 минута

# state файл
STATE_FILE = _first_env("STATE_FILE", default="/app/data/bot_state.json")

# текст
TEXT_EMPTY = "по стримам насрано"
TEXT_HEADER = "Сейчас в эфире:"

UA = {"User-Agent": "Mozilla/5.0 (compatible; StreamBot/4.0)"}

# =====================
# 3) STATE
# =====================
def _ensure_state_dir():
    try:
        d = os.path.dirname(STATE_FILE)
        if d:
            os.makedirs(d, exist_ok=True)
    except Exception:
        pass

def load_state() -> dict:
    _ensure_state_dir()
    if not os.path.exists(STATE_FILE):
        return {}
    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: dict) -> None:
    _ensure_state_dir()
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, STATE_FILE)

# =====================
# 4) YouTube LIVE detection
# =====================
@dataclass
class LiveItem:
    name: str
    url: str

def yt_api_get(endpoint: str, params: Dict[str, str]) -> Optional[dict]:
    if not YT_API_KEY:
        return None
    base = "https://www.googleapis.com/youtube/v3/"
    params = dict(params)
    params["key"] = YT_API_KEY
    try:
        r = requests.get(base + endpoint, params=params, timeout=25)
        if r.status_code != 200:
            print("YouTube API error:", r.status_code, r.text[:250])
            return None
        return r.json()
    except Exception as e:
        print("YouTube API exception:", e)
        return None

def find_live_video_api(channel_id: str) -> Optional[str]:
    """Возвращает videoId если канал сейчас live (через официальный API)."""
    data = yt_api_get("search", {
        "part": "id",
        "channelId": channel_id,
        "eventType": "live",
        "type": "video",
        "maxResults": "1",
    })
    if not data:
        return None
    items = data.get("items") or []
    if not items:
        return None
    vid = (items[0].get("id") or {}).get("videoId")
    return vid or None

# fallback без API: /channel/<id>/live + поиск videoId
_VIDEO_ID_RE = re.compile(r'"videoId":"([a-zA-Z0-9_-]{11})"')

def find_live_video_html(channel_id: str) -> Optional[str]:
    try:
        url = f"https://www.youtube.com/channel/{channel_id}/live"
        r = requests.get(url, headers=UA, timeout=25, allow_redirects=True)
        r.raise_for_status()
        html = r.text
        # важно: СНАЧАЛА проверяем isLiveNow, и только потом вытаскиваем id
        if '"isLiveNow":true' not in html:
            return None
        m = _VIDEO_ID_RE.search(html)
        if not m:
            return None
        return m.group(1)
    except Exception as e:
        print(f"Ошибка LIVE(html) {channel_id}: {e}")
        return None

def get_live_items() -> List[LiveItem]:
    """СНАЧАЛА проверяем все каналы, собираем список live."""
    live: List[LiveItem] = []
    # стабильно: по порядку, без параллельщины
    for name, cid in YOUTUBE_CHANNELS.items():
        vid = None
        if YT_API_KEY:
            vid = find_live_video_api(cid)
        if not vid:
            vid = find_live_video_html(cid)
        if vid:
            live.append(LiveItem(name=name, url=f"https://youtu.be/{vid}"))
        # чуть-чуть пауза, чтобы не долбить сеть
        time.sleep(0.12)
    return live

def build_post_text() -> Tuple[str, int]:
    """СНАЧАЛА проверка, потом текст. 'насрано' только если список пустой."""
    live = get_live_items()
    if not live:
        return TEXT_EMPTY, 0
    lines = [TEXT_HEADER, ""]
    for it in live:
        lines.append(f"🔴 {it.name}\n{it.url}\n")
    return "\n".join(lines).strip(), len(live)

# =====================
# 5) Telegram helpers
# =====================
def keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить", callback_data="refresh")],
    ])

async def is_channel_admin(bot, chat_id: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except TelegramError:
        return False

async def ensure_post_exists(bot) -> int:
    """Создаёт пост если его нет в state."""
    state = load_state()
    msg_id = state.get("post_id")
    created_at = state.get("created_at")
    if msg_id and created_at:
        return int(msg_id)

    text, cnt = build_post_text()
    msg = await bot.send_message(chat_id=CHAT_ID, text=text, disable_web_page_preview=True, reply_markup=keyboard())
    state = {
        "post_id": msg.message_id,
        "created_at": int(time.time()),
        "last_text": text,
        "last_count": cnt,
        "deleted": False,
    }
    save_state(state)
    print("✅ Создал пост:", msg.message_id)
    return msg.message_id

async def rotate_if_needed(bot) -> None:
    """Удаление на 60-й минуте, новый пост на 61-й."""
    state = load_state()
    msg_id = state.get("post_id")
    created_at = state.get("created_at")
    if not msg_id or not created_at:
        return
    now = int(time.time())
    age = now - int(created_at)

    if age >= DELETE_AFTER and not state.get("deleted"):
        try:
            await bot.delete_message(chat_id=CHAT_ID, message_id=int(msg_id))
            state["deleted"] = True
            save_state(state)
            print("🗑️ Удалил пост:", msg_id)
        except TelegramError as e:
            print("❌ Не смог удалить пост:", e)

    if age >= NEW_AFTER:
        text, cnt = build_post_text()
        try:
            msg = await bot.send_message(chat_id=CHAT_ID, text=text, disable_web_page_preview=True, reply_markup=keyboard())
            state = {
                "post_id": msg.message_id,
                "created_at": now,
                "last_text": text,
                "last_count": cnt,
                "deleted": False,
            }
            save_state(state)
            print("♻️ Создал новый пост:", msg.message_id)
        except TelegramError as e:
            print("❌ Не смог создать новый пост:", e)

async def update_post(bot, force: bool = False) -> None:
    """Обновляет (редактирует) текущий пост. Ротация отдельно."""
    msg_id = await ensure_post_exists(bot)
    text, cnt = build_post_text()

    state = load_state()
    last_text = state.get("last_text")

    if (not force) and last_text == text:
        print("ℹ️ Ничего не изменилось, не редактирую.")
        return

    try:
        await bot.edit_message_text(chat_id=CHAT_ID, message_id=int(msg_id), text=text, disable_web_page_preview=True, reply_markup=keyboard())
        state["last_text"] = text
        state["last_count"] = cnt
        save_state(state)
        print(f"✅ Обновил пост {msg_id}. В эфире: {cnt}")
    except BadRequest as e:
        s = str(e).lower()
        # если пост удалили вручную — создадим новый
        if "message to edit not found" in s or "message_id_invalid" in s:
            state.pop("post_id", None)
            state.pop("created_at", None)
            state.pop("deleted", None)
            save_state(state)
            await ensure_post_exists(bot)
            return
        print("BadRequest:", e)
    except TelegramError as e:
        print("TelegramError:", e)

# =====================
# 6) Commands / Handlers
# =====================
async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # отвечает в личку
    text, _ = build_post_text()
    await update.message.reply_text(text, disable_web_page_preview=True, reply_markup=keyboard())

async def cmd_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text, _ = build_post_text()
    await update.message.reply_text(text, disable_web_page_preview=True, reply_markup=keyboard())

async def cmd_refresh(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Проверяю эфиры и обновляю пост…")
    await update_post(context.bot, force=True)
    await update.message.reply_text("✅ Готово.")

async def cmd_reset_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # только админ канала
    if not await is_channel_admin(context.bot, CHAT_ID, update.effective_user.id):
        await update.message.reply_text("🚫 Только админ канала может сбрасывать пост.")
        return
    state = load_state()
    state.pop("post_id", None)
    state.pop("created_at", None)
    state.pop("deleted", None)
    save_state(state)
    await update.message.reply_text("♻️ Сбросил пост. Следующее обновление создаст новый.")

async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # ручное обновление поста в канале может делать только админ
    if not await is_channel_admin(context.bot, CHAT_ID, query.from_user.id):
        await query.answer("Только админ канала может обновлять пост.", show_alert=True)
        return

    await update_post(context.bot, force=True)
    try:
        # обновим сообщение в личке/где нажали кнопку, чтобы человек увидел актуальный текст
        text, _ = build_post_text()
        await query.edit_message_text(text, disable_web_page_preview=True, reply_markup=keyboard())
    except TelegramError:
        pass

# =====================
# 7) Scheduler job
# =====================
async def job_tick(context: ContextTypes.DEFAULT_TYPE):
    # сначала ротация, потом обновление
    await rotate_if_needed(context.bot)
    await update_post(context.bot, force=False)

def main():
    # Строго: токен берётся ТОЛЬКО из secrets_local.py
    if (not BOT_TOKEN) or BOT_TOKEN.startswith("PASTE_"):
        print("❌ BOT_TOKEN не задан. Открой secrets_local.py и вставь токен от @BotFather.")
        return
    # YouTube API ключ опционален, но если оставил плейсхолдер — считаем что ключа нет
    global YT_API_KEY
    if (not YT_API_KEY) or YT_API_KEY.startswith("PASTE_"):
        YT_API_KEY = ""

    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("now", cmd_now))
    app.add_handler(CommandHandler("refresh", cmd_refresh))
    app.add_handler(CommandHandler("reset_post", cmd_reset_post))
    app.add_handler(CallbackQueryHandler(on_callback, pattern="^refresh$"))

    if app.job_queue is None:
        print("❌ JobQueue недоступен. Нужен пакет: python-telegram-bot[job-queue]==20.8")
        return

    # первый запуск: быстро создадим/обновим пост
    app.job_queue.run_once(job_tick, when=3)
    # дальше каждые 15 минут
    app.job_queue.run_repeating(job_tick, interval=UPDATE_EVERY, first=UPDATE_EVERY)

    mode = "YouTube API" if YT_API_KEY else "HTML fallback"
    print(f"🔴 БОТ ЗАПУЩЕН | Канал: {CHAT_ID} | Обновление: 15 мин | Ротация: 60/61 мин | YouTube: {mode}")
    app.run_polling()

if __name__ == "__main__":
    main()

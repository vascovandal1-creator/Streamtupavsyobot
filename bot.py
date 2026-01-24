# -*- coding: utf-8 -*-
"""
Telegram bot: мониторинг YouTube стримов.

✅ Токен Telegram берётся из ENV: BOT_TOKEN
✅ Куда постить: ENV CHAT_ID (по умолчанию @Russian_Demon_Life)
✅ Интервал: ENV POLL_INTERVAL (сек), по умолчанию 120
✅ Состояние поста хранится в STATE_FILE (по умолчанию /app/data/bot_state.json)

🎯 Мониторинг двумя способами (бот сам выберет лучший):
1) Через YouTube Data API v3 (НАИБОЛЕЕ НАДЁЖНО) — если задан ENV YT_API_KEY
   - По channelId: Search API (eventType=live)
   - По videoId: Videos API (liveStreamingDetails)
2) Без API ключа (fallback) — через обычные страницы YouTube (/live и watch?v=)

Как задать videoId без правки кода:
- ENV YOUTUBE_VIDEO_IDS:
    "Название1=VIDEOID1;Название2=VIDEOID2"
  или:
    "VIDEOID1,VIDEOID2,VIDEOID3"

Как задать канал (channelId) без правки кода:
- ENV YOUTUBE_CHANNELS:
    "Имя1=UC....;Имя2=UC...."
  (если не задано — используются CHANNELS из кода)
"""

import json
import os
import re
import time
from typing import Dict, Optional, Tuple, List

import requests

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatMemberStatus
from telegram.error import TelegramError, BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    CallbackQueryHandler,
)

# =====================
# ENV / SETTINGS
# =====================
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID = os.getenv("CHAT_ID", "@Russian_Demon_Life").strip()
POLL_INTERVAL = int(os.getenv("POLL_INTERVAL", "120"))
STATE_FILE = os.getenv("STATE_FILE", "/app/data/bot_state.json")

# YouTube API (опционально)
YT_API_KEY = os.getenv("YT_API_KEY", "").strip()

EMPTY_TEXT = "По стримам насрано 😎"
HEADER_TEXT = "Сейчас в эфире:\n\n"

UA = {"User-Agent": "Mozilla/5.0 (compatible; TelegramLiveBot/3.0)"}

# =====================
# Channels (default)
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

def _parse_pairs_env(var: str) -> Dict[str, str]:
    raw = os.getenv(var, "").strip()
    if not raw:
        return {}
    out: Dict[str, str] = {}
    for part in [p.strip() for p in raw.split(";") if p.strip()]:
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
        else:
            out[part] = part
    return out

# allow override/extend channels from ENV
ENV_CHANNELS = _parse_pairs_env("YOUTUBE_CHANNELS")
if ENV_CHANNELS:
    CHANNELS = ENV_CHANNELS

def parse_video_ids_env() -> Dict[str, str]:
    raw = os.getenv("YOUTUBE_VIDEO_IDS", "").strip()
    if not raw:
        return {}
    if "=" in raw or ";" in raw:
        return _parse_pairs_env("YOUTUBE_VIDEO_IDS")
    vids = [v.strip() for v in raw.split(",") if v.strip()]
    return {v: v for v in vids}

VIDEO_IDS: Dict[str, str] = parse_video_ids_env()

# =====================
# state
# =====================
def load_state() -> dict:
    try:
        if not os.path.exists(STATE_FILE):
            return {}
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_state(state: dict) -> None:
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("Не смог сохранить state:", e)

# =====================
# YouTube API v3 helpers (без google-api-python-client)
# =====================
def yt_api_get(endpoint: str, params: Dict[str, str]) -> Optional[dict]:
    if not YT_API_KEY:
        return None
    base = "https://www.googleapis.com/youtube/v3/"
    params = dict(params)
    params["key"] = YT_API_KEY
    try:
        r = requests.get(base + endpoint, params=params, timeout=20)
        if r.status_code != 200:
            print("YouTube API error:", r.status_code, r.text[:300])
            return None
        return r.json()
    except Exception as e:
        print("YouTube API exception:", e)
        return None

def get_live_by_channel_api(channel_id: str) -> Optional[str]:
    """Возвращает URL live-видео по channelId, если сейчас live."""
    data = yt_api_get("search", {
        "part": "id",
        "channelId": channel_id,
        "eventType": "live",
        "type": "video",
        "maxResults": "1",
    })
    if not data or "items" not in data or not data["items"]:
        return None
    vid = data["items"][0].get("id", {}).get("videoId")
    if not vid:
        return None
    return f"https://youtu.be/{vid}"

def get_live_info_by_video_api(video_id: str) -> Tuple[bool, Optional[str], Optional[str], str]:
    url = f"https://youtu.be/{video_id}"
    data = yt_api_get("videos", {
        "part": "snippet,liveStreamingDetails",
        "id": video_id,
        "maxResults": "1",
    })
    if not data or "items" not in data or not data["items"]:
        return False, None, None, url
    item = data["items"][0]
    sn = item.get("snippet", {}) or {}
    live = item.get("liveStreamingDetails", {}) or {}
    title = sn.get("title")
    channel_name = sn.get("channelTitle")
    # live если есть actualStartTime и нет actualEndTime (обычно)
    is_live = bool(live.get("actualStartTime")) and not live.get("actualEndTime")
    return is_live, title, channel_name, url

# =====================
# Fallback (без API)
# =====================
_VIDEO_ID_RE = re.compile(r'"videoId":"([a-zA-Z0-9_-]{11})"')
_PLAYER_RESP_RE = re.compile(r'ytInitialPlayerResponse\s*=\s*(\{.*?\})\s*;', re.DOTALL)

def get_live_video_url_from_channel_html(channel_id: str) -> Optional[str]:
    try:
        url = f"https://www.youtube.com/channel/{channel_id}/live"
        r = requests.get(url, headers=UA, timeout=20, allow_redirects=True)
        r.raise_for_status()
        html = r.text
        if '"isLiveNow":true' not in html:
            return None
        m = _VIDEO_ID_RE.search(html)
        if not m:
            return None
        return f"https://youtu.be/{m.group(1)}"
    except Exception as e:
        print(f"Ошибка LIVE (html) для канала {channel_id}: {e}")
        return None

def get_video_live_info_html(video_id: str) -> Tuple[bool, Optional[str], Optional[str], str]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    try:
        r = requests.get(url, headers=UA, timeout=20)
        r.raise_for_status()
        html = r.text
        m = _PLAYER_RESP_RE.search(html)
        if not m:
            is_live = '"isLiveContent":true' in html or '"isLiveNow":true' in html
            return is_live, None, None, url
        data = json.loads(m.group(1))
        vd = data.get("videoDetails", {}) or {}
        micro = (data.get("microformat", {}) or {}).get("playerMicroformatRenderer", {}) or {}
        live_details = micro.get("liveBroadcastDetails", {}) or {}
        title = vd.get("title")
        channel_name = vd.get("author") or micro.get("ownerChannelName")
        is_live_now = bool(live_details.get("isLiveNow") is True) or (vd.get("isLiveContent") is True and '"isLiveNow":true' in html)
        return is_live_now, title, channel_name, url
    except Exception as e:
        print(f"Ошибка проверки videoId (html) {video_id}: {e}")
        return False, None, None, url

# =====================
# Compose post
# =====================
def build_post_text() -> Tuple[str, int]:
    live_items: List[Tuple[str, str]] = []

    # 1) channels
    for display_name, channel_id in sorted(CHANNELS.items(), key=lambda x: x[0].lower()):
        live_url = None
        if YT_API_KEY:
            live_url = get_live_by_channel_api(channel_id)
        if not live_url:
            live_url = get_live_video_url_from_channel_html(channel_id)
        if live_url:
            live_items.append((display_name, live_url))

    # 2) video IDs
    for display_name, video_id in sorted(VIDEO_IDS.items(), key=lambda x: x[0].lower()):
        if YT_API_KEY:
            is_live, title, channel_name, url = get_live_info_by_video_api(video_id)
        else:
            is_live, title, channel_name, url = get_video_live_info_html(video_id)
        if is_live:
            label = display_name
            extra = []
            if channel_name and channel_name not in label:
                extra.append(channel_name)
            if title and title not in label:
                extra.append(title)
            if extra:
                label = f"{label} ({' — '.join(extra)})"
            live_items.append((label, url))

    if not live_items:
        return EMPTY_TEXT, 0

    text = HEADER_TEXT
    for display_name, live_url in live_items:
        text += f"🔴 {display_name}:\n{live_url}\n\n"
    return text.strip(), len(live_items)

# =====================
# Telegram UI / handlers
# =====================
def main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Обновить (в личке)", callback_data="refresh_dm")],
        [InlineKeyboardButton("📣 Обновить пост в канале", callback_data="refresh_channel")],
    ])

async def is_channel_admin(bot, chat_id: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id=chat_id, user_id=user_id)
        return member.status in (ChatMemberStatus.OWNER, ChatMemberStatus.ADMINISTRATOR)
    except TelegramError:
        return False

async def ensure_announcement_message(bot) -> Optional[int]:
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
        print(f"[{time.strftime('%H:%M:%S')}] Обновил пост. В эфире: {active_count}")
    except BadRequest as e:
        s = str(e).lower()
        if "message is not modified" in s:
            return
        if "message to edit not found" in s or "message_id_invalid" in s:
            state = load_state()
            state.pop("announcement_message_id", None)
            save_state(state)
            try:
                msg = await bot.send_message(chat_id=CHAT_ID, text=post_text, disable_web_page_preview=True)
                state["announcement_message_id"] = msg.message_id
                save_state(state)
                print("♻️ Пост был потерян/удалён — создал новый.")
            except TelegramError as te:
                print("❌ Не смог создать новый пост в канале:", te)
            return
        print("BadRequest:", e)
    except TelegramError as e:
        print("TelegramError:", e)

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    post_text, _ = build_post_text()
    await update.message.reply_text(
        text=post_text,
        reply_markup=main_keyboard(),
        disable_web_page_preview=True,
    )

async def update_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_channel_admin(context.bot, CHAT_ID, update.effective_user.id):
        await update.message.reply_text("🚫 Только админы канала могут использовать /update")
        return
    await update.message.reply_text("⏳ Обновляю пост в канале...")
    await update_channel_post(context)
    await update.message.reply_text("✅ Готово.")

async def reset_post_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_channel_admin(context.bot, CHAT_ID, update.effective_user.id):
        await update.message.reply_text("🚫 Только админы канала могут использовать /reset_post")
        return
    state = load_state()
    state.pop("announcement_message_id", None)
    save_state(state)
    await update.message.reply_text("♻️ Сбросил message_id. Следующее обновление создаст новый пост.")

async def on_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.data == "refresh_dm":
        post_text, _ = build_post_text()
        await query.edit_message_text(
            text=post_text,
            reply_markup=main_keyboard(),
            disable_web_page_preview=True,
        )
        return

    if query.data == "refresh_channel":
        user_id = query.from_user.id
        if await is_channel_admin(context.bot, CHAT_ID, user_id):
            await update_channel_post(context)
            post_text, _ = build_post_text()
            await query.edit_message_text(
                text=post_text,
                reply_markup=main_keyboard(),
                disable_web_page_preview=True,
            )
        else:
            post_text, _ = build_post_text()
            await query.edit_message_text(
                text=post_text + "\n\n🚫 Пост в канале может обновлять только админ.",
                reply_markup=main_keyboard(),
                disable_web_page_preview=True,
            )

def main():
    if not BOT_TOKEN:
        print("❌ Нет BOT_TOKEN. Задай переменную окружения BOT_TOKEN в Bothost (Secrets/Env).")
        return

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("update", update_cmd))
    app.add_handler(CommandHandler("reset_post", reset_post_cmd))
    app.add_handler(CallbackQueryHandler(on_buttons, pattern="^(refresh_dm|refresh_channel)$"))

    if app.job_queue is None:
        print("❌ JobQueue недоступен. Установи зависимость: python-telegram-bot[job-queue]==20.8")
        return
    app.job_queue.run_repeating(update_channel_post, interval=POLL_INTERVAL, first=5)

    yt_mode = "API" if YT_API_KEY else "HTML(fallback)"
    print(f"🔴 БОТ ЗАПУЩЕН! Интервал: {POLL_INTERVAL} сек. Канал: {CHAT_ID} | YouTube: {yt_mode}")
    if VIDEO_IDS:
        print(f"🎯 Мониторю videoId: {', '.join(VIDEO_IDS.values())}")
    print(f"📺 Каналов: {len(CHANNELS)} | VideoId: {len(VIDEO_IDS)}")
    app.run_polling()

if __name__ == "__main__":
    main()

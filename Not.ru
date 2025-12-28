import requests
import time
from telegram import Bot

# =====================
# Настройки бота
# =====================
BOT_TOKEN = "8532903616:AAE6Ik1Y33VzwyJc4wDJoQQIRGzmZKoxfg8"        # <- вставь сюда токен
CHAT_ID = "@tupa_vsyo"                       # <- канал или чат для постов
YOUTUBE_API_KEY = "AIzaSyAfNP7l0gKt_o5ySimnto0Ba01675gRwh8"     # <- вставь сюда ключ YouTube

# =====================
# Каналы для отслеживания
# =====================
CHANNELS = {
    "Гусь": "UCOSbywsX9qgHc2No-Z4Z8CQ",
    "Нижняя полка": "UCyt77ruZOLVRztdcP-YQgbA",
    "Селюк": "UCw2d-PgHpthfpHRGX9vpPLQ",
    "Костик Сопляк": "UCz_-kouNzyug_2k0cIE1aig",
    "КамераСиевана": "UCIBiR242nRb3BV4Vf3h-0ZA",
    "Вьетнамские приключения": "UCOHaUXZer0z9soGdgkginag",
    "Бертолет": "UCDxns5jCJ09P4zCe_Kpyblg",
    "Саша Урина": "UCTXx6sWPILhFFGeOcmhPDIQ",
    "Олегон": "UCGyJh69PKkg49a4kJeTGSgQ",
    "Бертолет": "UCDxns5jCJ09P4zCe_Kpyblg"
}

bot = Bot(token=BOT_TOKEN)

# =====================
# Функция для получения последних видео
# =====================
def get_latest_videos(channel_id, max_results=5):
    url = f"https://www.googleapis.com/youtube/v3/search?key={YOUTUBE_API_KEY}&channelId={channel_id}&part=snippet,id&order=date&maxResults={max_results}"
    response = requests.get(url)
    if response.status_code == 200:
        data = response.json()
        videos = []
        for item in data.get("items", []):
            if item["id"]["kind"] == "youtube#video":
                title = item["snippet"]["title"]
                video_id = item["id"]["videoId"]
                url = f"https://youtu.be/{video_id}"
                videos.append(f"{title}: {url}")
        return videos
    else:
        print("Ошибка YouTube API:", response.text)
        return []

# =====================
# Главная функция бота
# =====================
def main():
    last_message_id = None

    while True:
        post_text = "🔥 Новые видео и стримы:\n\n"
        has_streams = False  # проверка, есть ли новые видео/стримы

        for name, channel_id in CHANNELS.items():
            videos = get_latest_videos(channel_id)
            if videos:
                has_streams = True
                post_text += f"🎬 {name}:\n"
                post_text += "\n".join(videos) + "\n\n"

        # Если видео/стримы не найдены
        if not has_streams:
            post_text += "По стримам насрано 😎"

        # Если уже есть старый пост, удаляем его
        if last_message_id:
            try:
                bot.delete_message(chat_id=CHAT_ID, message_id=last_message_id)
            except:
                pass

        # Отправляем новый пост
        message = bot.send_message(chat_id=CHAT_ID, text=post_text)
        last_message_id = message.message_id

        # Ждём 1 час
        time.sleep(3600)

# =====================
if __name__ == "__main__":
    main()

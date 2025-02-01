import os
import logging
import yt_dlp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# ✅ Configure Proxy (Replace with a real working proxy)
# PROXY_URL = "http://44.219.175.186/"

# ✅ yt-dlp options
yt_dlp_opts = {
    "format": "best",
    "quiet": True,
    "no_warnings": True,
    "outtmpl": "%(title)s.%(ext)s",  # Output template for filenames
}

# ✅ Initialize Logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Use `yt-dlp` to download video
def download_video(url, format_id=None):
    try:
        ydl_opts = yt_dlp_opts.copy()
        if format_id:
            ydl_opts["format"] = format_id  # Use the specific format_id for download
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)
            logger.info(f"Downloaded: {info.get('title')}")
            return ydl.prepare_filename(info)  # This should return the actual downloaded file path
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return None

# 🔹 Telegram Bot Handlers
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a YouTube link to download.")

async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    try:
        with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "Unknown Title")
            formats = info.get("formats", [])

        keyboard = []
        for f in formats:
            if f.get("video_ext") != "none" and f.get("audio_ext") != "none":  # Progressive formats
                quality = f"{f.get('format_note', 'Unknown')} ({f.get('ext')})"
                keyboard.append([InlineKeyboardButton(quality, callback_data=f"video_{f.get('format_id')}")])
        keyboard.append([InlineKeyboardButton("MP3 (Audio Only)", callback_data="audio")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Select quality for: {title}", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error fetching YouTube data: {e}")
        await update.message.reply_text("Sorry, something went wrong. Try again later.")

async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    url = query.message.reply_to_message.text

    try:
        if query.data == "audio":
            # Download as MP3
            await query.edit_message_text("Downloading audio... Please wait.")
            file_path = download_video(url)
        else:
            # Download video with specific quality
            format_id = query.data.replace("video_", "")
            await query.edit_message_text("Downloading video... Please wait.")
            file_path = download_video(url, format_id)

        # Send the media file
        if file_path:
            try:
                with open(file_path, "rb") as f:
                    if query.data == "audio":
                        await query.message.reply_audio(audio=f)
                    else:
                        await query.message.reply_video(video=f)
            finally:
                os.remove(file_path)  # Clean up file after sending
    except Exception as e:
        logger.error(f"Error processing YouTube video: {e}")
        await query.edit_message_text("Sorry, something went wrong. Please try again later.")

# 🔹 Run Telegram Bot
def main():
    application = Application.builder().token(os.getenv("TELEGRAM_BOT_TOKEN")).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
    application.add_handler(CallbackQueryHandler(handle_quality_selection))
    application.run_polling()

if __name__ == "__main__":
    main()

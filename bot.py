import os
import logging
from pytube import YouTube
from pydub import AudioSegment
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters

# Replace with your Telegram bot token
TELEGRAM_BOT_TOKEN = "7754682325:AAHXj7BPAjZx1PAzD7adoiq-QZoKBw7U9pQ"

# Enable logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Command: /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Welcome to the YouTube Downloader Bot! 🎥\n\n"
        "Send me a YouTube link, and I'll download it for you in your preferred quality or as MP3."
    )

# Command: Handle YouTube links
async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    if "youtube.com" not in url and "youtu.be" not in url:
        await update.message.reply_text("Please send a valid YouTube link.")
        return

    try:
        yt = YouTube(url)
        title = yt.title
        streams = yt.streams.filter(progressive=True, file_extension="mp4").order_by("resolution").desc()

        # Create a list of available qualities
        keyboard = []
        for stream in streams:
            quality = f"{stream.resolution} ({stream.mime_type})"
            keyboard.append([InlineKeyboardButton(quality, callback_data=f"video_{stream.itag}")])
        keyboard.append([InlineKeyboardButton("MP3 (Audio Only)", callback_data="audio")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Select quality for: {title}", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error fetching YouTube data: {e}")
        await update.message.reply_text("Sorry, something went wrong. Please try again later.")

# Callback: Handle quality selection
async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = query.message.reply_to_message.text
    yt = YouTube(url)
    title = yt.title

    if query.data == "audio":
        # Download as MP3
        await query.edit_message_text("Downloading audio... Please wait.")
        stream = yt.streams.filter(only_audio=True).first()
        file_path = stream.download(filename=f"{title}.mp4")
        mp3_path = f"{title}.mp3"

        # Convert to MP3 using pydub
        audio = AudioSegment.from_file(file_path, format="mp4")
        audio.export(mp3_path, format="mp3")

        # Send the MP3 file
        await query.message.reply_audio(audio=open(mp3_path, "rb"))
        os.remove(file_path)
        os.remove(mp3_path)
    else:
        # Download video
        itag = int(query.data.split("_")[1])
        stream = yt.streams.get_by_itag(itag)
        await query.edit_message_text("Downloading video... Please wait.")
        file_path = stream.download(filename=f"{title}.mp4")

        # Send the video file
        await query.message.reply_video(video=open(file_path, "rb"))
        os.remove(file_path)

# Main function to start the bot
def main():
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
    application.add_handler(CallbackQueryHandler(handle_quality_selection))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()
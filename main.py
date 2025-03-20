import os
import logging
import yt_dlp
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv

import threading
from health import run_health_server
from telegram.ext import ApplicationBuilder

# Start the health check server in a separate thread
health_thread = threading.Thread(target=run_health_server)
health_thread.daemon = True
health_thread.start()


# ✅ Load environment variables from .env file
load_dotenv()  # Make sure to install python-dotenv (pip install python-dotenv)

# ✅ Set up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# ✅ Telegram bot token from environment variable
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Ensure it's set in your environment variables

# ✅ Maximum file size allowed (50 MB)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# ✅ yt-dlp options with maximum timeout
yt_dlp_opts = {
    "quiet": True,  # Suppress output
    "no_warnings": True,  # Suppress warnings
    "format": "best",  # Best quality
    "outtmpl": "%(title)s.%(ext)s",  # Output template for filenames
    "socket_timeout": 300,  # Increase socket timeout to 300 seconds (5 minutes)
    "extract_timeout": 600,  # Increase extraction timeout to 600 seconds (10 minutes)
}

# ✅ Function to download video
async def download_video(url, format_id=None):
    try:
        opts = yt_dlp_opts.copy()
        if format_id:
            opts["format"] = format_id  # Use the selected format ID
        with yt_dlp.YoutubeDL(opts) as ydl:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, ydl.extract_info, url, True)
            return ydl.prepare_filename(info)
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return None

# ✅ Command to start the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a YouTube link to download.")

# ✅ Handle YouTube link message
async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    context.user_data['url'] = url  # Store the URL in user_data for later use
    try:
        with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "Unknown Title")
            formats = info.get("formats", [])

        # Debug: Print all available formats
        logger.info("Available formats:")
        for f in formats:
            logger.info(f"Format ID: {f.get('format_id')}, Ext: {f.get('ext')}, Resolution: {f.get('resolution')}, Note: {f.get('format_note')}")

        # Filter formats to include only MP4, WebM, and MP3
        filtered_formats = []
        for f in formats:
            ext = f.get("ext", "").lower()
            if ext in ["mp4", "webm"]:  # Include video formats
                filtered_formats.append(f)
            elif ext == "mp3":  # Include audio format
                filtered_formats.append(f)

        # Create buttons for filtered formats
        keyboard = []
        for f in filtered_formats:
            format_id = f.get("format_id")
            format_note = f.get("format_note", "Unknown")
            resolution = f.get("resolution", "Unknown")
            ext = f.get("ext", "Unknown")
            button_text = f"{format_note} ({resolution}, {ext})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"format_{format_id}")])

        # Add a button for MP3 (Audio Only) if not already included
        if not any(f.get("ext", "").lower() == "mp3" for f in filtered_formats):
            keyboard.append([InlineKeyboardButton("MP3 (Audio Only)", callback_data="audio")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Select quality for: {title}", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error fetching YouTube data: {e}")
        await update.message.reply_text("Sorry, something went wrong. Try again later.")

# ✅ Handle quality selection callback
async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # Retrieve the URL from user_data
    url = context.user_data.get('url')

    if not url:
        # Send error message if there's no valid URL
        await query.edit_message_text("Error: No valid YouTube URL found!")
        logger.error("No valid YouTube URL found in the user_data.")
        return

    try:
        if query.data == "audio":
            # Download as MP3
            await query.edit_message_text("Downloading audio... Please wait.")
            file_path = await download_video(url, format_id="bestaudio/best")  # Download best audio format

            # Check file size
            if file_path and os.path.getsize(file_path) > MAX_FILE_SIZE:
                await query.edit_message_text("The file is too large to send. Please try a smaller video.")
                os.remove(file_path)
                return

            # Send the MP3 file
            if file_path:
                await query.message.reply_audio(audio=open(file_path, "rb"))
                os.remove(file_path)  # Clean up the file after sending
        else:
            # Download video
            format_id = query.data.replace("format_", "")
            await query.edit_message_text("Downloading video... Please wait.")
            file_path = await download_video(url, format_id=format_id)  # Download selected video format

            # Check file size
            if file_path and os.path.getsize(file_path) > MAX_FILE_SIZE:
                await query.edit_message_text("The file is too large to send. Please try a smaller video.")
                os.remove(file_path)
                return

            # Send the video file
            if file_path:
                await query.message.reply_video(video=open(file_path, "rb"))
                os.remove(file_path)  # Clean up the file after sending
    except Exception as e:
        logger.error(f"Error processing YouTube video: {e}")
        await query.edit_message_text("Sorry, something went wrong. Please try again later.")

# ✅ Main function to start the bot
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

import os
import logging
import yt_dlp
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from dotenv import load_dotenv
import json
from http.server import BaseHTTPRequestHandler

# Load environment variables from .env file
load_dotenv()

# Set up logging
logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

# Telegram bot token from environment variable
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# Maximum file size allowed (50 MB)
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# yt-dlp options with maximum timeout
yt_dlp_opts = {
    "quiet": True,
    "no_warnings": True,
    "format": "best",
    "outtmpl": "%(title)s.%(ext)s",
    "socket_timeout": 300,
    "extract_timeout": 600,
}

# Function to download video
async def download_video(url, format_id=None):
    try:
        opts = yt_dlp_opts.copy()
        if format_id:
            opts["format"] = format_id
        with yt_dlp.YoutubeDL(opts) as ydl:
            loop = asyncio.get_event_loop()
            info = await loop.run_in_executor(None, ydl.extract_info, url, True)
            return ydl.prepare_filename(info)
    except Exception as e:
        logger.error(f"Error downloading video: {e}")
        return None

# Command to start the bot
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Send me a YouTube link to download.")

# Handle YouTube link message
async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text
    context.user_data['url'] = url
    try:
        with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            title = info.get("title", "Unknown Title")
            formats = info.get("formats", [])

        filtered_formats = [f for f in formats if f.get("ext", "").lower() in ["mp4", "webm", "mp3"]]

        keyboard = []
        for f in filtered_formats:
            format_id = f.get("format_id")
            format_note = f.get("format_note", "Unknown")
            resolution = f.get("resolution", "Unknown")
            ext = f.get("ext", "Unknown")
            button_text = f"{format_note} ({resolution}, {ext})"
            keyboard.append([InlineKeyboardButton(button_text, callback_data=f"format_{format_id}")])

        if not any(f.get("ext", "").lower() == "mp3" for f in filtered_formats):
            keyboard.append([InlineKeyboardButton("MP3 (Audio Only)", callback_data="audio")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(f"Select quality for: {title}", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error fetching YouTube data: {e}")
        await update.message.reply_text("Sorry, something went wrong. Try again later.")

# Handle quality selection callback
async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    url = context.user_data.get('url')

    if not url:
        await query.edit_message_text("Error: No valid YouTube URL found!")
        logger.error("No valid YouTube URL found in the user_data.")
        return

    try:
        if query.data == "audio":
            await query.edit_message_text("Downloading audio... Please wait.")
            file_path = await download_video(url, format_id="bestaudio/best")
        else:
            format_id = query.data.replace("format_", "")
            await query.edit_message_text("Downloading video... Please wait.")
            file_path = await download_video(url, format_id=format_id)

        if file_path and os.path.getsize(file_path) > MAX_FILE_SIZE:
            await query.edit_message_text("The file is too large to send. Please try a smaller video.")
            os.remove(file_path)
            return

        if file_path:
            if query.data == "audio":
                await query.message.reply_audio(audio=open(file_path, "rb"))
            else:
                await query.message.reply_video(video=open(file_path, "rb"))
            os.remove(file_path)
    except Exception as e:
        logger.error(f"Error processing YouTube video: {e}")
        await query.edit_message_text("Sorry, something went wrong. Please try again later.")

# Initialize the bot
app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

# Add handlers
app.add_handler(CommandHandler("start", start))
app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
app.add_handler(CallbackQueryHandler(handle_quality_selection))

# Vercel handler
class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        content_length = int(self.headers['Content-Length'])
        post_data = self.rfile.read(content_length)
        
        try:
            body = json.loads(post_data.decode('utf-8'))
            update = Update.de_json(body, app.bot)
            
            async def process_update():
                await app.process_update(update)

            asyncio.run(process_update())
            
            self.send_response(200)
            self.end_headers()
            self.wfile.write("OK".encode('utf-8'))
        except Exception as e:
            logger.error(f"Error processing update: {e}")
            self.send_response(500)
            self.end_headers()
            self.wfile.write(str(e).encode('utf-8'))

    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write("Bot is running".encode('utf-8'))


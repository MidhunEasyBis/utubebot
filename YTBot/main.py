import os
import math
import logging
import yt_dlp
import asyncio
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters
)
from datetime import datetime, timedelta
from collections import defaultdict
import threading
from dotenv import load_dotenv

# Health check server (keep this first)
from health import run_health_server
health_thread = threading.Thread(target=run_health_server)
health_thread.daemon = True
health_thread.start()

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
MAX_VIDEO_DURATION = 7200  # 2 hours in seconds
RATE_LIMIT = timedelta(seconds=30)

# Get the absolute path to cookies.txt
COOKIES_PATH = os.path.abspath("cookies.txt")

# Rate limiting storage
user_last_request = defaultdict(lambda: datetime.min)

async def rate_limit_check(user_id: int) -> bool:
    """Check if user is within rate limit"""
    key = str(user_id)
    if user_last_request[key] + RATE_LIMIT > datetime.now():
        return False
    user_last_request[key] = datetime.now()
    return True

# yt-dlp configuration
yt_dlp_opts = {
    "quiet": True,
    "no_warnings": True,
    "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
    "merge_output_format": "mp4",
    "outtmpl": "%(title)s.%(ext)s",
    "socket_timeout": 300,
    "extract_timeout": 600,
    "cookiefile": COOKIES_PATH,
    "noplaylist": True,
    "ignoreerrors": True,
    "retries": 3,
    "postprocessors": [],
}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    await update.message.reply_text(
        "🎬 Welcome to YouTube Downloader Pro!\n"
        "Send me a YouTube link to get started."
    )

def make_progress_hook(context, chat_id, message_id, use_caption=False):
    """Create a progress hook with rate limiting and proper async handling"""
    last_update = 0

    def progress_hook(d):
        nonlocal last_update
        try:
            if d['status'] == 'downloading':
                current_time = time.time()
                if current_time - last_update < 1.0:  # Throttle to 1 update/sec
                    return
                last_update = current_time

                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
                percent = downloaded / total * 100
                blocks = math.floor(percent / 5)
                progress_bar = f"[{'█' * blocks}{' ' * (20 - blocks)}] {percent:.1f}%"

                # Prepare the coroutine for updating the message
                if use_caption:
                    coro = context.bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_id,
                        caption=f"⏳ Downloading...\n{progress_bar}"
                    )
                else:
                    coro = context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"⏳ Downloading...\n{progress_bar}"
                    )

                # Schedule the coroutine in the event loop
                loop = asyncio.get_event_loop()
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                future.result(timeout=5)  # Wait for the coroutine to complete

            elif d['status'] == 'finished':
                # Prepare the coroutine for the final message
                if use_caption:
                    coro = context.bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_id,
                        caption="✅ Processing complete! Uploading file..."
                    )
                else:
                    coro = context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text="✅ Processing complete! Uploading file..."
                    )

                # Schedule the coroutine in the event loop
                loop = asyncio.get_event_loop()
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                future.result(timeout=5)  # Wait for the coroutine to complete

        except Exception as e:
            logger.error(f"Progress hook error: {e}")

    return progress_hook

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler"""
    user_id = update.effective_user.id
    if not await rate_limit_check(user_id):
        await update.message.reply_text(f"⏳ Please wait {RATE_LIMIT.seconds} seconds between requests")
        return

    url = update.message.text
    try:
        with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if info.get("is_live"):
                raise ValueError("📡 Live streams are not supported")
            if info.get("duration", 0) > MAX_VIDEO_DURATION:
                raise ValueError(f"⏳ Videos longer than {MAX_VIDEO_DURATION//3600} hours are not supported")

            # Create format selector
            formats = info.get("formats", [])
            # Filter for formats with both video and audio
            video_formats = [f for f in formats if f.get("video_ext") != "none" and f.get("acodec") != "none"]
            # Sort the formats by video height (resolution) in descending order
            video_formats = sorted(video_formats, key=lambda f: f.get('height', 0), reverse=True)
            # Select the top 3 video formats
            selected_video_formats = video_formats[:3]

            keyboard = []
            for f in selected_video_formats:
                format_id = f["format_id"]
                quality = f.get("format_note", "Unknown")
                ext = f.get("ext", "?")
                keyboard.append([InlineKeyboardButton(f"🎥 {quality} ({ext})", callback_data=f"format_{format_id}")])

            # Add a single audio option
            keyboard.append([InlineKeyboardButton("🎵 MP3 Audio", callback_data="audio")])


            # Get the highest quality thumbnail available
            thumbnails = info.get("thumbnails", [])
            thumb = next(
                (t for t in reversed(thumbnails) if t.get("url")),
                None
            ) if thumbnails else None

            caption = f"📽 {info.get('title', 'Untitled')}\nSelect quality:"

            if thumb:
                await update.message.reply_photo(
                    photo=thumb["url"],
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard))
            else:
                await update.message.reply_text(
                    caption,
                    reply_markup=InlineKeyboardMarkup(keyboard))

            # Store URL in user data for callback processing
            context.user_data["url"] = url

    except Exception as e:
        logger.error(f"Error: {e}")
        await update.message.reply_text(f"❌ Error: {e}")
        

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks with improved error handling"""
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get("url")
    media_type = query.data
    
    if not url:
        await query.edit_message_text("❌ Session expired. Please send a new link")
        return

    context.user_data["media_type"] = media_type

    # Determine message type and setup initial response
    use_caption = bool(query.message.caption)
    try:
        if use_caption:
            progress_msg = await query.edit_message_caption("⏳ Starting download...")
        else:
            progress_msg = await query.edit_message_text("⏳ Starting download...")
    except Exception as e:
        logger.error(f"Message edit failed: {e}")
        return

    # Configure yt-dlp options
    opts = yt_dlp_opts.copy()
    opts["progress_hooks"] = [make_progress_hook(context, query.message.chat_id, progress_msg.message_id, use_caption)]
    
    if media_type == "audio":
        opts.update({
            "format": "bestaudio/best",
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",
            }],
        })
    elif media_type.startswith("format_"):
        opts["format"] = media_type.split("_", 1)[1]

    filename = None
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Trigger download with progress hooks
            await loop.run_in_executor(None, ydl.download, [url])
            
            # Get final filename
            info = await loop.run_in_executor(None, ydl.extract_info, url, False)
            filename = ydl.prepare_filename(info)

            if os.path.getsize(filename) > MAX_FILE_SIZE:
                raise ValueError("📁 File size exceeds Telegram limits")

            # Send the file
            if media_type == "audio":
                with open(filename, "rb") as f:
                    await context.bot.send_audio(
                        chat_id=query.message.chat_id,
                        audio=f,
                        title=info.get('title', 'audio_file'),
                        read_timeout=30,
                        write_timeout=30
                    )
            else:
                with open(filename, "rb") as f:
                    await context.bot.send_video(
                        chat_id=query.message.chat_id,
                        video=f,
                        supports_streaming=True,
                        read_timeout=30,
                        write_timeout=30
                    )

            # Final success message
            if use_caption:
                await query.edit_message_caption("✅ Successfully sent!")
            else:
                await query.edit_message_text("✅ Successfully sent!")

    except Exception as e:
        logger.error(f"Download failed: {e}")
        error_msg = f"❌ Error: {str(e)[:200]}"
        if use_caption:
            await query.edit_message_caption(error_msg)
        else:
            await query.edit_message_text(error_msg)
    finally:
        if filename and os.path.exists(filename):
            try:
                os.remove(filename)
            except Exception as e:
                logger.error(f"File cleanup failed: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = (
        "🌟 YouTube Downloader Pro Help 🌟\n\n"
        "• Send any YouTube link to download\n"
        "• Choose video quality or MP3 audio\n"
        "• Max video length: 2 hours\n"
        "• Supported formats: MP4, WebM, MP3\n\n"
        "Commands:\n"
        "/help - Show this help\n"
        "/stats - Show usage statistics"
    )
    await update.message.reply_text(help_text)

def main():
    """Start the bot"""
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_handler(CallbackQueryHandler(handle_callback))

    application.run_polling()

if __name__ == "__main__":
    main()

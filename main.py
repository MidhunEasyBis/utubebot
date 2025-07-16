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

# Rate limiting storage
user_last_request = defaultdict(lambda: datetime.min)

async def rate_limit_check(user_id: int) -> bool:
    """Check if user is within rate limit"""
    key = str(user_id)
    if user_last_request[key] + RATE_LIMIT > datetime.now():
        return False
    user_last_request[key] = datetime.now()
    return True

# Base yt-dlp configuration for downloads.
# We deliberately leave out the "format" key when extracting info.
base_yt_dlp_opts = {
    "quiet": True,
    "no_warnings": True,
    "merge_output_format": "mp4",
    "outtmpl": "%(title)s.%(ext)s",
    "socket_timeout": 300,
    "extract_timeout": 600,
    "cookiefile": "cookies.txt",
    # Removed ignoreerrors to catch exceptions explicitly
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
    """Create a progress hook with proper async handling"""
    last_update = 0

    def progress_hook(d):
        nonlocal last_update
        try:
            if d['status'] == 'downloading':
                current_time = time.time()
                if current_time - last_update < 1.0:  # Throttle updates to once per second
                    return
                last_update = current_time

                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
                percent = downloaded / total * 100
                blocks = math.floor(percent / 5)
                progress_bar = f"[{'█' * blocks}{' ' * (20 - blocks)}] {percent:.1f}%"

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

                loop = asyncio.get_event_loop()
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                future.result(timeout=5)

            elif d['status'] == 'finished':
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
                loop = asyncio.get_event_loop()
                future = asyncio.run_coroutine_threadsafe(coro, loop)
                future.result(timeout=5)

        except Exception as e:
            logger.error(f"Progress hook error: {e}")

    return progress_hook

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler for incoming video URLs"""
    user_id = update.effective_user.id
    if not await rate_limit_check(user_id):
        await update.message.reply_text(f"⏳ Please wait {RATE_LIMIT.seconds} seconds between requests")
        return

    # In handle_message
    try:
        url = update.message.text.strip()

        # Super minimal options JUST for info extraction
        info_opts = {
            "quiet": True,
            "no_warnings": True,
            "cookiefile": "cookies.txt",
            "socket_timeout": 30,
            "extract_flat": False,  # important
            "force_generic_extractor": False,
            "verbose": True,
            "logger": logger,
            # NO "format" key here
        }

        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("❌ Unable to extract video information. Please check the URL.")
            if info.get("is_live"):
                raise ValueError("📡 Live streams are not supported")
            if info.get("duration", 0) > MAX_VIDEO_DURATION:
                raise ValueError(f"⏳ Videos longer than {MAX_VIDEO_DURATION // 3600} hours are not supported")

            # Get available formats: filter for video+audio.
            formats = info.get("formats", [])
            video_formats = [f for f in formats if f.get("vcodec") != "none" and f.get("acodec") != "none"]
            if not video_formats:
                raise ValueError("❌ No suitable video formats found.")
            video_formats = sorted(video_formats, key=lambda f: f.get('height', 0), reverse=True)
            selected_video_formats = video_formats[:3]

            keyboard = []
            for f in selected_video_formats:
                format_id = f["format_id"]
                quality = f.get("format_note", f"{f.get('height', 'Unknown')}p")
                ext = f.get("ext", "?")
                keyboard.append([InlineKeyboardButton(f"🎥 {quality} ({ext})", callback_data=f"format_{format_id}")])

            # Add a single audio option
            keyboard.append([InlineKeyboardButton("🎵 MP3 Audio", callback_data="audio")])

            # Grab the highest quality thumbnail if available
            thumbnails = info.get("thumbnails", [])
            thumb = next((t for t in reversed(thumbnails) if t.get("url")), None)
            caption = f"📽 {info.get('title', 'Untitled')}\nSelect quality:"

            if thumb:
                await update.message.reply_photo(
                    photo=thumb["url"],
                    caption=caption,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await update.message.reply_text(
                    caption,
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            # Save URL and info for later callback usage.
            context.user_data["url"] = url
            context.user_data["info"] = info

    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await update.message.reply_text(f"❌ Error: {e}")

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks with improved error handling and fresh extraction"""
    query = update.callback_query
    await query.answer()
    
    url = context.user_data.get("url")
    if not url:
        await query.edit_message_text("❌ Session expired. Please send a new link")
        return

    media_type = query.data
    context.user_data["media_type"] = media_type
    use_caption = bool(query.message.caption)
    try:
        if use_caption:
            progress_msg = await query.edit_message_caption("⏳ Starting download...")
        else:
            progress_msg = await query.edit_message_text("⏳ Starting download...")
    except Exception as e:
        logger.error(f"Message edit failed: {e}")
        return

    # Prepare download options. Now we add format selection based on the callback.
    opts = base_yt_dlp_opts.copy()
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
        # Set the chosen format explicitly.
        opts["format"] = media_type.split("_", 1)[1]

    filename = None
    try:
        loop = asyncio.get_event_loop()
        with yt_dlp.YoutubeDL(opts) as ydl:
            # Kick off the download in a separate thread.
            await loop.run_in_executor(None, ydl.download, [url])
            # Try using the cached info; if it's missing, re-extract.
            info = context.user_data.get("info")
            if not info:
                info = ydl.extract_info(url, download=False)
            filename = ydl.prepare_filename(info)

            if os.path.getsize(filename) > MAX_FILE_SIZE:
                raise ValueError("📁 File size exceeds Telegram limits")

            # Send the file based on media type.
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

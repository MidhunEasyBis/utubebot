import os
import math
import logging
import yt_dlp
import asyncio
import time
import tempfile
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
import re
import random
import string
from typing import Dict, List, Optional

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
TEMP_DIR = "temp_downloads"
SUPPORTED_SITES = ["youtube", "youtu.be", "vimeo", "dailymotion", "tiktok"]

# Create temp directory if not exists
os.makedirs(TEMP_DIR, exist_ok=True)

# Rate limiting storage
user_last_request = defaultdict(lambda: datetime.min)
user_stats = defaultdict(lambda: {"downloads": 0, "last_download": None})

# Base yt-dlp configuration for downloads
base_yt_dlp_opts = {
    "quiet": True,
    "no_warnings": True,
    "merge_output_format": "mp4",
    "outtmpl": os.path.join(TEMP_DIR, "%(title)s.%(ext)s"),
    "socket_timeout": 300,
    "extract_timeout": 600,
    "cookiefile": "cookies.txt",
    "retries": 3,
    "postprocessors": [],
    "noplaylist": True,
}

def generate_random_string(length=8):
    """Generate a random string for temp filenames"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

async def rate_limit_check(user_id: int) -> bool:
    """Check if user is within rate limit"""
    key = str(user_id)
    if user_last_request[key] + RATE_LIMIT > datetime.now():
        return False
    user_last_request[key] = datetime.now()
    return True

def update_user_stats(user_id: int):
    """Update user download statistics"""
    user_stats[str(user_id)]["downloads"] += 1
    user_stats[str(user_id)]["last_download"] = datetime.now()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    user = update.effective_user
    welcome_msg = (
        f"🎬 <b>Welcome to YouTube Downloader Pro, {user.first_name}!</b>\n\n"
        "🔹 <i>Send me a link from YouTube, Vimeo, Dailymotion, or TikTok</i>\n"
        "🔹 <i>I can download videos or extract audio</i>\n\n"
        "📌 <b>Features:</b>\n"
        "• Multiple quality options\n"
        "• MP3 audio extraction\n"
        "• Fast downloads\n"
        "• 2 hour limit (Telegram restriction)\n\n"
        "Type /help for more info!"
    )
    
    await update.message.reply_text(
        welcome_msg,
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Help", callback_data="help_button")]
        ])
    )

def make_progress_hook(context, chat_id, message_id, use_caption=False):
    """Create a progress hook with proper async handling"""
    last_update = 0
    last_percent = 0

    def progress_hook(d):
        nonlocal last_update, last_percent
        try:
            if d['status'] == 'downloading':
                current_time = time.time()
                current_percent = (d.get('downloaded_bytes', 0) / (d.get('total_bytes') or d.get('total_bytes_estimate', 1)) * 100)
                
                # Only update if significant change (5%) or 1 second passed
                if current_time - last_update < 1.0 and abs(current_percent - last_percent) < 5:
                    return
                
                last_update = current_time
                last_percent = current_percent

                downloaded = d.get('downloaded_bytes', 0)
                total = d.get('total_bytes') or d.get('total_bytes_estimate', 1)
                percent = downloaded / total * 100
                blocks = math.floor(percent / 5)
                progress_bar = f"[{'█' * blocks}{'░' * (20 - blocks)}] {percent:.1f}%"
                
                # Add download speed and ETA if available
                speed = d.get('speed')
                eta = d.get('eta')
                speed_info = ""
                if speed and eta:
                    speed_mb = speed / (1024 * 1024)
                    eta_str = str(timedelta(seconds=eta))
                    speed_info = f"\n🚀 {speed_mb:.1f} MB/s | ⏳ {eta_str}"

                if use_caption:
                    coro = context.bot.edit_message_caption(
                        chat_id=chat_id,
                        message_id=message_id,
                        caption=f"⏳ Downloading...\n{progress_bar}{speed_info}"
                    )
                else:
                    coro = context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=message_id,
                        text=f"⏳ Downloading...\n{progress_bar}{speed_info}"
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

def is_supported_url(url: str) -> bool:
    """Check if URL is from a supported site"""
    return any(site in url.lower() for site in SUPPORTED_SITES)

def format_duration(seconds: int) -> str:
    """Format duration in seconds to HH:MM:SS"""
    return str(timedelta(seconds=seconds))

def format_size(bytes: int) -> str:
    """Format file size in human-readable format"""
    if bytes == 0:
        return "0B"
    size_name = ("B", "KB", "MB", "GB", "TB")
    i = int(math.floor(math.log(bytes, 1024)))
    p = math.pow(1024, i)
    s = round(bytes / p, 2)
    return f"{s} {size_name[i]}"

def get_video_info_markdown(info: Dict) -> str:
    """Generate formatted video info in Markdown"""
    title = info.get('title', 'Unknown Title')
    duration = format_duration(info.get('duration', 0))
    uploader = info.get('uploader', 'Unknown Uploader')
    view_count = info.get('view_count', 0)
    like_count = info.get('like_count', 0)
    
    return (
        f"📌 *{title}*\n\n"
        f"⏱ *Duration:* {duration}\n"
        f"👤 *Uploader:* {uploader}\n"
        f"👀 *Views:* {view_count:,}\n"
        f"👍 *Likes:* {like_count:,}\n\n"
        "⬇️ *Select download option:*"
    )

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main message handler for incoming video URLs"""
    user_id = update.effective_user.id
    if not await rate_limit_check(user_id):
        await update.message.reply_text(
            f"⏳ Please wait {RATE_LIMIT.seconds} seconds between requests",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆘 Help", callback_data="help_button")]
            ])
        )
        return

    url = update.message.text.strip()
    
    # Validate URL
    if not re.match(r'^https?://', url, re.IGNORECASE):
        await update.message.reply_text(
            "❌ Please send a valid URL starting with http:// or https://",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆘 Help", callback_data="help_button")]
            ])
        )
        return
    
    if not is_supported_url(url):
        await update.message.reply_text(
            "❌ Unsupported website. I support:\n"
            "- YouTube\n- Vimeo\n- Dailymotion\n- TikTok\n\n"
            "Please try with a supported link.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆘 Help", callback_data="help_button")]
            ])
        )
        return

    # Send initial processing message
    processing_msg = await update.message.reply_text(
        "🔍 Processing your link...",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data="cancel_download")]
        ])
    )

    try:
        # Minimal options for info extraction
        info_opts = {
            "quiet": True,
            "no_warnings": True,
            "cookiefile": "cookies.txt",
            "socket_timeout": 30,
            "extract_flat": False,
            "force_generic_extractor": False,
            "verbose": True,
            "logger": logger,
        }

        with yt_dlp.YoutubeDL(info_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            if not info:
                raise ValueError("❌ Unable to extract video information. Please check the URL.")
            
            # Check for playlists
            if info.get('_type') == 'playlist':
                await processing_msg.edit_text(
                    "🎵 Playlist detected! How would you like to proceed?",
                    reply_markup=InlineKeyboardMarkup([
                        [
                            InlineKeyboardButton("📼 Download All", callback_data="playlist_all"),
                            InlineKeyboardButton("🎬 Select Videos", callback_data="playlist_select")
                        ],
                        [InlineKeyboardButton("❌ Cancel", callback_data="cancel_download")]
                    ])
                )
                context.user_data["playlist_info"] = info
                context.user_data["url"] = url
                return
            
            # Single video checks
            if info.get("is_live"):
                raise ValueError("📡 Live streams are not supported")
            
            duration = info.get("duration", 0)
            if duration > MAX_VIDEO_DURATION:
                raise ValueError(
                    f"⏳ Videos longer than {MAX_VIDEO_DURATION//3600} hours are not supported "
                    f"(your video: {format_duration(duration)})"
                )

            # Get available formats
            formats = info.get("formats", [])
            video_formats = [f for f in formats if f.get("vcodec") != "none" and f.get("acodec") != "none"]
            if not video_formats:
                raise ValueError("❌ No suitable video formats found.")
            
            # Sort formats by resolution and select top 3
            video_formats = sorted(
                video_formats,
                key=lambda f: (f.get('height', 0), f.get('width', 0), f.get('tbr', 0)),
                reverse=True
            )
            selected_video_formats = video_formats[:3]

            # Prepare quality buttons
            keyboard = []
            for f in selected_video_formats:
                format_id = f["format_id"]
                quality = f.get("format_note", f"{f.get('height', 'Unknown')}p")
                ext = f.get("ext", "?")
                filesize = format_size(f.get('filesize', 0))
                keyboard.append([
                    InlineKeyboardButton(
                        f"🎥 {quality} ({ext.upper()}, ~{filesize})", 
                        callback_data=f"format_{format_id}"
                    )
                ])

            # Audio options
            keyboard.append([
                InlineKeyboardButton("🎵 MP3 Audio (128kbps)", callback_data="audio_128"),
                InlineKeyboardButton("🎵 MP3 Audio (320kbps)", callback_data="audio_320")
            ])

            # Get best thumbnail
            thumbnails = info.get("thumbnails", [])
            thumb = next((t for t in reversed(thumbnails) if t.get("url")), None)
            
            # Format video info
            caption = get_video_info_markdown(info)

            # Edit the processing message with the options
            if thumb:
                await processing_msg.delete()  # Delete the processing message
                await update.message.reply_photo(
                    photo=thumb["url"],
                    caption=caption,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await processing_msg.edit_text(
                    caption,
                    parse_mode="Markdown",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            
            # Save URL and info for callback
            context.user_data["url"] = url
            context.user_data["info"] = info

    except yt_dlp.utils.DownloadError as e:
        logger.error(f"Download error: {e}")
        await processing_msg.edit_text(
            f"❌ Download error: {str(e)[:200]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆘 Help", callback_data="help_button")]
            ])
        )
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await processing_msg.edit_text(
            f"❌ Error: {str(e)[:200]}",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🆘 Help", callback_data="help_button")]
            ])
        )

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle button callbacks with improved error handling and responsiveness"""
    query = update.callback_query
    
    try:
        # Immediately acknowledge the callback with visual feedback
        await query.answer("⏳ Processing your request...")
        
        # Handle cancel action
        if query.data == "cancel_download":
            await query.edit_message_text("❌ Download canceled")
            return
        
        # Handle help button
        if query.data == "help_button":
            await help_command(query, context)
            return
        
        # Handle playlist options
        if query.data in ["playlist_all", "playlist_select"]:
            await handle_playlist_option(query, context)
            return
        
        # Verify we have required data
        url = context.user_data.get("url")
        if not url:
            await query.edit_message_text("❌ Session expired. Please send a new link")
            return

        media_type = query.data
        context.user_data["media_type"] = media_type
        use_caption = bool(query.message.caption)
        
        # Show processing message
        try:
            if use_caption:
                progress_msg = await query.edit_message_caption(
                    "⏳ Starting download...",
                    reply_markup=None
                )
            else:
                progress_msg = await query.edit_message_text(
                    "⏳ Starting download...",
                    reply_markup=None
                )
        except Exception as e:
            logger.error(f"Message edit failed: {e}")
            return

        # Generate random string for filename
        random_str = generate_random_string()
        
        # Prepare download options
        opts = base_yt_dlp_opts.copy()
        opts["progress_hooks"] = [make_progress_hook(context, query.message.chat_id, progress_msg.message_id, use_caption)]
        
        # Set format based on selection
        if media_type.startswith("audio_"):
            quality = media_type.split("_")[1]
            opts.update({
                "format": "bestaudio/best",
                "postprocessors": [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": quality,
                }],
            })
        elif media_type.startswith("format_"):
            opts["format"] = media_type.split("_", 1)[1]

        # Create a temporary directory for this download
        with tempfile.TemporaryDirectory(prefix="ytdl_") as temp_dir:
            # Update options with temp directory
            temp_opts = opts.copy()
            temp_opts["outtmpl"] = os.path.join(temp_dir, f"%(title)s_{random_str}.%(ext)s")
            
            try:
                with yt_dlp.YoutubeDL(temp_opts) as ydl:
                    # Download the file in a separate thread
                    def download():
                        try:
                            ydl.download([url])
                        except Exception as e:
                            logger.error(f"Download thread error: {e}")
                            raise

                    await asyncio.get_event_loop().run_in_executor(None, download)
                    
                    # Get the actual filename
                    info = context.user_data.get("info") or ydl.extract_info(url, download=False)
                    filename = ydl.prepare_filename(info)
                    
                    # Verify file exists and has content
                    if not os.path.exists(filename):
                        raise FileNotFoundError(f"Downloaded file not found at {filename}")
                    
                    file_size = os.path.getsize(filename)
                    if file_size == 0:
                        raise ValueError("Downloaded file is empty (0 bytes)")
                    
                    if file_size > MAX_FILE_SIZE:
                        raise ValueError(f"📁 File size ({format_size(file_size)}) exceeds Telegram limit ({format_size(MAX_FILE_SIZE)})")

                    # Update user stats
                    update_user_stats(query.from_user.id)

                    # Send the file with progress updates
                    try:
                        if media_type.startswith("audio_"):
                            with open(filename, "rb") as f:
                                await context.bot.send_audio(
                                    chat_id=query.message.chat_id,
                                    audio=f,
                                    title=info.get('title', 'audio_file'),
                                    performer=info.get('uploader', ''),
                                    duration=info.get('duration'),
                                    read_timeout=120,
                                    write_timeout=120
                                )
                        else:
                            with open(filename, "rb") as f:
                                await context.bot.send_video(
                                    chat_id=query.message.chat_id,
                                    video=f,
                                    supports_streaming=True,
                                    duration=info.get('duration'),
                                    width=info.get('width'),
                                    height=info.get('height'),
                                    caption=f"🎬 {info.get('title', 'video_file')}",
                                    read_timeout=120,
                                    write_timeout=120
                                )

                        if use_caption:
                            await query.edit_message_caption("✅ Download complete!")
                        else:
                            await query.edit_message_text("✅ Download complete!")

                    except Exception as upload_error:
                        logger.error(f"File upload failed: {upload_error}")
                        raise ValueError("Failed to upload file to Telegram")

            except FileNotFoundError as e:
                logger.error(f"File not found error: {e}")
                error_msg = "❌ Error: The downloaded file could not be found. Please try again."
                if use_caption:
                    await query.edit_message_caption(error_msg)
                else:
                    await query.edit_message_text(error_msg)
            except yt_dlp.utils.DownloadError as e:
                logger.error(f"Download error: {e}")
                error_msg = f"❌ Download failed: {str(e)[:200]}"
                if use_caption:
                    await query.edit_message_caption(error_msg)
                else:
                    await query.edit_message_text(error_msg)
            except Exception as e:
                logger.error(f"Unexpected error: {e}", exc_info=True)
                error_msg = f"❌ Error: {str(e)[:200]}"
                if use_caption:
                    await query.edit_message_caption(error_msg)
                else:
                    await query.edit_message_text(error_msg)
            finally:
                # Clean up downloaded file if it exists
                if 'filename' in locals() and os.path.exists(filename):
                    try:
                        os.remove(filename)
                    except Exception as e:
                        logger.error(f"Error cleaning up file: {e}")

    except Exception as e:
        logger.error(f"Callback handler error: {e}", exc_info=True)
        try:
            await query.edit_message_text("❌ An unexpected error occurred. Please try again.")
        except:
            pass
            
async def handle_playlist_option(query, context):
    """Handle playlist download options"""
    playlist_info = context.user_data.get("playlist_info")
    if not playlist_info:
        await query.edit_message_text("❌ Playlist info not found")
        return
    
    if query.data == "playlist_all":
        # Implement playlist download logic here
        await query.edit_message_text("⏳ This feature is coming soon!")
    else:
        # Implement playlist selection logic here
        await query.edit_message_text("⏳ This feature is coming soon!")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command or help button"""
    help_text = (
        "🌟 <b>YouTube Downloader Pro Help</b> 🌟\n\n"
        "<b>How to use:</b>\n"
        "1. Send me a link from YouTube, Vimeo, Dailymotion, or TikTok\n"
        "2. Select your preferred quality or audio format\n"
        "3. Wait for the download to complete\n\n"
        "<b>Features:</b>\n"
        "• Multiple video quality options\n"
        "• High-quality MP3 audio extraction\n"
        "• Fast downloads with progress tracking\n"
        "• Support for playlists (coming soon)\n\n"
        "<b>Limitations:</b>\n"
        "• Max video length: 2 hours\n"
        "• Max file size: 50MB (Telegram limit)\n"
        "• Rate limit: 1 request every 30 seconds\n\n"
        "<b>Commands:</b>\n"
        "/start - Show welcome message\n"
        "/help - Show this help\n"
        "/stats - Show your download statistics"
    )
    
    if isinstance(update, Update):
        await update.message.reply_text(help_text, parse_mode="HTML")
    else:  # CallbackQuery
        await update.edit_message_text(help_text, parse_mode="HTML")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user download statistics"""
    user_id = str(update.effective_user.id)
    stats = user_stats.get(user_id, {"downloads": 0, "last_download": None})
    
    last_download = "Never" if not stats["last_download"] else stats["last_download"].strftime("%Y-%m-%d %H:%M:%S")
    
    stats_text = (
        f"📊 <b>Your Download Statistics</b>\n\n"
        f"📥 Total downloads: <b>{stats['downloads']}</b>\n"
        f"⏳ Last download: <b>{last_download}</b>\n\n"
        f"🔄 Rate limit: 1 request every {RATE_LIMIT.seconds} seconds"
    )
    
    await update.message.reply_text(stats_text, parse_mode="HTML")

async def cleanup_temp_files():
    """Clean up temporary files older than 1 hour"""
    while True:
        try:
            now = time.time()
            for filename in os.listdir(TEMP_DIR):
                filepath = os.path.join(TEMP_DIR, filename)
                if os.path.isfile(filepath):
                    file_age = now - os.path.getmtime(filepath)
                    if file_age > 3600:  # 1 hour
                        try:
                            os.remove(filepath)
                            logger.info(f"Cleaned up temp file: {filename}")
                        except Exception as e:
                            logger.error(f"Error cleaning up {filename}: {e}")
        except Exception as e:
            logger.error(f"Error in cleanup_temp_files: {e}")
        
        await asyncio.sleep(3600)  # Run once per hour

def main():
    """Start the bot"""
    # Start the temp file cleanup task
    asyncio.get_event_loop().create_task(cleanup_temp_files())

    application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

    # Command handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    
    # Message handlers
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    # Callback handlers
    application.add_handler(CallbackQueryHandler(handle_callback))

    # Start the bot
    application.run_polling()

if __name__ == "__main__":
    main()

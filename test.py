# import os
# import logging
# import yt_dlp
# import asyncio
# from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
# from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
# from dotenv import load_dotenv

# import threading
# from health import run_health_server
# from telegram.ext import ApplicationBuilder

# # Start the health check server in a separate thread
# health_thread = threading.Thread(target=run_health_server)
# health_thread.daemon = True
# health_thread.start()

# # ✅ Load environment variables from .env file
# load_dotenv()  # Make sure to install python-dotenv (pip install python-dotenv)

# # ✅ Set up logging
# logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
# logger = logging.getLogger(__name__)

# # ✅ Telegram bot token from environment variable
# TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")  # Ensure it's set in your environment variables

# # ✅ Maximum file size allowed (50 MB)
# MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# # ✅ yt-dlp options with cookie support
# yt_dlp_opts = {
#     "quiet": True,  # Suppress output
#     "no_warnings": True,  # Suppress warnings
#     "format": "best",  # Best quality
#     "outtmpl": "%(title)s.%(ext)s",  # Output template for filenames
#     "socket_timeout": 300,  # Increase socket timeout to 300 seconds (5 minutes)
#     "extract_timeout": 600,  # Increase extraction timeout to 600 seconds (10 minutes)
#     "cookiefile": "cookies.txt",  # 👈 Use cookies.txt for authentication
# }

# # ✅ Function to download video
# async def download_video(url, format_id=None):
#     try:
#         opts = yt_dlp_opts.copy()
#         if format_id:
#             opts["format"] = format_id  # Use the selected format ID
#         with yt_dlp.YoutubeDL(opts) as ydl:
#             loop = asyncio.get_event_loop()
#             info = await loop.run_in_executor(None, ydl.extract_info, url, True)
#             return ydl.prepare_filename(info)
#     except Exception as e:
#         logger.error(f"Error downloading video: {e}")
#         return None

# # ✅ Command to start the bot
# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     await update.message.reply_text("Send me a YouTube link to download.")

# # ✅ Handle YouTube link message
# async def handle_youtube_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     url = update.message.text
#     context.user_data['url'] = url  # Store the URL in user_data for later use
#     try:
#         with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
#             info = ydl.extract_info(url, download=False)
#             title = info.get("title", "Unknown Title")
#             formats = info.get("formats", [])

#         # Debug: Print all available formats
#         logger.info("Available formats:")
#         for f in formats:
#             logger.info(f"Format ID: {f.get('format_id')}, Ext: {f.get('ext')}, Resolution: {f.get('resolution')}, Note: {f.get('format_note')}")

#         # Filter formats to include only MP4, WebM, and MP3
#         filtered_formats = []
#         for f in formats:
#             ext = f.get("ext", "").lower()
#             if ext in ["mp4", "webm"]:  # Include video formats
#                 filtered_formats.append(f)
#             elif ext == "mp3":  # Include audio format
#                 filtered_formats.append(f)

#         # Create buttons for filtered formats
#         keyboard = []
#         for f in filtered_formats:
#             format_id = f.get("format_id")
#             format_note = f.get("format_note", "Unknown")
#             resolution = f.get("resolution", "Unknown")
#             ext = f.get("ext", "Unknown")
#             button_text = f"{format_note} ({resolution}, {ext})"
#             keyboard.append([InlineKeyboardButton(button_text, callback_data=f"format_{format_id}")])

#         # Add a button for MP3 (Audio Only) if not already included
#         if not any(f.get("ext", "").lower() == "mp3" for f in filtered_formats):
#             keyboard.append([InlineKeyboardButton("MP3 (Audio Only)", callback_data="audio")])

#         reply_markup = InlineKeyboardMarkup(keyboard)
#         await update.message.reply_text(f"Select quality for: {title}", reply_markup=reply_markup)
#     except Exception as e:
#         logger.error(f"Error fetching YouTube data: {e}")
#         await update.message.reply_text("Sorry, something went wrong. Try again later.")

# # ✅ Handle quality selection callback
# async def handle_quality_selection(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     query = update.callback_query
#     await query.answer()

#     # Retrieve the URL from user_data
#     url = context.user_data.get('url')

#     if not url:
#         # Send error message if there's no valid URL
#         await query.edit_message_text("Error: No valid YouTube URL found!")
#         logger.error("No valid YouTube URL found in the user_data.")
#         return

#     try:
#         if query.data == "audio":
#             # Download as MP3
#             await query.edit_message_text("Downloading audio... Please wait.")
#             file_path = await download_video(url, format_id="bestaudio/best")  # Download best audio format

#             # Check file size
#             if file_path and os.path.getsize(file_path) > MAX_FILE_SIZE:
#                 await query.edit_message_text("The file is too large to send. Please try a smaller video.")
#                 os.remove(file_path)
#                 return

#             # Send the MP3 file
#             if file_path:
#                 await query.message.reply_audio(audio=open(file_path, "rb"))
#                 os.remove(file_path)  # Clean up the file after sending
#         else:
#             # Download video
#             format_id = query.data.replace("format_", "")
#             await query.edit_message_text("Downloading video... Please wait.")
#             file_path = await download_video(url, format_id=format_id)  # Download selected video format

#             # Check file size
#             if file_path and os.path.getsize(file_path) > MAX_FILE_SIZE:
#                 await query.edit_message_text("The file is too large to send. Please try a smaller video.")
#                 os.remove(file_path)
#                 return

#             # Send the video file
#             if file_path:
#                 await query.message.reply_video(video=open(file_path, "rb"))
#                 os.remove(file_path)  # Clean up the file after sending
#     except Exception as e:
#         logger.error(f"Error processing YouTube video: {e}")
#         await query.edit_message_text("Sorry, something went wrong. Please try again later.")

# # ✅ Main function to start the bot
# def main():
#     application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

#     # Add handlers
#     application.add_handler(CommandHandler("start", start))
#     application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_youtube_link))
#     application.add_handler(CallbackQueryHandler(handle_quality_selection))

#     # Start the bot
#     application.run_polling()

# if __name__ == "__main__":
#     main()

# import os
# import math
# import logging
# import yt_dlp
# import asyncio
# from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
# from telegram.ext import (
#     Application,
#     CommandHandler,
#     CallbackQueryHandler,
#     ContextTypes,
#     MessageHandler,
#     filters
# )
# from datetime import datetime, timedelta
# from collections import defaultdict
# import threading
# from dotenv import load_dotenv

# # Health check server (keep this first)
# from health import run_health_server
# health_thread = threading.Thread(target=run_health_server)
# health_thread.daemon = True
# health_thread.start()

# # Load environment variables
# load_dotenv()

# # Configure logging
# logging.basicConfig(
#     format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
#     level=logging.INFO
# )
# logger = logging.getLogger(__name__)

# # Configuration
# TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
# MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB
# MAX_VIDEO_DURATION = 7200  # 2 hours in seconds
# RATE_LIMIT = timedelta(seconds=30)

# # Rate limiting storage - using string keys for consistency
# user_last_request = defaultdict(lambda: datetime.min)

# async def rate_limit_check(user_id: int) -> bool:
#     """Check if user is within rate limit"""
#     key = str(user_id)
#     if user_last_request[key] + RATE_LIMIT > datetime.now():
#         return False
#     user_last_request[key] = datetime.now()
#     return True

# # yt-dlp configuration
# yt_dlp_opts = {
#     "quiet": True,
#     "no_warnings": True,
#     "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
#     "merge_output_format": "mp4",
#     "outtmpl": "%(title)s.%(ext)s",
#     "socket_timeout": 300,
#     "extract_timeout": 600,
#     "cookiefile": "cookies.txt",
#     "noplaylist": True,
#     "ignoreerrors": True,
#     "retries": 3,
#     "postprocessors": [],
# }

# async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Handle /start command"""
#     await update.message.reply_text(
#         "🎬 Welcome to YouTube Downloader Pro!\n"
#         "Send me a YouTube link to get started."
#     )

# async def download_media(url: str, media_type: str) -> str:
#     """Download media with yt-dlp"""
#     opts = yt_dlp_opts.copy()
    
#     if media_type == "audio":
#         opts.update({
#             "format": "bestaudio/best",
#             "postprocessors": [{
#                 "key": "FFmpegExtractAudio",
#                 "preferredcodec": "mp3",
#                 "preferredquality": "192",
#             }],
#         })
#     elif media_type.startswith("format_"):
#         opts["format"] = media_type.split("_", 1)[1]

#     try:
#         loop = asyncio.get_event_loop()
#         with yt_dlp.YoutubeDL(opts) as ydl:
#             info = await loop.run_in_executor(None, ydl.extract_info, url, False)
#             if info.get("is_live"):
#                 raise ValueError("Live streams are not supported")
#             if info.get("duration", 0) > MAX_VIDEO_DURATION:
#                 raise ValueError("Video duration exceeds maximum allowed")
#             filename = ydl.prepare_filename(info)
#             await loop.run_in_executor(None, ydl.process_info, info)
#             return filename
#     except Exception as e:
#         logger.error(f"Download error: {e}")
#         raise

# async def send_progress_updates(context, chat_id, stop_event):
#     """Send periodic chat actions during processing"""
#     while not stop_event.is_set():
#         # Determine chat action based on media type, defaulting to audio
#         media_type = context.user_data.get('media_type', '')
#         action = "upload_video" if "format_" in media_type else "upload_audio"
#         await context.bot.send_chat_action(chat_id=chat_id, action=action)
#         await asyncio.sleep(5)

# async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Main message handler"""
#     user_id = update.effective_user.id
#     if not await rate_limit_check(user_id):
#         await update.message.reply_text(f"⏳ Please wait {RATE_LIMIT.seconds} seconds between requests")
#         return

#     url = update.message.text
#     try:
#         with yt_dlp.YoutubeDL(yt_dlp_opts) as ydl:
#             info = ydl.extract_info(url, download=False)
#             if info.get("is_live"):
#                 raise ValueError("📡 Live streams are not supported")
#             if info.get("duration", 0) > MAX_VIDEO_DURATION:
#                 raise ValueError(f"⏳ Videos longer than {MAX_VIDEO_DURATION//3600} hours are not supported")

#             # Create format selector
#             formats = info.get("formats", [])
#             # Filter for formats with both video and audio
#             video_formats = [f for f in formats if f.get("video_ext") != "none" and f.get("acodec") != "none"]
#             # Sort the formats by video height (resolution) in descending order
#             video_formats = sorted(video_formats, key=lambda f: f.get('height', 0), reverse=True)
#             # Select the top 3 video formats
#             selected_video_formats = video_formats[:3]

#             keyboard = []
#             for f in selected_video_formats:
#                 format_id = f["format_id"]
#                 quality = f.get("format_note", "Unknown")
#                 ext = f.get("ext", "?")
#                 keyboard.append([InlineKeyboardButton(f"🎥 {quality} ({ext})", callback_data=f"format_{format_id}")])

#             # Add a single audio option
#             keyboard.append([InlineKeyboardButton("🎵 MP3 Audio", callback_data="audio")])


#             # Get the highest quality thumbnail available
#             thumbnails = info.get("thumbnails", [])
#             thumb = next(
#                 (t for t in reversed(thumbnails) if t.get("url")),
#                 None
#             ) if thumbnails else None

#             caption = f"📽 {info.get('title', 'Untitled')}\nSelect quality:"

#             if thumb:
#                 await update.message.reply_photo(
#                     photo=thumb["url"],
#                     caption=caption,
#                     reply_markup=InlineKeyboardMarkup(keyboard))
#             else:
#                 await update.message.reply_text(
#                     caption,
#                     reply_markup=InlineKeyboardMarkup(keyboard))

#             # Store URL in user data for callback processing
#             context.user_data["url"] = url

#     except Exception as e:
#         logger.error(f"Error: {e}")
#         await update.message.reply_text(f"❌ Error: {e}")
        
# # Define a helper to create a progress hook for yt-dlp
# def make_progress_hook(context, chat_id, message_id, use_caption=False):
#     """
#     Returns a function that updates the progress message.
#     use_caption: if True, uses edit_message_caption; else edit_message_text.
#     """
#     def progress_hook(d):
#         if d.get('status') == 'downloading':
#             downloaded = d.get('downloaded_bytes', 0)
#             total = d.get('total_bytes') or d.get('total_bytes_estimate') or 1
#             percent = downloaded / total * 100
#             # Create a simple progress bar (20 blocks)
#             blocks = math.floor(percent / 5)
#             progress_bar = f"[{'█' * blocks}{'.' * (20 - blocks)}] {percent:5.1f}%"
#             try:
#                 # Update the message asynchronously
#                 if use_caption:
#                     coro = context.bot.edit_message_caption(
#                         chat_id=chat_id,
#                         message_id=message_id,
#                         caption=f"⏳ Downloading...\n{progress_bar}"
#                     )
#                 else:
#                     coro = context.bot.edit_message_text(
#                         chat_id=chat_id,
#                         message_id=message_id,
#                         text=f"⏳ Downloading...\n{progress_bar}"
#                     )
#                 asyncio.run_coroutine_threadsafe(coro, context.application.loop)
#             except Exception as e:
#                 # Silently pass if update fails (might be due to rapid calls)
#                 pass
#         elif d.get('status') == 'finished':
#             # When finished, update the message once
#             try:
#                 if use_caption:
#                     coro = context.bot.edit_message_caption(
#                         chat_id=chat_id,
#                         message_id=message_id,
#                         caption="✅ Download complete! Uploading file, please wait..."
#                     )
#                 else:
#                     coro = context.bot.edit_message_text(
#                         chat_id=chat_id,
#                         message_id=message_id,
#                         text="✅ Download complete! Uploading file, please wait..."
#                     )
#                 asyncio.run_coroutine_threadsafe(coro, context.application.loop)
#             except Exception:
#                 pass
#     return progress_hook

# async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Handle button callbacks with download progress and clean cancellation."""
#     query = update.callback_query
#     await query.answer()
    
#     url = context.user_data.get("url")
#     media_type = query.data
    
#     if not url:
#         if query.message.caption:
#             await query.edit_message_caption("❌ Session expired. Please send a new link")
#         else:
#             await query.edit_message_text("❌ Session expired. Please send a new link")
#         return

#     context.user_data["media_type"] = media_type

#     # We'll use the same message (from the callback) to show progress.
#     # Determine if we need to update caption vs. text
#     use_caption = bool(query.message.caption)
#     # Initially update message to show starting progress
#     if use_caption:
#         progress_msg = await query.edit_message_caption("⏳ Starting download...")
#     else:
#         progress_msg = await query.edit_message_text("⏳ Starting download...")

#     # Update yt_dlp options to include our progress hook.
#     opts = yt_dlp_opts.copy()
#     # Inject our progress hook
#     opts["progress_hooks"] = [make_progress_hook(context, query.message.chat_id, progress_msg.message_id, use_caption)]
#     # Adjust format if necessary
#     if media_type == "audio":
#         opts.update({
#             "format": "bestaudio/best",
#             "postprocessors": [{
#                 "key": "FFmpegExtractAudio",
#                 "preferredcodec": "mp3",
#                 "preferredquality": "192",
#             }],
#         })
#     elif media_type.startswith("format_"):
#         opts["format"] = media_type.split("_", 1)[1]
    
#     filename = None
#     try:
#         loop = asyncio.get_event_loop()
#         with yt_dlp.YoutubeDL(opts) as ydl:
#             info = await loop.run_in_executor(None, ydl.extract_info, url, False)
#             if info.get("is_live"):
#                 raise ValueError("Live streams are not supported")
#             if info.get("duration", 0) > MAX_VIDEO_DURATION:
#                 raise ValueError("Video duration exceeds maximum allowed")
#             filename = ydl.prepare_filename(info)
#             await loop.run_in_executor(None, ydl.process_info, info)
        
#         if os.path.getsize(filename) > MAX_FILE_SIZE:
#             raise ValueError("📁 File size exceeds Telegram limits")
        
#         # Send the file using a context manager to auto-close the file
#         if media_type == "audio":
#             with open(filename, "rb") as audio_file:
#                 await context.bot.send_audio(
#                     chat_id=query.message.chat_id,
#                     audio=audio_file,
#                     title=os.path.splitext(os.path.basename(filename))[0]
#                 )
#         else:
#             with open(filename, "rb") as video_file:
#                 await context.bot.send_video(
#                     chat_id=query.message.chat_id,
#                     video=video_file,
#                     supports_streaming=True
#                 )
        
#         # After successful sending, update the message to indicate completion
#         if use_caption:
#             await query.edit_message_caption("✅ Download complete!")
#         else:
#             await query.edit_message_text("✅ Download complete!")
        
#     except Exception as e:
#         logger.error(f"Error: {e}")
#         err_msg = f"❌ Error: {e}"
#         if use_caption:
#             await query.edit_message_caption(err_msg)
#         else:
#             await query.edit_message_text(err_msg)
#     finally:
#         # Ensure that the downloaded file is deleted if it exists.
#         if filename and os.path.exists(filename):
#             try:
#                 os.remove(filename)
#             except Exception as e:
#                 logger.error(f"Error removing file: {e}")

# async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     """Handle /help command"""
#     help_text = (
#         "🌟 YouTube Downloader Pro Help 🌟\n\n"
#         "• Send any YouTube link to download\n"
#         "• Choose video quality or MP3 audio\n"
#         "• Max video length: 2 hours\n"
#         "• Supported formats: MP4, WebM, MP3\n\n"
#         "Commands:\n"
#         "/help - Show this help\n"
#         "/stats - Show usage statistics"
#     )
#     await update.message.reply_text(help_text)

# def main():
#     """Start the bot"""
#     application = Application.builder().token(TELEGRAM_BOT_TOKEN).build()

#     # Add handlers
#     application.add_handler(CommandHandler("start", start))
#     application.add_handler(CommandHandler("help", help_command))
#     application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
#     application.add_handler(CallbackQueryHandler(handle_callback))

#     # Start polling
#     application.run_polling()

# if __name__ == "__main__":
#     main()

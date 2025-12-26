import asyncio
import os
import time
import re
import yt_dlp
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, FSInputFile, InlineKeyboardButton, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

TOKEN = "PUT BOT TOKEN HERE"
DOWNLOAD_DIR = "downloads"

if not os.path.exists(DOWNLOAD_DIR):
    os.makedirs(DOWNLOAD_DIR)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- Ваша функція очищення назви ---
def remove_invalid_characters(text):
    """Видаляє з рядка символи, заборонені у назві файлів для Windows."""
    # Додано прапорець re.UNICODE про всяк випадок
    invalid_characters = r'[\\/*?":&<>|. ]'
    text = re.sub(invalid_characters, '_', text)
    return text

# --- Функції для роботи з YouTube ---

def get_video_info(url):
    ydl_opts = {'quiet': True}
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        return ydl.extract_info(url, download=False)

def download_task(url, mode):
    # Спочатку дізнаємося назву відео
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
        original_title = info.get('title', 'video')
    
    # Обробляємо назву вашою функцією
    safe_title = remove_invalid_characters(original_title)
    
    if mode == 'audio':
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': f'{DOWNLOAD_DIR}/{safe_title}.%(ext)s',
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '192',
            }],
            'quiet': True,
        }
    else:  # video
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'merge_output_format': 'mp4',
            'outtmpl': f'{DOWNLOAD_DIR}/{safe_title}.%(ext)s',
            'quiet': True,
        }
    
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])
        # Формуємо шлях для повернення (враховуючи розширення після обробки)
        ext = 'mp3' if mode == 'audio' else 'mp4'
        return os.path.join(DOWNLOAD_DIR, f"{safe_title}.{ext}")

async def delayed_delete(file_path):
    await asyncio.sleep(4 * 3600)
    if os.path.exists(file_path):
        os.remove(file_path)

# --- Обробники бота ---

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("🎥 Бот готовий! Надсилайте посилання. Використовую власну систему очищення назв.")

@dp.message(F.text.regexp(r'(https?://)?(www\.)?(youtube\.com|youtu\.be)/.+'))
async def process_link(message: Message):
    url = message.text.strip()
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="ℹ️ Інформація", callback_data=f"info|{url}"))
    builder.row(
        InlineKeyboardButton(text="🎵 Аудіо (MP3)", callback_data=f"audio|{url}"),
        InlineKeyboardButton(text="🎥 Відео (MP4)", callback_data=f"video|{url}")
    )
    await message.answer("Оберіть дію:", reply_markup=builder.as_markup())


@dp.callback_query(F.data.startswith("info|"))
async def show_info(callback: CallbackQuery):
    url = callback.data.split("|")[1]
    await callback.answer("Збираю метадані...")
    
    with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
        info = ydl.extract_info(url, download=False)
    
    duration = time.strftime('%H:%M:%S', time.gmtime(info.get('duration', 0)))
    thumbnail_url = info.get('thumbnail')  # Отримуємо посилання на обкладинку
    
    # Формуємо розширений звіт
    report = (
        f"🖼 **Назва:** {info.get('title')}\n"
        f"👤 **Автор:** {info.get('uploader')}\n"
        f"⏱ **Тривалість:** {duration}\n"
        f"👁 **Перегляди:** {info.get('view_count', 0):,}\n"
        f"📅 **Дата:** {info.get('upload_date')}\n"
        f"📏 **Роздільна здатність:** {info.get('width')}x{info.get('height')}\n"
        f"🔗 [Відкрити обкладинку в повній якості]({thumbnail_url})"
    )
    
    if thumbnail_url:
        # Надсилаємо фото з описом
        await callback.message.answer_photo(
            photo=thumbnail_url,
            caption=report,
            parse_mode="Markdown"
        )
    else:
        # Якщо раптом обкладинки немає, шлемо просто текст
        await callback.message.answer(report, parse_mode="Markdown")

@dp.callback_query(F.data.startswith("audio|") | F.data.startswith("video|"))
async def handle_download(callback: CallbackQuery):
    mode, url = callback.data.split("|")
    await callback.answer()
    status_msg = await callback.message.answer(f"⏳ Завантажую {mode}...")

    try:
        loop = asyncio.get_event_loop()
        file_path = await loop.run_in_executor(None, download_task, url, mode)
        
        file_size = os.path.getsize(file_path) / (1024 * 1024)
        
        if file_size > 50:
            await status_msg.edit_text(f"✅ Готово! Файл: `{os.path.basename(file_path)}` збережено на 4 години.", parse_mode="Markdown")
        else:
            await status_msg.edit_text("🚀 Надсилаю...")
            input_file = FSInputFile(file_path)
            if mode == 'audio':
                await callback.message.answer_audio(input_file)
            else:
                await callback.message.answer_video(input_file)
        
        asyncio.create_task(delayed_delete(file_path))
    except Exception as e:
        await callback.message.answer(f"❌ Помилка: {e}")
    finally:
        await status_msg.delete()

# --- Фонова чистка ---
async def main():
    # Чистка при старті (старше 24 годин)
    now = time.time()
    if os.path.exists(DOWNLOAD_DIR):
        for f in os.listdir(DOWNLOAD_DIR):
            p = os.path.join(DOWNLOAD_DIR, f)
            if os.path.isfile(p) and os.path.getmtime(p) < now - 86400:
                os.remove(p)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

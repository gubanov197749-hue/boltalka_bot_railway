from aiogram import types
import openai
from openai.error import AuthenticationError, RateLimitError, APIConnectionError, APIError
import asyncio
import logging
import random
import sqlite3
import aiohttp
import json
import time
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, MEGANOVA_API_KEY

# ================ ИМПОРТЫ ДЛЯ ПОГОДЫ ================
import pytz
from weather_service import get_weather_with_retry, format_weather_message
# ====================================================

# Словарь для защиты от спама (время последнего сообщения пользователя)
last_message_time = {}

# Словарь для подсказок (чтобы не спамить)
last_hint_time = {}

# ===== ДИАГНОСТИКА =====
import os
print(f"🔥 BOT_TOKEN = {os.getenv('BOT_TOKEN')}")
print(f"🔥 MEGANOVA_API_KEY = {os.getenv('MEGANOVA_API_KEY')}")
# ========================

# Глобальный список для хранения ссылок на задачи
BACKGROUND_TASKS = set()

# Флаг, что задачи уже запущены
_tasks_started = False

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# ================ ФОНОВЫЕ ЗАДАЧИ ================

async def game_timeout_checker():
    """Фоновая задача: проверяет активные игры и завершает просроченные"""
    while True:
        try:
            conn = sqlite3.connect('bot_database.db')
            c = conn.cursor()
            
            # Ищем все активные игры старше 5 минут
            c.execute('''SELECT chat_id, word FROM games 
                         WHERE game_type = 'crocodile' AND active = 1 
                         AND datetime(started_at) < datetime('now', '-5 minutes')''')
            expired_games = c.fetchall()
            
            for chat_id, word in expired_games:
                # Завершаем игру
                c.execute("UPDATE games SET active = 0 WHERE chat_id = ? AND game_type = 'crocodile'", 
                          (chat_id,))
                conn.commit()
                
                # Отправляем сообщение в чат
                try:
                    await bot.send_message(
                        chat_id,
                        f"⏰ Время вышло! Никто не угадал слово *{word}*.\n"
                        f"Можете начать новую игру: /crocodile"
                    )
                except:
                    pass  # Если не можем отправить — игнорируем
            
            conn.close()
            
        except Exception as e:
            logger.error(f"Ошибка в game_timeout_checker: {e}")
        
        # Проверяем каждые 60 секунд
        await asyncio.sleep(60)


# ================= ФОНОВАЯ ЗАДАЧА ДЛЯ ПОГОДЫ =================

async def weather_checker():
    """Фоновая задача: проверяет время и отправляет погоду"""
    target_hour = 21
    target_minute = 33  # поставь ближайшее время для теста
    
    while True:
        try:
            moscow_tz = pytz.timezone('Europe/Moscow')
            now = datetime.now(moscow_tz)
            
            # Проверяем каждую секунду (для точности)
            if now.hour == target_hour and now.minute == target_minute:
                logger.info(f"🌅 Время {target_hour}:{target_minute} — запускаем отправку погоды")
                await send_morning_weather()
                
                # Спим до конца минуты, чтобы не отправить повторно
                await asyncio.sleep(60 - now.second)
            
            # Ждём 1 секунду перед следующей проверкой
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"❌ Ошибка в weather_checker: {e}")
            await asyncio.sleep(5)

# =================== УТРЕННЯЯ РАССЫЛКА ПОГОДЫ ===================

async def send_morning_weather():
    """Отправляет погоду в группу каждый день в 23:08"""
    try:
        # ID твоей семейной группы
        GROUP_CHAT_ID = -4722324078
        
        logger.info("🌅 Запуск утренней рассылки погоды")
        
        weather_messages = []
        
        for city in ["Славянск-на-Кубани", "Липецк"]:
            status, weather_data = await get_weather_with_retry(city)
            
            if status == "success":
                message = format_weather_message(city, weather_data)
                weather_messages.append(message)
                await asyncio.sleep(2)
            else:
                logger.error(f"Не удалось получить погоду для {city}")
                await bot.send_message(
                    GROUP_CHAT_ID,
                    f"🌅 Доброе утро! Не удалось получить погоду для {city}, но день всё равно будет хорошим! ☀️"
                )
        
        for msg in weather_messages:
            await bot.send_message(GROUP_CHAT_ID, msg, parse_mode="Markdown")
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"Ошибка в утренней рассылке: {e}")

# ============== ТЕСТОВАЯ КОМАНДА ==============
@dp.message_handler(commands=['testweather'])
async def cmd_testweather(message: types.Message):
    """Тестовая команда для проверки погоды"""
    await send_morning_weather()
    await message.reply("✅ Проверка погоды запущена!")

# ================ БАЗА ДАННЫХ ================

def init_db():
    """Инициализация базы данных SQLite"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Таблица кармы
    c.execute('''CREATE TABLE IF NOT EXISTS karma
                 (user_id INTEGER, chat_id INTEGER, karma INTEGER DEFAULT 0,
                  PRIMARY KEY (user_id, chat_id))''')
    
    # Таблица игр
    c.execute('''CREATE TABLE IF NOT EXISTS games
                 (chat_id INTEGER, game_type TEXT, active INTEGER, 
                  word TEXT, players TEXT, started_at TIMESTAMP)''')
    
    # Таблица пар дня
    c.execute('''CREATE TABLE IF NOT EXISTS couples
                 (chat_id INTEGER, user1_id INTEGER, user2_id INTEGER, 
                  date TEXT)''')
    
    # Таблица слов для игры
    c.execute('''CREATE TABLE IF NOT EXISTS game_words
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  word TEXT UNIQUE,
                  added_by INTEGER,
                  added_at TIMESTAMP)''')
    
    conn.commit()
    
    # Добавляем начальные слова, если таблица пуста
    c.execute("SELECT COUNT(*) FROM game_words")
    count = c.fetchone()[0]
    if count == 0:
        default_words = ["крокодил", "слон", "робот", "пицца", "самолёт", 
                         "кофе", "гитара", "радуга", "космос", "шоколад",
                         "интернет", "дружба", "солнце", "море", "поезд",
                         "телефон", "компьютер", "книга", "цветок", "дождь"]
        for word in default_words:
            try:
                c.execute("INSERT INTO game_words (word, added_by, added_at) VALUES (?, ?, ?)",
                          (word, 0, datetime.now()))  # added_by = 0 значит служебное
            except:
                pass
        conn.commit()
        logger.info("Добавлены начальные слова для игры")
    
    conn.close()
    logger.info("База данных инициализирована")

# Создаем таблицы при запуске
init_db()

# ================ ФУНКЦИИ ДЛЯ ИГРОВЫХ СЛОВ ================

def get_random_word():
    """Возвращает случайное слово из базы данных"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT word FROM game_words ORDER BY RANDOM() LIMIT 1")
    result = c.fetchone()
    conn.close()
    
    if result:
        return result[0]
    else:
        # Если слов нет — возвращаем слово по умолчанию
        return "крокодил"

async def is_user_admin(message: types.Message) -> bool:
    """Проверяет, является ли пользователь администратором чата"""
    try:
        user = await bot.get_chat_member(message.chat.id, message.from_user.id)
        return user.status in ['creator', 'administrator']
    except:
        return False

def get_hint(guess: str, target: str) -> str:
    """Возвращает подсказку на основе сравнения слов"""
    guess = guess.lower().strip()
    target = target.lower().strip()
    
    # Если слова совпадают по длине
    if len(guess) == len(target):
        # Считаем совпадающие буквы
        matches = sum(1 for g, t in zip(guess, target) if g == t)
        if matches > len(target) * 0.7:
            return "🔥 Очень горячо! Ты очень близко!"
        elif matches > len(target) * 0.4:
            return "🌡️ Тепло! Есть совпадения"
        else:
            return "❄️ Холодно. Совсем не то"
    
    # Если длина разная
    elif abs(len(guess) - len(target)) <= 2:
        return "🌊 Тёпленько! Почти та же длина"
    elif len(guess) < len(target):
        return "⬆️ Слово короче загаданного"
    else:
        return "⬇️ Слово длиннее загаданного"

async def check_crocodile_guess(message: types.Message) -> bool:
    """Проверяет, угадал ли игрок слово. Даёт подсказки и следит за временем."""
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Получаем информацию об игре (слово и время начала)
    c.execute("SELECT word, started_at FROM games WHERE chat_id = ? AND game_type = 'crocodile' AND active = 1", 
              (message.chat.id,))
    result = c.fetchone()
    
    if not result:
        conn.close()
        return False
    
    word, started_at_str = result
    started_at = datetime.fromisoformat(started_at_str)
    
    # Проверяем, не прошло ли 5 минут
    time_diff = datetime.now() - started_at
    if time_diff.total_seconds() > 300:  # 5 минут = 300 секунд
        # Время вышло — завершаем игру
        c.execute("UPDATE games SET active = 0 WHERE chat_id = ? AND game_type = 'crocodile'", 
                  (message.chat.id,))
        conn.commit()
        conn.close()
        
        await message.reply(
            f"⏰ Время вышло! Никто не угадал слово *{word}*.\n"
            f"Можете начать новую игру: /crocodile"
        )
        return True  # Игра завершена
    
    # Сравниваем (регистронезависимо)
    if message.text.lower().strip() == word.lower():
        # Ура, угадал!
        c.execute("UPDATE games SET active = 0 WHERE chat_id = ? AND game_type = 'crocodile'", 
                  (message.chat.id,))
        conn.commit()
        conn.close()
        
        # Добавляем карму победителю
        add_karma(message.from_user.id, message.chat.id, 1)
        
        await message.reply(
            f"🎉 Поздравляю, {message.from_user.first_name}! Ты угадал слово *{word}*!\n"
            f"⭐ +1 к карме за победу!"
        )
        return True
    
    # Если не угадал — даём подсказку (но не чаще раза в 30 секунд)
    chat_id = message.chat.id
    now = time.time()
    
    if chat_id not in last_hint_time or now - last_hint_time[chat_id] > 30:
        hint = get_hint(message.text, word)
        await message.reply(f"🤔 {hint}")
        last_hint_time[chat_id] = now
    
    conn.close()
    return False

# ================ AI CHAT (MEGANOVA) ================

# Настройка OpenAI-совместимого клиента для MegaNova
openai.api_key = MEGANOVA_API_KEY
openai.api_base = "https://api.meganova.ai/v1"

async def get_ai_response(prompt: str, chat_id: int = None) -> str:
    """Получение ответа от MegaNova API"""
    
    if not MEGANOVA_API_KEY:
        logger.error("MEGANOVA_API_KEY не задан")
        return "🔑 Ошибка: API ключ не настроен."
    
    try:
        import openai
        openai.api_key = MEGANOVA_API_KEY
        openai.api_base = "https://api.meganova.ai/v1"
        
        response = await openai.ChatCompletion.acreate(
            model="mistralai/Mistral-Small-3.2-24B-Instruct-2506",
            messages=[
                {"role": "system", "content": "Ты Болталка — весёлый бот. Отвечай коротко, с эмодзи."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=250
        )
        
        return response.choices[0].message.content
        
    except Exception as e:
        logger.error(f"Ошибка MegaNova: {e}")
        # Если ошибка из-за лимита
        if "quota" in str(e).lower() or "rate limit" in str(e).lower() or "429" in str(e):
            return "🥺 Сегодня я уже наболталась! Завтра снова буду болтать. А пока давай в игру? /crocodile"
        else:
            return "😔 Что-то пошло не так. Попробуй позже или напиши /help"

# ================ КАРМА ================

def add_karma(user_id: int, chat_id: int, value: int = 1):
    """Добавить карму пользователю"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute('''INSERT INTO karma (user_id, chat_id, karma) 
                 VALUES (?, ?, ?)
                 ON CONFLICT(user_id, chat_id) 
                 DO UPDATE SET karma = karma + ?''',
              (user_id, chat_id, value, value))
    conn.commit()
    conn.close()

def get_user_karma(user_id: int, chat_id: int) -> int:
    """Получить карму пользователя"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute('SELECT karma FROM karma WHERE user_id = ? AND chat_id = ?', 
              (user_id, chat_id))
    result = c.fetchone()
    conn.close()
    return result[0] if result else 0

def get_top_karma(chat_id: int, limit: int = 10):
    """Получить топ пользователей по карме"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute('''SELECT user_id, karma FROM karma 
                 WHERE chat_id = ? ORDER BY karma DESC LIMIT ?''',
              (chat_id, limit))
    result = c.fetchall()
    conn.close()
    return result

# ================ НОВЫЕ КОМАНДЫ ДЛЯ СЛОВ ================

@dp.message_handler(commands=['addword'])
async def cmd_addword(message: types.Message):
    """Добавляет новое слово в игру (только для админов)"""
    
    # Проверяем, является ли пользователь админом
    if not await is_user_admin(message):
        await message.reply("❌ Только администраторы могут добавлять слова")
        return
    
    # Проверяем, есть ли текст после команды
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("❌ Напиши слово после команды, например:\n/addword самолёт")
        return
    
    new_word = parts[1].strip().lower()
    
    # Проверяем длину
    if len(new_word) < 3:
        await message.reply("❌ Слово должно быть длиннее 2 букв")
        return
    if len(new_word) > 20:
        await message.reply("❌ Слово слишком длинное (максимум 20 букв)")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    try:
        c.execute("INSERT INTO game_words (word, added_by, added_at) VALUES (?, ?, ?)",
                  (new_word, message.from_user.id, datetime.now()))
        conn.commit()
        await message.reply(f"✅ Слово «{new_word}» добавлено в игру!")
    except sqlite3.IntegrityError:
        await message.reply(f"⚠️ Слово «{new_word}» уже есть в списке")
    finally:
        conn.close()

@dp.message_handler(commands=['words'])
async def cmd_words(message: types.Message):
    """Показывает все доступные слова"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT word FROM game_words ORDER BY word")
    words = c.fetchall()
    conn.close()
    
    if not words:
        await message.reply("📭 Список слов пока пуст. Добавь через /addword")
        return
    
    word_list = "\n".join([f"• {w[0]}" for w in words])
    await message.reply(f"📚 Доступные слова ({len(words)} шт.):\n{word_list}")

# ================ ОБРАБОТЧИКИ КОМАНД ================

@dp.message_handler(commands=['start'])
async def cmd_start(message: types.Message):
    """Обработчик команды /start"""
    text = """Привет, меня зовут <b>Болталка</b> — Чат-бот создающий настроение в любом чате!

Добавь меня в чат с друзьями или коллегами и я начну развлекать вас и создавать настроение праздника :)

<b>Что я умею:</b>
1. 🎭 Общаться с помощью нейросети
2. 📚 Рассказывать факты и истории
3. 👋 Приветствовать новичков и ставить карму
4. 🏆 Показывать топы и рейтинги
5. 🎮 Играть в Крокодила, дуэли, выбирать пару дня
6. 🔍 Проверять достоверность информации

/help — все команды"""
    await message.reply(text)

# ================ НОВЫЙ КРАСИВЫЙ HELP ================

@dp.message_handler(commands=['help'])
async def cmd_help(message: types.Message):
    """Красивый help с кнопками"""
    
    # Создаем клавиатуру с разделами
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    keyboard.add(
        InlineKeyboardButton("🎭 Общение", callback_data="help_chat"),
        InlineKeyboardButton("🏆 Карма", callback_data="help_karma"),
        InlineKeyboardButton("🎮 Игры", callback_data="help_games"),
        InlineKeyboardButton("🔍 Полезное", callback_data="help_utils"),
        InlineKeyboardButton("📋 Все команды", callback_data="help_all")
    )
    
    text = (
        "📚 <b>Справка по командам</b>\n\n"
        "Я умею много всего интересного! Выбери раздел ниже 👇\n\n"
        "Или просто напиши мне сообщение с @упоминанием — и я отвечу 😊"
    )
    
    await message.reply(text, reply_markup=keyboard, parse_mode="HTML")

@dp.callback_query_handler(lambda c: c.data == "help_chat")
async def help_chat(callback_query: types.CallbackQuery):
    """Раздел Общение"""
    text = (
        "🎭 <b>Общение с ботом</b>\n\n"
        "• <b>@BoltalkaChatBot_bot [вопрос]</b> — спроси меня о чём угодно\n"
        "• <b>/fact</b> — случайный интересный факт\n"
        "• <b>/story</b> — короткая история от нейросети\n\n"
        "Я отвечаю только когда меня упомянули, чтобы не мешать общению в чате 😌"
    )
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("◀️ Назад", callback_data="help_back")
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help_karma")
async def help_karma(callback_query: types.CallbackQuery):
    """Раздел Карма"""
    text = (
        "🏆 <b>Карма и рейтинги</b>\n\n"
        "• <b>+</b> — поставь плюсик (ответом на сообщение)\n"
        "• <b>/karma</b> — узнать свою карму\n"
        "• <b>/top</b> — топ 10 пользователей чата\n\n"
        "Чем активнее и добрее человек — тем выше карма! ⭐"
    )
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("◀️ Назад", callback_data="help_back")
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help_games")
async def help_games(callback_query: types.CallbackQuery):
    """Раздел Игры"""
    text = (
        "🎮 <b>Игры</b>\n\n"
        "• <b>/crocodile</b> — начать игру в Крокодила\n"
        "• <b>/duel @user</b> — вызвать на дуэль\n"
        "• <b>/couple</b> — выбрать пару дня\n"
        "• <b>/addword [слово]</b> — добавить слово в игру (только админы)\n"
        "• <b>/words</b> — список всех доступных слов\n\n"
        "В Крокодиле я даю подсказки и сам завершаю игру через 5 минут ⏰"
    )
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("◀️ Назад", callback_data="help_back")
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help_utils")
async def help_utils(callback_query: types.CallbackQuery):
    """Раздел Полезное"""
    text = (
        "🔍 <b>Полезные команды</b>\n\n"
        "• <b>/factcheck [утверждение]</b> — проверить факт через Википедию\n"
        "• <b>/help</b> — эта справка\n"
        "• <b>/start</b> — приветствие\n\n"
        "Я также приветствую новых участников и выдаю +3 кармы за подтверждение ✅"
    )
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("◀️ Назад", callback_data="help_back")
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help_all")
async def help_all(callback_query: types.CallbackQuery):
    """Все команды одним списком"""
    text = (
        "📋 <b>Все команды бота</b>\n\n"
        "🎭 <b>Общение:</b>\n"
        "• @бот [вопрос]\n"
        "• /fact, /story\n\n"
        "🏆 <b>Карма:</b>\n"
        "• + (ответом), /karma, /top\n\n"
        "🎮 <b>Игры:</b>\n"
        "• /crocodile, /duel @user, /couple\n"
        "• /addword, /words\n\n"
        "🔍 <b>Полезное:</b>\n"
        "• /factcheck, /help, /start"
    )
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("◀️ Назад", callback_data="help_back")
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help_back")
async def help_back(callback_query: types.CallbackQuery):
    """Возврат в главное меню help"""
    # Просто вызываем команду /help заново
    await cmd_help(callback_query.message)
    await callback_query.answer()

@dp.message_handler(commands=['karma'])
async def cmd_karma(message: types.Message):
    """Показать карму пользователя"""
    if message.reply_to_message:
        user = message.reply_to_message.from_user
    else:
        user = message.from_user
    
    karma = get_user_karma(user.id, message.chat.id)
    await message.reply(f"⭐ Карма {user.first_name}: <b>{karma}</b>")

@dp.message_handler(commands=['top'])
async def cmd_top(message: types.Message):
    """Показать топ пользователей по карме"""
    top_users = get_top_karma(message.chat.id, 10)
    if not top_users:
        await message.reply("Пока нет статистики в этом чате 🥺")
        return
    
    text = "🏆 <b>Топ 10 по карме:</b>\n\n"
    for i, (user_id, karma) in enumerate(top_users, 1):
        try:
            user = await bot.get_chat_member(message.chat.id, user_id)
            name = user.user.first_name
        except:
            name = f"Пользователь {user_id}"
        text += f"{i}. {name} — {karma} ⭐\n"
    
    await message.reply(text)

@dp.message_handler(commands=['fact'])
async def cmd_fact(message: types.Message):
    """Случайный интересный факт"""
    facts = [
        "🍌 Бананы — это ягоды, а клубника — нет",
        "🐙 У осьминога три сердца",
        "🐹 В Швейцарии запрещено держать только одну морскую свинку — им нужна компания",
        "🐱 Кошки не чувствуют сладкого вкуса",
        "🐘 Слон — единственное животное с 4 коленями",
        "🦒 Язык жирафа достигает 50 см в длину",
        "🐧 Пингвины могут прыгать в высоту до 1.5 метров",
        "🦊 Лисы используют магнитное поле Земли для охоты"
    ]
    await message.reply(random.choice(facts))

@dp.message_handler(commands=['story'])
async def cmd_story(message: types.Message):
    """Короткая история от нейросети"""
    prompt = "Напиши очень короткую смешную историю из жизни, 2-3 предложения"
    story = await get_ai_response(prompt, message.chat.id)
    await message.reply(story)

@dp.message_handler(commands=['crocodile'])
async def cmd_crocodile(message: types.Message):
    """Игра в Крокодила"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Проверяем, не идёт ли уже игра
    c.execute("SELECT * FROM games WHERE chat_id = ? AND active = 1", 
              (message.chat.id,))
    if c.fetchone():
        await message.reply("В чате уже идёт игра! 🎮")
        conn.close()
        return
    
    # Получаем случайное слово из базы
    word = get_random_word()
    
    c.execute("INSERT INTO games (chat_id, game_type, active, word, started_at) VALUES (?, ?, ?, ?, ?)",
              (message.chat.id, "crocodile", 1, word, datetime.now()))
    conn.commit()
    conn.close()
    
    await message.reply(
        f"🎮 <b>Крокодил!</b>\n"
        f"Я загадал слово. Твоя задача — объяснить его другим участникам, не называя само слово.\n"
        f"<i>Слово из {len(word)} букв</i>"
    )

@dp.message_handler(commands=['duel'])
async def cmd_duel(message: types.Message):
    """Дуэль между участниками"""
    if not message.reply_to_message:
        await message.reply("Чтобы вызвать на дуэль, ответь на сообщение противника командой /duel")
        return
    
    opponent = message.reply_to_message.from_user
    if opponent.is_bot:
        await message.reply("С ботом нельзя дуэль! Я пацифист 🤖✌️")
        return
    
    questions = [
        "Сколько будет 2+2?",
        "Столица Франции?",
        "Сколько дней в феврале в високосный год?",
        "Кто написал 'Война и мир'?",
        "Сколько планет в Солнечной системе?",
        "Какой газ мы вдыхаем?"
    ]
    question = random.choice(questions)
    
    await message.reply(
        f"⚔️ <b>Дуэль!</b>\n"
        f"{message.from_user.first_name} против {opponent.first_name}\n\n"
        f"Вопрос: {question}\n"
        f"Кто первый ответит — тот победил!"
    )

@dp.message_handler(commands=['couple'])
async def cmd_couple(message: types.Message):
    """Выбор пары дня"""
    try:
        admins = await bot.get_chat_administrators(message.chat.id)
        members = [admin.user for admin in admins if not admin.user.is_bot]
    except:
        # Если не админ, берем последних активных
        members = [message.from_user]
        await message.reply("Недостаточно прав для выбора пары. Дайте мне права администратора! 🥺")
        return
    
    if len(members) < 2:
        await message.reply("В чате недостаточно активных участников для выбора пары 😢")
        return
    
    couple = random.sample(members, 2)
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT INTO couples (chat_id, user1_id, user2_id, date) VALUES (?, ?, ?, ?)",
              (message.chat.id, couple[0].id, couple[1].id, datetime.now().date()))
    conn.commit()
    conn.close()
    
    await message.reply(
        f"💑 <b>Пара дня!</b>\n"
        f"Сегодняшняя пара: {couple[0].first_name} и {couple[1].first_name}\n"
        f"Поздравляем! 🎉"
    )

@dp.message_handler(commands=['factcheck'])
async def cmd_factcheck(message: types.Message):
    """Проверка фактов через Wikipedia"""
    claim = message.text.replace("/factcheck", "").strip()
    if not claim:
        await message.reply("Напиши утверждение для проверки, например:\n/factcheck Правда ли, что банан — это ягода?")
        return
    
    search_url = "https://ru.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": claim,
        "format": "json",
        "utf8": 1
    }
    
    async with aiohttp.ClientSession() as session:
        try:
            async with session.get(search_url, params=params) as response:
                data = await response.json()
                if data["query"]["search"]:
                    title = data["query"]["search"][0]["title"]
                    result = f"🔍 <b>Нашёл информацию!</b>\n\nВот что говорит Википедия:\n<a href='https://ru.wikipedia.org/wiki/{title.replace(' ', '_')}'>{title}</a>"
                else:
                    result = "🤔 Не могу найти точную информацию. Возможно, это миф или малоизвестный факт."
        except Exception as e:
            logger.error(f"Fact check error: {e}")
            result = f"❌ Ошибка при проверке: {e}"
    
    await message.reply(result)

@dp.message_handler(lambda message: message.reply_to_message and message.text == "+")
async def plus_karma(message: types.Message):
    """Добавление кармы через плюсик"""
    if not message.reply_to_message.from_user.is_bot:
        target_user = message.reply_to_message.from_user
        add_karma(target_user.id, message.chat.id, 1)
        await message.reply(f"⭐ {target_user.first_name} получил +1 к карме!")

@dp.message_handler(content_types=['new_chat_members'])
async def welcome_new_member(message: types.Message):
    """Приветствие новых участников"""
    for new_member in message.new_chat_members:
        if new_member.id == bot.id:
            await message.reply(
                "Всем привет! Я ваш новый развлекательный бот 🤖\n"
                "Напишите /help для списка команд"
            )
        else:
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("✅ Я человек", callback_data=f"verify_{new_member.id}")
            )
            await message.reply(
                f"👋 Привет, {new_member.first_name}!\n"
                f"Нажми кнопку, чтобы подтвердить, что ты человек:",
                reply_markup=keyboard
            )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('verify_'))
async def verify_callback(callback_query: types.CallbackQuery):
    """Подтверждение человека"""
    user_id = int(callback_query.data.split("_")[1])
    
    if callback_query.from_user.id == user_id:
        await callback_query.message.edit_text(
            f"👤 {callback_query.from_user.first_name} подтверждён! Добро пожаловать в чат!"
        )
        add_karma(user_id, callback_query.message.chat.id, 3)
    else:
        await callback_query.answer("Это не твоя кнопка!", show_alert=True)
    
    await callback_query.answer()

# ================ ОСНОВНОЙ ОБРАБОТЧИК СООБЩЕНИЙ ================

# Ключевые слова для вызова бота (можно добавлять любые)
TRIGGER_WORDS = [
    "болталка",
    "болталочка",
    "бот",
    "друг",
    "подруга",
    "болбес",
    "помоги",
    "эй"
]

@dp.message_handler(content_types=['text'])
async def ai_chat_handler(message: types.Message):
    if message.text.startswith('/'):
        return
    
    # Проверка на активную игру
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM games WHERE chat_id = ? AND active = 1", (message.chat.id,))
    if c.fetchone():
        conn.close()
        logger.info(f"🎮 Игра идёт в чате {message.chat.id}, молчим")
        
        # Проверяем, не угадал ли кто слово
        if await check_crocodile_guess(message):
            return
        
        return
    conn.close()
    
    # Защита от спама (группы)
    if message.chat.type != 'private':
        user_id = message.from_user.id
        now = time.time()
        if user_id in last_message_time and now - last_message_time[user_id] < 8:
            logger.info(f"⏳ Спам-защита для {user_id}, молчим")
            return
        last_message_time[user_id] = now
    
    # Получаем username бота
    bot_user = await bot.me
    bot_username = bot_user.username if bot_user else None
    logger.info(f"🤖 bot_username = {bot_username}")
    
    # Проверяем, нужно ли отвечать
    should_reply = False
    
    # 1. Проверка на упоминание через @
    if bot_username and f"@{bot_username}" in message.text.lower():
        should_reply = True
        logger.info(f"✅ Упоминание через @")
    
    # 2. Проверка через entities
    if not should_reply and message.entities:
        for entity in message.entities:
            if entity.type == 'mention':
                mentioned = message.text[entity.offset:entity.offset + entity.length]
                if mentioned.lower() == f"@{bot_username.lower()}":
                    should_reply = True
                    logger.info(f"✅ Упоминание через entities")
                    break
    
    # 3. Проверка на ключевые слова (без @)
    if not should_reply:
        text_lower = message.text.lower()
        for word in TRIGGER_WORDS:
            if word.lower() in text_lower:
                should_reply = True
                logger.info(f"✅ Сработало ключевое слово: '{word}'")
                break
    
    logger.info(f"👀 should_reply = {should_reply}")
    
    # Отвечаем если нужно или это личка
    if should_reply or message.chat.type == 'private':
        # Очищаем от упоминания, если оно было
        prompt = message.text
        if bot_username:
            prompt = prompt.replace(f"@{bot_username}", "").strip()
        
        # Также удаляем ключевые слова (опционально)
        for word in TRIGGER_WORDS:
            prompt = prompt.replace(word, "").strip()
        
        if not prompt:
            prompt = "Привет!"
        
        logger.info(f"💬 Отвечаем на: '{prompt}'")
        response = await get_ai_response(prompt, message.chat.id)
        await message.reply(response)
    else:
        logger.info(f"⏭️ Нет причин для ответа, молчим")

# ================ ЗАПУСК ФОНОВЫХ ЗАДАЧ ================

async def start_background_tasks():
    """Запускает все фоновые задачи ТОЛЬКО ОДИН РАЗ"""
    global _tasks_started
    if _tasks_started:
        logger.info("⏭️ Фоновые задачи уже запущены, пропускаем")
        return
    
    _tasks_started = True
    logger.info("🚀 Запуск фоновых задач...")
    
    # Создаем задачи
    asyncio.create_task(game_timeout_checker())
    asyncio.create_task(weather_checker())

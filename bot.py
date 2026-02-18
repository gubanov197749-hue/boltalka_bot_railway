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
from weather_service import get_weather_with_retry, format_weather_message
# ====================================================

# Словарь для защиты от спама (время последнего сообщения пользователя)
last_message_time = {}

# Словарь для подсказок (чтобы не спамить)
last_hint_time = {}

# Список прикольных подписей для мемов
MEME_CAPTIONS = [
    "😂 Улыбнись!",
    "🤣 Поржали и хватит",
    "😁 Лучшее лекарство",
    "🥳 Настроение подскочило",
    "😎 Мем дня",
    "🤪 Держи порцию смеха",
    "🎉 Бесплатный смех без смс",
    "💪 Теперь ты готов к чату",
    "🔥 Огонь мем",
    "👌 Шедеврально",
    "😘 Целовашки дня",
    "🦄 Мем с приветом",
    "🎈 Праздник к нам приходит",
    "🌈 Радуга эмоций",
    "🍿 Самый сочный мем",
    "🎭 Театр абсурда",
    "🚀 Космический юмор",
    "🎸 Рок-н-ролльный мем",
    "🧸 Уютный вечер с мемом",
    "☕ Кофе и мемы"
]

# ===== ДИАГНОСТИКА (удалено для безопасности) =====
# import os
# print(f"🔥 BOT_TOKEN = {os.getenv('BOT_TOKEN')}")
# print(f"🔥 MEGANOVA_API_KEY = {os.getenv('MEGANOVA_API_KEY')}")
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

# =================== УНИВЕРСАЛЬНАЯ ФУНКЦИЯ ДЛЯ ПОГОДЫ ===================

async def send_weather_to_chat(chat_id: int):
    """Отправляет погоду в указанный чат"""
    try:
        logger.info(f"🌅 Запуск рассылки погоды в чат {chat_id}")
        
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
                    chat_id,
                    f"🌅 Доброе утро! Не удалось получить погоду для {city}, но день всё равно будет хорошим! ☀️"
                )
        
        for msg in weather_messages:
            await bot.send_message(chat_id, msg, parse_mode="Markdown")
            await asyncio.sleep(1)
            
    except Exception as e:
        logger.error(f"Ошибка в рассылке погоды: {e}")

# ============== КОМАНДА ДЛЯ РУЧНОЙ ОТПРАВКИ ПОГОДЫ ==============
@dp.message_handler(commands=['testweather'])
async def cmd_testweather(message: types.Message):
    """Команда для ручной отправки погоды"""
    try:
        # Отправляем погоду туда, откуда пришёл запрос
        await send_weather_to_chat(message.chat.id)
        
        # Отправляем подтверждение БЕЗ reply (чтобы избежать ошибки)
        if message.chat.type == 'private':
            await message.answer("🌤️ Погода для тебя!")
        else:
            await message.answer("✅ Погода отправлена в этот чат!")
            
    except Exception as e:
        logger.error(f"Ошибка в testweather: {e}")
        # Пробуем отправить простое сообщение, если что-то пошло не так
        await message.answer("✅ Погода отправлена!")

# ============== СТАРАЯ ФУНКЦИЯ ДЛЯ СОВМЕСТИМОСТИ ==============
async def send_morning_weather():
    """Отправляет погоду в группу по умолчанию"""
    GROUP_CHAT_ID = -4722324078
    await send_weather_to_chat(GROUP_CHAT_ID)

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
    
    # Таблица слов для игры с описанием
    c.execute('''CREATE TABLE IF NOT EXISTS game_words
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  word TEXT UNIQUE,
                  description TEXT,
                  added_by INTEGER,
                  added_at TIMESTAMP)''')
    
    # ===== НОВАЯ ТАБЛИЦА ДЛЯ СТАТИСТИКИ КРОКОДИЛА =====
    c.execute('''CREATE TABLE IF NOT EXISTS game_stats
                 (user_id INTEGER,
                  chat_id INTEGER,
                  games_played INTEGER DEFAULT 0,
                  games_won INTEGER DEFAULT 0,
                  total_guesses INTEGER DEFAULT 0,
                  last_played TIMESTAMP,
                  PRIMARY KEY (user_id, chat_id))''')
    # ==================================================
    
    conn.commit()
    
    # Добавляем начальные слова и описания, если таблица пуста
    c.execute("SELECT COUNT(*) FROM game_words")
    count = c.fetchone()[0]
    if count == 0:
        default_words = {
            "крокодил": "зелёное зубастое животное, которое живёт в реках и любит плавать",
            "слон": "огромное серое животное с длинным хоботом и большими ушами",
            "робот": "механическое устройство, которое может выполнять команды человека",
            "пицца": "итальянское блюдо: круглая лепёшка с томатным соусом и сыром",
            "самолёт": "летательный аппарат с крыльями, который перевозит людей и грузы",
            "кофе": "ароматный напиток из зёрен, бодрит по утрам",
            "гитара": "музыкальный инструмент с шестью струнами и грифом",
            "радуга": "разноцветная дуга на небе после дождя",
            "космос": "бесконечное пространство со звёздами и планетами за пределами Земли",
            "шоколад": "сладкое лакомство из какао-бобов, бывает молочным и горьким",
            "интернет": "глобальная сеть, которая соединяет компьютеры по всему миру",
            "дружба": "близкие отношения между людьми, основанные на доверии и взаимопомощи",
            "солнце": "звезда, которая даёт нам свет и тепло",
            "море": "огромное солёное водное пространство",
            "поезд": "транспортное средство из вагонов, которое движется по рельсам",
            "телефон": "устройство для связи с людьми на расстоянии",
            "компьютер": "электронная машина для работы, игр и выхода в интернет",
            "книга": "печатное издание с текстом и картинками",
            "цветок": "растение с красивыми лепестками и приятным запахом",
            "дождь": "атмосферные осадки в виде капель воды"
        }
        
        for word, description in default_words.items():
            try:
                c.execute("INSERT INTO game_words (word, description, added_by, added_at) VALUES (?, ?, ?, ?)",
                          (word, description, 0, datetime.now()))
            except:
                pass
        conn.commit()
        logger.info("Добавлены начальные слова для игры с описаниями")
    
    conn.close()
    logger.info("База данных инициализирована")

# Создаем таблицы при запуске
init_db()

# ================ ФУНКЦИИ ДЛЯ ИГРОВЫХ СЛОВ ================

def get_random_word_with_description():
    """Возвращает случайное слово и его описание из базы"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT word, description FROM game_words ORDER BY RANDOM() LIMIT 1")
    result = c.fetchone()
    conn.close()
    
    if result:
        return result[0], result[1]  # слово, описание
    else:
        # Запасной вариант
        return "крокодил", "зелёное зубастое животное, которое живёт в реках"

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

# ================ НОВАЯ ФУНКЦИЯ ДЛЯ СТАТИСТИКИ ================
def update_game_stats(user_id: int, chat_id: int, won: bool = False):
    """Обновляет статистику игрока в Крокодиле"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Проверяем, есть ли запись
    c.execute("SELECT * FROM game_stats WHERE user_id = ? AND chat_id = ?", (user_id, chat_id))
    if c.fetchone():
        # Обновляем существующую
        if won:
            c.execute('''UPDATE game_stats 
                         SET games_played = games_played + 1,
                             games_won = games_won + 1,
                             last_played = ?
                         WHERE user_id = ? AND chat_id = ?''',
                      (datetime.now(), user_id, chat_id))
        else:
            c.execute('''UPDATE game_stats 
                         SET games_played = games_played + 1,
                             last_played = ?
                         WHERE user_id = ? AND chat_id = ?''',
                      (datetime.now(), user_id, chat_id))
    else:
        # Создаём новую запись
        if won:
            c.execute('''INSERT INTO game_stats (user_id, chat_id, games_played, games_won, last_played)
                         VALUES (?, ?, 1, 1, ?)''',
                      (user_id, chat_id, datetime.now()))
        else:
            c.execute('''INSERT INTO game_stats (user_id, chat_id, games_played, games_won, last_played)
                         VALUES (?, ?, 1, 0, ?)''',
                      (user_id, chat_id, datetime.now()))
    
    conn.commit()
    conn.close()
# =============================================================

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
        
        await message.answer(
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
        
        # ===== ОБНОВЛЯЕМ СТАТИСТИКУ =====
        update_game_stats(message.from_user.id, message.chat.id, won=True)
        # ================================
        
        # Получаем описание слова
        desc_conn = sqlite3.connect('bot_database.db')
        desc_c = desc_conn.cursor()
        desc_c.execute("SELECT description FROM game_words WHERE word = ?", (word,))
        desc_result = desc_c.fetchone()
        desc_conn.close()
        
        description = desc_result[0] if desc_result else ""
        
        if description:
            await message.answer(
                f"🎉 Поздравляю, {message.from_user.first_name}! Ты угадал слово *{word}*!\n\n📖 <b>Значение:</b> {description}\n\n⭐ +1 к карме за победу!",
                parse_mode="HTML"
            )
        else:
            await message.answer(
                f"🎉 Поздравляю, {message.from_user.first_name}! Ты угадал слово *{word}*!\n\n⭐ +1 к карме за победу!",
                parse_mode="HTML"
            )
        return True
    
    # Если не угадал — даём подсказку (но не чаще раза в 30 секунд)
    chat_id = message.chat.id
    now = time.time()
    
    if chat_id not in last_hint_time or now - last_hint_time[chat_id] > 30:
        hint = get_hint(message.text, word)
        await message.answer(f"🤔 {hint}")
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
    """Добавляет новое слово и его описание в игру"""
    
    # Проверяем, является ли пользователь админом
    if not await is_user_admin(message):
        await message.answer("❌ Только администраторы могут добавлять слова")
        return
    
    # Разбираем аргументы: слово | описание
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2 or '|' not in parts[1]:
        await message.answer(
            "❌ Формат: /addword слово | описание\n"
            "Например: /addword айсберг | огромная ледяная глыба, плавающая в океане"
        )
        return
    
    # Извлекаем слово и описание
    word_part, desc_part = parts[1].split('|', 1)
    new_word = word_part.strip().lower()
    description = desc_part.strip()
    
    # Проверки длины
    if len(new_word) < 3:
        await message.answer("❌ Слово должно быть длиннее 2 букв")
        return
    if len(new_word) > 20:
        await message.answer("❌ Слово слишком длинное (максимум 20 букв)")
        return
    if len(description) < 5:
        await message.answer("❌ Описание слишком короткое (минимум 5 символов)")
        return
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    try:
        c.execute("INSERT INTO game_words (word, description, added_by, added_at) VALUES (?, ?, ?, ?)",
                  (new_word, description, message.from_user.id, datetime.now()))
        conn.commit()
        await message.answer(f"✅ Слово «{new_word}» с описанием добавлено в игру!")
    except sqlite3.IntegrityError:
        await message.answer(f"⚠️ Слово «{new_word}» уже есть в списке")
    finally:
        conn.close()

@dp.message_handler(commands=['words'])
async def cmd_words(message: types.Message):
    """Показывает все доступные слова"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT word, description FROM game_words ORDER BY word")
    words = c.fetchall()
    conn.close()
    
    if not words:
        await message.answer("📭 Список слов пока пуст. Добавь через /addword")
        return
    
    # Формируем список слов с описаниями
    word_list = []
    for w, desc in words:
        word_list.append(f"• {w} — _{desc[:30]}..._")
    
    await message.answer(
        f"📚 <b>Доступные слова ({len(words)} шт.):</b>\n" + "\n".join(word_list),
        parse_mode="HTML"
    )

# ================ MEME API (HUMOR API) ================

HUMOR_API_KEY = "7a10744d91b342e389367ddb520ea689"

async def get_random_meme():
    """Получает случайный мем из Humor API"""
    try:
        url = f"https://api.humorapi.com/memes/random?api-key={HUMOR_API_KEY}"
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    data = await response.json()
                    return {
                        "success": True,
                        "url": data.get("url"),
                        "title": data.get("title", "😂 Случайный мем"),
                        "nsfw": data.get("nsfw", False)
                    }
                else:
                    logger.error(f"Humor API error: {response.status}")
                    return {"success": False, "error": f"API error {response.status}"}
                    
    except Exception as e:
        logger.error(f"Error fetching meme: {e}")
        return {"success": False, "error": str(e)}

@dp.message_handler(commands=['meme'])
async def cmd_meme(message: types.Message):
    """Отправляет случайный мем"""
    
    # Сразу показываем, что бот работает
    status_msg = await message.answer("🔍 Ищу свежий мем...")
    
    # Получаем мем
    result = await get_random_meme()
    
    if result["success"]:
        # Удаляем сообщение о поиске
        await status_msg.delete()
        
        # Выбираем случайную подпись
        caption_text = random.choice(MEME_CAPTIONS)
        caption = f"{caption_text}\n\n/meme — ещё мем"
        
        # Отправляем картинку
        await message.answer_photo(
            photo=result["url"],
            caption=caption
        )
    else:
        await status_msg.edit_text(
            "😔 Не удалось найти мем. Попробуй позже.\n"
            "А пока можешь сыграть в /crocodile"
        )

# ================ НОВАЯ КОМАНДА ТОП КРОКОДИЛА ================
@dp.message_handler(commands=['croctop'])
async def cmd_croctop(message: types.Message):
    """Показывает топ игроков в Крокодила в этом чате"""
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Получаем топ-10 по победам
    c.execute('''SELECT user_id, games_won, games_played 
                 FROM game_stats 
                 WHERE chat_id = ? 
                 ORDER BY games_won DESC 
                 LIMIT 10''', (message.chat.id,))
    top_players = c.fetchall()
    conn.close()
    
    if not top_players:
        await message.answer(
            "📊 В этом чате ещё нет статистики игр в Крокодила.\n"
            "Сыграйте первую игру: /crocodile"
        )
        return
    
    # Формируем сообщение
    text = "🏆 <b>Топ игроков в Крокодила</b>\n\n"
    
    for i, (user_id, wins, played) in enumerate(top_players, 1):
        try:
            user = await bot.get_chat_member(message.chat.id, user_id)
            name = user.user.first_name
        except:
            name = f"Игрок {user_id}"
        
        win_rate = (wins / played * 100) if played > 0 else 0
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "▫️"
        text += f"{medal} {name} — {wins} побед из {played} игр ({win_rate:.1f}%)\n"
    
    await message.answer(text, parse_mode="HTML")
# =============================================================

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
    await message.answer(text)

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
        InlineKeyboardButton("📊 Топ Крокодила", callback_data="help_croctop"),
        InlineKeyboardButton("🔍 Полезное", callback_data="help_utils"),
        InlineKeyboardButton("🌤️ Погода", callback_data="help_weather"),
        InlineKeyboardButton("😂 Мемы", callback_data="help_meme"),
        InlineKeyboardButton("🔮 Гороскоп", callback_data="help_horoscope"),
        InlineKeyboardButton("📋 Все команды", callback_data="help_all")
    )
    
    text = (
        "📚 <b>Справка по командам</b>\n\n"
        "Я умею много всего интересного! Выбери раздел ниже 👇\n\n"
        "Или просто напиши мне сообщение с @упоминанием — и я отвечу 😊"
    )
    
    await message.answer(text, reply_markup=keyboard, parse_mode="HTML")

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
        "• <b>/crocodile</b> — начать игру в Крокодила (с кнопкой подсказки!)\n"
        "• <b>/duel @user</b> — вызвать на дуэль\n"
        "• <b>/couple</b> — выбрать пару дня\n"
        "• <b>/addword слово | описание</b> — добавить слово в игру (только админы)\n"
        "• <b>/words</b> — список всех доступных слов\n\n"
        "В Крокодиле я даю подсказки, сам завершаю игру через 5 минут, а во время угадывания не блокирую игроков ⏰"
    )
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("◀️ Назад", callback_data="help_back")
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help_croctop")
async def help_croctop(callback_query: types.CallbackQuery):
    """Раздел Топ Крокодила"""
    text = (
        "📊 <b>Статистика Крокодила</b>\n\n"
        "• <b>/croctop</b> — топ-10 игроков в этом чате\n\n"
        "Статистика считается автоматически:\n"
        "• победы\n"
        "• количество сыгранных игр\n"
        "• процент побед"
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

@dp.callback_query_handler(lambda c: c.data == "help_weather")
async def help_weather(callback_query: types.CallbackQuery):
    """Раздел Погода"""
    text = (
        "🌤️ <b>Погода</b>\n\n"
        "• <b>/testweather</b> — показать погоду в Славянске-на-Кубани и Липецке\n\n"
        "👉 Если команда вызвана в группе — погода уйдёт в группу\n"
        "👉 Если в личке — погода придёт лично тебе"
    )
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("◀️ Назад", callback_data="help_back")
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help_meme")
async def help_meme(callback_query: types.CallbackQuery):
    """Раздел Мемы"""
    text = (
        "😂 <b>Мемы и юмор</b>\n\n"
        "• <b>/meme</b> — случайный мем (из Humor API)\n\n"
        "Бесплатный лимит: 100 запросов в день. Мемы безопасны для всей семьи!"
    )
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("◀️ Назад", callback_data="help_back")
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    await callback_query.answer()

@dp.callback_query_handler(lambda c: c.data == "help_horoscope")
async def help_horoscope(callback_query: types.CallbackQuery):
    """Раздел Гороскоп"""
    
    # 1. СРАЗУ отвечаем на колбэк (это самая важная строка!)
    await callback_query.answer()
    
    # 2. Теперь логируем и работаем дальше
    logger.info(f"🔥 help_horoscope ВЫЗВАН для пользователя {callback_query.from_user.id}")
    
    text = (
        "🔮 <b>Гороскоп на сегодня</b>\n\n"
        "• <b>/horoscope</b> — выбрать знак и получить реальный AI-гороскоп\n\n"
        "Доступные знаки: Телец, Весы, Скорпион, Рыбы\n"
        "Гороскоп генерируется нейросетью на русском языке."
    )
    
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("◀️ Назад", callback_data="help_back")
    )
    
    await callback_query.message.edit_text(text, reply_markup=keyboard, parse_mode="HTML")
    logger.info("✅ help_horoscope отработал")
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
        "• /addword [слово | описание]\n"
        "• /words\n"
        "• /croctop\n\n"
        "🌤️ <b>Погода:</b>\n"
        "• /testweather\n\n"
        "😂 <b>Мемы:</b>\n"
        "• /meme\n\n"
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
    await cmd_help(callback_query.message)
    await callback_query.answer()

# ================ КОМАНДА КРОКОДИЛ С ПОДСКАЗКОЙ ================

@dp.message_handler(commands=['crocodile'])
async def cmd_crocodile(message: types.Message):
    """Игра в Крокодила с кнопкой подсказки"""
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    
    # Проверяем, не идёт ли уже игра
    c.execute("SELECT * FROM games WHERE chat_id = ? AND active = 1", 
              (message.chat.id,))
    if c.fetchone():
        await message.answer("В чате уже идёт игра! 🎮")
        conn.close()
        return
    
    # Получаем случайное слово и его описание из базы
    word, description = get_random_word_with_description()
    
    # Сохраняем игру (слово и время начала)
    c.execute("INSERT INTO games (chat_id, game_type, active, word, started_at) VALUES (?, ?, ?, ?, ?)",
              (message.chat.id, "crocodile", 1, word, datetime.now()))
    conn.commit()
    conn.close()
    
    # Создаём кнопку подсказки
    keyboard = InlineKeyboardMarkup().add(
        InlineKeyboardButton("🔍 Подсказка", callback_data=f"hint_{word}")
    )
    
    await message.answer(
        f"🎮 <b>Крокодил!</b>\n"
        f"Я загадал слово. Твоя задача — объяснить его другим участникам, не называя само слово.\n\n"
        f"<i>Слово из {len(word)} букв</i>\n\n"
        f"Если совсем сложно — нажми кнопку подсказки 👇",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

# ================ ОБРАБОТЧИК КНОПКИ ПОДСКАЗКИ ================

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('hint_'))
async def process_hint(callback_query: types.CallbackQuery):
    """Обработчик кнопки подсказки"""
    word = callback_query.data.replace('hint_', '')
    
    # Проверяем, что игра ещё идёт
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("SELECT * FROM games WHERE chat_id = ? AND active = 1", 
              (callback_query.message.chat.id,))
    if not c.fetchone():
        await callback_query.answer("Игра уже закончилась!", show_alert=True)
        conn.close()
        return
    
    # Получаем описание слова из базы
    c.execute("SELECT description FROM game_words WHERE word = ?", (word,))
    result = c.fetchone()
    conn.close()
    
    description = result[0] if result else "У этого слова нет подсказки 😅"
    
    # Отвечаем (уведомление появится у всех в чате)
    await callback_query.message.answer(f"🔍 <b>Подсказка:</b> {description}", parse_mode="HTML")
    await callback_query.answer()

# ================ ОСТАЛЬНЫЕ ОБРАБОТЧИКИ КОМАНД ================

@dp.message_handler(commands=['karma'])
async def cmd_karma(message: types.Message):
    """Показать карму пользователя"""
    if message.reply_to_message:
        user = message.reply_to_message.from_user
    else:
        user = message.from_user
    
    karma = get_user_karma(user.id, message.chat.id)
    await message.answer(f"⭐ Карма {user.first_name}: <b>{karma}</b>")

@dp.message_handler(commands=['top'])
async def cmd_top(message: types.Message):
    """Показать топ пользователей по карме"""
    top_users = get_top_karma(message.chat.id, 10)
    if not top_users:
        await message.answer("Пока нет статистики в этом чате 🥺")
        return
    
    text = "🏆 <b>Топ 10 по карме:</b>\n\n"
    for i, (user_id, karma) in enumerate(top_users, 1):
        try:
            user = await bot.get_chat_member(message.chat.id, user_id)
            name = user.user.first_name
        except:
            name = f"Пользователь {user_id}"
        text += f"{i}. {name} — {karma} ⭐\n"
    
    await message.answer(text)

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
    await message.answer(random.choice(facts))

@dp.message_handler(commands=['story'])
async def cmd_story(message: types.Message):
    """Короткая история от нейросети"""
    prompt = "Напиши очень короткую смешную историю из жизни, 2-3 предложения"
    story = await get_ai_response(prompt, message.chat.id)
    await message.answer(story)

@dp.message_handler(commands=['duel'])
async def cmd_duel(message: types.Message):
    """Дуэль между участниками"""
    if not message.reply_to_message:
        await message.answer("Чтобы вызвать на дуэль, ответь на сообщение противника командой /duel")
        return
    
    opponent = message.reply_to_message.from_user
    if opponent.is_bot:
        await message.answer("С ботом нельзя дуэль! Я пацифист 🤖✌️")
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
    
    await message.answer(
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
        await message.answer("Недостаточно прав для выбора пары. Дайте мне права администратора! 🥺")
        return
    
    if len(members) < 2:
        await message.answer("В чате недостаточно активных участников для выбора пары 😢")
        return
    
    couple = random.sample(members, 2)
    
    conn = sqlite3.connect('bot_database.db')
    c = conn.cursor()
    c.execute("INSERT INTO couples (chat_id, user1_id, user2_id, date) VALUES (?, ?, ?, ?)",
              (message.chat.id, couple[0].id, couple[1].id, datetime.now().date()))
    conn.commit()
    conn.close()
    
    await message.answer(
        f"💑 <b>Пара дня!</b>\n"
        f"Сегодняшняя пара: {couple[0].first_name} и {couple[1].first_name}\n"
        f"Поздравляем! 🎉"
    )

# Словарь для временного хранения вопросов пользователей
user_questions = {}

@dp.message_handler(commands=['factcheck'])
async def cmd_factcheck(message: types.Message):
    """Запускает режим проверки фактов"""
    claim = message.text.replace("/factcheck", "").strip()
    
    # Если пользователь сразу написал вопрос
    if claim:
        await process_factcheck(message, claim)
        return
    
    # Если команда без вопроса — просим ввести
    user_questions[message.from_user.id] = True
    await message.answer(
        "🔍 <b>Режим проверки фактов</b>\n\n"
        "Напиши свой вопрос или утверждение, и я найду информацию в Википедии.\n\n"
        "Например:\n"
        "• банан это ягода\n"
        "• столица Франции\n"
        "• кто написал война и мир\n\n"
        "✏️ <i>Жду твой вопрос...</i>",
        parse_mode="HTML"
    )

@dp.message_handler(lambda message: message.from_user.id in user_questions and not message.text.startswith('/'))
async def handle_factcheck_question(message: types.Message):
    """Обрабатывает вопрос, введённый после команды /factcheck"""
    logger.info(f"🔥 handle_factcheck_question вызвана для пользователя {message.from_user.id}")
    logger.info(f"📝 Текст сообщения: {message.text}")
    
    # Удаляем пользователя из режима ожидания
    if message.from_user.id in user_questions:
        del user_questions[message.from_user.id]
        logger.info("✅ Пользователь удалён из user_questions")
    else:
        logger.warning("⚠️ Пользователя нет в user_questions")
    
    # Обрабатываем вопрос
    await process_factcheck(message, message.text)

async def process_factcheck(message: types.Message, claim: str):
    """Основная логика проверки фактов (Wikipedia)"""
    logger.info(f"🔥 process_factcheck НАЧАЛАСЬ с claim: '{claim}'")
    
    # Показываем, что ищем
    status_msg = await message.answer("🔎 Ищу информацию в Википедии...")
    
    # Используем Wikipedia API
    search_url = "https://ru.wikipedia.org/w/api.php"
    
    # Функция для поиска
    async def search_wiki(query):
        params = {
            "action": "query",
            "list": "search",
            "srsearch": query,
            "srlimit": 5,
            "format": "json",
            "utf8": 1
        }
        
        headers = {
            "User-Agent": "BoltalkaBot/1.0 (Telegram bot for family chat; https://t.me/BoltalkaChatBot_bot)",
            "Accept": "application/json"
        }
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(search_url, params=params, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        logger.info(f"🔍 API ответ для '{query}': {data}")
                        results = data.get("query", {}).get("search", [])
                        logger.info(f"📦 Найдено результатов: {len(results)}")
                        return results
                    else:
                        logger.error(f"❌ API ошибка: статус {response.status}")
                        return []
        except Exception as e:
            logger.error(f"❌ Ошибка запроса к API: {e}")
            return []
    
    try:
        # Пробуем найти по исходному запросу
        results = await search_wiki(claim)
        
        # Если ничего не нашли, пробуем извлечь ключевые слова
        if not results:
            # Убираем вопросительные слова и предлоги
            stop_words = ['правда', 'ли', 'что', 'как', 'где', 'когда', 'почему', 
                         'зачем', 'чей', 'какая', 'какое', 'какие', 'это', 'эти']
            
            words = claim.lower().split()
            # Оставляем только значимые слова (длиннее 3 букв)
            keywords = [w for w in words if len(w) > 3 and w not in stop_words]
            
            # Пробуем разные комбинации
            for keyword in keywords:
                logger.info(f"🔍 Пробуем ключевое слово: '{keyword}'")
                results = await search_wiki(keyword)
                if results:
                    claim = keyword
                    break
            
            # Если всё ещё ничего нет, берём последнее слово
            if not results and words:
                last_word = words[-1]
                if len(last_word) > 3:
                    logger.info(f"🔍 Пробуем последнее слово: '{last_word}'")
                    results = await search_wiki(last_word)
                    if results:
                        claim = last_word
        
        # Удаляем сообщение о поиске
        await status_msg.delete()
        
        if results:
            # Берём первый результат
            best_match = results[0]
            title = best_match["title"]
            
            # Очищаем snippet
            snippet = best_match.get('snippet', '')
            snippet = snippet.replace('<span class="searchmatch">', '<b>').replace('</span>', '</b>')
            
            response = (
                f"🔍 <b>Нашёл информацию!</b>\n\n"
                f"По запросу: <i>«{claim}»</i>\n"
                f"📖 Статья: <b>{title}</b>\n"
                f"📝 Краткое описание: {snippet}\n\n"
                f"👉 <a href='https://ru.wikipedia.org/wiki/{title.replace(' ', '_')}'>Читать полностью на Википедии</a>\n\n"
                f"🔄 /factcheck — новый вопрос"
            )
            await message.answer(response, parse_mode="HTML")
        else:
            await message.answer(
                "🤔 <b>Ничего не найдено</b>\n\n"
                "Попробуй упростить запрос или использовать ключевые слова.\n"
                "Например: «банан», «франция», «война и мир»\n\n"
                "🔄 /factcheck — попробовать ещё"
            )
            
    except Exception as e:
        logger.error(f"❌ Ошибка в process_factcheck: {e}", exc_info=True)
        await status_msg.edit_text(
            "❌ Ошибка при поиске. Попробуй позже.\n"
            "🔄 /factcheck — повторить"
        )

@dp.message_handler(lambda message: message.reply_to_message and message.text == "+")
async def plus_karma(message: types.Message):
    """Добавление кармы через плюсик"""
    if not message.reply_to_message.from_user.is_bot:
        target_user = message.reply_to_message.from_user
        add_karma(target_user.id, message.chat.id, 1)
        await message.answer(f"⭐ {target_user.first_name} получил +1 к карме!")

@dp.message_handler(content_types=['new_chat_members'])
async def welcome_new_member(message: types.Message):
    """Приветствие новых участников"""
    for new_member in message.new_chat_members:
        if new_member.id == bot.id:
            await message.answer(
                "Всем привет! Я ваш новый развлекательный бот 🤖\n"
                "Напишите /help для списка команд"
            )
        else:
            keyboard = InlineKeyboardMarkup().add(
                InlineKeyboardButton("✅ Я человек", callback_data=f"verify_{new_member.id}")
            )
            await message.answer(
                f"👋 Привет, {new_member.first_name}!\n"
                f"Нажми кнопку, чтобы подтвердить, что ты человек:",
                reply_markup=keyboard
            )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('verify_') and c.data[7:].isdigit())
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
    game_active = c.fetchone() is not None
    conn.close()
    
    if game_active:
        logger.info(f"🎮 Игра идёт, антиспам отключён")
        # Проверяем, не угадал ли кто слово
        if await check_crocodile_guess(message):
            return
        return  # Во время игры не обрабатываем AI и не применяем антиспам
    
    # Защита от спама (только вне игры)
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
        await message.answer(response)
    else:
        logger.info(f"⏭️ Нет причин для ответа, молчим")

# ================ ГОРОСКОП (RAPIDAPI) ================

RAPIDAPI_KEY = "7a3f09c18dmsh25d17a2b71a4ffbp17caa7jsn97al4c600486"
RAPIDAPI_HOST = "multilingual-ai-zodiac-customized-horoscopes-for-all-signs.p.rapidapi.com"

# Знаки зодиака для семейного чата
ZODIAC_SIGNS = {
    "♉ Телец": "taurus",
    "♎ Весы": "libra", 
    "♏ Скорпион": "scorpio",
    "♓ Рыбы": "pisces"
}

async def get_horoscope(sign: str) -> dict:
    """Получает гороскоп для указанного знака из RapidAPI"""
    try:
        # Получаем сегодняшнюю дату в формате YYYY-MM-DD
        today = datetime.now().strftime("%Y-%m-%d")
        
        url = f"https://{RAPIDAPI_HOST}/horoscope-detailed.php"
        
        params = {
            "sign": sign,
            "period": "day",
            "mode": "serious",
            "language": "Russian",
            "date": today
        }
        
        headers = {
            "X-RapidAPI-Key": RAPIDAPI_KEY,
            "X-RapidAPI-Host": RAPIDAPI_HOST
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(url, params=params, headers=headers) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"🔮 API ответ для {sign}: {data}")
                    return {"success": True, "data": data}
                else:
                    logger.error(f"❌ Ошибка API гороскопа: {response.status}")
                    return {"success": False, "error": f"API error {response.status}"}
    except Exception as e:
        logger.error(f"❌ Ошибка запроса к API гороскопа: {e}")
        return {"success": False, "error": str(e)}

@dp.message_handler(commands=['horoscope'])
async def cmd_horoscope(message: types.Message):
    """Показывает гороскоп на сегодня для выбранного знака"""
    
    # Создаём клавиатуру с кнопками знаков
    keyboard = InlineKeyboardMarkup(row_width=2)
    
    for sign_name in ZODIAC_SIGNS.keys():
        keyboard.insert(
            InlineKeyboardButton(sign_name, callback_data=f"horo_{ZODIAC_SIGNS[sign_name]}")
        )
    
    await message.answer(
        "🔮 <b>Гороскоп на сегодня</b>\n\n"
        "Выбери свой знак зодиака, и я расскажу, что звёзды приготовили для тебя ✨",
        reply_markup=keyboard,
        parse_mode="HTML"
    )

@dp.callback_query_handler(lambda c: c.data and c.data.startswith('horo_'))
async def process_horoscope(callback_query: types.CallbackQuery):
    """Обработчик выбора знака зодиака"""
    
    # Получаем знак из callback_data
    sign_key = callback_query.data.replace('horo_', '')
    
    # Находим название знака
    sign_name = next((name for name, key in ZODIAC_SIGNS.items() if key == sign_key), "Твой знак")
    
    # Показываем, что ищем
    await callback_query.answer()  # Закрываем уведомление
    status_msg = await callback_query.message.answer(f"🔮 Узнаю гороскоп для {sign_name}...")
    
    # Получаем гороскоп из API
    result = await get_horoscope(sign_key)
    
    # Удаляем сообщение о поиске
    await status_msg.delete()
    
    if result["success"] and result["data"]:
        data = result["data"]
        
        # Извлекаем данные из ответа API
        sign = data.get("sign", sign_name)
        date = data.get("date", datetime.now().strftime("%d.%m.%Y"))
        horoscope_text = data.get("text", "")
        mood = data.get("mood", "")
        lucky_number = data.get("lucky_number", "")
        lucky_color = data.get("lucky_color", "")
        
        # Формируем красивое сообщение
        response = f"🔮 <b>Гороскоп для {sign}</b>\n📅 на {date}\n\n{horoscope_text}\n"
        
        if mood:
            response += f"\n😊 Настроение: {mood}"
        if lucky_number:
            response += f"\n🔢 Счастливое число: {lucky_number}"
        if lucky_color:
            response += f"\n🎨 Цвет дня: {lucky_color}"
        
        response += "\n\n🌟 Хорошего дня!"
        
        await callback_query.message.answer(response, parse_mode="HTML")
    else:
        # Запасной вариант на случай ошибки API
        fallback = {
            "taurus": "Звёзды говорят, что сегодня Тельцам стоит обратить внимание на финансовые вопросы и быть открытыми к новым знакомствам.",
            "libra": "Весам сегодня звёзды рекомендуют уделить время семье и не бояться принимать важные решения.",
            "scorpio": "Скорпионов ждёт день, полный энергии и неожиданных поворотов — доверьтесь интуиции.",
            "pisces": "Рыбам сегодня стоит прислушаться к советам близких и не торопиться с выводами."
        }
        
        await callback_query.message.answer(
            f"🔮 <b>Гороскоп для {sign_name}</b>\n\n"
            f"{fallback.get(sign_key, 'Сегодня отличный день!')}\n\n"
            f"🌟 Хорошего дня!",
            parse_mode="HTML"
        )

# ================ ЗАПУСК ФОНОВЫХ ЗАДАЧ ================

async def start_background_tasks():
    """Запускает все фоновые задачи ТОЛЬКО ОДИН РАЗ и сохраняет ссылки"""
    global _tasks_started, BACKGROUND_TASKS
    if _tasks_started:
        logger.info("⏭️ Фоновые задачи уже запущены, пропускаем")
        return

    _tasks_started = True
    logger.info("🚀 Запуск фоновых задач...")

    # Создаем задачи и СОХРАНЯЕМ ссылки
    task1 = asyncio.create_task(game_timeout_checker())

    # Добавляем в глобальный список (сильная ссылка)
    BACKGROUND_TASKS.add(task1)

    # Автоматически удаляем из списка при завершении
    task1.add_done_callback(BACKGROUND_TASKS.discard)

    logger.info(f"✅ Запущено {len(BACKGROUND_TASKS)} фоновых задач")

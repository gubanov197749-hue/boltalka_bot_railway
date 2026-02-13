import openai
from openai.error import AuthenticationError, RateLimitError, APIConnectionError, APIError
import asyncio
import logging
import random
import sqlite3
import aiohttp
import json
from datetime import datetime
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from config import BOT_TOKEN, MEGANOVA_API_KEY

# ===== ДИАГНОСТИКА =====
import os
print(f"🔥 BOT_TOKEN = {os.getenv('BOT_TOKEN')}")
print(f"🔥 MEGANOVA_API_KEY = {os.getenv('MEGANOVA_API_KEY')}")
# ========================

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

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
    
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

# Создаем таблицы при запуске
init_db()

# ================ AI CHAT (MEGANOVA) ================
import openai
from openai.error import AuthenticationError, RateLimitError, APIConnectionError, APIError

# Настройка OpenAI-совместимого клиента для MegaNova
openai.api_key = MEGANOVA_API_KEY
openai.api_base = "https://api.meganova.ai/v1"

async def get_ai_response(prompt: str, chat_id: int = None) -> str:
    """Получение ответа от MegaNova API"""
    
    # Проверяем ключ (уже знаем, что он есть)
    if not MEGANOVA_API_KEY:
        logger.error("MEGANOVA_API_KEY пустой!")
        return "🔑 Ошибка: API ключ не найден."
    
    logger.info(f"🤖 Запрос к MegaNova: {prompt[:50]}...")
    
    try:
        import openai
        openai.api_key = MEGANOVA_API_KEY
        openai.api_base = "https://api.meganova.ai/v1"
        
        response = await openai.ChatCompletion.acreate(
            model="deepseek-ai/DeepSeek-V3-0324-Free",
            messages=[
                {"role": "system", "content": "Ты Болталка — весёлый бот. Отвечай коротко, с эмодзи."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8,
            max_tokens=250
        )
        
        result = response.choices[0].message.content
        logger.info(f"✅ Ответ получен")
        return result
        
    except Exception as e:
        logger.error(f"Ошибка MegaNova: {e}")
        return "😔 Ой, нейросеть временно не отвечает. Попробуй позже."

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

@dp.message_handler(commands=['help'])
async def cmd_help(message: types.Message):
    """Обработчик команды /help"""
    text = """📋 <b>Все команды бота:</b>

🎭 <b>Общение:</b>
• @бот [вопрос] — спроси меня о чём угодно
• /fact — случайный интересный факт
• /story — короткая история от нейросети

🏆 <b>Карма и рейтинги:</b>
• + — поставить плюсик (ответом на сообщение)
• /karma — моя карма
• /top — топ 10 пользователей

🎮 <b>Игры:</b>
• /crocodile — начать игру в Крокодила
• /duel @user — вызвать на дуэль
• /couple — выбрать пару дня

🔍 <b>Полезное:</b>
• /factcheck [утверждение] — проверить факт"""
    await message.reply(text)

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
    
    words = ["крокодил", "слон", "робот", "пицца", "самолёт", "кофе", 
             "гитара", "радуга", "космос", "шоколад", "интернет", "дружба"]
    word = random.choice(words)
    
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
            f"✅ {callback_query.from_user.first_name} подтверждён! Добро пожаловать в чат!"
        )
        add_karma(user_id, callback_query.message.chat.id, 3)
    else:
        await callback_query.answer("Это не твоя кнопка!", show_alert=True)
    await callback_query.answer()

@dp.message_handler(content_types=['text'])
async def ai_chat_handler(message: types.Message):
    """Обработка упоминаний бота"""
    # Получаем информацию о боте (безопасно)
    try:
        # Пытаемся получить username разными способами
        if hasattr(bot, 'username') and bot.username:
            bot_username = bot.username
        elif hasattr(bot, '_me') and bot._me:
            bot_username = bot._me.username
        else:
            # Если ничего нет - используем значение по умолчанию
            bot_username = "BoltalkaChatBot_bot"
    except:
        bot_username = "BoltalkaChatBot_bot"

    # Не отвечаем на команды
    if message.text.startswith('/'):
        return

    # Если бот упомянут - отвечаем
    if bot_username and f"@{bot_username}" in message.text.lower():
        prompt = message.text.replace(f"@{bot_username}", "").strip()
        response = await get_ai_response(prompt, message.chat.id)
        await message.reply(response)
    else:
        # На любое другое сообщение тоже отвечаем (для теста)
        response = await get_ai_response(message.text, message.chat.id)
        await message.reply(response)

import os
import logging
from flask import Flask, request, jsonify
import requests
from datetime import datetime
import asyncio
import traceback
import threading

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Импортируем бота
from bot import dp, bot, start_background_tasks
from aiogram import types
from config import BOT_TOKEN

# !!! ВАЖНО: устанавливаем текущий экземпляр бота
bot.set_current(bot)

# Создаем Flask приложение
app = Flask(__name__)

# ================ ЗАПУСК ФОНОВЫХ ЗАДАЧ В ОТДЕЛЬНОМ ПОТОКЕ ================
def run_background_tasks():
    """Запускает фоновые задачи в отдельном потоке со своим event loop"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(start_background_tasks())
        logger.info("✅ Фоновые задачи запущены в отдельном потоке")
    except Exception as e:
        logger.error(f"❌ Ошибка запуска фоновых задач: {e}")

# Запускаем в отдельном потоке, чтобы не мешать Flask
thread = threading.Thread(target=run_background_tasks, daemon=True)
thread.start()
logger.info("🚀 Поток для фоновых задач запущен")
# ===================================================================

@app.route('/')
def index():
    return '''<html>
        <head><title>Бот Болталка</title></head>
        <body style="font-family: Arial; text-align: center; margin-top: 50px;">
            <h1>🤖 Бот Болталка</h1>
            <p style="color: green; font-size: 24px;">✅ Бот запущен и работает!</p>
            <p>Telegram: <b>@BoltalkaChatBot_bot</b></p>
            <p><a href="/webhook_info">Проверить вебхук</a> | <a href="/set_webhook">Установить вебхук</a></p>
        </body>
    </html>'''

@app.route('/webhook', methods=['POST'])
def webhook():
    """Синхронная версия вебхука"""
    if request.method == 'POST':
        try:
            update_data = request.get_json()
            logger.info(f"Получено обновление: {update_data.get('update_id')}")
            
            # Создаем новый цикл событий для каждого запроса
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Обрабатываем обновление
            update = types.Update(**update_data)
            loop.run_until_complete(dp.process_update(update))
            
            loop.close()
            return 'OK', 200
        except Exception as e:
            logger.error(f"Ошибка обработки вебхука: {e}")
            logger.error(traceback.format_exc())
            return 'Error', 500
    return 'Method not allowed', 405

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Установка вебхука"""
    try:
        railway_url = os.getenv('RAILWAY_STATIC_URL')
        if not railway_url:
            railway_url = os.getenv('RAILWAY_PUBLIC_DOMAIN')
        
        if not railway_url:
            return "❌ Ошибка: Не удалось определить URL приложения", 500
        
        webhook_url = f"https://{railway_url}/webhook"
        
        # Удаляем старый вебхук
        requests.get(f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook")
        
        # Устанавливаем новый
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        response = requests.post(url, json={
            'url': webhook_url,
            'allowed_updates': ['message', 'callback_query', 'chat_member', 'new_chat_members']
        })
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                return f"✅ Webhook успешно установлен на {webhook_url}", 200
        
        return f"❌ Ошибка: {response.text}", 500
    except Exception as e:
        logger.error(traceback.format_exc())
        return f"❌ Ошибка: {str(e)}", 500

@app.route('/delete_webhook', methods=['GET'])
def delete_webhook():
    """Удаление вебхука"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
        response = requests.get(url)
        return "✅ Webhook удален", 200
    except Exception as e:
        return f"❌ Ошибка: {str(e)}", 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Информация о вебхуке"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
        response = requests.get(url)
        return jsonify(response.json()), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'healthy', 'timestamp': datetime.now().isoformat()}), 200

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

import os
import logging
import asyncio
from flask import Flask, request, jsonify
import requests
from datetime import datetime

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Импортируем бота
from bot import dp, bot
from aiogram import types
from config import WEBHOOK_URL, BOT_TOKEN

# Создаем Flask приложение
app = Flask(__name__)

@app.route('/')
def index():
    """Главная страница - проверка что бот работает"""
    return '''
    <html>
        <head>
            <title>Бот Болталка</title>
            <style>
                body { font-family: Arial, sans-serif; margin: 40px; text-align: center; }
                h1 { color: #2c3e50; }
                .success { color: #27ae60; font-size: 24px; margin: 20px; }
                .info { color: #34495e; margin: 10px; }
            </style>
        </head>
        <body>
            <h1>🤖 Бот Болталка</h1>
            <div class="success">✅ Бот запущен и работает!</div>
            <div class="info">Telegram: @BoltalkaChatBot_bot</div>
            <div class="info">
                <a href="/webhook_info">Проверить вебхук</a> | 
                <a href="/set_webhook">Установить вебхук</a>
            </div>
        </body>
    </html>
    '''

@app.route('/webhook', methods=['POST'])
async def webhook():
    """Принимаем обновления от Telegram"""
    if request.method == 'POST':
        try:
            update_data = request.get_json()
            logger.info(f"Получено обновление: {update_data.get('update_id')}")
            update = types.Update(**update_data)
            await dp.process_update(update)
            return 'OK', 200
        except Exception as e:
            logger.error(f"Ошибка обработки вебхука: {e}")
            return 'Error', 500
    return 'Method not allowed', 405

@app.route('/set_webhook', methods=['GET'])
def set_webhook():
    """Установка вебхука для бота"""
    try:
        railway_url = os.getenv('RAILWAY_PUBLIC_DOMAIN')
        if not railway_url:
            railway_url = os.getenv('RAILWAY_STATIC_URL')
        
        if not railway_url:
            return "❌ Ошибка: Не удалось определить URL приложения", 500
        
        webhook_url = f"https://{railway_url}/webhook"
        
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
        response = requests.post(url, json={
            'url': webhook_url,
            'allowed_updates': ['message', 'callback_query', 'chat_member', 'new_chat_members']
        })
        
        if response.status_code == 200:
            result = response.json()
            if result.get('ok'):
                return f'''
                <html>
                    <head><title>Webhook установлен</title></head>
                    <body style="font-family: Arial; margin: 40px;">
                        <h1 style="color: #27ae60;">✅ Webhook успешно установлен!</h1>
                        <p>URL: <code>{webhook_url}</code></p>
                        <p>Ответ Telegram: {result}</p>
                        <p><a href="/">Вернуться на главную</a></p>
                    </body>
                </html>
                '''
        
        return f"❌ Ошибка установки вебхука: {response.text}", 500
    except Exception as e:
        logger.error(f"Ошибка установки вебхука: {e}")
        return f"❌ Ошибка: {str(e)}", 500

@app.route('/delete_webhook', methods=['GET'])
def delete_webhook():
    """Удаление вебхука"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/deleteWebhook"
        response = requests.get(url)
        result = response.json()
        if result.get('ok'):
            return "✅ Webhook успешно удален!", 200
        return f"❌ Ошибка удаления: {result}", 500
    except Exception as e:
        return f"❌ Ошибка: {str(e)}", 500

@app.route('/webhook_info', methods=['GET'])
def webhook_info():
    """Информация о текущем вебхуке"""
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/getWebhookInfo"
        response = requests.get(url)
        result = response.json()
        
        if result.get('ok'):
            info = result.get('result', {})
            webhook_url = info.get('url', 'не установлен')
            
            html = f'''
            <html>
                <head><title>Информация о вебхуке</title></head>
                <body style="font-family: Arial; margin: 40px;">
                    <h1>🔍 Информация о вебхуке</h1>
                    <p><b>URL:</b> <code>{webhook_url}</code></p>
                    <p><b>Ожидает обновлений:</b> {info.get('pending_update_count', 0)}</p>
                    <p><b>Последняя ошибка:</b> {info.get('last_error_message', 'нет')}</p>
                    <p><b>Последняя ошибка в:</b> {info.get('last_error_date', 'никогда')}</p>
                    <p><a href="/">На главную</a> | <a href="/set_webhook">Переустановить</a></p>
                </body>
            </html>
            '''
            return html, 200
        
        return f"❌ Ошибка: {result}", 500
    except Exception as e:
        return f"❌ Ошибка: {str(e)}", 500

@app.route('/health', methods=['GET'])
def health():
    """Проверка здоровья для Railway"""
    return jsonify({
        'status': 'healthy',
        'bot': 'running',
        'timestamp': datetime.now().isoformat()
    }), 200

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Not found'}), 404

@app.errorhandler(500)
def internal_error(e):
    return jsonify({'error': 'Internal server error'}), 500

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

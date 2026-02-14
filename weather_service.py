import aiohttp
import logging
import asyncio
from datetime import datetime
import pytz
from typing import Dict, Tuple

logger = logging.getLogger(__name__)

# Координаты городов (можно заменить на названия для геокодинга)
CITIES = {
    "Славянск-на-Кубани": {"lat": 45.2558, "lon": 38.1256},
    "Липецк": {"lat": 52.6031, "lon": 39.5708}
}

# Бесплатный API Open-Meteo (не требует ключа)
WEATHER_API_URL = "https://api.open-meteo.com/v1/forecast"

async def get_weather(city_name: str) -> Tuple[str, Dict]:
    """
    Получает погоду для указанного города через Open-Meteo API
    Возвращает (статус, данные_погоды)
    """
    try:
        coords = CITIES.get(city_name)
        if not coords:
            return "error", {"message": f"Город {city_name} не найден"}
        
        params = {
            "latitude": coords["lat"],
            "longitude": coords["lon"],
            "current": ["temperature_2m", "weather_code", "wind_speed_10m", "relative_humidity_2m"],
            "daily": ["temperature_2m_max", "temperature_2m_min", "weather_code"],
            "timezone": "Europe/Moscow",
            "forecast_days": 1
        }
        
        async with aiohttp.ClientSession() as session:
            async with session.get(WEATHER_API_URL, params=params) as response:
                if response.status == 200:
                    data = await response.json()
                    return "success", data
                else:
                    logger.error(f"Ошибка API погоды: {response.status}")
                    return "error", {"message": f"Ошибка API: {response.status}"}
                    
    except Exception as e:
        logger.error(f"Исключение при получении погоды: {e}")
        return "error", {"message": str(e)}

async def get_weather_with_retry(city_name: str, max_retries: int = 3):
    """Получает погоду с повторными попытками при ошибках"""
    for attempt in range(max_retries):
        status, data = await get_weather(city_name)
        
        if status == "success":
            return status, data
        
        # Если ошибка 429 (слишком много запросов)
        if data.get("message") and "429" in str(data.get("message")):
            wait_time = 2 ** attempt  # экспоненциальная задержка: 1, 2, 4 секунды
            logger.warning(f"⚠️ Лимит API, повтор через {wait_time}с (попытка {attempt+1}/{max_retries})")
            await asyncio.sleep(wait_time)
        else:
            # Другие ошибки не повторяем
            break
    
    return "error", data

def get_weather_emoji(weather_code: int) -> str:
    """Преобразует код погоды Open-Meteo в эмодзи """
    weather_codes = {
        0: "☀️", 1: "🌤️", 2: "⛅", 3: "☁️",
        45: "🌫️", 48: "🌫️",
        51: "🌧️", 53: "🌧️", 55: "🌧️",
        61: "🌧️", 63: "🌧️", 65: "🌧️",
        71: "❄️", 73: "❄️", 75: "❄️", 77: "❄️",
        80: "🌧️", 81: "🌧️", 82: "🌧️",
        85: "❄️", 86: "❄️",
        95: "⛈️", 96: "⛈️", 99: "⛈️",
    }
    return weather_codes.get(weather_code, "🌈")

def format_weather_message(city: str, weather_data: Dict) -> str:
    """
    Форматирует красивое сообщение о погоде с приветствием
    """
    try:
        current = weather_data.get("current", {})
        daily = weather_data.get("daily", {})
        
        # Текущая погода
        temp = current.get("temperature_2m", "?")
        wind = current.get("wind_speed_10m", "?")
        humidity = current.get("relative_humidity_2m", "?")
        weather_code = current.get("weather_code", 0)
        weather_emoji = get_weather_emoji(weather_code)
        
        # Прогноз на день
        max_temp = daily.get("temperature_2m_max", [temp])[0] if daily.get("temperature_2m_max") else temp
        min_temp = daily.get("temperature_2m_min", [temp])[0] if daily.get("temperature_2m_min") else temp
        
        # Определяем время суток для приветствия
        moscow_tz = pytz.timezone('Europe/Moscow')
        current_time = datetime.now(moscow_tz)
        hour = current_time.hour
        
        if 5 <= hour < 12:
            greeting = "Доброе утро"
        elif 12 <= hour < 18:
            greeting = "Добрый день"
        elif 18 <= hour < 23:
            greeting = "Добрый вечер"
        else:
            greeting = "Доброй ночи"
        
        # Формируем сообщение
        message = (
            f"🌅 *{greeting}, дорогие!*\n\n"
            f"🏙️ *Погода в {city}* {weather_emoji}\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"🌡️ Сейчас: *{temp:.1f}°C*\n"
            f"📊 За день: от *{min_temp:.1f}°C* до *{max_temp:.1f}°C*\n"
            f"💨 Ветер: *{wind:.1f} м/с*\n"
            f"💧 Влажность: *{humidity}%*\n"
            f"━━━━━━━━━━━━━━━━\n"
            f"☕ Хорошего дня и отличного настроения!\n"
            f"🌸 Ваша Болталка"
        )
        
        return message
        
    except Exception as e:
        logger.error(f"Ошибка форматирования погоды: {e}")
        return f"❌ Не удалось получить погоду для {city}. Попробую позже."

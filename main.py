

import asyncio
import aiohttp
from aiogram import Bot, Dispatcher, Router, types
from aiogram.filters import Command

API_TOKEN = "8454009227:AAHP3Q1HArGgcr519se0Qye4x7eQp4-cjZ4"
WEBAPP_BASE = "https://script.google.com/macros/s/AKfycbzBysv3Fm1zgUf2Z7qWp-yC8pJHpBACrAd0ALpqoUmbjZ9Czl_lmvK2nZg0bAnIEfSS/exec"  # URL вашего Web App

bot = Bot(token=API_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# 📌 Команда /start
@router.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        "Привет! Чтобы записаться, отправьте данные в формате:\n\n"
        "Имя, Телефон, Услуга, Дата(YYYY-MM-DD), Время(HH:MM)\n\n"
        "Например:\nАйгуль, 87001234567, Маникюр, 2025-12-01, 10:00"
    )

# 📌 Обработка записи
@router.message()
async def record_handler(message: types.Message):
    try:
        # Разбираем сообщение
        parts = [p.strip() for p in message.text.split(",")]
        if len(parts) != 5:
            await message.answer("⚠️ Формат неверный. Нужно: Имя, Телефон, Услуга, Дата, Время")
            return

        name, phone, service, date, time = parts
        payload = {
            "Имя": name,
            "Телефон": phone,
            "Услуга": service,
            "Дата": date,
            "Время": time
        }

        # Отправляем POST в Web App
        async with aiohttp.ClientSession() as session:
            async with session.post(WEB_APP_URL, json=payload) as resp:
                data = await resp.json()

        # Обрабатываем ответ
        if data["status"] == "ok":
            await message.answer(data["message"])
        elif data["status"] == "busy":
            before = ", ".join(data["suggestions"]["before"])
            after = ", ".join(data["suggestions"]["after"])
            await message.answer(
                f"❌ Время занято.\n\n"
                f"Возможные варианты:\n"
                f"До: {before if before else 'нет'}\n"
                f"После: {after if after else 'нет'}"
            )
        else:
            await message.answer("Ошибка: " + data.get("message", "Неизвестно"))
    except Exception as e:
        await message.answer(f"⚠️ Ошибка обработки: {e}")

# 📌 Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

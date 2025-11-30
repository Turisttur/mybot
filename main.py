
import os
import logging
import json
import aiohttp
import asyncio
import pytz
from datetime import datetime, timedelta, time
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

# Длительность услуг в часах (берётся из листа «Услуги»)
DURATION_MAP = {
    "Медицинская подология": 1.5,
    "Эстетический маникюр": 1.0,
    "Педикюр премиум": 2.0,
    "Наращивание ресниц": 1.0,
    "Коррекция бровей": 0.5,
    "Прокалывание ушей": 0.5,
    "Визаж Макияж": 1.0
}

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6734540756"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # например https://bot-k7rs.onrender.com/webhook
# WEB_APP_URL = "https://script.google.com/macros/s/AKfycbwtNHEI30kUAnBXZBtYldQd5g6k-ANYsHnJ_bLokI-n9MqX_coozbiMjygG11xiVgc/exec"
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
if not WEBAPP_URL:
    raise ValueError("❌ WEBAPP_URL не задан в переменных окружения!")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

TIMEZONE = pytz.timezone("Asia/Almaty")

class Booking(StatesGroup):
    choosing_service = State()
    entering_name = State()
    entering_phone = State()
    choosing_day = State()
    choosing_time = State()

# === Запрос слотов из WebApp ===
async def get_slots():
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(WEBAPP_URL) as resp:
                text = await resp.text()
                # Проверяем, что ответ действительно JSON
                result = json.loads(text)
                return result.get("slots", [])
    except Exception as e:
        print(f"❌ Ошибка получения слотов: {e}")
        return []


# === Клавиатуры ===
def build_days_kb(slots):
    buttons = []
    dates = sorted(set(slot["Дата"] for slot in slots))
    for date in dates:
        buttons.append([InlineKeyboardButton(text=date, callback_data=f"day_{date}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def build_times_kb(slots, date):
    buttons = []
    for slot in slots:
        if slot["Дата"] == date:
            if slot["status"] == "free":
                buttons.append([InlineKeyboardButton(
                    text=f"{slot['Время']} ✅",
                    callback_data=f"time_{slot['Время']}"
                )])
            else:
                buttons.append([InlineKeyboardButton(
                    text=f"{slot['Время']} ❌",
                    callback_data="busy"
                )])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# === Отправка записи в WebApp ===
async def send_booking(name, phone, service, date, time):
    payload = {
        "Имя": name,
        "Телефон": phone,
        "Услуга": service,
        "Дата": date,
        "Время": time
    }
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(WEBAPP_URL, json=payload) as resp:
                text = await resp.text()
                return json.loads(text)
    except Exception as e:
        print(f"❌ Ошибка записи: {e}")
        return {"status": "error", "message": str(e)}

# === Хэндлеры ===
@router.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="book")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="contact")]
    ])
    await msg.answer("🌸 Добро пожаловать в ASEM PODO @ BEAUTY!", reply_markup=kb)

@router.callback_query(F.data == "main")
async def main_menu(cb: CallbackQuery, state: FSMContext):
    await start(cb.message, state)

@router.callback_query(F.data == "book")
async def book(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Booking.choosing_service)
    buttons = [
        [InlineKeyboardButton(text="Медицинская подология", callback_data="srv_Медицинская подология")],
        [InlineKeyboardButton(text="Эстетический маникюр", callback_data="srv_Эстетический маникюр")],
        [InlineKeyboardButton(text="Педикюр премиум", callback_data="srv_Педикюр премиум")],
        [InlineKeyboardButton(text="Наращивание ресниц", callback_data="srv_Наращивание ресниц")],
        [InlineKeyboardButton(text="Коррекция бровей", callback_data="srv_Коррекция бровей")],
        [InlineKeyboardButton(text="Прокалывание ушей", callback_data="srv_Прокалывание ушей")],
        [InlineKeyboardButton(text="Визаж Макияж", callback_data="srv_Визаж Макияж")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ]
    await cb.message.edit_text("Выберите услугу:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("srv_"))
async def srv(cb: CallbackQuery, state: FSMContext):
    service = cb.data[4:]
    await state.update_data(service=service)
    await state.set_state(Booking.entering_name)
    await cb.message.edit_text("Введите ваше имя:")

@router.message(Booking.entering_name)
async def name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text)
    await state.set_state(Booking.entering_phone)
    await msg.answer("Введите ваш телефон:")

@router.message(Booking.entering_phone)
async def phone(msg: Message, state: FSMContext):
    await state.update_data(phone=msg.text)
    await state.set_state(Booking.choosing_day)
    slots = await get_slots()
    kb = build_days_kb(slots)
    await msg.answer("Выберите день:", reply_markup=kb)

@router.callback_query(F.data.startswith("day_"))
async def day(cb: CallbackQuery, state: FSMContext):
    date = cb.data[4:]
    await state.update_data(date=date)
    await state.set_state(Booking.choosing_time)
    slots = await get_slots()
    kb = build_times_kb(slots, date)
    await cb.message.edit_text(f"Выберите время на {date}:", reply_markup=kb)

@router.callback_query(F.data.startswith("time_"))
async def time(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data:
        await cb.message.answer("⚠️ Сессия устарела. Начните с /start.")
        await state.clear()
        return

    service = data.get("service", "не указана")
    name = data.get("name", "—")
    phone = data.get("phone", "—")
    date_str = data.get("date")
    tm = cb.data[5:]

    result = await send_booking(name, phone, service, date_str, tm)

    if result.get("status") == "ok":
        await cb.message.edit_text(result["message"])
    elif result.get("status") == "busy":
        text = result["message"]
        suggestions = result.get("suggestions", [])
        if suggestions:
            text += "\n\n💡 Предлагаем:\n"
            for s in suggestions[:3]:
                text += f"• {s['Дата']} в {s['Время']}\n"
        await cb.message.edit_text(text)
    else:
        await cb.message.edit_text(f"❌ Сервер: {result.get('message', 'ошибка')}")

    await state.clear()

@router.callback_query(F.data == "contact")
async def contact(cb: CallbackQuery):
    text = (
        "📍 *Аягоз, ул. Актамберды, 23*\n"
        "🕒 *Пн–Пт:* 10:00–20:00\n"
        "🕒 *Сб:* 10:00–18:00\n"
        "📱 +7 777 123 45 67\n"
        "🌐 [asem-podo.pages.dev](https://asem-podo.pages.dev)"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 WhatsApp", url="https://wa.me/77771234567")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ])
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

# === FastAPI для webhook ===
app = FastAPI()

@app.on_event("startup")
async def on_startup():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook("https://bot-k7rs.onrender.com/webhook")  # замените на ваш Render-домен

@app.post("/webhook")
async def telegram_webhook(request: Request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.get("/")
async def root():
    return {"status": "бот запущен"}

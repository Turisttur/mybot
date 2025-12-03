# bot.py — ASEM PODO (исправленная логика слотов, старый Apps Script)
import os
import json
import logging
from datetime import datetime, timedelta
import asyncio
import aiohttp
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# === Настройки (замените на свои) ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "8454009227:AAEV5eAl8L3pxUC_JQa6FI8dsJAZ2yHtdQc")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6734540756"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://asem-podo-bot.onrender.com/webhook").strip()
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://script.google.com/macros/s/AKfycbwYowZ-08UQL1Dh0HorTcBB9liso9l64eiuplqPqspwX66YCXMR8DLQWNhVcjNoTB0p/exec").strip()

if not BOT_TOKEN or "YOUR_TOKEN" in BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан")

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

class Booking(StatesGroup):
    choosing_service = State()
    entering_name = State()
    entering_phone = State()
    choosing_day = State()
    choosing_time = State()

# === Генерация рабочих слотов (с перерывом 12:30–14:00) ===
def get_working_slots(date_str: str) -> list[str]:
    """Возвращает список рабочих слотов для даты в формате 'YYYY-MM-DD'."""
    day = datetime.strptime(date_str, "%Y-%m-%d")
    wd = day.weekday()  # 0=пн, 6=вс
    
    # Воскресенье — выходной
    if wd == 6:
        return []
    
    slots = []
    
    # Утро: 10:00–12:30 (шаг 30 мин)
    current = datetime(day.year, day.month, day.day, 10, 0)
    end_morning = datetime(day.year, day.month, day.day, 12, 30)
    while current < end_morning:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    
    # Вечер: 14:00–20:00 (пн–пт) или 18:00 (сб)
    end_evening_hour = 20 if wd < 5 else 18
    current = datetime(day.year, day.month, day.day, 14, 0)
    end_evening = datetime(day.year, day.month, day.day, end_evening_hour, 0)
    while current < end_evening:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    
    return slots

# === Хэндлеры ===
@router.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="book")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="contact")]
    ])
    await msg.answer("🌸 Добро пожаловать в ASEM PODO @ BEAUTY!", reply_markup=kb)

@router.callback_query(F.data == "book")
async def book(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Booking.choosing_service)
    buttons = [
        [InlineKeyboardButton(text="Медицинская подология", callback_data="srv_Медицинская подология")],
        [InlineKeyboardButton(text="Эстетический маникюр", callback_data="srv_Эстетический маникюр")],
        [InlineKeyboardButton(text="Педикюр премиум", callback_data="srv_Педикюр премиум")],
        [InlineKeyboardButton(text="Визаж", callback_data="srv_Визаж")],
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
    
    # Генерируем 14 дней вперёд
    today = datetime.now()
    buttons = []
    for i in range(14):
        day = today + timedelta(days=i)
        wd = day.weekday()
        if wd == 6:  # Воскресенье — пропускаем
            continue
        text = "Сегодня" if i == 0 else "Завтра" if i == 1 else day.strftime("%d %b")
        date_key = day.strftime("%Y-%m-%d")
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"day_{date_key}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await msg.answer("Выберите день:", reply_markup=kb)

@router.callback_query(F.data.startswith("day_"))
async def day(cb: CallbackQuery, state: FSMContext):
    date_key = cb.data[4:]  # YYYY-MM-DD
    await state.update_data(date=date_key)
    await state.set_state(Booking.choosing_time)
    
    slots = get_working_slots(date_key)
    buttons = []
    for i in range(0, len(slots), 3):
        row = [InlineKeyboardButton(text=t, callback_data=f"time_{t}") for t in slots[i:i+3]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.edit_text(f"Выберите время на {date_key}:", reply_markup=kb)

@router.callback_query(F.data.startswith("time_"))
async def time(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not 
        await cb.message.answer("⚠️ Сессия устарела. Начните с /start.")
        await state.clear()
        return

    service = data.get("service", "—")
    name = data.get("name", "—")
    phone = data.get("phone", "—")
    date_str = data.get("date", "—")  # YYYY-MM-DD
    time_str = cb.data[5:]            # HH:MM

    # ✅ ФОРМАТ ДАННЫХ ДЛЯ СТАРОГО APPS SCRIPT:
    # Дата: dd.MM.yyyy, Время: HH:mm
    date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m.%Y")

    payload = {
        "Имя": name,
        "Телефон": phone,
        "Услуга": service,
        "Дата": date_display,   # ← 03.12.2025
        "Время": time_str,      # ← 10:00
        "ДлительностьЧасы": 1.0
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(WEBAPP_URL, json=payload) as resp:
                result = await resp.json()
    except Exception as e:
        print(f"❌ WebApp error: {e}")
        await cb.message.edit_text("❌ Не удалось отправить запись.")
        return

    if result.get("status") == "ok":
        await cb.message.edit_text(result["message"])
        # Уведомление админу
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"🆕 Новая запись!\n📅 {date_display}\n⏰ {time_str}\n💅 {service}\n👤 {name}\n📱 {phone}"
        )
    elif result.get("status") == "busy":
        await cb.message.edit_text("⛔ Это время занято. Выберите другое.")
    else:
        await cb.message.edit_text(f"❌ Ошибка: {result.get('message', 'неизвестно')}")

    await state.clear()

@router.callback_query(F.data == "contact")
async def contact(cb: CallbackQuery):
    text = (
        "📍 *Аягоз, ул. Актамберды, 23*\n"
        "🕒 *Пн–Пт:* 10:00–12:30, 14:00–20:00\n"
        "🕒 *Сб:* 10:00–12:30, 14:00–18:00\n"
        "📱 +7 777 123 45 67"
        "🌐 [asem-podo.pages.dev](https://asem-podo.pages.dev)"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 WhatsApp", url="https://wa.me/77771234567")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ])
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

# === FastAPI (обязательно для Render) ===
app = FastAPI()

@app.on_event("startup")
async def startup():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)

@app.post("/webhook")
async def webhook(request: Request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

# Health-check для Render
@app.get("/healthz")
@app.head("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok"}

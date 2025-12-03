# bot.py — ASEM PODO (финальная версия: никаких накладок, только рабочее время)
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

# === Настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6734540756"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
SLOTS_URL = os.getenv("SLOTS_URL", "").strip()
BOOKING_URL = os.getenv("BOOKING_URL", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан")

# Длительность услуг (часы)
DURATION_MAP = {
    "Медицинская подология": 2.0,
    "Эстетический маникюр": 2.0,
    "Педикюр премиум": 2.0,
    "Наращивание ресниц": 1.0,
    "Коррекция бровей": 0.5,
    "Прокалывание ушей": 0.5,
    "Визаж Макияж": 1.5
}

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

# === ГЕНЕРАЦИЯ ТОЛЬКО РАБОЧИХ СЛОТОВ (с перерывом) ===
def get_working_slots(date_iso: str) -> list[str]:
    """Возвращает список ВРЕМЕННЫХ МЕТОК (HH:MM) для даты в формате '2025-12-03'."""
    day = datetime.fromisoformat(date_iso)
    wd = day.weekday()  # 0=пн, 6=вс
    
    if wd == 6:  # воскресенье — выходной
        return []

    slots = []
    
    # Утро: 10:00 → 12:30 (включительно), шаг 30 мин
    current = day.replace(hour=10, minute=0, second=0, microsecond=0)
    end_morning = day.replace(hour=12, minute=30, second=0, microsecond=0)
    while current <= end_morning:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    
    # Вечер: 14:00 → 20:00 (пн–пт) или 18:00 (сб)
    end_hour = 20 if wd < 5 else 18
    current = day.replace(hour=14, minute=0, second=0, microsecond=0)
    end_evening = day.replace(hour=end_hour, minute=0, second=0, microsecond=0)
    while current < end_evening:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    
    return slots

# === ОТПРАВКА В СТАРЫЙ APPS SCRIPT (формат dd.MM.yyyy) ===
async def send_to_webapp(name: str, phone: str, service: str, date_iso: str, time_str: str):
    # Преобразуем 2025-12-03 → 03.12.2025
    dt = datetime.fromisoformat(date_iso)
    date_display = dt.strftime("%d.%m.%Y")
    
    payload = {
        "Имя": name.strip(),
        "Телефон": phone.strip(),
        "Услуга": service.strip(),
        "Дата": date_display,        # ← критично для старого Apps Script
        "Время": time_str,           # ← "10:00", "14:30"
        "ДлительностьЧасы": DURATION_MAP.get(service, 1.0)
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(WEBAPP_URL, json=payload) as resp:
                text = await resp.text()
                try:
                    return json.loads(text)
                except json.JSONDecodeError:
                    # Логируем сырой ответ при ошибке
                    print(f"⚠️ Не JSON от WebApp: {text[:200]}")
                    return {"status": "error", "message": "Некорректный ответ от сервера"}
    except Exception as e:
        print(f"❌ WebApp exception: {e}")
        return {"status": "error", "message": f"Ошибка подключения: {e}"}

# === ХЭНДЛЕРЫ ===
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
        [InlineKeyboardButton(text=t, callback_data=f"srv_{t}")] 
        for t in DURATION_MAP.keys()
    ] + [[InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]]
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
    
    # Генерация 14 дней вперёд (только будни и сб)
    today = datetime.now()
    buttons = []
    for i in range(14):
        day = today + timedelta(days=i)
        if day.weekday() == 6:  # воскресенье — пропускаем
            continue
        text = "Сегодня" if i == 0 else "Завтра" if i == 1 else day.strftime("%d %b")
        date_key = day.strftime("%Y-%m-%d")
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"day_{date_key}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await msg.answer("Выберите день:", reply_markup=kb)

@router.callback_query(F.data.startswith("day_"))
async def day(cb: CallbackQuery, state: FSMContext):
    date_iso = cb.data[4:]  # 2025-12-03
    await state.update_data(date=date_iso)
    await state.set_state(Booking.choosing_time)
    
    slots = get_working_slots(date_iso)  # ← ТОЛЬКО 10:00–12:30 и 14:00–...
    buttons = []
    for i in range(0, len(slots), 3):
        row = [InlineKeyboardButton(text=t, callback_data=f"time_{t}") for t in slots[i:i+3]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.edit_text(f"Выберите время на {date_iso}:", reply_markup=kb)

@router.callback_query(F.data.startswith("time_"))
async def time(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data:
        await cb.message.answer("⚠️ Сессия устарела. Начните с /start.")
        await state.clear()
        return

    service = data.get("service", "—")
    name = data.get("name", "—")
    phone = data.get("phone", "—")
    date_iso = data.get("date", "—")
    time_str = cb.data[5:]  # "10:00"

    # ✅ Проверка: не попали ли мы в перерыв (должно быть невозможно, но на всякий)
    hour = int(time_str.split(':')[0])
    minute = int(time_str.split(':')[1])
    if (12 <= hour < 14) or (hour == 12 and minute >= 30):
        await cb.answer("❌ Это время в перерыве. Выберите другое.", show_alert=True)
        return

    result = await send_to_webapp(name, phone, service, date_iso, time_str)

    if result.get("status") == "ok":
        # Подтверждение клиенту
        dt = datetime.fromisoformat(date_iso)
        date_display = dt.strftime("%d.%m.%Y")
        await cb.message.edit_text(f"✅ Запись подтверждена!\n📅 {date_display}\n⏰ {time_str}\n💅 {service}")
        # Уведомление админу
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"🆕 Новая запись!\n📅 {date_display}\n⏰ {time_str}\n💅 {service}\n👤 {name}\n📱 {phone}"
        )
    elif result.get("status") == "busy":
        await cb.message.edit_text("⛔ Это время занято. Выберите другое.")
    else:
        await cb.message.edit_text(f"❌ Ошибка сервера: {result.get('message', 'неизвестно')}")

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

# === FastAPI (для Render) ===
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

# Health-check (обязательно для Render)
@app.get("/healthz")
@app.head("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok"}

# bot.py — ASEM PODO (финал: никаких ошибок, только рабочее время)
import zoneinfo
TZ = zoneinfo.ZoneInfo("Asia/Almaty")
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

# === 1. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ (обязательно в начале!) ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6734540756"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
SLOTS_URL = os.getenv("SLOTS_URL", "").strip()      # для GET / doGet
BOOKING_URL = os.getenv("BOOKING_URL", "").strip()  # для POST / doPost

# Проверка обязательных переменных
if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан")
if not BOOKING_URL:
    raise RuntimeError("❌ BOOKING_URL не задан")
if not WEBHOOK_URL:
    raise RuntimeError("❌ WEBHOOK_URL не задан")

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

# === 2. ИНИЦИАЛИЗАЦИЯ ===
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

# === 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def get_working_slots(date_iso: str) -> list[str]:
    """Генерирует слоты ТОЛЬКО в рабочее время: 10:00–12:30, 14:00–20:00/18:00"""
    day = datetime.fromisoformat(date_iso)
    wd = day.weekday()
    if wd == 6:  # воскресенье — выходной
        return []
    
    slots = []
    # Утро: 10:00–12:30
    current = day.replace(hour=10, minute=0)
    end = day.replace(hour=12, minute=30)
    while current <= end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    
    # Вечер: 14:00–20:00 (пн–пт) или 18:00 (сб)
    end_hour = 20 if wd < 5 else 18
    current = day.replace(hour=14, minute=0)
    end = day.replace(hour=end_hour, minute=0)
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    
    return slots

async def send_booking(name: str, phone: str, service: str, date_display: str, time_str: str):
    """
    Отправляет запись в Apps Script.
    date_display — ОБЯЗАТЕЛЬНО в формате '04.12.2025' (dd.MM.yyyy)
    """
    payload = {
        "Имя": name.strip(),
        "Телефон": phone.strip(),
        "Услуга": service.strip(),
        "Дата": date_display,        # ← ожидает dd.MM.yyyy
        "Время": time_str,
        "ДлительностьЧасы": DURATION_MAP.get(service, 1.0)
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(BOOKING_URL, json=payload) as resp:
                return await resp.json()
    except Exception as e:
        logging.error(f"❌ send_booking error: {e}")
        return {"status": "error", "message": str(e)}

# === 4. ХЭНДЛЕРЫ ===
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
    buttons = [[InlineKeyboardButton(text=t, callback_data=f"srv_{t}")] for t in DURATION_MAP.keys()]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    await cb.message.edit_text("Выберите услугу:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@router.callback_query(F.data.startswith("srv_"))
async def srv(cb: CallbackQuery, state: FSMContext):
    service = cb.data[4:]
    await state.update_data(service=service)
    await state.set_state(Booking.entering_name)
    await cb.message.edit_text("Введите ваше имя:")

@router.message(Booking.entering_phone)
async def phone(msg: Message, state: FSMContext):
    await state.update_data(phone=msg.text)
    await state.set_state(Booking.choosing_day)
    
    # Локальное время (Алматы / Астана — UTC+5)
    now = datetime.now(TZ).replace(tzinfo=None)  # naive datetime в локальном времени
    # await msg.answer(f"🕒 Локальное время: {now.strftime('%d.%m %H:%M')}")  # отладка — можно временно раскомментировать

    buttons = []

    for i in range(14):
        day = now + timedelta(days=i)
        if day.weekday() == 6:  # воскресенье — пропускаем
            continue

        if i == 0:
            date_iso = day.strftime("%Y-%m-%d")
            slots_today = get_working_slots(date_iso)
            current_time_str = now.strftime("%H:%M")  # напр. "22:00"
            future_slots = [s for s in slots_today if s > current_time_str]
            if not future_slots:
                continue  # пропускаем "Сегодня"

        text = "Сегодня" if i == 0 else "Завтра" if i == 1 else day.strftime("%d %b")
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"day_{day.strftime('%Y-%m-%d')}")])

    if not buttons:
        await msg.answer("К сожалению, свободных дней нет в ближайшие 2 недели.")
        await state.clear()
        return

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await msg.answer("Выберите день:", reply_markup=kb)

@router.callback_query(F.data.startswith("day_"))
async def day(cb: CallbackQuery, state: FSMContext):
    date_iso = cb.data[4:]  # 2025-12-04
    await state.update_data(date=date_iso)
    await state.set_state(Booking.choosing_time)
    
    slots = get_working_slots(date_iso)
    buttons = []
    for i in range(0, len(slots), 3):
        row = [InlineKeyboardButton(text=t, callback_data=f"time_{t}") for t in slots[i:i+3]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.edit_text(f"Выберите время:", reply_markup=kb)

@router.callback_query(F.data.startswith("time_"))
async def time(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data:  # ✅ ИСПРАВЛЕНО: if not data → if not data:
        await cb.message.answer("⚠️ Сессия устарела. Начните с /start.")
        await state.clear()
        return

    service = data.get("service", "—")
    name = data.get("name", "—")
    phone = data.get("phone", "—")
    date_iso = data.get("date", "—")  # 2025-12-04
    time_str = cb.data[5:]            # 10:00

    # Преобразуем 2025-12-04 → 04.12.2025 для Apps Script
    dt = datetime.fromisoformat(date_iso)
    date_display = dt.strftime("%d.%m.%Y")

    # Отправка в Apps Script
    result = await send_booking(name, phone, service, date_display, time_str)

    if result.get("status") == "ok":
        await cb.message.edit_text(f"✅ Запись подтверждена!\n📅 {date_display}\n⏰ {time_str}\n💅 {service}")
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"🆕 Новая запись!\n📅 {date_display}\n⏰ {time_str}\n💅 {service}\n👤 {name}\n📱 {phone}"
        )
    elif result.get("status") == "busy":
        suggestions = result.get("suggestions", [])
        if suggestions:
            buttons = []
            for s in suggestions[:3]:
                # Используем дату как есть из Apps Script (dd.MM.yyyy)
                btn_text = f"{s['Дата']} в {s['Время']}"
                # Для callback сохраняем ISO
                iso_date = f"{s['Дата'][6:10]}-{s['Дата'][3:5]}-{s['Дата'][:2]}"
                cb_data = f"alt_{iso_date}_{s['Время']}"
                buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
            buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await cb.message.edit_text("⛔ Это время занято. Предлагаем:", reply_markup=kb)
        else:
            await cb.message.edit_text("⛔ Нет свободных слотов в ближайшие дни.")
    else:
        await cb.message.edit_text(f"❌ Ошибка сервера: {result.get('message', 'неизвестно')}")

    await state.clear()

@router.callback_query(F.data.startswith("alt_"))
async def alt_time(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_", 2)
    if len(parts) != 3:
        await cb.answer("❌ Ошибка формата", show_alert=True)
        return
    
    # parts[1] = YYYY-MM-DD, parts[2] = HH:mm
    date_iso = parts[1]
    time_str = parts[2]
    
    # Преобразуем в dd.MM.yyyy для отправки
    dt = datetime.fromisoformat(date_iso)
    date_display = dt.strftime("%d.%m.%Y")
    
    data = await state.get_data()
    result = await send_booking(
        data.get("name", "—"),
        data.get("phone", "—"),
        data.get("service", "—"),
        date_display,  # ← dd.MM.yyyy
        time_str
    )
    
    if result.get("status") == "ok":
        await cb.message.edit_text(result["message"])
    else:
        await cb.message.edit_text(f"❌ Не удалось забронировать: {result.get('message', 'ошибка')}")
    
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

# === 5. FASTAPI (для Render) ===
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

# Health-check для Render (обязательно!)
@app.get("/healthz")
@app.head("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok"}

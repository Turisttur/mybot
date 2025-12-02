# bot.py — ASEM PODO (исправленные слоты + кнопки-альтернативы)
import os
import json
import logging
import aiohttp
import asyncio
import pytz
from datetime import datetime
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage

# === Настройки ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6734540756"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
SLOTS_URL = os.getenv("SLOTS_URL", "").strip()
BOOKING_URL = os.getenv("BOOKING_URL", "").strip()

for name, val in [("BOT_TOKEN", BOT_TOKEN), ("WEBHOOK_URL", WEBHOOK_URL),
                  ("SLOTS_URL", SLOTS_URL), ("BOOKING_URL", BOOKING_URL)]:
    if not val:
        raise ValueError(f"❌ {name} не задан")

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

# === Утилиты ===
def error_reload_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_days")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ])

def build_days_kb(slots: list[dict]) -> InlineKeyboardMarkup:
    dates = sorted({s["Дата"] for s in slots if s.get("Дата")})
    buttons = [[InlineKeyboardButton(text=d, callback_data=f"day_{d}")] for d in dates]
    if not buttons:
        buttons = [[InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_days")]]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def build_times_kb(slots: list[dict], date: str) -> InlineKeyboardMarkup:
    day_slots = [s for s in slots if s.get("Дата") == date]
    day_slots.sort(key=lambda x: x.get("Время", ""))
    
    buttons = []
    row = []
    for s in day_slots:
        label = f"{s['Время']} ✅" if s["status"] == "free" else f"{s['Время']} ❌"
        cb = f"time_{s['Время']}" if s["status"] == "free" else "busy"
        row.append(InlineKeyboardButton(text=label, callback_data=cb))
        if len(row) == 3:
            buttons.append(row)
            row = []
    if row: buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

async def get_slots() -> list[dict]:
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(SLOTS_URL) as resp:
                if resp.status != 200:
                    raise ValueError(f"HTTP {resp.status}")
                return (await resp.json()).get("slots", [])
    except Exception as e:
        print(f"⚠️ get_slots error: {e}")
        return []

async def send_booking(name, phone, service, date, time) -> dict:
    payload = {
        "Имя": name,
        "Телефон": phone,
        "Услуга": service,
        "Дата": date,
        "Время": time,
        "ДлительностьЧасы": DURATION_MAP.get(service, 1.0)
    }
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(BOOKING_URL, json=payload) as resp:
                return await resp.json()
    except Exception as e:
        print(f"❌ send_booking error: {e}")
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

    slots = await get_slots()
    if not slots:
        await msg.answer("❌ Не удалось загрузить расписание.", reply_markup=error_reload_kb())
        return

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

@router.callback_query(F.data == "refresh_days")
async def refresh_days(cb: CallbackQuery, state: FSMContext):
    await cb.answer("Обновляю…")
    slots = await get_slots()
    kb = build_days_kb(slots) if slots else error_reload_kb()
    try:
        await cb.message.edit_text("Выберите день:", reply_markup=kb)
    except Exception:
        await cb.message.answer("Выберите день:", reply_markup=kb)

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
    date_str = data.get("date", "—")
    tm = cb.data[5:]

    result = await send_booking(name, phone, service, date_str, tm)

    if result.get("status") == "ok":
        await cb.message.edit_text(result["message"])
    elif result.get("status") == "busy":
        suggestions = result.get("suggestions", [])
        if suggestions:
            buttons = []
            for s in suggestions:
                # Формат: DD.MM.YYYY → преобразуем в YYYY-MM-DD для callback
                iso_date = f"{s['Дата'][6:10]}-{s['Дата'][3:5]}-{s['Дата'][:2]}"
                btn_text = f"{s['Дата']} в {s['Время']}"
                cb_data = f"alt_{iso_date}_{s['Время']}"
                buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
            buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await cb.message.edit_text("⛔ Это время занято. Предлагаем:", reply_markup=kb)
        else:
            await cb.message.edit_text("⛔ Нет свободных слотов в ближайшие дни.")
    else:
        await cb.message.edit_text(f"❌ Ошибка: {result.get('message', 'неизвестно')}")

    await state.clear()

# === НОВЫЙ ХЕНДЛЕР: выбор альтернативы ===
@router.callback_query(F.data.startswith("alt_"))
async def alt_time(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_", 2)
    if len(parts) != 3:
        await cb.answer("❌ Ошибка формата", show_alert=True)
        return
    
    # alt_2025-12-02_10:30 → date="02.12.2025"
    date_iso = parts[1]
    time_str = parts[2]
    date_display = f"{date_iso[8:10]}.{date_iso[5:7]}.{date_iso[:4]}"

    data = await state.get_data()
    result = await send_booking(
        data.get("name", "—"),
        data.get("phone", "—"),
        data.get("service", "—"),
        date_display,
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
        "🕒 *Пн–Пт:* 10:00–20:00\n"
        "🕒 *Сб:* 10:00–18:00\n"
        "📱 +7 777 123 45 67"
        "🌐 [asem-podo.pages.dev](https://asem-podo.pages.dev)"
  
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 WhatsApp", url="https://wa.me/77771234567")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ])
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

# === FastAPI ===
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

@app.get("/healthz")
async def healthz():
    return {"status": "ok"}
@app.get("/")
async def root():
    return {"status": "ok", "service": "ASEM PODO Bot", "webhook": WEBHOOK_URL}  

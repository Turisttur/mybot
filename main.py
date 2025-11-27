import os
import logging
from datetime import datetime, timedelta, time
import pytz
import aiohttp
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# 🔑 Настройки
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6734540756"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL")  # например https://bot-k7rs.onrender.com/webhook

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
app = FastAPI()

# === Google Form настройки ===
FORM_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfA9agctAXbg3897M0N2aSGAy1BQOBc8zUJuNtuXj_JMUvHUw/formResponse"

ENTRY_NAME = "entry.929095536"
ENTRY_PHONE = "entry.1802722855"
ENTRY_DATE = "entry.1964769702"
ENTRY_TIME = "entry.1869005656"
ENTRY_SERVICE = "entry.1966683913"

async def send_to_google_form(name, phone, date_str, time_str, service):
    try:
        # Преобразуем дату из YYYY-MM-DD → ДД.ММ.ГГГГ
        date_obj = datetime.strptime(date_str, "%Y-%m-%d")
        date_fmt = date_obj.strftime("%d.%m.%Y")

        # Преобразуем время в формат HH:MM
        time_obj = datetime.strptime(time_str, "%H:%M")
        time_fmt = time_obj.strftime("%H:%M")

        form_data = {
            ENTRY_NAME: name.strip(),
            ENTRY_PHONE: phone.strip(),
            ENTRY_DATE: date_fmt,
            ENTRY_TIME: time_fmt,
            ENTRY_SERVICE: service.strip(),
            "fvv": "1",
            "draftResponse": [],
            "pageHistory": "0"
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "User-Agent": "Mozilla/5.0",
            "Referer": FORM_URL.replace("formResponse", "viewform")
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(FORM_URL, data=form_data, headers=headers) as resp:
                text = await resp.text()
                if resp.status in (200, 302):
                    print("✅ Данные успешно отправлены в Google Form")
                else:
                    print(f"⚠️ Ошибка Google Form: {resp.status}, ответ: {text[:200]}")
    except Exception as e:
        print(f"❌ Ошибка при отправке в Google Form: {e}")

# === FSM ===
TIMEZONE = pytz.timezone("Asia/Almaty")
WORKING_HOURS = {
    "mon": (time(10, 0), time(20, 0)),
    "tue": (time(10, 0), time(20, 0)),
    "wed": (time(10, 0), time(20, 0)),
    "thu": (time(10, 0), time(20, 0)),
    "fri": (time(10, 0), time(20, 0)),
    "sat": (time(10, 0), time(18, 0)),
    "sun": None
}

class Booking(StatesGroup):
    choosing_service = State()
    entering_name = State()
    entering_phone = State()
    choosing_day = State()
    choosing_time = State()

def get_days_kb():
    now = datetime.now(TIMEZONE)
    buttons = []
    for i in range(14):
        day = now + timedelta(days=i)
        wd = day.strftime("%a").lower()[:3]
        if WORKING_HOURS[wd]:
            text = "Сегодня" if i == 0 else "Завтра" if i == 1 else day.strftime("%d %b")
            buttons.append([InlineKeyboardButton(text=text, callback_data=f"day_{day.strftime('%Y-%m-%d')}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_times_kb(date_str):
    day = datetime.strptime(date_str, "%Y-%m-%d")
    wd = day.strftime("%a").lower()[:3]
    hours = WORKING_HOURS[wd]
    if not hours:
        return None
    start, end = hours
    slots = []
    current = TIMEZONE.localize(datetime.combine(day.date(), start))
    end_dt = TIMEZONE.localize(datetime.combine(day.date(), end))
    while current < end_dt:
        if (current - datetime.now(TIMEZONE)).total_seconds() > 1800:
            slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=60)
    if not slots:
        return None
    buttons = [[InlineKeyboardButton(text=t, callback_data=f"time_{t}")] for t in slots]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# === Хэндлеры ===
@dp.message(Command("start"))
async def start(msg: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="book")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="contact")]
    ])
    await msg.answer("🌸 Добро пожаловать в ASEM PODO @ BEAUTY!", reply_markup=kb)

@dp.callback_query(F.data == "main")
async def main_menu(cb: CallbackQuery, state: FSMContext):
    await start(cb.message, state)

@dp.callback_query(F.data == "book")
async def book(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Booking.choosing_service)
    buttons = [
        [InlineKeyboardButton(text="Медицинская подология", callback_data="srv_Медподология")],
        [InlineKeyboardButton(text="Эстетический маникюр", callback_data="srv_Маникюр")],
        [InlineKeyboardButton(text="Педикюр премиум", callback_data="srv_Педикюр")],
        [InlineKeyboardButton(text="Визаж", callback_data="srv_Визаж")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ]
    await cb.message.edit_text("Выберите услугу:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))

@dp.callback_query(F.data.startswith("srv_"))
async def srv(cb: CallbackQuery, state: FSMContext):
    service = cb.data[4:]
    await state.update_data(service=service)
    await state.set_state(Booking.entering_name)
    await cb.message.edit_text("Введите ваше имя:")

@dp.message(Booking.entering_name)
async def name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text)
    await state.set_state(Booking.entering_phone)
    await msg.answer("Введите ваш телефон:")

@dp.message(Booking.entering_phone)
async def phone(msg: Message, state: FSMContext):
    await state.update_data(phone=msg.text)
    await state.set_state(Booking.choosing_day)
    await msg.answer("Выберите день:", reply_markup=get_days_kb())

@dp.callback_query(F.data.startswith("day_"))
async def day(cb: CallbackQuery, state: FSMContext):
    date = cb.data[4:]
    await state.update_data(date=date)
    await state.set_state(Booking.choosing_time)
    kb = get_times_kb(date)
    if kb:
        await cb.message.edit_text("Выберите время:", reply_markup=kb)
    else:
        await cb.answer("Нет свободного времени в этот день.", show_alert=True)

@dp.callback_query(F.data.startswith("time_"))
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

    if not date_str:
        await cb.message.answer("❌ Не указана дата. Начните с /start.")
        await state.clear()
        return

    await send_to_google_form(name, phone, date_str, tm, service)

    date_obj = datetime.strptime(date_str, "%Y-%m-%d")
    date_fmt = date_obj.strftime("%d.%m")
    await cb.message.edit_text(
        f"✅ Запись подтверждена!\n\n📅 {date_fmt}\n⏰ {tm}\n💅 {service}\n📍 Аягоз, ул. Актамберды, 23"
    )
    await bot.send_message(
        ADMIN_CHAT_ID,
        f"🆕 Новая запись!\n👤 {name}\n📱 {phone}\n📅 {date_fmt}\n⏰ {tm}\n💅 {service}"
    )
    await state.clear()

@dp.callback_query(F.data == "contact")
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

# === Webhook настройка ===
@app.on_event("startup")
async def on_startup():
    logging.basicConfig(level=logging.INFO)
    await bot.set_webhook(WEBHOOK_URL)
    print(f"✅ Webhook установлен: {WEBHOOK_URL}")

@app.post("/webhook")
async def webhook(request: Request):
    data = await request.json()
    update = types.Update(**data)
    await dp.feed_update(bot, update)
    return {"ok": True}

# Health-check для Render
@app.get("/healthz")
async def healthz():
    return {"status": "ok"}

# main.py — ASEM PODO (финал: 07.12.2025)
# ✅ Все фичи: поиск, отмена, напоминания, отзывы — без ошибок
import os
import json
import logging
from datetime import datetime, timedelta, timezone
import asyncio
import aiohttp
from fastapi import FastAPI, Request
from aiogram import Bot, Dispatcher, Router, F, types
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# === 0. ЛОГГИРОВАНИЕ ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# === 1. ЧАСОВОЙ ПОЯС ===
try:
    import zoneinfo
    TZ = zoneinfo.ZoneInfo("Asia/Almaty")
except ImportError:
    TZ = timezone(timedelta(hours=5))

# === 2. ПЕРЕМЕННЫЕ ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6734540756"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
SLOTS_URL = os.getenv("SLOTS_URL", "").strip()
BOOKING_URL = os.getenv("BOOKING_URL", "").strip()

if not BOT_TOKEN:
    raise RuntimeError("❌ BOT_TOKEN не задан")
if not BOOKING_URL:
    raise RuntimeError("❌ BOOKING_URL не задан")
if not WEBHOOK_URL:
    raise RuntimeError("❌ WEBHOOK_URL не задан")

DURATION_MAP = {
    "Медицинская подология": 2.0,
    "Эстетический маникюр": 2.0,
    "Педикюр премиум": 2.0,
    "Наращивание ресниц": 1.0,
    "Коррекция бровей": 0.5,
    "Прокалывание ушей": 0.5,
    "Визаж Макияж": 1.5
}

# === 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="book")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="contact")]
    ])

def get_service_keyboard():
    buttons = [[InlineKeyboardButton(text=t, callback_data=f"srv_{t}")] for t in DURATION_MAP]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_working_slots(date_iso: str) -> list[str]:
    day = datetime.fromisoformat(date_iso)
    wd = day.weekday()
    if wd == 6:
        return []
    slots = []
    current = day.replace(hour=10, minute=0)
    end = day.replace(hour=12, minute=30)
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    end_hour = 20 if wd < 5 else 18
    current = day.replace(hour=14, minute=0)
    end = day.replace(hour=end_hour, minute=0)
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    return slots

async def fetch_free_slots(date_iso: str) -> list[str]:
    working_slots = get_working_slots(date_iso)
    if not working_slots or not SLOTS_URL:
        return working_slots
    try:
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            url = f"{SLOTS_URL}?date={date_iso}"
            async with session.get(url) as resp:
                data = await resp.json()
                free_times = []
                if "slots" in data and isinstance(data["slots"], list):
                    for item in data["slots"]:
                        if (item.get("Дата") == date_iso and 
                            item.get("status", "").lower() == "free"):
                            free_times.append(item.get("Время", ""))
                return [t for t in free_times if t in working_slots]
    except Exception as e:
        logger.error(f"💥 fetch_free_slots: {e}")
        return working_slots

async def search_booking(phone: str):
    try:
        url = f"{BOOKING_URL}?action=find&phone={phone}"
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                data = await resp.json()
                return data.get("booking") if data.get("status") == "ok" else None
    except Exception as e:
        logger.error(f"🔍 Поиск по телефону: {e}")
        return None

async def search_bookings_by_name(name: str):
    try:
        url = f"{BOOKING_URL}?action=find&name={name}"
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                data = await resp.json()
                return data.get("bookings", []) if data.get("status") == "ok" else []
    except Exception as e:
        logger.error(f"🔍 Поиск по имени: {e}")
        return []

async def delete_booking(phone: str):
    try:
        url = f"{BOOKING_URL}?action=delete&phone={phone}"
        timeout = aiohttp.ClientTimeout(total=6)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as resp:
                data = await resp.json()
                return data.get("status") == "ok"
    except Exception as e:
        logger.error(f"🗑 Удаление: {e}")
        return False

# === 4. ИНИЦИАЛИЗАЦИЯ ===
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# === 5. FSM ===
class Booking(StatesGroup):
    choosing_service = State()
    entering_name = State()
    entering_phone = State()
    choosing_day = State()
    choosing_time = State()
    canceling = State()
    finding_by_name = State()
    finding_by_phone = State()

# === 6. КОМАНДЫ ===
@router.message(Command("start"))
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("🌸 Добро пожаловать в ASEM PODO @ BEAUTY!", reply_markup=get_main_keyboard())

@router.message(Command("book"))
async def cmd_book(msg: Message, state: FSMContext):
    await state.clear()
    await state.set_state(Booking.choosing_service)
    await msg.answer("Выберите услугу:", reply_markup=get_service_keyboard())

@router.message(Command("contact"))
async def cmd_contact(msg: Message, state: FSMContext):
    await state.clear()
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
    await msg.answer(text, parse_mode="Markdown", reply_markup=kb)

@router.message(Command("cancelbooking"))
async def cmd_cancelbooking(msg: Message, state: FSMContext):
    await state.set_state(Booking.canceling)
    await msg.answer("📱 Введите телефон, чтобы отменить запись:")

@router.message(Command("mybooking"))
async def cmd_mybooking(msg: Message, state: FSMContext):
    await state.set_state(Booking.finding_by_phone)
    await msg.answer("📱 Введите телефон (как при записи):")

@router.message(Command("findbooking"))
async def cmd_findbooking(msg: Message, state: FSMContext):
    await state.set_state(Booking.finding_by_name)
    await msg.answer("👤 Введите имя (как при записи):")

@router.message(Command("cancel"))
async def cmd_cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("🛑 Действие отменено.", reply_markup=get_main_keyboard())

@router.message(Command("help"))
async def cmd_help(msg: Message):
    text = (
        "💡 Как пользоваться:\n"
        "/start — Главное меню\n"
        "/book — Записаться\n"
        "/mybooking — Посмотреть запись (по телефону)\n"
        "/cancelbooking — Отменить запись\n"
        "/findbooking — Найти запись по имени\n"
        "/contact — Контакты\n\n"
        "⚠️ Если бот «молчит» — нажмите /start"
    )
    await msg.answer(text, parse_mode="Markdown")

# === 7. CALLBACK ХЭНДЛЕРЫ ===
@router.callback_query(F.data == "book")
async def book(cb: CallbackQuery, state: FSMContext):
    await state.set_state(Booking.choosing_service)
    await cb.message.edit_text("Выберите услугу:", reply_markup=get_service_keyboard())

@router.callback_query(F.data.startswith("srv_"))
async def srv(cb: CallbackQuery, state: FSMContext):
    await state.update_data(service=cb.data[4:])
    await state.set_state(Booking.entering_name)
    await cb.message.edit_text("Введите ваше имя:")

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

@router.callback_query(F.data == "main")
async def back_to_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    await cb.message.edit_text("🌸 Добро пожаловать в ASEM PODO @ BEAUTY!", reply_markup=get_main_keyboard())

@router.callback_query(F.data.startswith("day_"))
async def day(cb: CallbackQuery, state: FSMContext):
    date_iso = cb.data[4:]
    await state.update_data(date=date_iso)
    await state.set_state(Booking.choosing_time)

    slots = await fetch_free_slots(date_iso)
    now = datetime.now(TZ).replace(tzinfo=None)
    today_iso = now.strftime("%Y-%m-%d")
    if date_iso == today_iso:
        current_time = now.strftime("%H:%M")
        slots = [t for t in slots if t > current_time]

    if not slots:
        logger.info(f"🕗 Нет слотов на {date_iso}. Ищем следующий день...")
        next_date = datetime.fromisoformat(date_iso)
        for _ in range(7):
            next_date += timedelta(days=1)
            if next_date.weekday() == 6:
                continue
            next_iso = next_date.strftime("%Y-%m-%d")
            next_slots = await fetch_free_slots(next_iso)
            if next_slots:
                await cb.message.edit_text(f"🕗 На {date_iso} нет слотов. Предлагаем {next_date.strftime('%d %b')}:")
                await state.update_data(date=next_iso)
                cb.data = f"day_{next_iso}"
                return await day(cb, state)
        await cb.message.edit_text("🕗 Свободных слотов нет в ближайшую неделю.")
        return

    buttons = []
    for i in range(0, len(slots), 3):
        row = [InlineKeyboardButton(text=t, callback_data=f"time_{t}") for t in slots[i:i+3]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.edit_text("Выберите время:", reply_markup=kb)

@router.callback_query(F.data.startswith("time_"))
async def time(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data:
        await cb.message.answer("⚠️ Сессия устарела. /start")
        await state.clear()
        return

    service = data.get("service")
    name = data.get("name")
    phone = data.get("phone")
    date_iso = data.get("date")
    time_str = cb.data[5:]

    if not all([service, name, phone, date_iso]):
        await cb.message.edit_text("⚠️ Данные утеряны. /start")
        await state.clear()
        return

    try:
        dt = datetime.fromisoformat(date_iso)
        date_display = dt.strftime("%d.%m.%Y")
    except:
        await cb.message.edit_text("❌ Некорректная дата.")
        await state.clear()
        return

    # Сохраняем chat_id для напоминаний
    chat_id = cb.message.chat.id

    result = await send_booking(name, phone, service, date_display, time_str, chat_id)

    if result.get("status") == "ok":
        await cb.message.edit_text(f"✅ Запись подтверждена!\n📅 {date_display}\n⏰ {time_str}\n💅 {service}")
        await bot.send_message(ADMIN_CHAT_ID, f"🆕 {service} | {name} | {phone} | {date_display} {time_str}")
        await state.clear()

    elif result.get("status") == "busy":
        suggestions = result.get("suggestions", [])
        if suggestions:
            buttons = []
            for s in suggestions[:3]:
                btn_text = f"{s['Дата']} в {s['Время']}"
                d = s['Дата']
                iso_date = f"{d[6:10]}-{d[3:5]}-{d[:2]}"
                cb_data = f"sug_{iso_date}_{s['Время']}"
                buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
            buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await cb.message.edit_text("🕗 Это время занято. Предлагаем:", reply_markup=kb)
        else:
            await cb.message.edit_text("🕗 Нет ближайших свободных слотов.")
        # Не очищаем state — данные нужны для sug_

    else:
        msg = result.get("message", "серверная ошибка")
        await cb.message.edit_text(f"❌ {msg}")
        await state.clear()

@router.callback_query(F.data.startswith("sug_"))
async def suggest_time(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_", 2)
    if len(parts) != 3:
        await cb.answer("❌ Ошибка формата", show_alert=True)
        return
    date_iso, time_str = parts[1], parts[2]
    try:
        dt = datetime.fromisoformat(date_iso)
        date_display = dt.strftime("%d.%m.%Y")
    except:
        await cb.message.edit_text("❌ Некорректная дата.")
        return
    data = await state.get_data()
    required = {"name", "phone", "service"}
    if not (required <= set(data.keys())):
        await cb.message.edit_text("⚠️ Сессия устарела. /start")
        await state.clear()
        return
    chat_id = cb.message.chat.id
    result = await send_booking(data["name"], data["phone"], data["service"], date_display, time_str, chat_id)
    if result.get("status") == "ok":
        await cb.message.edit_text(f"✅ Запись подтверждена!\n📅 {date_display}\n⏰ {time_str}")
        await bot.send_message(ADMIN_CHAT_ID, f"🆕 {data['service']} | {data['name']} | {data['phone']} | {date_display} {time_str}")
        await state.clear()
    else:
        await cb.message.edit_text(f"❌ Не удалось: {result.get('message', 'неизвестно')}")
        await state.clear()

@router.callback_query(F.data == "choose_day")
async def back_to_days(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    required = {"service", "name", "phone"}
    if not (required <= set(data.keys())):
        await cb.message.edit_text("⚠️ Данные утеряны. /start")
        await state.clear()
        return
    now = datetime.now(TZ).replace(tzinfo=None)
    buttons = []
    for i in range(7):
        day = now + timedelta(days=i)
        if day.weekday() == 6:
            continue
        if i == 0:
            slots_today = await fetch_free_slots(day.strftime("%Y-%m-%d"))
            current_time_str = now.strftime("%H:%M")
            future_slots = [s for s in slots_today if s > current_time_str]
            if not future_slots:
                continue
        text = "Сегодня" if i == 0 else "Завтра" if i == 1 else day.strftime("%d %b")
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"day_{day.strftime('%Y-%m-%d')}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.edit_text("📅 Выберите день:", reply_markup=kb)

# === 8. FSM ХЭНДЛЕРЫ ===
@router.message(Booking.entering_name)
async def name(msg: Message, state: FSMContext):
    if msg.text and msg.text.startswith("/"):
        return
    if not (msg.text and msg.text.strip()):
        await msg.answer("❌ Введите имя текстом.")
        return
    name_clean = msg.text.strip()
    if len(name_clean) < 2:
        await msg.answer("❌ Имя от 2 символов.")
        return
    await state.update_data(name=name_clean)
    await state.set_state(Booking.entering_phone)
    await msg.answer("📱 Введите телефон:")

@router.message(Booking.entering_phone)
async def phone(msg: Message, state: FSMContext):
    if msg.text and msg.text.startswith("/"):
        return
    if not (msg.text and msg.text.strip()):
        await msg.answer("❌ Введите телефон текстом.")
        return
    phone_clean = msg.text.strip()
    digits = "".join(filter(str.isdigit, phone_clean))
    if len(digits) < 8:
        await msg.answer("❌ Номер слишком короткий.")
        return
    await state.update_data(phone=phone_clean)
    await state.set_state(Booking.choosing_day)

    now = datetime.now(TZ).replace(tzinfo=None)
    buttons = []
    for i in range(7):
        day = now + timedelta(days=i)
        if day.weekday() == 6:
            continue
        if i == 0:
            slots_today = await fetch_free_slots(day.strftime("%Y-%m-%d"))
            current_time_str = now.strftime("%H:%M")
            future_slots = [s for s in slots_today if s > current_time_str]
            if not future_slots:
                continue
        text = "Сегодня" if i == 0 else "Завтра" if i == 1 else day.strftime("%d %b")
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"day_{day.strftime('%Y-%m-%d')}")])
    if not buttons:
        await msg.answer("🕗 Нет свободных дней в ближайшую неделю.")
        await state.clear()
        return
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await msg.answer("📅 Выберите день:", reply_markup=kb)

@router.message(Booking.canceling)
async def cancel_by_phone(msg: Message, state: FSMContext):
    if msg.text and msg.text.startswith("/"):
        return
    phone = msg.text.strip()
    success = await delete_booking(phone)
    if success:
        await msg.answer("✅ Запись отменена.")
    else:
        await msg.answer("❌ Не удалось отменить. Проверьте номер.")
    await state.clear()

@router.message(Booking.finding_by_phone)
async def find_by_phone(msg: Message, state: FSMContext):
    if msg.text and msg.text.startswith("/"):
        return
    phone = msg.text.strip()
    booking = await search_booking(phone)
    if booking:
        text = f"📅 Ваша запись:\n{booking['date']} в {booking['time']}\n💅 {booking['service']}"
        await msg.answer(text)
    else:
        await msg.answer("❌ Запись не найдена.")
    await state.clear()

@router.message(Booking.finding_by_name)
async def find_by_name(msg: Message, state: FSMContext):
    if msg.text and msg.text.startswith("/"):
        return
    name = msg.text.strip()
    bookings = await search_bookings_by_name(name)
    if bookings:
        text = "📋 Найдено:\n" + "\n".join(
            f"• {b['date']} в {b['time']} — {b['service']}" for b in bookings[:5]
        )
        await msg.answer(text)
    else:
        await msg.answer("❌ Записи не найдены.")
    await state.clear()

# === 9. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ===
async def send_booking(name: str, phone: str, service: str, date_display: str, time_str: str, chat_id: int):
    payload = {
        "Имя": name.strip(),
        "Телефон": phone.strip(),
        "Услуга": service.strip(),
        "Дата": date_display,
        "Время": time_str,
        "ДлительностьЧасы": DURATION_MAP.get(service, 1.0),
        "chat_id": chat_id  # ← для напоминаний
    }
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(BOOKING_URL, json=payload) as resp:
                return await resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}

# === 10. FASTAPI ===
app = FastAPI()

@app.on_event("startup")
async def startup():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("✅ Бот запущен.")

@app.post("/webhook")
async def webhook(request: Request):
    update = types.Update(**await request.json())
    await dp.feed_update(bot, update)
    return {"ok": True}

@app.post("/remind")
async def remind_handler(request: Request):
    data = await request.json()
    text = f"🔔 Напоминание!\nЧерез час у вас запись:\n📅 {data['date']} в {data['time']}\n💅 {data['service']}"
    try:
        await bot.send_message(chat_id=data["chat_id"], text=text)
    except Exception as e:
        logger.error(f"📩 Не удалось отправить напоминание: {e}")
    return {"ok": True}

@app.post("/review")
async def review_handler(request: Request):
    data = await request.json()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⭐️⭐️⭐️⭐️⭐️", callback_data="review_5")],
        [InlineKeyboardButton(text="⭐️⭐️⭐️⭐️", callback_data="review_4")],
        [InlineKeyboardButton(text="⭐️⭐️⭐️", callback_data="review_3")],
    ])
    try:
        await bot.send_message(
            chat_id=data["chat_id"],
            text="✨ Спасибо за визит! Оцените, пожалуйста, сервис:",
            reply_markup=kb
        )
    except Exception as e:
        logger.error(f"📩 Не удалось отправить отзыв: {e}")
    return {"ok": True}

@router.callback_query(F.data.startswith("review_"))
async def review_cb(cb: CallbackQuery):
    stars = cb.data.split("_")[1]
    await cb.message.edit_text(f"🙏 Спасибо за оценку: {stars}⭐!")

@app.get("/healthz")
@app.head("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok"}

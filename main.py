# bot_final.py — ASEM PODO (финальная версия: стабильно, без молчания, с альтернативами)
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

# === 0. ЛОГГИРОВАНИЕ И ЧАСОВОЙ ПОЯС ===
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

try:
    import zoneinfo
    TZ = zoneinfo.ZoneInfo("Asia/Almaty")  # UTC+5 — Казахстан
except ImportError:
    from datetime import timezone
    TZ = timezone(timedelta(hours=5))

# === 1. ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ ===
BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID", "6734540756"))
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").strip()
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
    day = datetime.fromisoformat(date_iso)
    wd = day.weekday()
    if wd == 6:  # воскресенье — выходной
        return []
    
    slots = []
    # Утро: 10:00–12:30
    current = day.replace(hour=10, minute=0, second=0, microsecond=0)
    end = day.replace(hour=12, minute=30)
    while current <= end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    
    # Вечер: 14:00–20:00 (пн–пт) или 18:00 (сб)
    end_hour = 20 if wd < 5 else 18
    current = day.replace(hour=14, minute=0, second=0, microsecond=0)
    end = day.replace(hour=end_hour, minute=0)
    while current < end:
        slots.append(current.strftime("%H:%M"))
        current += timedelta(minutes=30)
    
    return slots

async def send_booking(name: str, phone: str, service: str, date_display: str, time_str: str):
    payload = {
        "Имя": name.strip(),
        "Телефон": phone.strip(),
        "Услуга": service.strip(),
        "Дата": date_display,
        "Время": time_str,
        "ДлительностьЧасы": DURATION_MAP.get(service, 1.0)
    }
    
    try:
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(BOOKING_URL, json=payload) as resp:
                return await resp.json()
    except Exception as e:
        logger.error(f"❌ send_booking error: {e}")
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

@router.message(Booking.entering_name)
async def name(msg: Message, state: FSMContext):
    if not msg.text or not isinstance(msg.text, str) or not msg.text.strip():
        await msg.answer("❌ Пожалуйста, введите ваше имя текстом (например, Айгерим).")
        return

    name_clean = msg.text.strip()
    if len(name_clean) < 2:
        await msg.answer("❌ Имя должно быть от 2 символов. Попробуйте снова:")
        return
    if len(name_clean) > 50:
        await msg.answer("❌ Имя слишком длинное (макс. 50 симв.). Попробуйте короче:")
        return

    await state.update_data(name=name_clean)
    await state.set_state(Booking.entering_phone)
    logger.info(f"User {msg.from_user.id} entered name: {name_clean}")
    await msg.answer("📱 Введите ваш телефон (например, +7 777 123 4567):")

@router.message(Booking.entering_phone)
async def phone(msg: Message, state: FSMContext):
    if not msg.text or not isinstance(msg.text, str) or not msg.text.strip():
        await msg.answer("❌ Пожалуйста, введите номер телефона текстом.")
        return

    phone_clean = msg.text.strip()
    digits = "".join(filter(str.isdigit, phone_clean))
    if len(digits) < 8:
        await msg.answer("❌ Номер слишком короткий. Введите, например: +7 777 123 4567")
        return
    if len(digits) > 15:
        await msg.answer("❌ Номер слишком длинный.")
        return

    await state.update_data(phone=phone_clean)
    await state.set_state(Booking.choosing_day)

    now = datetime.now(TZ).replace(tzinfo=None)
    logger.info(f"[phone] Local time: {now.strftime('%Y-%m-%d %H:%M')}")

    buttons = []
    for i in range(14):
        day = now + timedelta(days=i)
        if day.weekday() == 6:
            continue
        if i == 0:
            slots_today = get_working_slots(day.strftime("%Y-%m-%d"))
            future_slots = [s for s in slots_today if s > now.strftime("%H:%M")]
            if not future_slots:
                continue
        text = "Сегодня" if i == 0 else "Завтра" if i == 1 else day.strftime("%d %b")
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"day_{day.strftime('%Y-%m-%d')}")])

    if not buttons:
        await msg.answer("🕗 К сожалению, свободных дней нет в ближайшие 2 недели.")
        await state.clear()
        return

    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await msg.answer("📅 Выберите день:", reply_markup=kb)

@router.callback_query(F.data.startswith("day_"))
async def day(cb: CallbackQuery, state: FSMContext):
    date_iso = cb.data[4:]
    await state.update_data(date=date_iso)
    await state.set_state(Booking.choosing_time)
    
    slots = get_working_slots(date_iso)
    if not slots:
        await cb.message.edit_text("❌ В этот день нет рабочих слотов. Выберите другой день.")
        return

    buttons = []
    for i in range(0, len(slots), 3):
        row = [InlineKeyboardButton(text=t, callback_data=f"time_{t}") for t in slots[i:i+3]]
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.edit_text("Выберите время:", reply_markup=kb)

@router.callback_query(F.data.startswith("time_"))
async def time(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not data:
        await cb.message.answer("⚠️ Сессия устарела. Начните с /start.")
        await state.clear()
        return

    service = data.get("service")
    name = data.get("name")
    phone = data.get("phone")
    date_iso = data.get("date")
    time_str = cb.data[5:]

    if not all([service, name, phone, date_iso]):
        await cb.message.edit_text("⚠️ Недостаточно данных. Начните с /start.")
        await state.clear()
        return

    try:
        dt = datetime.fromisoformat(date_iso)
        date_display = dt.strftime("%d.%m.%Y")
    except Exception as e:
        logger.error(f"Date parse error: {e}")
        await cb.message.edit_text("❌ Некорректная дата.")
        await state.clear()
        return

    result = await send_booking(name, phone, service, date_display, time_str)

    if result.get("status") == "ok":
        await cb.message.edit_text(f"✅ Запись подтверждена!\n📅 {date_display}\n⏰ {time_str}\n💅 {service}")
        await bot.send_message(
            ADMIN_CHAT_ID,
            f"🆕 Новая запись!\n📅 {date_display}\n⏰ {time_str}\n💅 {service}\n👤 {name}\n📱 {phone}"
        )
        await state.clear()

    elif result.get("status") == "busy":
        suggestions = result.get("suggestions", [])
        if suggestions:
            buttons = []
            for s in suggestions[:3]:
                iso_date = f"{s['Дата'][6:10]}-{s['Дата'][3:5]}-{s['Дата'][:2]}"
                cb_data = f"alt_{iso_date}_{s['Время']}"
                btn_text = f"{s['Дата']} в {s['Время']}"
                buttons.append([InlineKeyboardButton(text=btn_text, callback_data=cb_data)])
            buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="choose_day")])
            kb = InlineKeyboardMarkup(inline_keyboard=buttons)
            await cb.message.edit_text("⛔ Это время занято. Предлагаем:", reply_markup=kb)
            # ✅ НЕ очищаем state — данные нужны для alt_time
        else:
            await cb.message.edit_text("⛔ Нет свободных слотов в ближайшие дни.")
            await state.clear()

    else:
        msg_err = result.get("message", "неизвестно")
        logger.error(f"Booking error: {msg_err}")
        await cb.message.edit_text(f"❌ Ошибка сервера: {msg_err}")
        await state.clear()

@router.callback_query(F.data.startswith("alt_"))
async def alt_time(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("_", 2)
    if len(parts) != 3:
        await cb.answer("❌ Ошибка формата", show_alert=True)
        return

    date_iso, time_str = parts[1], parts[2]

    try:
        dt = datetime.fromisoformat(date_iso)
        date_display = dt.strftime("%d.%m.%Y")
    except Exception as e:
        logger.error(f"Alt date parse error: {e}")
        await cb.message.edit_text("❌ Некорректная дата.")
        await state.clear()
        return

    data = await state.get_data()
    required = {"service", "name", "phone"}
    if not (required <= set(data.keys())):
        await cb.message.edit_text("⚠️ Данные утеряны. Начните с /start.")
        await state.clear()
        return

    result = await send_booking(
        data["name"],
        data["phone"],
        data["service"],
        date_display,
        time_str
    )

    if result.get("status") == "ok":
        await cb.message.edit_text("✅ Запись подтверждена!\nСпасибо за выбор ASEM PODO ❤️")
    else:
        msg_err = result.get("message", "ошибка")
        logger.error(f"Alt booking error: {msg_err}")
        await cb.message.edit_text(f"❌ Не удалось забронировать: {msg_err}")

    await state.clear()

@router.callback_query(F.data == "contact")
async def contact(cb: CallbackQuery):
    text = (
        "📍 *Аягоз, ул. Актамберды, 23*\n"
        "🕒 *Пн–Пт:* 10:00–12:30, 14:00–20:00\n"
        "🕒 *Сб:* 10:00–12:30, 14:00–18:00\n"
        "📱 +7 777 123 45 67"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 WhatsApp", url="https://wa.me/77771234567")],
        [InlineKeyboardButton(text="⬅️ Назад", callback_data="main")]
    ])
    await cb.message.edit_text(text, parse_mode="Markdown", reply_markup=kb)

@router.callback_query(F.data == "main")
async def back_to_main(cb: CallbackQuery, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📅 Записаться", callback_data="book")],
        [InlineKeyboardButton(text="📞 Контакты", callback_data="contact")]
    ])
    await cb.message.edit_text("🌸 Добро пожаловать в ASEM PODO @ BEAUTY!", reply_markup=kb)

@router.callback_query(F.data == "choose_day")
async def back_to_days(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    required = {"service", "name", "phone"}
    if not (required <= set(data.keys())):
        await cb.message.edit_text("⚠️ Данные утеряны. Начните с /start.")
        await state.clear()
        return

    now = datetime.now(TZ).replace(tzinfo=None)
    buttons = []
    for i in range(14):
        day = now + timedelta(days=i)
        if day.weekday() == 6:
            continue
        if i == 0:
            slots_today = get_working_slots(day.strftime("%Y-%m-%d"))
            future_slots = [s for s in slots_today if s > now.strftime("%H:%M")]
            if not future_slots:
                continue
        text = "Сегодня" if i == 0 else "Завтра" if i == 1 else day.strftime("%d %b")
        buttons.append([InlineKeyboardButton(text=text, callback_data=f"day_{day.strftime('%Y-%m-%d')}")])
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="main")])
    kb = InlineKeyboardMarkup(inline_keyboard=buttons)
    await cb.message.edit_text("Выберите день:", reply_markup=kb)

# === 5. FASTAPI (для Render) ===
app = FastAPI()

@app.on_event("startup")
async def startup():
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(WEBHOOK_URL)
    logger.info("✅ Bot started. Webhook set.")

@app.post("/webhook")
async def webhook(request: Request):
    try:
        update = types.Update(**await request.json())
        await dp.feed_update(bot, update)
        return {"ok": True}
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return {"ok": False, "error": str(e)}

@app.get("/healthz")
@app.head("/healthz")
async def healthz():
    return {"status": "ok"}

@app.get("/")
@app.head("/")
async def root():
    return {"status": "ok"}

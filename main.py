from aiogram import Bot, Dispatcher, types
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.utils.keyboard import InlineKeyboardBuilder
import aiohttp, asyncio, re
from datetime import datetime, timedelta

API_TOKEN = "8454009227:AAHP3Q1HArGgcr519se0Qye4x7eQp4-cjZ4"
WEBAPP_BASE = "https://script.google.com/macros/s/AKfycbzBysv3Fm1zgUf2Z7qWp-yC8pJHpBACrAd0ALpqoUmbjZ9Czl_lmvK2nZg0bAnIEfSS/exec"  # например: https://script.google.com/macros/s/XXX/exec

bot = Bot(token=API_TOKEN)
dp = Dispatcher()

# ------------------- FSM для записи -------------------
class BookingForm(StatesGroup):
    name = State()
    phone = State()
    service = State()
    date = State()
    time = State()
    confirm = State()

async def post_json(url, payload):
    async with aiohttp.ClientSession() as s:
        async with s.post(url, json=payload) as r:
            return await r.json()

async def get_json(url):
    async with aiohttp.ClientSession() as s:
        async with s.get(url) as r:
            return await r.json()

# ------------------- START -------------------
@dp.message_handler(commands=["start"])
async def start_command(m: types.Message):
    text = (
        "👋 Добро пожаловать в наш бот‑CRM!\n\n"
        "Доступные команды:\n"
        "/book — записать клиента\n"
        "/records — показать список последних записей\n"
        "/clients — показать список клиентов\n"
        "/services — показать список услуг\n"
        "/help — показать справку по командам\n"
    )
    await m.answer(text)

# ------------------- HELP -------------------
@dp.message_handler(commands=["help"])
async def show_help(m: types.Message):
    text = (
        "🛠 Справка по командам:\n\n"
        "/book — записать клиента\n"
        "/records — показать список последних записей\n"
        "/clients — показать список клиентов\n"
        "/services — показать список услуг\n"
        "/help — показать это меню\n"
    )
    await m.answer(text)

# ------------------- BOOK -------------------
@dp.message_handler(commands=["book"])
async def start_booking(m: types.Message, state: FSMContext):
    await m.answer("Как вас зовут?")
    await state.set_state(BookingForm.name)

@dp.message_handler(state=BookingForm.name)
async def process_name(m: types.Message, state: FSMContext):
    await state.update_data(name=m.text.strip())
    await m.answer("Укажите телефон (например, 87001234567):")
    await state.set_state(BookingForm.phone)

@dp.message_handler(state=BookingForm.phone)
async def process_phone(m: types.Message, state: FSMContext):
    phone = re.sub(r"\D","",m.text)
    if not re.match(r"^\d{10,12}$",phone):
        await m.answer("❌ Неверный формат телефона.")
        return
    await state.update_data(phone=phone)

    services_data = await get_json(f"{WEBAPP_BASE}/services")
    services = services_data.get("services",[])
    kb = InlineKeyboardBuilder()
    for s in services:
        kb.button(text=s["name"], callback_data=f"service:{s['name']}")
    kb.adjust(2)
    await m.answer("Выберите услугу:", reply_markup=kb.as_markup())

@dp.callback_query_handler(lambda c: c.data.startswith("service:"), state=BookingForm.phone)
async def process_service(c: types.CallbackQuery, state: FSMContext):
    await state.update_data(service=c.data.split(":",1)[1])
    kb = InlineKeyboardBuilder()
    today = datetime.today()
    for i in range(7):
        d = today+timedelta(days=i)
        kb.button(text=d.strftime("%Y-%m-%d"), callback_data=f"date:{d.strftime('%Y-%m-%d')}")
    kb.adjust(2)
    await c.message.answer("Выберите дату:", reply_markup=kb.as_markup())
    await state.set_state(BookingForm.date)
    await c.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("date:"), state=BookingForm.date)
async def process_date(c: types.CallbackQuery, state: FSMContext):
    await state.update_data(date=c.data.split(":",1)[1])
    kb = InlineKeyboardBuilder()
    for h in range(10,19):
        kb.button(text=f"{h:02d}:00", callback_data=f"time:{h:02d}:00")
    kb.adjust(3)
    await c.message.answer("Выберите время:", reply_markup=kb.as_markup())
    await state.set_state(BookingForm.time)
    await c.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("time:"), state=BookingForm.time)
async def process_time(c: types.CallbackQuery, state: FSMContext):
    await state.update_data(time=c.data.split(":",1)[1])
    data = await state.get_data()
    result = await post_json(WEBAPP_BASE,data)
    if result.get("status")=="busy":
        kb = InlineKeyboardBuilder()
        for t in result.get("suggestions",{}).get("before",[])+result.get("suggestions",{}).get("after",[]):
            kb.button(text=t, callback_data=f"choose_time:{t}")
        kb.adjust(3)
        await c.message.answer(result.get("message","⚠️ Занято"), reply_markup=kb.as_markup())
        await state.set_state(BookingForm.confirm)
    else:
        await c.message.answer(result.get("message","❌ Ошибка"))
        await state.clear()
    await c.answer()

@dp.callback_query_handler(lambda c: c.data.startswith("choose_time:"), state=BookingForm.confirm)
async def process_choice(c: types.CallbackQuery, state: FSMContext):
    new_time = c.data.split(":",1)[1]
    data = await state.get_data()
    data["time"] = new_time
    result = await post_json(WEBAPP_BASE,data)
    await c.message.answer(result.get("message","❌ Ошибка"))
    await c.answer()
    await state.clear()

# ------------------- RECORDS -------------------
@dp.message_handler(commands=["records"])
async def show_records(m: types.Message):
    records_data = await get_json(f"{WEBAPP_BASE}/records")
    records = records_data.get("records",[])
    if not records:
        await m.answer("❌ Записей нет.")
        return

    text = "📋 Список записей:\n\n"
    for rec in records[:10]:
        text += (f"👤 {rec['name']} ({rec['phone']})\n"
                 f"📅 {rec['date']} {rec['time']}\n"
                 f"💅 {rec['service']}\n"
                 f"⏱️ {rec['durationHours']} ч | 💰 {rec['price']} ₸\n\n")
    await m.answer(text)

# ------------------- CLIENTS -------------------
@dp.message_handler(commands=["clients"])
async def show_clients(m: types.Message):
    clients_data = await get_json(f"{WEBAPP_BASE}/clients")
    clients = clients_data.get("clients", [])
    if not clients:
        await m.answer("❌ Клиентов нет.")
        return

    text = "👥 Список клиентов:\n\n"
    for cl in clients[:10]:
        text += f"👤 {cl['name']} — 📞 {cl['phone']}\n"
    await m.answer(text)

# ------------------- SERVICES -------------------
@dp.message_handler(commands=["services"])
async def show_services(m: types.Message):
    services_data = await get_json(f"{WEBAPP_BASE}/services")
    services = services_data.get("services", [])
    if not services:
        await m.answer("❌ Услуг нет.")
        return

    text = "💅 Список услуг:\n\n"
    for s in services[:10]:
        text += (f"🔹 {s['name']}\n"
                 f"⏱️ {s['durationHours']} ч | 💰 {s['price']} ₸\n\n")
    await m.answer(text)

# ------------------- Запуск -------------------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())


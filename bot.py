#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OSIO Focus line Telegram bot — "DUNE: hi-tech / dry life" style
Stack: Python 3.10+, aiogram 3.x
Author: ChatGPT

What it does (prototype):
- Main menu: Presentation, Buy, Warranty Service, Contacts
- Immersive copy in DUNE-inspired tone (without shipping copyrighted frames)
- Purchase flow (collects contact & delivery info for South Africa market)
- Warranty flow implementing your exact escalation ladder
- Simple JSON "DB" for tickets/orders (prototype-friendly)
- Admin notifications (optional): ADMIN_CHAT_ID
- Ready for polling or webhook (instructions in README.md)

Replace placeholder image URLs with your licensed images before production.
"""

import asyncio
import json
import os
import re
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, F, Router
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, InputMediaPhoto
)

# ==== CONFIG ====
TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID", "")  # optional: int/str
BASE_CURRENCY = "ZAR"  # South African Rand

# Product card (adjust freely)
PRODUCT = {
    "name": "OSIO Focus line 14",
    "tagline": "Сделан в России. Готов к пустыне. Рождён для дела.",
    "price": 14999,  # ZAR — placeholder
    "specs": [
        "14\" IPS 1920x1200, антибликовый",
        "AMD Ryzen 7 / 16 ГБ / 1 ТБ NVMe",
        "Wi‑Fi 6, BT 5.2, 2×USB‑C, HDMI, microSD",
        "Вес 1.35 кг, корпус с защитой от пыли (IP5X*)",
        "Батарея 70 Вт·ч — до 14 ч работы",
    ],
    "disclaimer": "* Степень пылезащиты ориентировочная для демо. Уточняйте точные IP-показатели в финальной спецификации.",
    "gallery": [
        # Replace these with licensed images or your own renders
        "https://images.unsplash.com/photo-1517336714731-489689fd1ca8",
        "https://images.unsplash.com/photo-1518779578993-ec3579fee39f",
        "https://images.unsplash.com/photo-1498050108023-c5249f4df085",
    ]
}

# DUNE-style flavor text
FLAVOR = {
    "hero": "Он — курьер знаний. Темнокожий юноша 25 лет в бежевой мантии из муслина. "
             "В мире, где влага — роскошь, он выбирает устройства, на которые можно положиться.",
    "mood": "hi‑tech / dry life: минимум лишнего, максимум выносливости и пользы."
}

DATA_DIR = os.getenv("DATA_DIR", "./data")
os.makedirs(DATA_DIR, exist_ok=True)
ORDERS_DB = os.path.join(DATA_DIR, "orders.json")
TICKETS_DB = os.path.join(DATA_DIR, "tickets.json")

def _load(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return {}

def _save(path: str, data: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ==== FSMs ====
class BuyForm(StatesGroup):
    taking_name = State()
    taking_email = State()
    taking_phone = State()
    taking_city = State()
    taking_address = State()
    taking_delivery = State()
    confirm = State()

class WarrantyForm(StatesGroup):
    taking_serial = State()
    taking_issue = State()
    ask_remote = State()
    schedule_remote = State()
    tl_wait = State()
    asc_redirect = State()
    asc_control = State()
    repair = State()
    handover = State()
    feedback = State()

# ==== Bot setup ====
bot = Bot(TOKEN, parse_mode=ParseMode.HTML)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)

# ==== Keyboards ====
def main_menu() -> InlineKeyboardMarkup:
    btns = [
        [InlineKeyboardButton(text="💻 Презентация OSIO Focus", callback_data="menu_presentation")],
        [InlineKeyboardButton(text="🛒 Купить", callback_data="menu_buy")],
        [InlineKeyboardButton(text="🛠 Гарантийный сервис", callback_data="menu_warranty")],
        [InlineKeyboardButton(text="📩 Контакты", callback_data="menu_contacts")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=btns)

def back_menu() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="↩️ В меню", callback_data="menu_home")]])

def delivery_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Стандартная курьерская (3–5 дней)", callback_data="del_standard")],
        [InlineKeyboardButton(text="Экспресс (1–2 дня)", callback_data="del_express")],
        [InlineKeyboardButton(text="Самовывоз партнёр", callback_data="del_pickup")],
        [InlineKeyboardButton(text="↩️ Назад", callback_data="buy_back")]
    ])

def yesno_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Да", callback_data="yes"),
        InlineKeyboardButton(text="Нет", callback_data="no"),
    ]])

def warranty_progress_kb(ticket_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏳ Ожидать ответ ТЛ (3–5 раб. дней)", callback_data=f"tl_wait:{ticket_id}")],
        [InlineKeyboardButton(text="🏥 Направить в АСЦ (2–3 дня)", callback_data=f"asc_redirect:{ticket_id}")],
        [InlineKeyboardButton(text="📦 Контроль АСЦ и ЗЧ (3–7 дней)", callback_data=f"asc_control:{ticket_id}")],
        [InlineKeyboardButton(text="🛠 Ремонт (7–30 дней)", callback_data=f"repair:{ticket_id}")],
        [InlineKeyboardButton(text="📬 Передача клиенту (3–5 дней)", callback_data=f"handover:{ticket_id}")],
        [InlineKeyboardButton(text="✅ Получение ОС", callback_data=f"feedback:{ticket_id}")],
        [InlineKeyboardButton(text="↩️ В меню", callback_data="menu_home")]
    ])

# ==== Helpers ====
def money(amount: int) -> str:
    return f"{amount:,} {BASE_CURRENCY}".replace(",", " ")

def next_ticket_id() -> str:
    db = _load(TICKETS_DB)
    i = len(db) + 1
    return f"T{datetime.utcnow().strftime('%Y%m%d')}-{i:04d}"

def next_order_id() -> str:
    db = _load(ORDERS_DB)
    i = len(db) + 1
    return f"O{datetime.utcnow().strftime('%Y%m%d')}-{i:04d}"

# ==== Start & Menu ====
@router.message(CommandStart())
async def cmd_start(msg: Message):
    welcome = (
        f"<b>OSIO Focus line</b>\n"
        f"{FLAVOR['hero']}\n\n"
        f"Мир «{FLAVOR['mood']}». Ты в официальном чат‑боте OSIO.\n"
        f"Выбирай действие ниже."
    )
    await msg.answer_photo(
        photo=PRODUCT["gallery"][0],
        caption=welcome,
        reply_markup=main_menu()
    )

@router.callback_query(F.data == "menu_home")
async def cb_home(cb: CallbackQuery):
    await cb.message.edit_caption(
        caption=f"<b>Главное меню</b>\nВыбери раздел.",
        reply_markup=main_menu()
    )
    await cb.answer()

@router.callback_query(F.data == "menu_presentation")
async def cb_presentation(cb: CallbackQuery):
    text = (
        f"<b>{PRODUCT['name']}</b> — {PRODUCT['tagline']}\n\n"
        f"Цена: <b>{money(PRODUCT['price'])}</b>\n\n"
        "Ключевые характеристики:\n"
        + "\n".join([f"• {s}" for s in PRODUCT["specs"]]) +
        f"\n\n{PRODUCT['disclaimer']}"
    )
    # carousel-ish swap to second image if exists
    media = InputMediaPhoto(media=PRODUCT["gallery"][1] if len(PRODUCT["gallery"])>1 else PRODUCT["gallery"][0], caption=text)
    try:
        await cb.message.edit_media(media=media, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🛒 Купить", callback_data="menu_buy")],
            [InlineKeyboardButton(text="🛠 Гарантия", callback_data="menu_warranty")],
            [InlineKeyboardButton(text="↩️ В меню", callback_data="menu_home")],
        ]))
    except Exception:
        await cb.message.answer_photo(photo=PRODUCT["gallery"][0], caption=text, reply_markup=back_menu())
    await cb.answer()

@router.callback_query(F.data == "menu_contacts")
async def cb_contacts(cb: CallbackQuery):
    text = (
        "<b>Контакты OSIO для Южной Африки</b>\n"
        "• Email: support@osio.example (замените на рабочий)\n"
        "• Телефон: +27 10 555 0123 (пример)\n"
        "• Вопросы по партнёрству: partners@osio.example\n\n"
        "<i>Совет:</i> добавьте локальные соцсети и адреса выдачи."
    )
    await cb.message.answer(text, reply_markup=back_menu())
    await cb.answer()

# ==== Buy flow ====
@router.callback_query(F.data == "menu_buy")
async def cb_buy(cb: CallbackQuery, state: FSMContext):
    await state.set_state(BuyForm.taking_name)
    await cb.message.answer(
        "🛒 <b>Оформление заказа</b>\nКак к вам обращаться (Имя и Фамилия)?"
    )
    await cb.answer()

@router.message(BuyForm.taking_name)
async def buy_name(msg: Message, state: FSMContext):
    await state.update_data(name=msg.text.strip())
    await state.set_state(BuyForm.taking_email)
    await msg.answer("✉️ Ваша электронная почта (для счёта и отслеживания):")

@router.message(BuyForm.taking_email)
async def buy_email(msg: Message, state: FSMContext):
    email = msg.text.strip()
    if not re.match(r"[^@]+@[^@]+\.[^@]+", email):
        await msg.answer("Похоже, это не похоже на email. Попробуйте ещё раз:")
        return
    await state.update_data(email=email)
    await state.set_state(BuyForm.taking_phone)
    await msg.answer("📞 Телефон (формат +27…):")

@router.message(BuyForm.taking_phone)
async def buy_phone(msg: Message, state: FSMContext):
    await state.update_data(phone=msg.text.strip())
    await state.set_state(BuyForm.taking_city)
    await msg.answer("🏙 Город в ЮАР (например, Кейптаун/Йоханнесбург/Дурбан):")

@router.message(BuyForm.taking_city)
async def buy_city(msg: Message, state: FSMContext):
    await state.update_data(city=msg.text.strip())
    await state.set_state(BuyForm.taking_address)
    await msg.answer("🏠 Адрес доставки (улица, дом, индекс):")

@router.message(BuyForm.taking_address)
async def buy_address(msg: Message, state: FSMContext):
    await state.update_data(address=msg.text.strip())
    await state.set_state(BuyForm.taking_delivery)
    await msg.answer("🚚 Выберите способ доставки:", reply_markup=delivery_kb())

@router.callback_query(BuyForm.taking_delivery, F.data.startswith("del_"))
async def buy_delivery(cb: CallbackQuery, state: FSMContext):
    options = {
        "del_standard": "Стандартная (3–5 дней)",
        "del_express": "Экспресс (1–2 дня)",
        "del_pickup": "Самовывоз партнёр"
    }
    await state.update_data(delivery=options.get(cb.data, "Стандартная"))
    data = await state.get_data()
    order_id = next_order_id()
    # persist order
    db = _load(ORDERS_DB)
    db[order_id] = {
        "created_at": datetime.utcnow().isoformat(),
        "product": PRODUCT["name"],
        "price": PRODUCT["price"],
        **data
    }
    _save(ORDERS_DB, db)
    await state.clear()

    text = (
        f"✅ <b>Заказ создан</b>\n"
        f"Номер: <code>{order_id}</code>\n"
        f"Товар: {PRODUCT['name']}\n"
        f"Сумма к оплате: <b>{money(PRODUCT['price'])}</b>\n\n"
        f"Получатель: {data.get('name')}\n"
        f"Email: {data.get('email')}\n"
        f"Телефон: {data.get('phone')}\n"
        f"Город: {data.get('city')}\n"
        f"Адрес: {data.get('address')}\n"
        f"Доставка: {data.get('delivery')}\n\n"
        "Мы свяжемся с вами для счёта и подтверждения.\n"
        "Если допустили ошибку — просто повторите /start и оформите заново."
    )
    await cb.message.answer(text, reply_markup=back_menu())
    await cb.answer("Заказ оформлен!")

    if ADMIN_CHAT_ID:
        try:
            await bot.send_message(
                int(ADMIN_CHAT_ID),
                f"🆕 ORDER {order_id}\n{json.dumps(db[order_id], ensure_ascii=False, indent=2)}"
            )
        except Exception:
            pass

# ==== Warranty flow ====

WARRANTY_STEPS = [
    "1) Обращение: сайт / email / заявка через КЦ.",
    "2) Решение силами ТП: инструкции по переписке / удалённое подключение (обработка 15–30 минут в зависимости от загрузки).",
    "3) Эскалация ТЛ: если решение не найдено. Ответ в течение 3–5 рабочих дней.",
    "4) Направление в АСЦ: при отсутствии решения. В особых случаях — забор курьером (2–3 дня).",
    "5) Контроль работы АСЦ: при уведомлении о визите. Помощь в логистике ЗЧ (3–7 дней).",
    "6) Ремонт устройства: 7–30 дней, зависит от удалённости АСЦ и сложности.",
    "7) Передача устройства клиенту: 3–5 дней, зависит от удалённости.",
    "8) Получение ОС (обратная связь).",
]

@router.callback_query(F.data == "menu_warranty")
async def cb_warranty(cb: CallbackQuery, state: FSMContext):
    await state.set_state(WarrantyForm.taking_serial)
    steps = "\n".join([f"• {s}" for s in WARRANTY_STEPS])
    intro = (
        "🛠 <b>Гарантийный сервис OSIO</b>\n"
        "Работаем по следующему регламенту:\n" + steps +
        "\n\nНачнём оформление тикета. Введите серийный номер устройства:"
    )
    await cb.message.answer(intro)
    await cb.answer()

@router.message(WarrantyForm.taking_serial)
async def w_serial(msg: Message, state: FSMContext):
    serial = re.sub(r"\s+", "", msg.text.upper())
    await state.update_data(serial=serial)
    await state.set_state(WarrantyForm.taking_issue)
    await msg.answer("Опишите проблему максимально подробно. Можно приложить фото/видео/логи.")

@router.message(WarrantyForm.taking_issue)
async def w_issue(msg: Message, state: FSMContext):
    await state.update_data(issue=msg.text.strip())
    await state.set_state(WarrantyForm.ask_remote)
    await msg.answer(
        "Готовы ли вы к удалённому подключению нашего инженера для быстрой диагностики? "
        "(это ускоряет этап 2 — 15–30 минут)",
        reply_markup=yesno_kb()
    )

@router.callback_query(WarrantyForm.ask_remote, F.data.in_({"yes","no"}))
async def w_remote(cb: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    ticket_id = next_ticket_id()
    db = _load(TICKETS_DB)
    db[ticket_id] = {
        "created_at": datetime.utcnow().isoformat(),
        "serial": data.get("serial"),
        "issue": data.get("issue"),
        "remote_ok": cb.data == "yes",
        "status": "remote_scheduled" if cb.data == "yes" else "tl_wait",
        "history": [
            {"ts": datetime.utcnow().isoformat(), "event": "created"},
            {"ts": datetime.utcnow().isoformat(), "event": f"remote_consent:{cb.data}"},
        ]
    }
    _save(TICKETS_DB, db)

    if ADMIN_CHAT_ID:
        try:
            await bot.send_message(
                int(ADMIN_CHAT_ID),
                f"🆘 TICKET {ticket_id}\n{json.dumps(db[ticket_id], ensure_ascii=False, indent=2)}"
            )
        except Exception:
            pass

    if cb.data == "yes":
        await state.set_state(WarrantyForm.schedule_remote)
        await cb.message.answer(
            f"✅ Тикет <code>{ticket_id}</code> создан.\n"
            "Отправьте удобные <b>дата/время (UTC+2)</b> и контакт для удалённого подключения."
        )
    else:
        await state.set_state(WarrantyForm.tl_wait)
        await cb.message.answer(
            f"✅ Тикет <code>{ticket_id}</code> создан.\n"
            "Мы передали запрос тимлиду (ТЛ). Ожидайте ответ в течение 3–5 рабочих дней.",
            reply_markup=warranty_progress_kb(ticket_id)
        )
    await cb.answer()

@router.message(WarrantyForm.schedule_remote)
async def w_schedule_remote(msg: Message, state: FSMContext):
    schedule = msg.text.strip()
    await state.update_data(schedule=schedule)
    data = await state.get_data()
    # find ticket by serial+issue created last
    db = _load(TICKETS_DB)
    ticket_id = None
    for k, v in sorted(db.items(), key=lambda x: x[1]["created_at"], reverse=True):
        if v["serial"] == data["serial"] and v["issue"] == data["issue"]:
            ticket_id = k
            break
    if ticket_id:
        db[ticket_id]["history"].append({"ts": datetime.utcnow().isoformat(), "event": f"remote_scheduled:{schedule}"})
        db[ticket_id]["status"] = "remote_scheduled"
        _save(TICKETS_DB, db)

    await state.set_state(WarrantyForm.tl_wait)
    await msg.answer(
        "Инженер свяжется в указанный слот. Если проблема сохранится — эскалируем к ТЛ (3–5 рабочих дней).",
        reply_markup=warranty_progress_kb(ticket_id or "unknown")
    )

# Progression callbacks
@router.callback_query(F.data.startswith(("tl_wait","asc_redirect","asc_control","repair","handover","feedback")))
async def w_progress(cb: CallbackQuery):
    action, _, ticket_id = cb.data.partition(":")
    db = _load(TICKETS_DB)
    if ticket_id not in db:
        await cb.answer("Тикет не найден", show_alert=True)
        return
    mapping = {
        "tl_wait": ("Ожидание ответа ТЛ (3–5 раб. дней).", "tl_wait"),
        "asc_redirect": ("Направлено в АСЦ. В особых случаях — забор курьером (2–3 дня).", "asc_redirect"),
        "asc_control": ("Контроль АСЦ и логистики ЗЧ (3–7 дней).", "asc_control"),
        "repair": ("Ремонт (7–30 дней).", "repair"),
        "handover": ("Передача устройства клиенту (3–5 дней).", "handover"),
        "feedback": ("Получение ОС. Спасибо за обратную связь!", "closed"),
    }
    text, status = mapping[action]
    db[ticket_id]["history"].append({"ts": datetime.utcnow().isoformat(), "event": action})
    db[ticket_id]["status"] = status
    _save(TICKETS_DB, db)
    await cb.message.answer(f"🔄 Тикет <code>{ticket_id}</code>: {text}")
    await cb.answer()

# ==== Admin helpers ====
@router.message(Command("orders"))
async def admin_orders(msg: Message):
    if not ADMIN_CHAT_ID or str(msg.chat.id) != str(ADMIN_CHAT_ID):
        return
    db = _load(ORDERS_DB)
    if not db:
        await msg.answer("Нет заказов.")
        return
    text = "<b>Заказы</b>\n" + "\n".join([f"• {k}: {v['product']} — {v['price']} {BASE_CURRENCY}, {v['email']}" for k,v in db.items()])
    await msg.answer(text)

@router.message(Command("tickets"))
async def admin_tickets(msg: Message):
    if not ADMIN_CHAT_ID or str(msg.chat.id) != str(ADMIN_CHAT_ID):
        return
    db = _load(TICKETS_DB)
    if not db:
        await msg.answer("Нет тикетов.")
        return
    rows = []
    for k,v in db.items():
        rows.append(f"{k}: {v['serial']} | {v['status']} | {v['issue'][:40]}")
    await msg.answer("<b>Тикеты</b>\n" + "\n".join(rows))

# ==== Run ====
async def main():
    if not TOKEN:
        print("ERROR: set BOT_TOKEN env var")
        return
    print("Bot starting...")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        print("Bot stopped.")

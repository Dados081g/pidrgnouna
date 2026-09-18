"""
Oxide Reseller Shop Bot — однофайловая версия.

Установка:
    pip install aiogram==3.13.1 aiosqlite==0.20.0

Запуск:
    python bot_single_file.py

Перед запуском заполни BOT_TOKEN и ADMIN_IDS ниже (раздел CONFIG).
"""

import asyncio
import datetime
import logging
import secrets

import aiosqlite
from aiogram import Bot, Dispatcher, Router, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import CommandStart, Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder


# =========================================================
# CONFIG
# =========================================================

BOT_TOKEN = "ВСТАВЬ_СЮДА_ТОКЕН_БОТА"

ADMIN_IDS = [
    123456789,  # <- замени на свой Telegram ID
]

DB_PATH = "shop.db"
RESELLER_PERCENT = 15  # % реф. бонуса реселлерам
CURRENCY = "₽"
SHOP_NAME = "OXIDE SHOP"


# =========================================================
# PREMIUM EMOJI
# =========================================================
# Чтобы вставить свои premium-эмодзи: пропиши себя в ADMIN_IDS, отправь боту
# сообщение из нужных эмодзи, ответь на него командой /getemoji — бот вернёт
# custom_emoji_id. Подставь их сюда.

EMOJI = {
    "fire": {"id": "5368324170671202286", "fallback": "🔥"},
    "check": {"id": "5417915203100613993", "fallback": "✅"},
    "cross": {"id": "5312536423851630001", "fallback": "❌"},
    "diamond": {"id": "5215916940135283532", "fallback": "💎"},
    "rocket": {"id": "5312241539987020022", "fallback": "🚀"},
    "money": {"id": "5417897114358827509", "fallback": "💰"},
    "key": {"id": "5312130595986467508", "fallback": "🔑"},
    "star": {"id": "5215919251696552044", "fallback": "⭐"},
    "warning": {"id": "5312241704671736656", "fallback": "⚠️"},
    "gear": {"id": "5312436424855871328", "fallback": "⚙️"},
}


def tg(key: str) -> str:
    e = EMOJI.get(key)
    if not e:
        return ""
    return f'<tg-emoji emoji-id="{e["id"]}">{e["fallback"]}</tg-emoji>'


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


# =========================================================
# DATABASE
# =========================================================

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    username    TEXT,
    balance     REAL DEFAULT 0,
    is_reseller INTEGER DEFAULT 0,
    ref_code    TEXT UNIQUE,
    invited_by  INTEGER,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS products (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    name            TEXT,
    description     TEXT,
    price           REAL,
    reseller_price  REAL,
    active          INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS stock (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id  INTEGER,
    key_value   TEXT,
    is_sold     INTEGER DEFAULT 0,
    buyer_id    INTEGER,
    sold_at     TEXT,
    FOREIGN KEY (product_id) REFERENCES products (id)
);

CREATE TABLE IF NOT EXISTS orders (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER,
    product_id  INTEGER,
    price_paid  REAL,
    created_at  TEXT
);
"""


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript(SCHEMA)
        await db.commit()


async def get_or_create_user(user_id: int, username: str, invited_by: int | None = None):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        if row:
            return dict(row)

        ref_code = secrets.token_hex(4)
        await db.execute(
            "INSERT INTO users (user_id, username, ref_code, invited_by, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (user_id, username, ref_code, invited_by, datetime.datetime.utcnow().isoformat()),
        )
        await db.commit()
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row)


async def get_user(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def get_user_by_ref(ref_code: str):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM users WHERE ref_code = ?", (ref_code,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def set_balance(user_id: int, amount: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()


async def set_reseller(user_id: int, flag: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET is_reseller = ? WHERE user_id = ?", (int(flag), user_id))
        await db.commit()


async def all_user_ids():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id FROM users")
        rows = await cur.fetchall()
        return [r[0] for r in rows]


async def add_product(name: str, description: str, price: float, reseller_price: float):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO products (name, description, price, reseller_price) VALUES (?, ?, ?, ?)",
            (name, description, price, reseller_price),
        )
        await db.commit()


async def list_products(active_only: bool = True):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        q = "SELECT * FROM products"
        if active_only:
            q += " WHERE active = 1"
        cur = await db.execute(q)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def get_product(product_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("SELECT * FROM products WHERE id = ?", (product_id,))
        row = await cur.fetchone()
        return dict(row) if row else None


async def stock_count(product_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute(
            "SELECT COUNT(*) FROM stock WHERE product_id = ? AND is_sold = 0", (product_id,)
        )
        (count,) = await cur.fetchone()
        return count


async def add_stock_bulk(product_id: int, keys: list[str]):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executemany(
            "INSERT INTO stock (product_id, key_value) VALUES (?, ?)",
            [(product_id, k) for k in keys],
        )
        await db.commit()


async def buy_product(user_id: int, product_id: int) -> dict | None:
    user = await get_user(user_id)
    product = await get_product(product_id)
    if not user or not product:
        return None

    price = product["reseller_price"] if user["is_reseller"] else product["price"]
    if user["balance"] < price:
        return None

    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT * FROM stock WHERE product_id = ? AND is_sold = 0 LIMIT 1", (product_id,)
        )
        stock_row = await cur.fetchone()
        if not stock_row:
            return None

        now = datetime.datetime.utcnow().isoformat()
        await db.execute(
            "UPDATE stock SET is_sold = 1, buyer_id = ?, sold_at = ? WHERE id = ?",
            (user_id, now, stock_row["id"]),
        )
        await db.execute("UPDATE users SET balance = balance - ? WHERE user_id = ?", (price, user_id))
        await db.execute(
            "INSERT INTO orders (user_id, product_id, price_paid, created_at) VALUES (?, ?, ?, ?)",
            (user_id, product_id, price, now),
        )
        await db.commit()

        if user["invited_by"]:
            cur = await db.execute("SELECT * FROM users WHERE user_id = ?", (user["invited_by"],))
            inviter = await cur.fetchone()
            if inviter and inviter["is_reseller"]:
                bonus = price * RESELLER_PERCENT / 100
                await db.execute(
                    "UPDATE users SET balance = balance + ? WHERE user_id = ?",
                    (bonus, inviter["user_id"]),
                )
                await db.commit()

        return {"key": stock_row["key_value"], "price": price}


async def user_orders(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute(
            "SELECT o.*, p.name as product_name FROM orders o "
            "JOIN products p ON p.id = o.product_id "
            "WHERE o.user_id = ? ORDER BY o.created_at DESC",
            (user_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


async def stats():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users")
        (users_count,) = await cur.fetchone()
        cur = await db.execute("SELECT COUNT(*), COALESCE(SUM(price_paid),0) FROM orders")
        orders_count, revenue = await cur.fetchone()
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE is_reseller = 1")
        (resellers_count,) = await cur.fetchone()
        return {
            "users": users_count,
            "orders": orders_count,
            "revenue": revenue,
            "resellers": resellers_count,
        }


# =========================================================
# KEYBOARDS
# =========================================================

def main_menu(admin: bool = False):
    b = InlineKeyboardBuilder()
    b.button(text=f"{EMOJI['fire']['fallback']} Каталог", callback_data="catalog")
    b.button(text=f"{EMOJI['money']['fallback']} Баланс", callback_data="balance")
    b.button(text=f"{EMOJI['key']['fallback']} Мои покупки", callback_data="orders")
    b.button(text=f"{EMOJI['diamond']['fallback']} Реф. программа", callback_data="referral")
    b.button(text="🛟 Поддержка", callback_data="support")
    if admin:
        b.button(text=f"{EMOJI['gear']['fallback']} Админ-панель", callback_data="admin")
    b.adjust(2, 2, 1, 1)
    return b.as_markup()


def catalog_kb(products: list[dict]):
    b = InlineKeyboardBuilder()
    for p in products:
        b.button(text=f"{p['name']}", callback_data=f"product_{p['id']}")
    b.button(text="⬅️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


def product_kb(product_id: int):
    b = InlineKeyboardBuilder()
    b.button(text=f"{EMOJI['check']['fallback']} Купить", callback_data=f"buy_{product_id}")
    b.button(text="⬅️ К каталогу", callback_data="catalog")
    b.adjust(1)
    return b.as_markup()


def back_kb(target: str = "back_main"):
    b = InlineKeyboardBuilder()
    b.button(text="⬅️ Назад", callback_data=target)
    return b.as_markup()


def admin_menu():
    b = InlineKeyboardBuilder()
    b.button(text="➕ Добавить товар", callback_data="admin_add_product")
    b.button(text="📦 Добавить ключи на склад", callback_data="admin_add_stock")
    b.button(text="📊 Статистика", callback_data="admin_stats")
    b.button(text="📢 Рассылка", callback_data="admin_broadcast")
    b.button(text="🤝 Выдать статус реселлера", callback_data="admin_set_reseller")
    b.button(text="💸 Пополнить баланс юзеру", callback_data="admin_add_balance")
    b.button(text="⬅️ Назад", callback_data="back_main")
    b.adjust(1)
    return b.as_markup()


# =========================================================
# FSM STATES
# =========================================================

class AddProduct(StatesGroup):
    name = State()
    description = State()
    price = State()
    reseller_price = State()


class AddStock(StatesGroup):
    product_id = State()
    keys = State()


class SetReseller(StatesGroup):
    user_id = State()


class AddBalance(StatesGroup):
    user_id = State()
    amount = State()


class Broadcast(StatesGroup):
    text = State()


# =========================================================
# USER HANDLERS
# =========================================================

user_router = Router()


@user_router.message(CommandStart())
async def cmd_start(message: Message, bot: Bot):
    args = message.text.split(maxsplit=1)
    invited_by = None
    if len(args) > 1 and args[1].startswith("ref_"):
        ref_code = args[1].removeprefix("ref_")
        inviter = await get_user_by_ref(ref_code)
        if inviter and inviter["user_id"] != message.from_user.id:
            invited_by = inviter["user_id"]

    await get_or_create_user(message.from_user.id, message.from_user.username, invited_by)

    text = (
        f"{tg('fire')} <b>{SHOP_NAME}</b> {tg('fire')}\n\n"
        f"Добро пожаловать{', ' + message.from_user.first_name if message.from_user.first_name else ''}!\n"
        f"Здесь ты можешь купить доступ к нашим продуктам и, если ты реселлер — "
        f"зарабатывать на реф. программе.\n\n"
        f"{tg('diamond')} Выбирай раздел ниже {tg('diamond')}"
    )
    await message.answer(text, reply_markup=main_menu(is_admin(message.from_user.id)))


@user_router.callback_query(F.data == "back_main")
async def back_main(call: CallbackQuery):
    await call.message.edit_text(
        f"{tg('fire')} <b>{SHOP_NAME}</b> — главное меню",
        reply_markup=main_menu(is_admin(call.from_user.id)),
    )
    await call.answer()


@user_router.callback_query(F.data == "catalog")
async def show_catalog(call: CallbackQuery):
    products = await list_products()
    if not products:
        await call.message.edit_text("Пока пусто, загляни позже 🙂", reply_markup=back_kb())
        await call.answer()
        return
    await call.message.edit_text(
        f"{tg('key')} <b>Каталог товаров</b>\nВыбери позицию:",
        reply_markup=catalog_kb(products),
    )
    await call.answer()


@user_router.callback_query(F.data.startswith("product_"))
async def show_product(call: CallbackQuery):
    product_id = int(call.data.split("_")[1])
    product = await get_product(product_id)
    if not product:
        await call.answer("Товар не найден", show_alert=True)
        return

    user = await get_user(call.from_user.id)
    price = product["reseller_price"] if user and user["is_reseller"] else product["price"]
    count = await stock_count(product_id)

    text = (
        f"{tg('star')} <b>{product['name']}</b>\n\n"
        f"{product['description']}\n\n"
        f"{tg('money')} Цена: <b>{price} {CURRENCY}</b>\n"
        f"{tg('check') if count else tg('cross')} В наличии: <b>{count}</b> шт."
    )
    await call.message.edit_text(text, reply_markup=product_kb(product_id))
    await call.answer()


@user_router.callback_query(F.data.startswith("buy_"))
async def buy_product_handler(call: CallbackQuery):
    product_id = int(call.data.split("_")[1])
    result = await buy_product(call.from_user.id, product_id)
    if not result:
        await call.answer(
            "Не получилось купить: либо нет товара в наличии, либо не хватает баланса.",
            show_alert=True,
        )
        return

    text = (
        f"{tg('check')} <b>Покупка успешна!</b>\n\n"
        f"Списано: <b>{result['price']} {CURRENCY}</b>\n\n"
        f"{tg('key')} Твой ключ:\n<code>{result['key']}</code>"
    )
    await call.message.answer(text)
    await call.answer()


@user_router.callback_query(F.data == "balance")
async def show_balance(call: CallbackQuery):
    user = await get_user(call.from_user.id)
    status = f"{tg('diamond')} Реселлер" if user["is_reseller"] else "Обычный клиент"
    text = (
        f"{tg('money')} <b>Твой баланс:</b> {user['balance']} {CURRENCY}\n"
        f"Статус: {status}\n\n"
        f"Чтобы пополнить баланс — напиши в поддержку."
    )
    await call.message.edit_text(text, reply_markup=back_kb())
    await call.answer()


@user_router.callback_query(F.data == "orders")
async def show_orders(call: CallbackQuery):
    orders = await user_orders(call.from_user.id)
    if not orders:
        await call.message.edit_text("У тебя пока нет покупок.", reply_markup=back_kb())
        await call.answer()
        return
    lines = [f"{tg('check')} <b>История покупок</b>\n"]
    for o in orders[:20]:
        lines.append(f"• {o['product_name']} — {o['price_paid']} {CURRENCY} ({o['created_at'][:16]})")
    await call.message.edit_text("\n".join(lines), reply_markup=back_kb())
    await call.answer()


@user_router.callback_query(F.data == "referral")
async def show_referral(call: CallbackQuery, bot: Bot):
    user = await get_user(call.from_user.id)
    me = await bot.get_me()
    link = f"https://t.me/{me.username}?start=ref_{user['ref_code']}"
    status = "активен ✅" if user["is_reseller"] else "не активен (обратись к админу за статусом реселлера)"

    text = (
        f"{tg('rocket')} <b>Реферальная программа</b>\n\n"
        f"Твоя ссылка:\n<code>{link}</code>\n\n"
        f"Статус реселлера: {status}\n"
        f"Если ты реселлер — получаешь бонус на баланс с каждой покупки "
        f"приглашённого пользователя."
    )
    await call.message.edit_text(text, reply_markup=back_kb())
    await call.answer()


@user_router.callback_query(F.data == "support")
async def show_support(call: CallbackQuery):
    text = f"{tg('warning')} По всем вопросам пиши администратору магазина."
    await call.message.edit_text(text, reply_markup=back_kb())
    await call.answer()


@user_router.message(Command("getemoji"))
async def get_emoji_ids(message: Message):
    if not is_admin(message.from_user.id):
        return
    if not message.reply_to_message:
        await message.answer("Ответь этой командой на сообщение, содержащее premium-эмодзи.")
        return

    target = message.reply_to_message
    if not target.entities:
        await message.answer("В этом сообщении не найдено эмодзи-сущностей.")
        return

    found = []
    for ent in target.entities:
        if ent.type == "custom_emoji":
            piece = target.text[ent.offset: ent.offset + ent.length]
            found.append(f"{piece} → <code>{ent.custom_emoji_id}</code>")

    if not found:
        await message.answer("Premium-эмодзи не найдены (обычные эмодзи не имеют ID).")
        return

    await message.answer("Найденные ID:\n" + "\n".join(found))


# =========================================================
# ADMIN HANDLERS
# =========================================================

admin_router = Router()


@admin_router.callback_query(F.data == "admin")
async def admin_panel(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("Нет доступа", show_alert=True)
        return
    await call.message.edit_text(f"{tg('gear')} <b>Админ-панель</b>", reply_markup=admin_menu())
    await call.answer()


@admin_router.callback_query(F.data == "admin_add_product")
async def add_product_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AddProduct.name)
    await call.message.edit_text("Введи название товара:", reply_markup=back_kb("admin"))
    await call.answer()


@admin_router.message(StateFilter(AddProduct.name))
async def add_product_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text)
    await state.set_state(AddProduct.description)
    await message.answer("Введи описание товара:")


@admin_router.message(StateFilter(AddProduct.description))
async def add_product_desc(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await state.set_state(AddProduct.price)
    await message.answer("Введи розничную цену (число):")


@admin_router.message(StateFilter(AddProduct.price))
async def add_product_price(message: Message, state: FSMContext):
    try:
        price = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Нужно число, попробуй ещё раз:")
        return
    await state.update_data(price=price)
    await state.set_state(AddProduct.reseller_price)
    await message.answer("Введи цену для реселлеров (число):")


@admin_router.message(StateFilter(AddProduct.reseller_price))
async def add_product_reseller_price(message: Message, state: FSMContext):
    try:
        reseller_price = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Нужно число, попробуй ещё раз:")
        return
    data = await state.get_data()
    await add_product(data["name"], data["description"], data["price"], reseller_price)
    await state.clear()
    await message.answer(f"{tg('check')} Товар добавлен!", reply_markup=admin_menu())


@admin_router.callback_query(F.data == "admin_add_stock")
async def add_stock_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    products = await list_products(active_only=False)
    if not products:
        await call.message.edit_text("Сначала добавь хотя бы один товар.", reply_markup=admin_menu())
        await call.answer()
        return
    listing = "\n".join(f"{p['id']} — {p['name']}" for p in products)
    await state.set_state(AddStock.product_id)
    await call.message.edit_text(
        f"Введи ID товара, к которому добавляем ключи:\n\n{listing}", reply_markup=back_kb("admin")
    )
    await call.answer()


@admin_router.message(StateFilter(AddStock.product_id))
async def add_stock_pid(message: Message, state: FSMContext):
    try:
        pid = int(message.text)
    except ValueError:
        await message.answer("Нужен числовой ID, попробуй ещё раз:")
        return
    product = await get_product(pid)
    if not product:
        await message.answer("Товар с таким ID не найден, попробуй ещё раз:")
        return
    await state.update_data(product_id=pid)
    await state.set_state(AddStock.keys)
    await message.answer("Пришли ключи — каждый с новой строки:")


@admin_router.message(StateFilter(AddStock.keys))
async def add_stock_keys(message: Message, state: FSMContext):
    keys = [line.strip() for line in message.text.splitlines() if line.strip()]
    data = await state.get_data()
    await add_stock_bulk(data["product_id"], keys)
    await state.clear()
    await message.answer(f"{tg('check')} Добавлено ключей: {len(keys)}", reply_markup=admin_menu())


@admin_router.callback_query(F.data == "admin_set_reseller")
async def set_reseller_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(SetReseller.user_id)
    await call.message.edit_text(
        "Пришли Telegram ID пользователя, которому нужно выдать статус реселлера:",
        reply_markup=back_kb("admin"),
    )
    await call.answer()


@admin_router.message(StateFilter(SetReseller.user_id))
async def set_reseller_apply(message: Message, state: FSMContext):
    try:
        uid = int(message.text)
    except ValueError:
        await message.answer("Нужен числовой ID, попробуй ещё раз:")
        return
    user = await get_user(uid)
    if not user:
        await message.answer("Такой пользователь ещё не запускал бота.")
        await state.clear()
        return
    await set_reseller(uid, True)
    await state.clear()
    await message.answer(f"{tg('diamond')} Пользователь {uid} теперь реселлер.", reply_markup=admin_menu())


@admin_router.callback_query(F.data == "admin_add_balance")
async def add_balance_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(AddBalance.user_id)
    await call.message.edit_text("Пришли Telegram ID пользователя:", reply_markup=back_kb("admin"))
    await call.answer()


@admin_router.message(StateFilter(AddBalance.user_id))
async def add_balance_uid(message: Message, state: FSMContext):
    try:
        uid = int(message.text)
    except ValueError:
        await message.answer("Нужен числовой ID, попробуй ещё раз:")
        return
    user = await get_user(uid)
    if not user:
        await message.answer("Такой пользователь ещё не запускал бота.")
        await state.clear()
        return
    await state.update_data(user_id=uid)
    await state.set_state(AddBalance.amount)
    await message.answer("На сколько пополнить баланс (число, можно отрицательное)?")


@admin_router.message(StateFilter(AddBalance.amount))
async def add_balance_amount(message: Message, state: FSMContext):
    try:
        amount = float(message.text.replace(",", "."))
    except ValueError:
        await message.answer("Нужно число, попробуй ещё раз:")
        return
    data = await state.get_data()
    await set_balance(data["user_id"], amount)
    await state.clear()
    await message.answer(
        f"{tg('money')} Баланс пользователя {data['user_id']} изменён на {amount}.",
        reply_markup=admin_menu(),
    )


@admin_router.callback_query(F.data == "admin_stats")
async def show_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    s = await stats()
    text = (
        f"{tg('star')} <b>Статистика</b>\n\n"
        f"Пользователей: {s['users']}\n"
        f"Реселлеров: {s['resellers']}\n"
        f"Заказов: {s['orders']}\n"
        f"Выручка: {s['revenue']}"
    )
    await call.message.edit_text(text, reply_markup=admin_menu())
    await call.answer()


@admin_router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(call: CallbackQuery, state: FSMContext):
    if not is_admin(call.from_user.id):
        return
    await state.set_state(Broadcast.text)
    await call.message.edit_text("Пришли текст рассылки (HTML разрешён):", reply_markup=back_kb("admin"))
    await call.answer()


@admin_router.message(StateFilter(Broadcast.text))
async def broadcast_send(message: Message, state: FSMContext, bot: Bot):
    await state.clear()
    ids = await all_user_ids()
    sent, failed = 0, 0
    status_msg = await message.answer(f"Рассылка запущена на {len(ids)} пользователей...")
    for uid in ids:
        try:
            await bot.send_message(uid, message.html_text)
            sent += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)
    await status_msg.edit_text(f"{tg('check')} Готово. Успешно: {sent}, ошибок: {failed}.")


# =========================================================
# ENTRYPOINT
# =========================================================

async def main():
    logging.basicConfig(level=logging.INFO)

    await init_db()

    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(admin_router)
    dp.include_router(user_router)

    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())

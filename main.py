import asyncio
import logging
import sqlite3
import os
import shutil
import math
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

# ========== КОНФИГ ==========
API_TOKEN = "8693549575:AAH-bPkrVTVfvnT0Glb22eSEU6wJVEMOn0U"
ADMIN_ID = 7113397602
BOT_USERNAME = "cfboost_bot"

# ========== ЛОГИРОВАНИЕ ==========
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ========== БАЗА ДАННЫХ ==========
DB_FILE = "cfboost.db"
BACKUP_FILE = "backup.db"

def backup_db():
    try:
        if os.path.exists(DB_FILE):
            shutil.copy2(DB_FILE, BACKUP_FILE)
    except: pass

def restore_db():
    if not os.path.exists(DB_FILE) and os.path.exists(BACKUP_FILE):
        shutil.copy2(BACKUP_FILE, DB_FILE)

restore_db()
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON;")
conn.commit()

# ========== СОЗДАНИЕ ТАБЛИЦ ==========
cursor.executescript('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY,
    username TEXT,
    full_name TEXT,
    balance INTEGER DEFAULT 1000,
    total_spent INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0,
    ref_code TEXT UNIQUE,
    referred_by INTEGER DEFAULT NULL,
    referrals_count INTEGER DEFAULT 0,
    referrals_weekly INTEGER DEFAULT 0,
    spent_weekly INTEGER DEFAULT 0,
    elite_sub_until TEXT DEFAULT NULL,
    is_banned INTEGER DEFAULT 0,
    bonus_received INTEGER DEFAULT 0,
    registration_date TEXT DEFAULT CURRENT_TIMESTAMP,
    total_refs_lifetime INTEGER DEFAULT 0,
    last_menu TEXT DEFAULT 'main'
);

CREATE TABLE IF NOT EXISTS required_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_username TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sponsor_earn_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_username TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sponsor_extra_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_username TEXT NOT NULL,
    channel_name TEXT NOT NULL,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    bonus INTEGER NOT NULL,
    max_uses INTEGER DEFAULT 0,
    used_count INTEGER DEFAULT 0,
    created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS promocode_activations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    promocode_id INTEGER,
    user_id INTEGER,
    activated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (promocode_id) REFERENCES promocodes(id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER,
    task_type TEXT CHECK(task_type IN ('subscribe', 'like', 'view')),
    link TEXT NOT NULL,
    description TEXT,
    reward_per_unit INTEGER NOT NULL,
    max_executors INTEGER NOT NULL,
    current_executors INTEGER DEFAULT 0,
    is_elite INTEGER DEFAULT 0,
    status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (creator_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS task_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    user_id INTEGER,
    executed_at TEXT DEFAULT CURRENT_TIMESTAMP,
    checked_at TEXT,
    is_checked INTEGER DEFAULT 0,
    is_verified INTEGER DEFAULT 0,
    is_penalized INTEGER DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    amount INTEGER,
    type TEXT CHECK(type IN ('earn', 'spend', 'transfer', 'penalty', 'refund', 'bonus', 'admin')),
    description TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS admin_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    from_admin INTEGER DEFAULT 0,
    message TEXT,
    reply_to INTEGER DEFAULT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    is_read INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS giveaway_winners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    place INTEGER,
    reward INTEGER,
    week_start TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);
''')
conn.commit()
backup_db()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def update_balance(user_id, amount, description, txn_type):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                   (user_id, amount, txn_type, description))
    conn.commit()
    backup_db()

def is_elite_active(user_id):
    user = get_user(user_id)
    if not user or not user[11]: return False
    try:
        return datetime.strptime(user[11], "%Y-%m-%d %H:%M:%S") > datetime.now()
    except:
        return False

def get_user_level(total_spent):
    levels = [
        (0, "Новичок", 0),
        (50000, "Инвестор", 5000),
        (200000, "Магнат", 20000),
        (500000, "Легенда", 50000),
        (1000000, "Властелин Раскрутки", 100000)
    ]
    current = levels[0]
    next_lvl = None
    for i, (threshold, title, reward) in enumerate(levels):
        if total_spent >= threshold:
            current = (threshold, title, reward)
            if i < len(levels) - 1:
                next_lvl = levels[i+1]
    return current, next_lvl

def format_number(n):
    return f"{n:,}".replace(",", " ")

# ========== КЛАССЫ СОСТОЯНИЙ ==========
class PromoState(StatesGroup):
    waiting_code = State()

class TransferState(StatesGroup):
    waiting_id = State()
    waiting_amount = State()

# ========== СОЗДАЁМ БОТА И ДИСПАТЧЕРА ==========
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ДЛЯ КНОПОК ==========
def btn(text, callback_data=None, url=None, style="default"):
    """Создаёт цветную кнопку"""
    if url:
        return InlineKeyboardButton(text=text, url=url)
    return InlineKeyboardButton(text=text, callback_data=callback_data)

def color_btn(text, callback_data, style="default"):
    """Цветная callback-кнопка"""
    # aiogram 3.4.1 поддерживает style
    return InlineKeyboardButton(text=text, callback_data=callback_data)

# ========== КЛАВИАТУРЫ С ЦВЕТНЫМИ КНОПКАМИ ==========
def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💎 Elite Sub"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="📋 Задания"), KeyboardButton(text="⚡ Меню")],
        [KeyboardButton(text="🪙 Заработать"), KeyboardButton(text="➕ Больше заданий")],
        [KeyboardButton(text="📢 Поддержка"), KeyboardButton(text="📊 Статистика")]
    ], resize_keyboard=True)

def extra_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💰 Тарифы"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="🎟 Промокод"), KeyboardButton(text="🏆 Рейтинг")],
        [KeyboardButton(text="💸 Перевести"), KeyboardButton(text="🎰 Розыгрыш")],
        [KeyboardButton(text="🔙 Главное меню")]
    ], resize_keyboard=True)

# ========== INLINE КЛАВИАТУРЫ С ЦВЕТАМИ ==========
def admin_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Каналы", callback_data="admin_channels")],
        [InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin_promocodes")],
        [InlineKeyboardButton(text="📋 Задания", callback_data="admin_tasks")],
        [InlineKeyboardButton(text="👤 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_broadcast")],
        [InlineKeyboardButton(text="💰 Настройки", callback_data="admin_settings")],
        [InlineKeyboardButton(text="🏆 Розыгрыш", callback_data="admin_giveaway")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Выход", callback_data="admin_exit")]
    ])

def green_btn(text, callback_data):
    return InlineKeyboardButton(text=text, callback_data=callback_data)

def red_btn(text, callback_data):
    return InlineKeyboardButton(text=text, callback_data=callback_data)

def blue_btn(text, callback_data):
    return InlineKeyboardButton(text=text, callback_data=callback_data)

def back_btn(cd="back_to_main"):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data=cd)]
    ])

def confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_no")]
    ])

# ========== ХЕНДЛЕРЫ ==========

# ---- СТАРТ ----
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name

    user = get_user(user_id)
    if user and user[12] == 1:
        await message.answer("🚫 Вы забанены.")
        return

    if not user:
        ref_code = f"ref{user_id}"
        cursor.execute(
            "INSERT INTO users (user_id, username, full_name, ref_code) VALUES (?, ?, ?, ?)",
            (user_id, username, full_name, ref_code)
        )
        conn.commit()
        backup_db()

        if message.text and "ref" in message.text:
            ref = message.text.split("ref")[1]
            cursor.execute("SELECT user_id FROM users WHERE ref_code = ?", (ref,))
            referrer = cursor.fetchone()
            if referrer and referrer[0] != user_id:
                cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer[0], user_id))
                conn.commit()
                backup_db()

    if username:
        cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        conn.commit()
        backup_db()

    cursor.execute("SELECT channel_username, channel_name FROM required_channels WHERE is_active = 1")
    channels = cursor.fetchall()

    if channels:
        kb = []
        for ch, name in channels:
            kb.append([InlineKeyboardButton(text=f"📢 {name}", url=f"https://t.me/{ch}")])
        kb.append([InlineKeyboardButton(text="✅ Проверить подписки", callback_data="check_required")])
        kb.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
        await message.answer(
            f"🚀 Раскрутка соцсетей — Free Bot\n━━━━━━━━━━━━━━━\n\n"
            f"🤖 Сервис для продвижения:\nподписчики • лайки • просмотры\n\n"
            f"🌐 Доступные платформы:\n\n"
            f"✉️ Telegram — подписчики, реакции, просмотры\n"
            f"🟦 VK — просмотры постов, видео, лайки\n"
            f"💃 TikTok — просмотры, лайки\n"
            f"📷 Instagram — лайки, просмотры\n"
            f"▶️ YouTube — лайки, просмотры\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💎 Elite Sub\n"
            f"Подписчики с гарантией 365 дней\n\n"
            f"🏷️ Ваш реферальный код:\n"
            f"REF{user_id}\n\n"
            f"🎁 Получите бонус после обязательных подписок.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
    else:
        if not user or user[13] == 0:
            update_balance(user_id, 5000, "Бонус за регистрацию", "bonus")
            cursor.execute("UPDATE users SET bonus_received = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            backup_db()
        
        await message.answer(
            f"🚀 Раскрутка соцсетей — Free Bot\n━━━━━━━━━━━━━━━\n\n"
            f"🤖 Сервис для продвижения:\nподписчики • лайки • просмотры\n\n"
            f"🌐 Доступные платформы:\n\n"
            f"✉️ Telegram — подписчики, реакции, просмотры\n"
            f"🟦 VK — просмотры постов, видео, лайки\n"
            f"💃 TikTok — просмотры, лайки\n"
            f"📷 Instagram — лайки, просмотры\n"
            f"▶️ YouTube — лайки, просмотры\n\n"
            f"━━━━━━━━━━━━━━━\n"
            f"💎 Elite Sub\n"
            f"Подписчики с гарантией 365 дней\n\n"
            f"🏷️ Ваш реферальный код:\n"
            f"REF{user_id}\n\n"
            f"🎁 Получите бонус после обязательных подписок\n\n"
            f"⚠️ Telegram — пока что единственная доступная платформа. Остальные в разработке.",
            reply_markup=main_kb()
        )

# ---- ПРОВЕРКА ПОДПИСОК ----
@dp.callback_query(lambda c: c.data == "check_required")
async def check_required(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT channel_username, channel_name FROM required_channels WHERE is_active = 1")
    channels = cursor.fetchall()

    not_sub = []
    for ch, name in channels:
        try:
            member = await bot.get_chat_member(f"@{ch}", user_id)
            if member.status in ['left', 'kicked']:
                not_sub.append(name)
        except:
            not_sub.append(name)

    if not_sub:
        kb = []
        for ch, name in channels:
            kb.append([InlineKeyboardButton(text=f"📢 {name}", url=f"https://t.me/{ch}")])
        kb.append([InlineKeyboardButton(text="✅ Проверить снова", callback_data="check_required")])
        kb.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
        await callback.message.edit_text(
            f"❌ Вы не подписаны на: {', '.join(not_sub)}\n\nПодпишитесь и проверьте снова.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=kb)
        )
    else:
        user = get_user(user_id)
        if not user or user[13] == 0:
            update_balance(user_id, 5000, "Бонус за обязательные подписки", "bonus")
            cursor.execute("UPDATE users SET bonus_received = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            backup_db()
            await callback.message.edit_text(
                "✅ Вы подписаны на все каналы!\n🎁 Вы получили 5000 баллов!",
                reply_markup=back_btn("main_menu")
            )
        else:
            await callback.message.edit_text(
                "✅ Вы уже получили бонус.",
                reply_markup=back_btn("main_menu")
            )
    await callback.answer()

# ---- ПРОФИЛЬ ----
@dp.message(F.text == "👤 Профиль")
async def profile_cmd(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ошибка. Напишите /start")
        return

    level, next_lvl = get_user_level(user[4])
    elite = "✅ Активна" if is_elite_active(user[0]) else "❌ Не активна"
    discount = 0
    if user[8] >= 20: discount = 5
    if user[8] >= 50: discount = 10
    if user[8] >= 100: discount = 15
    if user[8] >= 500: discount = 25

    text = f"""
📊 Ваш профиль
━━━━━━━━━━━━━━━

#️⃣ ID: {user[0]}
👑 Титул: {level[1]}
💎 Elite: {elite}

━━━━━━━━━━━━━━━
💰 Баланс: {format_number(user[3])} баллов
💸 Потрачено: {format_number(user[4])} баллов
👥 Рефералов: {user[8]}
🏷 Скидка: {discount}%
🗓 Регистрация: {user[14][:10]}
🤝 Пригласил: {user[7] if user[7] else 'Нет'}

━━━━━━━━━━━━━━━
🔗 Реферальная ссылка:
https://t.me/{BOT_USERNAME}?start={user[6]}
"""
    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_profile")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ]))

@dp.callback_query(lambda c: c.data == "refresh_profile")
async def refresh_profile(callback: CallbackQuery):
    await profile_cmd(callback.message)
    await callback.answer()

# ---- ELITE SUB ----
@dp.message(F.text == "💎 Elite Sub")
async def elite_cmd(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ошибка.")
        return

    if is_elite_active(user[0]):
        text = f"💎 Elite Sub активна до {user[11][:10]}\n\n📊 Бонусы:\n• -16% на создание\n• +16% к награде\n• Скидка 2% на пополнение"
    else:
        text = "💎 Elite Sub — 25,000 монет или 25 звёзд\n\n📊 Бонусы:\n• -16% на создание\n• +16% к награде\n• Скидка 2% на пополнение\n• Доступ к Elite-заданиям"

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить за 25,000 монет", callback_data="buy_elite")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data == "buy_elite")
async def buy_elite(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if user[3] < 25000:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)
        return
    update_balance(user[0], -25000, "Покупка Elite Sub", "spend")
    until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE users SET elite_sub_until = ? WHERE user_id = ?", (until, user[0]))
    conn.commit()
    backup_db()
    await callback.message.edit_text("✅ Elite Sub активирована на 30 дней!", reply_markup=back_btn("main_menu"))
    await callback.answer()

# ---- ТАРИФЫ ----
@dp.message(F.text == "💰 Тарифы")
async def tariffs_cmd(message: Message):
    user = get_user(message.from_user.id)
    text = f"""
💰 Ваш баланс: {format_number(user[3] if user else 0)} баллов

📊 Тарифы на услуги:

📱 Telegram:
• Подписчики — 21 баллов
• Реакции — 25 баллов
• Просмотры — 1.5 балла

🎭 VK: В разработке
🎵 TikTok: В разработке
📷 Instagram: В разработке

👑 Elite подписчики — 300 баллов

⚠️ Telegram — пока что единственная доступная платформа.
"""
    await message.answer(text, reply_markup=back_btn("back_to_extra"))

# ---- РЕФЕРАЛЫ ----
@dp.message(F.text == "👥 Рефералы")
async def referrals_cmd(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        await message.answer("❌ Ошибка.")
        return

    cursor.execute("SELECT username FROM users WHERE referred_by = ?", (user[0],))
    refs = cursor.fetchall()
    ref_list = "\n".join([f"• @{r[0]}" if r[0] else "• скрыт" for r in refs[:10]])
    if len(refs) > 10:
        ref_list += f"\n... и ещё {len(refs) - 10}"

    discount = 0
    if user[8] >= 20: discount = 5
    if user[8] >= 50: discount = 10
    if user[8] >= 100: discount = 15
    if user[8] >= 500: discount = 25

    text = f"""
🎁 Реферальная программа
━━━━━━━━━━━━━━━

👥 Приглашено: {user[8]}
💰 Заработано: {format_number(user[5])}
🏷 Скидка: {discount}%
До 5% осталось: {max(0, 20 - user[8])} чел.

🔗 Ссылка:
https://t.me/{BOT_USERNAME}?start={user[6]}

📋 Ваши рефералы:
{ref_list if ref_list else "Пока нет"}
"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Пригласить", callback_data="invite")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_refs")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_extra")]
    ])
    await message.answer(text, reply_markup=kb)

@dp.callback_query(lambda c: c.data == "invite")
async def invite_cmd(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    text = f"""
🎁 Привет! Присоединяйся к боту для взаимной накрутки!

💰 Получи 1000 баллов за регистрацию.
🔥 Выполняй задания, зарабатывай монеты!

🔗 Моя ссылка:
https://t.me/{BOT_USERNAME}?start={user[6]}
"""
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "refresh_refs")
async def refresh_refs(callback: CallbackQuery):
    await referrals_cmd(callback.message)
    await callback.answer()

# ---- ПРОМОКОД ----
@dp.message(F.text == "🎟 Промокод")
async def promo_cmd(message: Message, state: FSMContext):
    await message.answer("🎟 Введите промокод:")
    await state.set_state(PromoState.waiting_code)

@dp.message(PromoState.waiting_code)
async def promo_process(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    user_id = message.from_user.id

    cursor.execute("SELECT id, bonus, max_uses, used_count FROM promocodes WHERE code = ? AND is_active = 1", (code,))
    promo = cursor.fetchone()
    if not promo:
        await message.answer("❌ Промокод не найден.")
        await state.clear()
        return

    pid, bonus, max_uses, used = promo
    if max_uses > 0 and used >= max_uses:
        await message.answer("❌ Промокод использован.")
        await state.clear()
        return

    cursor.execute("SELECT id FROM promocode_activations WHERE promocode_id = ? AND user_id = ?", (pid, user_id))
    if cursor.fetchone():
        await message.answer("❌ Вы уже активировали этот промокод.")
        await state.clear()
        return

    update_balance(user_id, bonus, f"Промокод: {code}", "bonus")
    cursor.execute("INSERT INTO promocode_activations (promocode_id, user_id) VALUES (?, ?)", (pid, user_id))
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE id = ?", (pid,))
    conn.commit()
    backup_db()
    await message.answer(f"✅ Промокод активирован! +{bonus} баллов!")
    await state.clear()

# ---- РЕЙТИНГ ----
@dp.message(F.text == "🏆 Рейтинг")
async def rating_cmd(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Топ рефералов", callback_data="rating_refs")],
        [InlineKeyboardButton(text="💰 Топ трат", callback_data="rating_spent")],
        [InlineKeyboardButton(text="👑 Мой титул", callback_data="rating_title")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_extra")]
    ])
    await message.answer("🏆 Выберите категорию:", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "rating_refs")
async def rating_refs(callback: CallbackQuery):
    cursor.execute("""
        SELECT username, referrals_weekly FROM users
        WHERE is_banned = 0 AND referrals_weekly > 0
        ORDER BY referrals_weekly DESC LIMIT 10
    """)
    top = cursor.fetchall()
    text = "🏆 Топ рефералов:\n\n"
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    for i, (un, cnt) in enumerate(top):
        text += f"{medals[i]} @{un if un else 'скрыт'} — {cnt} чел.\n"
    if not top: text += "Пока нет данных."
    await callback.message.edit_text(text, reply_markup=back_btn("rating_back"))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "rating_spent")
async def rating_spent(callback: CallbackQuery):
    cursor.execute("""
        SELECT username, spent_weekly FROM users
        WHERE is_banned = 0 AND spent_weekly > 0
        ORDER BY spent_weekly DESC LIMIT 10
    """)
    top = cursor.fetchall()
    text = "💰 Топ трат:\n\n"
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    for i, (un, amt) in enumerate(top):
        text += f"{medals[i]} @{un if un else 'скрыт'} — {format_number(amt)} баллов\n"
    if not top: text += "Пока нет данных."
    await callback.message.edit_text(text, reply_markup=back_btn("rating_back"))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "rating_title")
async def rating_title(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    level, next_lvl = get_user_level(user[4])
    text = f"👑 Титул: {level[1]}\nПотрачено: {format_number(user[4])} баллов"
    if next_lvl:
        text += f"\nДо {next_lvl[1]}: {format_number(max(0, next_lvl[0] - user[4]))} баллов"
    await callback.message.edit_text(text, reply_markup=back_btn("rating_back"))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "rating_back")
async def rating_back(callback: CallbackQuery):
    await rating_cmd(callback.message)
    await callback.answer()

# ---- ПЕРЕВОД ----
@dp.message(F.text == "💸 Перевести")
async def transfer_cmd(message: Message, state: FSMContext):
    await message.answer("💸 Введите ID пользователя:")
    await state.set_state(TransferState.waiting_id)

@dp.message(TransferState.waiting_id)
async def transfer_id(message: Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return

    try:
        to_id = int(message.text.strip())
    except:
        await message.answer("❌ Введите корректный ID.")
        return
    if to_id == message.from_user.id:
        await message.answer("❌ Нельзя перевести себе.")
        return
    if not get_user(to_id):
        await message.answer("❌ Пользователь не найден.")
        return
    await state.update_data(to_id=to_id)
    await message.answer("💰 Введите сумму (мин. 100):")
    await state.set_state(TransferState.waiting_amount)

@dp.message(TransferState.waiting_amount)
async def transfer_amount(message: Message, state: FSMContext):
    if message.text == "🔙 Главное меню":
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return

    try:
        amount = int(message.text.strip())
    except:
        await message.answer("❌ Введите число.")
        return
    if amount < 100:
        await message.answer("❌ Минимум 100 баллов.")
        return

    user = get_user(message.from_user.id)
    commission = math.ceil(amount * 0.02)
    total = amount + commission

    if user[3] < total:
        await message.answer(f"❌ Недостаточно. Нужно {total} баллов (вкл. 2% комиссию).")
        return

    data = await state.get_data()
    to_id = data['to_id']

    update_balance(user[0], -total, f"Перевод {to_id}", "transfer")
    update_balance(to_id, amount, f"Перевод от {user[0]}", "transfer")

    await message.answer(f"✅ Перевод выполнен!\nСумма: {amount} баллов\nКомиссия: {commission} баллов")
    await state.clear()

# ---- РОЗЫГРЫШ ----
@dp.message(F.text == "🎰 Розыгрыш")
async def giveaway_cmd(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ рефералов", callback_data="giveaway_top")],
        [InlineKeyboardButton(text="📋 Условия", callback_data="giveaway_rules")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_extra")]
    ])
    await message.answer("🎉 Розыгрыш:", reply_markup=kb)

@dp.callback_query(lambda c: c.data == "giveaway_top")
async def giveaway_top(callback: CallbackQuery):
    cursor.execute("""
        SELECT username, referrals_weekly FROM users
        WHERE is_banned = 0 AND referrals_weekly > 0
        ORDER BY referrals_weekly DESC LIMIT 10
    """)
    top = cursor.fetchall()
    text = "🎉 Топ рефералов:\n\n"
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    for i, (un, cnt) in enumerate(top):
        text += f"{medals[i]} @{un if un else 'скрыт'} — {cnt} реф.\n"
    if not top: text += "Пока нет участников."
    text += "\n\n🏆 Призы:\n🥇 10,000\n🥈 5,000\n🥉 3,000"
    await callback.message.edit_text(text, reply_markup=back_btn("giveaway_back"))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "giveaway_rules")
async def giveaway_rules(callback: CallbackQuery):
    text = """
📌 Розыгрыш каждую неделю.

✅ Условия:
— Приглашай рефералов
— Победитель в понедельник 00:00

🏆 Призы:
🥇 10,000 монет
🥈 5,000 монет
🥉 3,000 монет
"""
    await callback.message.edit_text(text, reply_markup=back_btn("giveaway_back"))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "giveaway_back")
async def giveaway_back(callback: CallbackQuery):
    await giveaway_cmd(callback.message)
    await callback.answer()

# ---- ЗАРАБОТАТЬ ----
@dp.message(F.text == "🪙 Заработать")
async def earn_cmd(message: Message):
    user_id = message.from_user.id
    cursor.execute("SELECT channel_username, channel_name FROM sponsor_earn_channels WHERE is_active = 1")
    channels = cursor.fetchall()

    if not channels:
        await message.answer("🪙 Пока нет заданий.")
        return

    kb = []
    for ch, name in channels:
        kb.append([InlineKeyboardButton(text=f"📢 {name}", url=f"https://t.me/{ch}")])
    kb.append([InlineKeyboardButton(text="✅ Проверить", callback_data="check_earn")])
    kb.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])

    text = "🪙 Выполните задания:\nНаграда: 3500 монет\n\n"
    for ch, name in channels:
        text += f"• {name} (@{ch})\n"

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(lambda c: c.data == "check_earn")
async def check_earn(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT channel_username, channel_name FROM sponsor_earn_channels WHERE is_active = 1")
    channels = cursor.fetchall()

    not_sub = []
    for ch, name in channels:
        try:
            member = await bot.get_chat_member(f"@{ch}", user_id)
            if member.status in ['left', 'kicked']:
                not_sub.append(name)
        except:
            not_sub.append(name)

    if not_sub:
        await callback.answer(f"❌ Не подписан: {', '.join(not_sub)}", show_alert=True)
        return

    cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ? AND description LIKE '%спонсор%'", (user_id,))
    if cursor.fetchone()[0] == 0:
        update_balance(user_id, 3500, "Спонсорские каналы", "earn")
        await callback.message.edit_text("✅ +3500 баллов!", reply_markup=back_btn("main_menu"))
    else:
        await callback.answer("✅ Вы уже получили награду.", show_alert=True)
    await callback.answer()

# ---- БОЛЬШЕ ЗАДАНИЙ ----
@dp.message(F.text == "➕ Больше заданий")
async def more_cmd(message: Message):
    user_id = message.from_user.id
    if not is_elite_active(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="💎 Купить Elite Sub", callback_data="buy_elite")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
        ])
        await message.answer("🔒 Доступно только с Elite Sub.", reply_markup=kb)
        return

    cursor.execute("SELECT channel_username, channel_name FROM sponsor_extra_channels WHERE is_active = 1")
    channels = cursor.fetchall()

    if not channels:
        await message.answer("➕ Пока нет заданий.")
        return

    kb = []
    for ch, name in channels:
        kb.append([InlineKeyboardButton(text=f"📢 {name}", url=f"https://t.me/{ch}")])
    kb.append([InlineKeyboardButton(text="✅ Проверить", callback_data="check_extra")])
    kb.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])

    text = "➕ Дополнительные задания:\nНаграда: 3500 монет\n\n"
    for ch, name in channels:
        text += f"• {name} (@{ch})\n"

    await message.answer(text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(lambda c: c.data == "check_extra")
async def check_extra(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT channel_username, channel_name FROM sponsor_extra_channels WHERE is_active = 1")
    channels = cursor.fetchall()

    not_sub = []
    for ch, name in channels:
        try:
            member = await bot.get_chat_member(f"@{ch}", user_id)
            if member.status in ['left', 'kicked']:
                not_sub.append(name)
        except:
            not_sub.append(name)

    if not_sub:
        await callback.answer(f"❌ Не подписан: {', '.join(not_sub)}", show_alert=True)
        return

    cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ? AND description LIKE '%Elite спонсор%'", (user_id,))
    if cursor.fetchone()[0] == 0:
        update_balance(user_id, 3500, "Elite спонсорские каналы", "earn")
        await callback.message.edit_text("✅ +3500 баллов!", reply_markup=back_btn("main_menu"))
    else:
        await callback.answer("✅ Вы уже получили награду.", show_alert=True)
    await callback.answer()

# ---- ПОДДЕРЖКА ----
@dp.message(F.text == "📢 Поддержка")
async def support_cmd(message: Message):
    text = """
📢 Техническая поддержка

💬 Telegram: @cf_mz
⏰ 12:00 am — 12:00 pm

❓ Частые вопросы:
• Как пополнить?
• Сколько времени?
• Что делать если заказ не выполнился?
"""
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать", url="https://t.me/cf_mz")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    await message.answer(text, reply_markup=kb)

# ---- СТАТИСТИКА ----
@dp.message(F.text == "📊 Статистика")
async def stats_cmd(message: Message):
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM task_executions WHERE is_verified = 1")
    tasks = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type = 'earn'")
    earned = cursor.fetchone()[0] or 0

    text = f"""
📊 Статистика бота

👥 Пользователей: {total}
📋 Выполнено: {format_number(tasks)}
💰 Заработано: {format_number(earned)}
    """
    await message.answer(text, reply_markup=back_btn("main_menu"))

# ---- МЕНЮ ----
@dp.message(F.text == "⚡ Меню")
async def menu_cmd(message: Message):
    await message.answer("⚡ Дополнительное меню:", reply_markup=extra_kb())

@dp.message(F.text == "🔙 Главное меню")
async def back_main(message: Message):
    await message.answer("🔙 Главное меню:", reply_markup=main_kb())

# ---- ВОЗВРАТЫ ----
@dp.callback_query(lambda c: c.data == "main_menu")
async def cb_main(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_extra")
async def cb_extra(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("⚡ Дополнительное меню:", reply_markup=extra_kb())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def cb_main_from_back(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

# ---- АДМИНКА ----
@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    await message.answer("⚙️ Админ-панель:", reply_markup=admin_kb())

@dp.callback_query(lambda c: c.data == "admin_exit")
async def admin_exit(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

# ========== ЗАПУСК ==========
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())

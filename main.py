import asyncio
import logging
import sqlite3
import os
import shutil
import math
import re
import html
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import aiohttp

# ========== КОНФИГ ==========
API_TOKEN = "8630282287:AAEKQoNz5Y3mMDiDI1QbrUGk42ObFRG4q-A"
ADMIN_ID = 7113397602
BOT_USERNAME = "mzboost_bot"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{API_TOKEN}"

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
    except:
        pass

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

CREATE TABLE IF NOT EXISTS giveaway_winners (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    place INTEGER,
    reward INTEGER,
    week_start TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS task_penalties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    task_id INTEGER,
    amount INTEGER,
    reason TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS pending_penalties (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    task_id INTEGER,
    exec_id INTEGER,
    creator_id INTEGER,
    reward INTEGER,
    channel TEXT,
    start_time TEXT DEFAULT CURRENT_TIMESTAMP,
    is_active INTEGER DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (exec_id) REFERENCES task_executions(id)
);

CREATE TABLE IF NOT EXISTS elite_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER,
    user_id INTEGER,
    screenshot_file_id TEXT,
    message_id INTEGER,
    status TEXT DEFAULT 'pending',
    rework_count INTEGER DEFAULT 0,
    rework_message TEXT,
    submitted_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_elite ON tasks(is_elite);
CREATE INDEX IF NOT EXISTS idx_executions_user ON task_executions(user_id, task_id);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_elite_submissions_status ON elite_submissions(status);
CREATE INDEX IF NOT EXISTS idx_pending_penalties_active ON pending_penalties(is_active);
''')
conn.commit()
backup_db()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def create_user(user_id, username=None, full_name=None):
    ref_code = str(user_id)
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, full_name, ref_code) VALUES (?, ?, ?, ?)", (user_id, username, full_name, ref_code))
    conn.commit()
    backup_db()
    return get_user(user_id)

def update_balance(user_id, amount, description, txn_type):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    if amount > 0:
        cursor.execute("UPDATE users SET total_earned = total_earned + ? WHERE user_id = ?", (amount, user_id))
    else:
        abs_amount = abs(amount)
        cursor.execute("UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?", (abs_amount, user_id))
        if txn_type != 'admin':
            cursor.execute("UPDATE users SET spent_weekly = spent_weekly + ? WHERE user_id = ?", (abs_amount, user_id))
    cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)", (user_id, amount, txn_type, description))
    conn.commit()
    backup_db()

def is_elite_active(user_id):
    user = get_user(user_id)
    if not user or not user[11]:
        return False
    try:
        return datetime.strptime(user[11], "%Y-%m-%d %H:%M:%S") > datetime.now()
    except:
        return False

def get_user_level(total_spent):
    levels = [(0, "Новичок", 0), (50000, "Инвестор", 5000), (200000, "Магнат", 20000), (500000, "Легенда", 50000), (1000000, "Властелин Раскрутки", 100000)]
    current = levels[0]
    next_lvl = None
    for i, (threshold, title, reward) in enumerate(levels):
        if total_spent >= threshold:
            current = (threshold, title, reward)
            if i < len(levels) - 1:
                next_lvl = levels[i+1]
    return current, next_lvl

def format_number(n):
    if n is None:
        return "0"
    return f"{n:,}".replace(",", " ")

def extract_channel_from_link(link):
    pattern = r'(?:https?://)?(?:www\.)?t\.me/(?:joinchat/)?([a-zA-Z0-9_\-+]+)'
    match = re.search(pattern, link)
    if match:
        return match.group(1)
    if link.startswith('@'):
        return link[1:]
    return None

def is_admin(user_id):
    return user_id == ADMIN_ID

def get_referral_discount(ref_count):
    if ref_count >= 500:
        return 25
    elif ref_count >= 100:
        return 15
    elif ref_count >= 50:
        return 10
    elif ref_count >= 20:
        return 5
    return 0

# ========== АСИНХРОННЫЙ HTTP КЛИЕНТ ==========
async def async_post(url, data=None, json_data=None):
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data, json=json_data) as response:
            return await response.json()

async def async_get(url, params=None):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as response:
            return await response.json()

async def check_bot_in_channel_async(channel_username):
    try:
        data = await async_get(f"{TELEGRAM_API_URL}/getChat", {"chat_id": f"@{channel_username}"})
        if not data.get('ok'):
            return False, "❌ Бот не найден в канале. Добавьте бота в канал как администратора."
        data = await async_get(f"{TELEGRAM_API_URL}/getChatMember", {"chat_id": f"@{channel_username}", "user_id": bot.id})
        if not data.get('ok'):
            return False, "❌ Бот не является администратором канала."
        member = data.get('result', {})
        if member.get('status') not in ['administrator', 'creator']:
            return False, "❌ Бот не администратор канала."
        return True, "✅ Бот в канале!"
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

# ========== ФОТО ==========
PHOTOS = {
    "start": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260628_221441_342.jpg",
    "profile": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_014712_433.jpg",
    "create_task": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260628_220902_523.jpg",
    "elite": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_015340_722.jpg",
    "tasks": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_015804_465.jpg",
    "menu": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_021014_135.jpg",
    "referrals": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_021417_462.jpg",
    "more": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_021910_584.jpg",
    "earn": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_022220_001.jpg",
    "support": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_032316_145.jpg",
    "stats": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_022550_144.jpg",
    "tariffs": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_022847_627.jpg",
    "rating": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_023312_383.jpg",
    "transfer": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_023748_686.jpg",
    "giveaway": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_024213_393.jpg",
    "admin": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_024716_180.jpg",
    "promo": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_021528_210.jpg"
}

async def send_with_photo(message_or_callback, photo_key, text, kb=None):
    photo_url = PHOTOS.get(photo_key)
    try:
        if isinstance(message_or_callback, Message):
            if kb:
                await message_or_callback.answer_photo(photo=photo_url, caption=text, reply_markup=kb)
            else:
                await message_or_callback.answer_photo(photo=photo_url, caption=text)
        else:
            if kb:
                await message_or_callback.message.edit_caption(caption=text, reply_markup=kb)
            else:
                await message_or_callback.message.edit_caption(caption=text)
    except Exception as e:
        logger.error(f"Ошибка отправки фото: {e}")
        if isinstance(message_or_callback, Message):
            await message_or_callback.answer(text, reply_markup=kb)
        else:
            await message_or_callback.message.edit_text(text, reply_markup=kb)

def make_kb(*buttons_per_row):
    """Создаёт InlineKeyboardMarkup из списка кнопок. Каждый аргумент — строка кнопок."""
    keyboard = []
    for row in buttons_per_row:
        keyboard.append(list(row))
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ========== КЛАССЫ СОСТОЯНИЙ ==========
class PromoState(StatesGroup):
    waiting_code = State()

class TransferState(StatesGroup):
    waiting_id = State()
    waiting_amount = State()

class TaskState(StatesGroup):
    waiting_type = State()
    waiting_link = State()
    waiting_description = State()
    waiting_count = State()
    waiting_confirmation = State()

class EliteTaskState(StatesGroup):
    waiting_type = State()
    waiting_link = State()
    waiting_description = State()
    waiting_reward = State()
    waiting_count = State()
    waiting_confirmation = State()

class EliteSubmitState(StatesGroup):
    waiting_screenshot = State()
    waiting_rework_message = State()
    waiting_custom_message = State()

class AdminState(StatesGroup):
    waiting_channel_username = State()
    waiting_channel_name = State()
    waiting_promo_code = State()
    waiting_promo_bonus = State()
    waiting_promo_uses = State()
    waiting_user_id = State()
    waiting_user_amount = State()
    waiting_broadcast_text = State()

# ========== БОТ ==========
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== КЛАВИАТУРЫ ==========
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

def admin_only(func):
    async def wrapper(callback: CallbackQuery, *args, **kwargs):
        if not is_admin(callback.from_user.id):
            await callback.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        return await func(callback, *args, **kwargs)
    return wrapper

# ========== /start (сбрасывает все FSM) ==========
@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext):
    await state.clear()
    
    user_id = message.from_user.id
    username = message.from_user.username
    full_name = message.from_user.full_name
    user = get_user(user_id)
    
    if user and user[12] == 1:
        await message.answer("🚫 Вы забанены.")
        return
    
    if not user:
        create_user(user_id, username, full_name)
        user = get_user(user_id)
        
        if message.text and "start=ref" in message.text:
            try:
                ref = message.text.split("start=ref")[1].split()[0]
                cursor.execute("SELECT user_id FROM users WHERE ref_code = ?", (ref,))
                referrer = cursor.fetchone()
                if referrer and referrer[0] != user_id:
                    cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer[0], user_id))
                    update_balance(referrer[0], 7500, f"Реферал {user_id}", "bonus")
                    update_balance(user_id, 1000, "Бонус за регистрацию по рефссылке", "bonus")
                    cursor.execute("UPDATE users SET referrals_count = referrals_count + 1, referrals_weekly = referrals_weekly + 1, total_refs_lifetime = total_refs_lifetime + 1 WHERE user_id = ?", (referrer[0],))
                    conn.commit()
                    backup_db()
            except:
                pass
    
    if username:
        cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        conn.commit()
        backup_db()
    
    cursor.execute("SELECT channel_username, channel_name FROM required_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    
    welcome = (
        f"🚀 Раскрутка соцсетей — Free Bot\n━━━━━━━━━━━━━━━\n\n"
        f"🤖 Сервис для продвижения:\nподписчики • лайки • просмотры\n\n"
        f"🏷️ Ваш реферальный код: REF{user_id}\n\n"
        f"⚠️ Telegram — пока единственная доступная платформа."
    )
    
    if channels:
        kb_rows = [[InlineKeyboardButton(text=f"📢 {name}", url=f"https://t.me/{ch}")] for ch, name in channels]
        kb_rows.append([InlineKeyboardButton(text="✅ Проверить подписки", callback_data="check_required")])
        kb_rows.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
        await send_with_photo(message, "start", welcome + "\n\n🎁 Подпишитесь на каналы и получите бонус!", InlineKeyboardMarkup(inline_keyboard=kb_rows))
    else:
        if not user or user[13] == 0:
            update_balance(user_id, 5000, "Бонус за регистрацию", "bonus")
            cursor.execute("UPDATE users SET bonus_received = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            backup_db()
            welcome += "\n\n🎁 Вы получили 5000 баллов!"
        await send_with_photo(message, "start", welcome, None)

# ========== ОТМЕНА FSM ==========
@dp.message(lambda m: m.text and m.text.lower() in ["отмена", "/cancel"])
async def cancel_fsm(message: Message, state: FSMContext):
    current = await state.get_state()
    if current:
        await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=main_kb())

# ========== ПРОВЕРКА ПОДПИСОК ==========
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
        kb_rows = [[InlineKeyboardButton(text=f"📢 {name}", url=f"https://t.me/{ch}")] for ch, name in channels]
        kb_rows.append([InlineKeyboardButton(text="✅ Проверить снова", callback_data="check_required")])
        kb_rows.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
        await callback.message.edit_caption(caption=f"❌ Не подписаны: {', '.join(not_sub)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb_rows))
    else:
        user = get_user(user_id)
        if not user or user[13] == 0:
            update_balance(user_id, 5000, "Бонус за подписки", "bonus")
            cursor.execute("UPDATE users SET bonus_received = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            backup_db()
            await callback.message.edit_caption(caption="✅ Подписаны на все! +5000 баллов!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]]))
        else:
            await callback.message.edit_caption(caption="✅ Вы уже получили бонус.", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]]))
    await callback.answer()

# ========== ПРОФИЛЬ ==========
@dp.message(F.text == "👤 Профиль")
async def profile_cmd(message: Message):
    await show_profile(message)

async def show_profile(message_or_cb):
    if isinstance(message_or_cb, CallbackQuery):
        user_id = message_or_cb.from_user.id
        target = message_or_cb.message
    else:
        user_id = message_or_cb.from_user.id
        target = message_or_cb
    
    user = get_user(user_id)
    if not user:
        create_user(user_id, target.from_user.username, target.from_user.full_name)
        user = get_user(user_id)
    
    level, next_lvl = get_user_level(user[4])
    elite = "✅ Активна" if is_elite_active(user_id) else "❌ Не активна"
    discount = get_referral_discount(user[8])
    
    text = (
        f"📊 Ваш профиль\n━━━━━━━━━━━━━━━\n"
        f"#️⃣ ID: {user[0]}\n👑 Титул: {level[1]}\n💎 Elite: {elite}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 Баланс: {format_number(user[3])}\n💸 Потрачено: {format_number(user[4])}\n"
        f"👥 Рефералов: {user[8]}\n🏷 Скидка: {discount}%\n"
        f"🗓 Регистрация: {user[14][:10] if user[14] else '—'}\n"
        f"🤝 Пригласил: {user[7] if user[7] else 'Нет'}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 Ссылка:\nhttps://t.me/{BOT_USERNAME}?start=ref{user[0]}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_profile")],
        [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
    ])
    await send_with_photo(target, "profile", text, kb)

@dp.callback_query(lambda c: c.data == "refresh_profile")
async def refresh_profile(callback: CallbackQuery):
    await callback.message.delete()
    await show_profile(callback)
    await callback.answer()

# ========== ELITE SUB ==========
@dp.message(F.text == "💎 Elite Sub")
async def elite_cmd(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        user = get_user(message.from_user.id)
    
    if is_elite_active(user[0]):
        text = f"💎 Elite Sub активна до {user[11][:10]}\n\n📊 Бонусы:\n• -16% на создание\n• +16% к награде\n• Скидка 2% на пополнение"
    else:
        text = "💎 Elite Sub — 25,000 монет или 25 звёзд\n\n📊 Бонусы:\n• -16% на создание\n• +16% к награде\n• Скидка 2% на пополнение\n• Доступ к Elite-заданиям"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Купить за 25,000 монет", callback_data="buy_elite")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    await send_with_photo(message, "elite", text, kb)

@dp.callback_query(lambda c: c.data == "buy_elite")
async def buy_elite(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
        user = get_user(callback.from_user.id)
    
    if user[3] < 25000:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)
        return
    
    update_balance(user[0], -25000, "Покупка Elite Sub", "spend")
    until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("UPDATE users SET elite_sub_until = ? WHERE user_id = ?", (until, user[0]))
    conn.commit()
    backup_db()
    await callback.message.edit_caption(
        caption="✅ Elite Sub активирована на 30 дней!",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]])
    )
    await callback.answer()

# ========== ТАРИФЫ ==========
@dp.message(F.text == "💰 Тарифы")
async def tariffs_cmd(message: Message):
    user = get_user(message.from_user.id)
    text = (
        f"💰 Баланс: {format_number(user[3] if user else 0)} баллов\n\n"
        f"📊 Тарифы:\n\n"
        f"📱 Telegram:\n• Подписчики — 21 балл\n• Реакции — 25 баллов\n• Просмотры — 1.5 балла\n\n"
        f"👑 Elite подписчики — 300 баллов\n\n"
        f"⚠️ Telegram — единственная платформа."
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_extra")]
    ])
    await send_with_photo(message, "tariffs", text, kb)

# ========== РЕФЕРАЛЫ ==========
@dp.message(F.text == "👥 Рефералы")
async def referrals_cmd(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        user = get_user(message.from_user.id)
    
    cursor.execute("SELECT username FROM users WHERE referred_by = ?", (user[0],))
    refs = cursor.fetchall()
    ref_list = "\n".join([f"• @{r[0]}" if r[0] else "• скрыт" for r in refs[:10]])
    if len(refs) > 10:
        ref_list += f"\n... и ещё {len(refs) - 10}"
    
    discount = get_referral_discount(user[8])
    remaining = max(0, 20 - user[8])
    
    text = (
        f"🎁 Реферальная программа\n━━━━━━━━━━━━━━━\n"
        f"👥 Приглашено: {user[8]}\n💰 Заработано: {format_number(user[5])}\n"
        f"🏷 Скидка: {discount}%\nДо 5% осталось: {remaining} чел.\n"
        f"🔗 Ссылка:\nhttps://t.me/{BOT_USERNAME}?start=ref{user[0]}\n\n"
        f"📋 Рефералы:\n{ref_list if ref_list else 'Пока нет'}"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📤 Пригласить", callback_data="invite")],
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_refs")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_extra")]
    ])
    await send_with_photo(message, "referrals", text, kb)

@dp.callback_query(lambda c: c.data == "invite")
async def invite_cmd(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
        user = get_user(callback.from_user.id)
    text = f"🎁 Привет! Присоединяйся к боту!\n💰 Получи 1000 баллов.\n🔗 https://t.me/{BOT_USERNAME}?start=ref{user[0]}"
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "refresh_refs")
async def refresh_refs(callback: CallbackQuery):
    await callback.message.delete()
    await referrals_cmd(callback.message)
    await callback.answer()

# ========== ПРОМОКОД ==========
@dp.message(F.text == "🎟 Промокод")
async def promo_cmd(message: Message, state: FSMContext):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_extra")]
    ])
    await send_with_photo(message, "promo", "🎟 Введите промокод:", kb)
    await state.set_state(PromoState.waiting_code)

@dp.message(PromoState.waiting_code)
async def promo_process(message: Message, state: FSMContext):
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    
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

# ========== РЕЙТИНГ ==========
@dp.message(F.text == "🏆 Рейтинг")
async def rating_cmd(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👥 Топ рефералов", callback_data="rating_refs")],
        [InlineKeyboardButton(text="💰 Топ трат", callback_data="rating_spent")],
        [InlineKeyboardButton(text="👑 Мой титул", callback_data="rating_title")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_extra")]
    ])
    await send_with_photo(message, "rating", "🏆 Выберите категорию:", kb)

@dp.callback_query(lambda c: c.data == "rating_refs")
async def rating_refs(callback: CallbackQuery):
    cursor.execute("SELECT username, referrals_weekly FROM users WHERE is_banned = 0 AND referrals_weekly > 0 ORDER BY referrals_weekly DESC LIMIT 10")
    top = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    text = "🏆 Топ рефералов:\n\n"
    for i, (un, cnt) in enumerate(top):
        text += f"{medals[i]} @{un if un else 'скрыт'} — {cnt} чел.\n"
    if not top:
        text += "Пока нет данных."
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="rating_back")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "rating_spent")
async def rating_spent(callback: CallbackQuery):
    cursor.execute("SELECT username, spent_weekly FROM users WHERE is_banned = 0 AND spent_weekly > 0 ORDER BY spent_weekly DESC LIMIT 10")
    top = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    text = "💰 Топ трат:\n\n"
    for i, (un, amt) in enumerate(top):
        text += f"{medals[i]} @{un if un else 'скрыт'} — {format_number(amt)} баллов\n"
    if not top:
        text += "Пока нет данных."
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="rating_back")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "rating_title")
async def rating_title(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
        user = get_user(callback.from_user.id)
    level, next_lvl = get_user_level(user[4])
    text = f"👑 Титул: {level[1]}\nПотрачено: {format_number(user[4])} баллов"
    if next_lvl:
        text += f"\nДо {next_lvl[1]}: {format_number(max(0, next_lvl[0] - user[4]))} баллов"
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="rating_back")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "rating_back")
async def rating_back(callback: CallbackQuery):
    await rating_cmd(callback.message)
    await callback.answer()

# ========== ПЕРЕВОД ==========
@dp.message(F.text == "💸 Перевести")
async def transfer_cmd(message: Message, state: FSMContext):
    await message.answer("💸 Введите ID пользователя:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_extra")]]))
    await state.set_state(TransferState.waiting_id)

@dp.message(TransferState.waiting_id)
async def transfer_id(message: Message, state: FSMContext):
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
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
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
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
        await message.answer(f"❌ Недостаточно. Нужно {total} баллов (комиссия 2%).")
        return
    
    data = await state.get_data()
    to_id = data['to_id']
    
    update_balance(user[0], -total, f"Перевод {to_id}", "transfer")
    update_balance(to_id, amount, f"Перевод от {user[0]}", "transfer")
    
    await message.answer(f"✅ Перевод выполнен!\n💰 Сумма: {amount}\n💸 Комиссия: {commission}\n👤 Получатель: {to_id}")
    try:
        await bot.send_message(to_id, f"💰 Вам перевели баллы!\n👤 Отправитель: @{message.from_user.username or user[0]}\n💵 Сумма: +{amount}\n📊 Баланс: {format_number(get_user(to_id)[3])}")
    except:
        pass
    await state.clear()

# ========== РОЗЫГРЫШ ==========
@dp.message(F.text == "🎰 Розыгрыш")
async def giveaway_cmd(message: Message):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Топ рефералов", callback_data="giveaway_top")],
        [InlineKeyboardButton(text="📋 Условия", callback_data="giveaway_rules")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_extra")]
    ])
    await send_with_photo(message, "giveaway", "🎉 Розыгрыш:", kb)

@dp.callback_query(lambda c: c.data == "giveaway_top")
async def giveaway_top(callback: CallbackQuery):
    cursor.execute("SELECT username, referrals_weekly FROM users WHERE is_banned = 0 AND referrals_weekly > 0 ORDER BY referrals_weekly DESC LIMIT 10")
    top = cursor.fetchall()
    medals = ["🥇", "🥈", "🥉", "4.", "5.", "6.", "7.", "8.", "9.", "10."]
    text = "🎉 Топ рефералов:\n\n"
    for i, (un, cnt) in enumerate(top):
        text += f"{medals[i]} @{un if un else 'скрыт'} — {cnt} реф.\n"
    if not top:
        text += "Пока нет участников."
    text += "\n🏆 Призы:\n🥇 10,000\n🥈 5,000\n🥉 3,000"
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="giveaway_back")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "giveaway_rules")
async def giveaway_rules(callback: CallbackQuery):
    text = "📌 Розыгрыш каждую неделю.\n✅ Условия:\n— Приглашай рефералов\n— Победитель в понедельник 00:00\n🏆 Призы:\n🥇 10,000\n🥈 5,000\n🥉 3,000"
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="giveaway_back")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "giveaway_back")
async def giveaway_back(callback: CallbackQuery):
    await giveaway_cmd(callback.message)
    await callback.answer()

# ========== ЗАРАБОТАТЬ ==========
@dp.message(F.text == "🪙 Заработать")
async def earn_cmd(message: Message):
    user_id = message.from_user.id
    cursor.execute("SELECT channel_username, channel_name FROM sponsor_earn_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    if not channels:
        await send_with_photo(message, "earn", "🪙 Пока нет заданий.", InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]]))
        return
    
    kb = [[InlineKeyboardButton(text=f"📢 {name}", url=f"https://t.me/{ch}")] for ch, name in channels]
    kb.append([InlineKeyboardButton(text="✅ Проверить", callback_data="check_earn")])
    kb.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    
    text = "🪙 Выполните задания:\nНаграда: 3500 монет\n\n"
    for ch, name in channels:
        text += f"• {name} (@{ch})\n"
    await send_with_photo(message, "earn", text, InlineKeyboardMarkup(inline_keyboard=kb))

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
        await callback.message.edit_caption(caption="✅ +3500 баллов!", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]]))
    else:
        await callback.answer("✅ Вы уже получили награду.", show_alert=True)
    await callback.answer()

# ========== БОЛЬШЕ ЗАДАНИЙ ==========
@dp.message(F.text == "➕ Больше заданий")
async def more_cmd(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.username, message.from_user.full_name)
        user = get_user(user_id)
    
    cursor.execute("SELECT channel_username, channel_name FROM sponsor_extra_channels WHERE is_active = 1")
    sponsor_channels = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE is_elite = 1 AND status = 'active' AND current_executors < max_executors")
    elite_count = cursor.fetchone()[0]
    
    text = "👑 ELITE-РАЗДЕЛ\n━━━━━━━━━━━━━━━\n\n"
    text += "⚠️ ПРАВИЛА:\n• Проверка — 2 дня\n• Доработки — макс. 3 раза\n• После 3-й — авто-зачисление\n• Злоупотребление — блокировка\n\n"
    
    if sponsor_channels:
        text += "📢 СПОНСОРСКИЕ КАНАЛЫ:\n"
        for ch, name in sponsor_channels:
            text += f"• {name} (@{ch})\n"
        text += "\n"
    
    text += f"📋 ELITE-ЗАДАНИЙ: {elite_count} шт.\n"
    
    can_create = is_elite_active(user_id)
    kb = [[InlineKeyboardButton(text="📋 Список заданий", callback_data="more_tasks_list")]]
    if can_create:
        kb.append([InlineKeyboardButton(text="➕ Создать Elite-задание", callback_data="create_elite_task")])
    else:
        kb.append([InlineKeyboardButton(text="🔒 Купить Elite Sub", callback_data="buy_elite")])
    kb.append([InlineKeyboardButton(text="📤 Мои задания", callback_data="more_my_tasks")])
    kb.append([InlineKeyboardButton(text="📥 Мои выполнения", callback_data="more_my_executions")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")])
    
    await send_with_photo(message, "more", text, InlineKeyboardMarkup(inline_keyboard=kb))

# ========== ПОДДЕРЖКА ==========
@dp.message(F.text == "📢 Поддержка")
async def support_cmd(message: Message):
    text = "📢 Поддержка\n💬 @cf_mz\n⏰ 12:00 am — 12:00 pm\n❓ Частые вопросы:\n• Как пополнить?\n• Сроки выполнения\n• Проблемы с заданием"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📩 Написать", url="https://t.me/cf_mz")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="main_menu")]
    ])
    await send_with_photo(message, "support", text, kb)

# ========== СТАТИСТИКА ==========
@dp.message(F.text == "📊 Статистика")
async def stats_cmd(message: Message):
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM task_executions WHERE is_verified = 1")
    tasks = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type = 'earn'")
    earned = cursor.fetchone()[0] or 0
    text = f"📊 Статистика\n👥 Пользователей: {total}\n📋 Выполнено: {format_number(tasks)}\n💰 Заработано: {format_number(earned)}"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]])
    await send_with_photo(message, "stats", text, kb)

# ========== МЕНЮ ==========
@dp.message(F.text == "⚡ Меню")
async def menu_cmd(message: Message):
    await send_with_photo(message, "menu", "⚡ Дополнительное меню:", extra_kb())

@dp.message(F.text == "🔙 Главное меню")
async def back_main(message: Message):
    await message.answer("🔙 Главное меню:", reply_markup=main_kb())

# ========== CALLBACK-ВОЗВРАТЫ ==========
@dp.callback_query(lambda c: c.data == "main_menu")
async def cb_main(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_extra")
async def cb_extra(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("⚡ Дополнительное меню:", reply_markup=extra_kb())
    await callback.answer()

# ========== ОБЫЧНЫЕ ЗАДАНИЯ ==========
@dp.message(F.text == "📋 Задания")
async def tasks_menu(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.username, message.from_user.full_name)
        user = get_user(user_id)
    
    cursor.execute("SELECT id, creator_id, task_type, link, description, reward_per_unit, max_executors, current_executors, is_elite FROM tasks WHERE status = 'active' AND current_executors < max_executors AND is_elite = 0")
    tasks = cursor.fetchall()
    
    if not tasks:
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="➕ Создать задание", callback_data="create_task")],
            [InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")]
        ])
        await send_with_photo(message, "tasks", "📋 Задания\n\nПока нет активных заданий.", kb)
        return
    
    text = "📋 Доступные задания:\n\n"
    kb = []
    for i, task in enumerate(tasks[:10]):
        tid, creator_id, ttype, link, desc, reward, max_exec, cur_exec, is_elite = task
        free = max_exec - cur_exec
        cursor.execute("SELECT id FROM task_executions WHERE task_id = ? AND user_id = ?", (tid, user_id))
        already = cursor.fetchone()
        text += f"{i+1}. {ttype.capitalize()}: {link[:30]}...\n   💰 {reward} монет | 📊 {free}/{max_exec}\n\n"
        if free > 0 and not already:
            kb.append([InlineKeyboardButton(text=f"✅ Взять #{i+1}", callback_data=f"take_task_{tid}")])
    
    kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="refresh_tasks")])
    kb.append([InlineKeyboardButton(text="➕ Создать задание", callback_data="create_task")])
    kb.append([InlineKeyboardButton(text="🔙 Главное меню", callback_data="main_menu")])
    await send_with_photo(message, "tasks", text, InlineKeyboardMarkup(inline_keyboard=kb))

@dp.callback_query(lambda c: c.data == "refresh_tasks")
async def refresh_tasks(callback: CallbackQuery):
    await tasks_menu(callback.message)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("take_task_"))
async def take_task(callback: CallbackQuery):
    user_id = callback.from_user.id
    task_id = int(callback.data.replace("take_task_", ""))
    
    cursor.execute("SELECT * FROM tasks WHERE id = ? AND status = 'active'", (task_id,))
    task = cursor.fetchone()
    if not task:
        await callback.answer("❌ Задание неактивно.", show_alert=True)
        return
    
    tid, creator_id, ttype, link, desc, reward, max_exec, cur_exec, is_elite, status, created = task
    
    if cur_exec >= max_exec:
        await callback.answer("❌ Мест нет.", show_alert=True)
        return
    
    cursor.execute("SELECT id FROM task_executions WHERE task_id = ? AND user_id = ?", (tid, user_id))
    if cursor.fetchone():
        await callback.answer("❌ Уже выполнено.", show_alert=True)
        return
    
    if is_elite and not is_elite_active(user_id):
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="💎 Купить Elite Sub", callback_data="buy_elite")]])
        await callback.message.edit_caption(caption="🔒 Требуется Elite Sub.", reply_markup=kb)
        await callback.answer()
        return
    
    channel = extract_channel_from_link(link)
    if channel:
        try:
            member = await bot.get_chat_member(f"@{channel}", user_id)
            if member.status in ['left', 'kicked']:
                await callback.message.edit_caption(caption=f"❌ Подпишитесь на @{channel}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="tasks_menu_back")]]))
                await callback.answer()
                return
        except:
            pass
    
    update_balance(user_id, reward, f"Задание #{tid}", "earn")
    cursor.execute("UPDATE tasks SET current_executors = current_executors + 1 WHERE id = ?", (tid,))
    cursor.execute("INSERT INTO task_executions (task_id, user_id, is_checked, is_verified) VALUES (?, ?, 0, 1)", (tid, user_id))
    conn.commit()
    backup_db()
    
    try:
        await bot.send_message(creator_id, f"✅ Выполнение задания #{tid}\n👤 @{callback.from_user.username or user_id}\n💰 {reward} монет\n📊 {cur_exec+1}/{max_exec}")
    except:
        pass
    
    await callback.message.edit_caption(caption=f"✅ ВЫПОЛНЕНО! +{reward} монет!\n📊 Осталось: {max_exec - (cur_exec+1)}", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 К заданиям", callback_data="tasks_menu_back")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "create_task")
async def create_task_start(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    if not user or user[3] < 100:
        await callback.answer("❌ Минимум 100 монет.", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Подписка", callback_data="task_type_subscribe")],
        [InlineKeyboardButton(text="❤️ Лайк", callback_data="task_type_like")],
        [InlineKeyboardButton(text="👁 Просмотр", callback_data="task_type_view")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="tasks_menu_back")]
    ])
    await callback.message.delete()
    await send_with_photo(callback.message, "create_task", "➕ Создание задания\nВыберите тип:", kb)
    await state.set_state(TaskState.waiting_type)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("task_type_"))
async def task_type_selected(callback: CallbackQuery, state: FSMContext):
    await state.update_data(task_type=callback.data.replace("task_type_", ""))
    await callback.message.edit_caption(caption="📎 Введите ссылку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="tasks_menu_back")]]))
    await state.set_state(TaskState.waiting_link)
    await callback.answer()

@dp.message(TaskState.waiting_link)
async def task_link(message: Message, state: FSMContext):
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(link=message.text)
    await message.answer("📝 Введите описание:")
    await state.set_state(TaskState.waiting_description)

@dp.message(TaskState.waiting_description)
async def task_description(message: Message, state: FSMContext):
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(description=html.escape(message.text))
    await message.answer("👥 Количество исполнителей (1-1000):")
    await state.set_state(TaskState.waiting_count)

@dp.message(TaskState.waiting_count)
async def task_count(message: Message, state: FSMContext):
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        count = int(message.text.strip())
        if count < 1 or count > 1000:
            raise ValueError
    except:
        await message.answer("❌ 1-1000.")
        return
    
    await state.update_data(count=count)
    data = await state.get_data()
    task_type = data['task_type']
    link = data['link']
    description = data['description']
    
    channel = extract_channel_from_link(link)
    if not channel:
        await message.answer("❌ Неверная ссылка.")
        await state.clear()
        return
    
    is_ok, msg = await check_bot_in_channel_async(channel)
    if not is_ok:
        await message.answer(f"❌ {msg}")
        await state.clear()
        return
    
    prices = {'subscribe': 21, 'like': 5, 'view': 3}
    rewards = {'subscribe': 15, 'like': 3, 'view': 1}
    price_per = prices.get(task_type, 21)
    reward_per = rewards.get(task_type, 15)
    total_cost = price_per * count
    
    user = get_user(message.from_user.id)
    if user[3] < total_cost:
        await message.answer(f"❌ Нужно {total_cost} монет.")
        await state.clear()
        return
    
    text = f"📋 Подтверждение:\nТип: {task_type}\nСсылка: {link}\nОписание: {description}\nКоличество: {count}\nЦена: {price_per}₿/шт\nНаграда: {reward_per}₿/шт\nИтого: {total_cost}₿\n{msg}"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать", callback_data="task_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="task_cancel")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.set_state(TaskState.waiting_confirmation)

@dp.callback_query(lambda c: c.data == "task_confirm")
async def task_confirm(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    task_type = data['task_type']
    link = data['link']
    description = data['description']
    count = data['count']
    
    prices = {'subscribe': 21, 'like': 5, 'view': 3}
    rewards = {'subscribe': 15, 'like': 3, 'view': 1}
    price_per = prices.get(task_type, 21)
    reward_per = rewards.get(task_type, 15)
    total_cost = price_per * count
    
    user = get_user(user_id)
    if user[3] < total_cost:
        await callback.message.edit_text("❌ Недостаточно монет!")
        await state.clear()
        await callback.answer()
        return
    
    update_balance(user_id, -total_cost, f"Создание задания: {task_type}", "spend")
    cursor.execute("INSERT INTO tasks (creator_id, task_type, link, description, reward_per_unit, max_executors, is_elite) VALUES (?, ?, ?, ?, ?, ?, 0)",
                   (user_id, task_type, link, description, reward_per, count))
    conn.commit()
    backup_db()
    
    await callback.message.edit_text("✅ Задание создано!")
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "task_cancel")
async def task_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Отменено.")
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "tasks_menu_back")
async def tasks_menu_back(callback: CallbackQuery, state: FSMContext = None):
    if state:
        await state.clear()
    await tasks_menu(callback.message)
    await callback.answer()

# ========== ELITE-ЗАДАНИЯ (пагинация) ==========
@dp.callback_query(lambda c: c.data == "more_tasks_list" or c.data.startswith("more_tasks_page_"))
async def more_tasks_list(callback: CallbackQuery):
    user_id = callback.from_user.id
    page = 0
    if callback.data.startswith("more_tasks_page_"):
        page = int(callback.data.replace("more_tasks_page_", ""))
    
    per_page = 5
    offset = page * per_page
    
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = 'active' AND current_executors < max_executors AND is_elite = 1")
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)
    
    cursor.execute("SELECT id, creator_id, task_type, link, description, reward_per_unit, max_executors, current_executors FROM tasks WHERE status = 'active' AND current_executors < max_executors AND is_elite = 1 LIMIT ? OFFSET ?", (per_page, offset))
    tasks = cursor.fetchall()
    
    if not tasks:
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="more_back")]])
        await callback.message.edit_caption(caption="👑 ELITE-ЗАДАНИЯ\n\nПока нет активных заданий.", reply_markup=kb)
        await callback.answer()
        return
    
    text = f"👑 ELITE-ЗАДАНИЯ (стр. {page+1}/{total_pages}):\n\n"
    kb = []
    for i, task in enumerate(tasks):
        tid, creator_id, ttype, link, desc, reward, max_exec, cur_exec = task
        free = max_exec - cur_exec
        cursor.execute("SELECT id FROM elite_submissions WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'rework')", (tid, user_id))
        already = cursor.fetchone()
        text += f"{offset+i+1}. {ttype.capitalize()}: {link[:30]}...\n   💰 {reward}₿ | 📊 {free}/{max_exec}\n"
        if not already and free > 0:
            kb.append([InlineKeyboardButton(text=f"✅ Взять #{tid}", callback_data=f"take_elite_task_{tid}")])
    
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="⬅️", callback_data=f"more_tasks_page_{page-1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(text="➡️", callback_data=f"more_tasks_page_{page+1}"))
    if nav:
        kb.append(nav)
    
    kb.append([InlineKeyboardButton(text="🔄 Обновить", callback_data="more_tasks_list")])
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="more_back")])
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("take_elite_task_"))
async def take_elite_task(callback: CallbackQuery):
    user_id = callback.from_user.id
    task_id = int(callback.data.replace("take_elite_task_", ""))
    
    if not is_elite_active(user_id):
        await callback.answer("❌ Требуется Elite Sub!", show_alert=True)
        return
    
    cursor.execute("SELECT * FROM tasks WHERE id = ? AND status = 'active'", (task_id,))
    task = cursor.fetchone()
    if not task:
        await callback.answer("❌ Неактивно.", show_alert=True)
        return
    
    tid, creator_id, ttype, link, desc, reward, max_exec, cur_exec, is_elite, status, created = task
    
    if cur_exec >= max_exec:
        await callback.answer("❌ Мест нет.", show_alert=True)
        return
    
    cursor.execute("SELECT id FROM elite_submissions WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'rework')", (tid, user_id))
    if cursor.fetchone():
        await callback.answer("❌ Уже взято.", show_alert=True)
        return
    
    cursor.execute("INSERT INTO elite_submissions (task_id, user_id, status) VALUES (?, ?, 'pending')", (tid, user_id))
    cursor.execute("UPDATE tasks SET current_executors = current_executors + 1 WHERE id = ?", (tid,))
    conn.commit()
    backup_db()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📸 Отправить скриншот", callback_data=f"elite_submit_{tid}")],
        [InlineKeyboardButton(text="🔙 К списку", callback_data="more_tasks_list")]
    ])
    await callback.message.edit_caption(caption=f"👑 Задание #{tid} взято!\n💰 Награда: {reward}₿\n📝 {desc}\n\nОтправьте скриншот.", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("elite_submit_"))
async def elite_submit(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("elite_submit_", ""))
    await state.update_data(task_id=task_id)
    await callback.message.edit_caption(caption="📸 Отправьте скриншот:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Отмена", callback_data="more_tasks_list")]]))
    await state.set_state(EliteSubmitState.waiting_screenshot)
    await callback.answer()

@dp.message(EliteSubmitState.waiting_screenshot, F.photo | F.document)
async def elite_screenshot_received(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data['task_id']
    user_id = message.from_user.id
    
    file_id = message.photo[-1].file_id if message.photo else message.document.file_id
    
    cursor.execute("SELECT creator_id, reward_per_unit FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        await message.answer("❌ Задание не найдено.")
        await state.clear()
        return
    
    creator_id, reward = task
    cursor.execute("UPDATE elite_submissions SET screenshot_file_id = ?, status = 'pending', submitted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND user_id = ?", (file_id, task_id, user_id))
    conn.commit()
    backup_db()
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"elite_approve_{task_id}_{user_id}")],
        [InlineKeyboardButton(text="🔄 Доработка", callback_data=f"elite_rework_{task_id}_{user_id}")]
    ])
    
    try:
        await bot.send_message(creator_id, f"📸 Скриншот от @{message.from_user.username or user_id}\n📋 Задание #{task_id}\n💰 {reward}₿", reply_markup=kb)
    except:
        pass
    
    await message.answer("✅ Скриншот отправлен!")
    await state.clear()

@dp.message(EliteSubmitState.waiting_screenshot)
async def elite_screenshot_text(message: Message, state: FSMContext):
    if message.text and message.text.lower() in ["отмена", "🔙 отмена"]:
        await state.clear()
        await more_cmd(message)
        return
    await message.answer("❌ Отправьте фото или документ. Или 'Отмена'.")

@dp.callback_query(lambda c: c.data.startswith("elite_approve_"))
async def elite_approve(callback: CallbackQuery):
    parts = callback.data.split("_")
    task_id = int(parts[2])
    user_id = int(parts[3])
    
    cursor.execute("SELECT creator_id, reward_per_unit FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        await callback.answer("❌ Задание не найдено.", show_alert=True)
        return
    
    creator_id, reward = task
    if callback.from_user.id != creator_id and callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Только заказчик.", show_alert=True)
        return
    
    commission = math.ceil(reward * 0.1)
    final_reward = reward - commission
    update_balance(user_id, final_reward, f"Elite-задание #{task_id}", "earn")
    cursor.execute("UPDATE elite_submissions SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND user_id = ?", (task_id, user_id))
    conn.commit()
    backup_db()
    
    try:
        await bot.send_message(user_id, f"✅ Задание #{task_id} подтверждено!\n💰 +{final_reward}₿ (комиссия 10%)")
    except:
        pass
    
    await callback.message.delete()
    await callback.answer("✅ Подтверждено!")

@dp.callback_query(lambda c: c.data.startswith("elite_rework_"))
async def elite_rework(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    task_id = int(parts[2])
    user_id = int(parts[3])
    
    cursor.execute("SELECT creator_id FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        await callback.answer("❌ Задание не найдено.", show_alert=True)
        return
    
    if callback.from_user.id != task[0] and callback.from_user.id != ADMIN_ID:
        await callback.answer("⛔ Только заказчик.", show_alert=True)
        return
    
    cursor.execute("SELECT rework_count FROM elite_submissions WHERE task_id = ? AND user_id = ?", (task_id, user_id))
    result = cursor.fetchone()
    if not result:
        await callback.answer("❌ Запись не найдена.", show_alert=True)
        return
    
    rework_count = result[0]
    if rework_count >= 4:
        cursor.execute("SELECT reward_per_unit FROM tasks WHERE id = ?", (task_id,))
        reward = cursor.fetchone()[0]
        commission = math.ceil(reward * 0.1)
        final_reward = reward - commission
        update_balance(user_id, final_reward, f"Elite-задание #{task_id} авто-принято", "earn")
        cursor.execute("UPDATE elite_submissions SET status = 'auto_approved' WHERE task_id = ? AND user_id = ?", (task_id, user_id))
        conn.commit()
        backup_db()
        await callback.answer("✅ Авто-принято (лимит доработок).", show_alert=True)
        await callback.message.delete()
        return
    
    await state.update_data(task_id=task_id, user_id=user_id, rework_count=rework_count)
    await callback.message.edit_text("📝 Введите сообщение для исполнителя:")
    await state.set_state(EliteSubmitState.waiting_rework_message)
    await callback.answer()

@dp.message(EliteSubmitState.waiting_rework_message)
async def elite_rework_msg(message: Message, state: FSMContext):
    data = await state.get_data()
    task_id = data['task_id']
    user_id = data['user_id']
    new_count = data['rework_count'] + 1
    
    cursor.execute("UPDATE elite_submissions SET rework_count = ?, rework_message = ?, status = 'rework', updated_at = CURRENT_TIMESTAMP WHERE task_id = ? AND user_id = ?",
                   (new_count, html.escape(message.text), task_id, user_id))
    conn.commit()
    backup_db()
    
    warning = ""
    if new_count == 3:
        warning = "\n\n⚠️ ЭТО ПОСЛЕДНЯЯ ДОРАБОТКА!"
        try:
            await bot.send_message(message.from_user.id, "⚠️ 3-я доработка! Следующая — авто-зачисление.\nЗлоупотребление → блокировка.")
        except:
            pass
    elif new_count == 4:
        cursor.execute("SELECT reward_per_unit FROM tasks WHERE id = ?", (task_id,))
        reward = cursor.fetchone()[0]
        commission = math.ceil(reward * 0.1)
        final_reward = reward - commission
        update_balance(user_id, final_reward, f"Elite-задание #{task_id} авто-принято", "earn")
        cursor.execute("UPDATE elite_submissions SET status = 'auto_approved' WHERE task_id = ? AND user_id = ?", (task_id, user_id))
        conn.commit()
        backup_db()
        try:
            await bot.send_message(user_id, f"✅ Задание #{task_id} авто-принято! +{final_reward}₿")
        except:
            pass
        await message.answer("✅ Баллы зачислены (4-я доработка).")
        await state.clear()
        return
    
    try:
        await bot.send_message(user_id, f"🔄 Доработка ({new_count}/4):\n{message.text}{warning}")
    except:
        pass
    
    await message.answer("✅ Отправлено.")
    await state.clear()

@dp.callback_query(lambda c: c.data == "more_my_tasks")
async def more_my_tasks(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT id, task_type, link, current_executors, max_executors, status FROM tasks WHERE creator_id = ? AND is_elite = 1 ORDER BY id DESC LIMIT 10", (user_id,))
    tasks = cursor.fetchall()
    if not tasks:
        await callback.answer("❌ Нет созданных Elite-заданий.", show_alert=True)
        return
    text = "📤 МОИ ELITE-ЗАДАНИЯ:\n\n"
    for t in tasks:
        text += f"#{t[0]} {t[1]}: {t[3]}/{t[4]} | {t[5]}\n"
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="more_back")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "more_my_executions")
async def more_my_executions(callback: CallbackQuery):
    user_id = callback.from_user.id
    cursor.execute("SELECT es.task_id, t.task_type, es.status, es.rework_count FROM elite_submissions es JOIN tasks t ON es.task_id = t.id WHERE es.user_id = ? ORDER BY es.id DESC LIMIT 10", (user_id,))
    subs = cursor.fetchall()
    if not subs:
        await callback.answer("❌ Нет выполнений.", show_alert=True)
        return
    text = "📥 МОИ ВЫПОЛНЕНИЯ:\n\n"
    for s in subs:
        text += f"#{s[0]} {s[1]}: {s[2]} | Доработок: {s[3]}\n"
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="more_back")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "more_back")
async def more_back(callback: CallbackQuery):
    await more_cmd(callback.message)
    await callback.answer()

# ========== СОЗДАНИЕ ELITE-ЗАДАНИЯ ==========
@dp.callback_query(lambda c: c.data == "create_elite_task")
async def create_elite_task_start(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not is_elite_active(user_id):
        await callback.answer("❌ Требуется Elite Sub!", show_alert=True)
        return
    if get_user(user_id)[3] < 250:
        await callback.answer("❌ Минимум 250 монет!", show_alert=True)
        return
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📱 Подписка", callback_data="elite_type_subscribe")],
        [InlineKeyboardButton(text="❤️ Лайк", callback_data="elite_type_like")],
        [InlineKeyboardButton(text="👁 Просмотр", callback_data="elite_type_view")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="more_back")]
    ])
    await callback.message.delete()
    await send_with_photo(callback.message, "create_task", "👑 Elite-задание\nВыберите тип:", kb)
    await state.set_state(EliteTaskState.waiting_type)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("elite_type_"))
async def elite_type_selected(callback: CallbackQuery, state: FSMContext):
    await state.update_data(task_type=callback.data.replace("elite_type_", ""))
    await callback.message.edit_caption(caption="📎 Введите ссылку:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="more_back")]]))
    await state.set_state(EliteTaskState.waiting_link)
    await callback.answer()

@dp.message(EliteTaskState.waiting_link)
async def elite_link(message: Message, state: FSMContext):
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(link=message.text)
    await message.answer("📝 Введите описание:")
    await state.set_state(EliteTaskState.waiting_description)

@dp.message(EliteTaskState.waiting_description)
async def elite_desc(message: Message, state: FSMContext):
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(description=html.escape(message.text))
    await message.answer("💰 Награда исполнителю (мин. 30₿):")
    await state.set_state(EliteTaskState.waiting_reward)

@dp.message(EliteTaskState.waiting_reward)
async def elite_reward(message: Message, state: FSMContext):
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        reward = int(message.text.strip())
        if reward < 30:
            raise ValueError
    except:
        await message.answer("❌ Мин. 30.")
        return
    await state.update_data(reward=reward)
    await message.answer("👥 Количество исполнителей (1-1000):")
    await state.set_state(EliteTaskState.waiting_count)

@dp.message(EliteTaskState.waiting_count)
async def elite_count(message: Message, state: FSMContext):
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        count = int(message.text.strip())
        if count < 1 or count > 1000:
            raise ValueError
    except:
        await message.answer("❌ 1-1000.")
        return
    
    await state.update_data(count=count)
    data = await state.get_data()
    total_cost = 250 * count
    user = get_user(message.from_user.id)
    
    if user[3] < total_cost:
        await message.answer(f"❌ Нужно {total_cost}₿.")
        await state.clear()
        return
    
    text = f"👑 ПОДТВЕРЖДЕНИЕ\n━━━━━━━━━━━━━━━\nТип: {data['task_type']}\nСсылка: {data['link']}\nОписание: {data['description']}\nКоличество: {count}\nНаграда: {data['reward']}₿\nЦена: 250₿ × {count} = {total_cost}₿\nКомиссия: 10%\n\n⚠️ Доработки — макс. 3 раза"
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Создать", callback_data="elite_task_confirm")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="elite_task_cancel")]
    ])
    await message.answer(text, reply_markup=kb)
    await state.set_state(EliteTaskState.waiting_confirmation)

@dp.callback_query(lambda c: c.data == "elite_task_confirm")
async def elite_task_confirm(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()
    total_cost = 250 * data['count']
    user = get_user(user_id)
    
    if user[3] < total_cost:
        await callback.message.edit_text("❌ Недостаточно монет!")
        await state.clear()
        await callback.answer()
        return
    
    update_balance(user_id, -total_cost, f"Elite-задание: {data['task_type']}", "spend")
    cursor.execute("INSERT INTO tasks (creator_id, task_type, link, description, reward_per_unit, max_executors, is_elite) VALUES (?, ?, ?, ?, ?, ?, 1)",
                   (user_id, data['task_type'], data['link'], data['description'], data['reward'], data['count']))
    conn.commit()
    backup_db()
    await callback.message.edit_text("✅ Elite-задание создано!")
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "elite_task_cancel")
async def elite_task_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Отменено.")
    await state.clear()
    await callback.answer()

# ========== АДМИН-ПАНЕЛЬ ==========
@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Каналы", callback_data="admin_channels"), InlineKeyboardButton(text="🎟 Промокоды", callback_data="admin_promocodes")],
        [InlineKeyboardButton(text="📋 Задания", callback_data="admin_tasks"), InlineKeyboardButton(text="👤 Пользователи", callback_data="admin_users")],
        [InlineKeyboardButton(text="📨 Рассылка", callback_data="admin_broadcast"), InlineKeyboardButton(text="💰 Настройки", callback_data="admin_settings")],
        [InlineKeyboardButton(text="🏆 Розыгрыш", callback_data="admin_giveaway"), InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Выход", callback_data="admin_exit")]
    ])
    await send_with_photo(message, "admin", "⚙️ Админ-панель:", kb)

# --- Каналы ---
@dp.callback_query(lambda c: c.data == "admin_channels")
@admin_only
async def admin_channels(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Обязательные", callback_data="admin_required_channels")],
        [InlineKeyboardButton(text="🪙 Спонсоры (Заработать)", callback_data="admin_earn_channels")],
        [InlineKeyboardButton(text="👑 Спонсоры (Elite)", callback_data="admin_extra_channels")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_caption(caption="📢 Управление каналами:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_required_channels")
@admin_only
async def admin_required_channels(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM required_channels WHERE is_active = 1")
    chs = cursor.fetchall()
    text = "📢 Обязательные каналы:\n\n"
    text += "\n".join([f"• {n} (@{u})" for _, u, n in chs]) if chs else "Пока нет."
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add_required")],
        [InlineKeyboardButton(text="➖ Удалить", callback_data="admin_remove_required")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_channels")]
    ])
    await callback.message.edit_caption(caption=text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_add_required")
@admin_only
async def admin_add_required(callback: CallbackQuery, state: FSMContext):
    await state.update_data(channel_type="required")
    await callback.message.edit_caption(caption="📝 Username канала (без @):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_required_channels")]]))
    await state.set_state(AdminState.waiting_channel_username)
    await callback.answer()

@dp.message(AdminState.waiting_channel_username)
async def admin_ch_username(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(channel_username=message.text.strip().replace('@', ''))
    await message.answer("📝 Название канала:")
    await state.set_state(AdminState.waiting_channel_name)

@dp.message(AdminState.waiting_channel_name)
async def admin_ch_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    data = await state.get_data()
    username = data['channel_username']
    name = message.text.strip()
    ct = data.get('channel_type', 'required')
    
    table = {'required': 'required_channels', 'earn': 'sponsor_earn_channels', 'extra': 'sponsor_extra_channels'}[ct]
    cursor.execute(f"INSERT INTO {table} (channel_username, channel_name) VALUES (?, ?)", (username, name))
    conn.commit()
    backup_db()
    await message.answer(f"✅ Канал @{username} добавлен!")
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_remove_required")
@admin_only
async def admin_remove_required(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM required_channels WHERE is_active = 1")
    chs = cursor.fetchall()
    if not chs:
        await callback.answer("❌ Нет каналов.", show_alert=True)
        return
    kb = [[InlineKeyboardButton(text=f"🗑 {n} (@{u})", callback_data=f"admin_remove_required_{i}")] for i, u, n in chs]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_required_channels")])
    await callback.message.edit_caption(caption="🗑 Выберите канал:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_remove_required_"))
@admin_only
async def admin_remove_required_do(callback: CallbackQuery):
    ch_id = int(callback.data.replace("admin_remove_required_", ""))
    cursor.execute("UPDATE required_channels SET is_active = 0 WHERE id = ?", (ch_id,))
    conn.commit()
    backup_db()
    await callback.answer("✅ Удалён!")
    await admin_required_channels(callback)

@dp.callback_query(lambda c: c.data in ["admin_earn_channels", "admin_extra_channels"])
@admin_only
async def admin_earn_extra_channels(callback: CallbackQuery):
    ct = "earn" if callback.data == "admin_earn_channels" else "extra"
    table = {'earn': 'sponsor_earn_channels', 'extra': 'sponsor_extra_channels'}[ct]
    prefix = {'earn': 'admin_earn', 'extra': 'admin_extra'}[ct]
    label = {'earn': '🪙 Спонсоры (Заработать)', 'extra': '👑 Спонсоры (Elite)'}[ct]
    
    cursor.execute(f"SELECT id, channel_username, channel_name FROM {table} WHERE is_active = 1")
    chs = cursor.fetchall()
    text = f"{label}:\n\n"
    text += "\n".join([f"• {n} (@{u})" for _, u, n in chs]) if chs else "Пока нет."
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data=f"{prefix}_add")],
        [InlineKeyboardButton(text="➖ Удалить", callback_data=f"{prefix}_remove")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_channels")]
    ])
    await callback.message.edit_caption(caption=text, reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data in ["admin_earn_add", "admin_extra_add"])
@admin_only
async def admin_earn_extra_add(callback: CallbackQuery, state: FSMContext):
    ct = "earn" if "earn" in callback.data else "extra"
    await state.update_data(channel_type=ct)
    prefix = "admin_earn" if ct == "earn" else "admin_extra"
    await callback.message.edit_caption(caption="📝 Username канала (без @):", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}_channels")]]))
    await state.set_state(AdminState.waiting_channel_username)
    await callback.answer()

@dp.callback_query(lambda c: c.data in ["admin_earn_remove", "admin_extra_remove"])
@admin_only
async def admin_earn_extra_remove(callback: CallbackQuery):
    ct = "earn" if "earn" in callback.data else "extra"
    table = {'earn': 'sponsor_earn_channels', 'extra': 'sponsor_extra_channels'}[ct]
    prefix = {'earn': 'admin_earn', 'extra': 'admin_extra'}[ct]
    
    cursor.execute(f"SELECT id, channel_username, channel_name FROM {table} WHERE is_active = 1")
    chs = cursor.fetchall()
    if not chs:
        await callback.answer("❌ Нет каналов.", show_alert=True)
        return
    kb = [[InlineKeyboardButton(text=f"🗑 {n} (@{u})", callback_data=f"{prefix}_remove_{i}")] for i, u, n in chs]
    kb.append([InlineKeyboardButton(text="🔙 Назад", callback_data=f"{prefix}_channels")])
    await callback.message.edit_caption(caption="🗑 Выберите канал:", reply_markup=InlineKeyboardMarkup(inline_keyboard=kb))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_earn_remove_") or c.data.startswith("admin_extra_remove_"))
@admin_only
async def admin_earn_extra_remove_do(callback: CallbackQuery):
    parts = callback.data.split("_remove_")
    ct = parts[0].replace("admin_", "")
    ch_id = int(parts[1])
    table = {'earn': 'sponsor_earn_channels', 'extra': 'sponsor_extra_channels'}[ct]
    cursor.execute(f"UPDATE {table} SET is_active = 0 WHERE id = ?", (ch_id,))
    conn.commit()
    backup_db()
    await callback.answer("✅ Удалён!")
    prefix = "admin_earn" if ct == "earn" else "admin_extra"
    # Редирект на список
    cb_copy = callback
    cb_copy.data = f"{prefix}_channels"
    await admin_earn_extra_channels(cb_copy)

@dp.callback_query(lambda c: c.data in ["admin_earn_channels", "admin_extra_channels"])
@admin_only
async def admin_earn_extra_channels_alias(callback: CallbackQuery):
    await admin_earn_extra_channels(callback)

# --- Промокоды ---
@dp.callback_query(lambda c: c.data == "admin_promocodes")
@admin_only
async def admin_promocodes(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Создать", callback_data="admin_create_promo")],
        [InlineKeyboardButton(text="📋 Список", callback_data="admin_list_promo")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_caption(caption="🎟 Промокоды:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_create_promo")
@admin_only
async def admin_create_promo(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_caption(caption="📝 Код промокода:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")]]))
    await state.set_state(AdminState.waiting_promo_code)
    await callback.answer()

@dp.message(AdminState.waiting_promo_code)
async def admin_promo_code(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(promo_code=message.text.strip().upper())
    await message.answer("💰 Бонус (монеты):")
    await state.set_state(AdminState.waiting_promo_bonus)

@dp.message(AdminState.waiting_promo_bonus)
async def admin_promo_bonus(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        bonus = int(message.text.strip())
    except:
        await message.answer("❌ Число.")
        return
    await state.update_data(promo_bonus=bonus)
    await message.answer("👥 Лимит использований (0 = безлимит):")
    await state.set_state(AdminState.waiting_promo_uses)

@dp.message(AdminState.waiting_promo_uses)
async def admin_promo_uses(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        max_uses = int(message.text.strip())
    except:
        await message.answer("❌ Число.")
        return
    data = await state.get_data()
    try:
        cursor.execute("INSERT INTO promocodes (code, bonus, max_uses, created_by) VALUES (?, ?, ?, ?)",
                       (data['promo_code'], data['promo_bonus'], max_uses, ADMIN_ID))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Промокод {data['promo_code']} создан!")
    except sqlite3.IntegrityError:
        await message.answer("❌ Уже существует.")
    await state.clear()

@dp.callback_query(lambda c: c.data == "admin_list_promo")
@admin_only
async def admin_list_promo(callback: CallbackQuery):
    cursor.execute("SELECT id, code, bonus, max_uses, used_count, is_active FROM promocodes")
    promos = cursor.fetchall()
    text = "📋 Промокоды:\n\n"
    if promos:
        for p in promos:
            text += f"• {p[1]}: {p[2]} монет ({p[4]}/{p[3] if p[3] else '∞'})\n"
    else:
        text += "Пока нет."
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promocodes")]]))
    await callback.answer()

# --- Пользователи ---
@dp.callback_query(lambda c: c.data == "admin_users")
@admin_only
async def admin_users(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔍 Найти", callback_data="admin_find_user")],
        [InlineKeyboardButton(text="💰 Выдать монеты", callback_data="admin_give_coins")],
        [InlineKeyboardButton(text="💸 Забрать монеты", callback_data="admin_take_coins")],
        [InlineKeyboardButton(text="💎 Выдать Elite", callback_data="admin_give_elite")],
        [InlineKeyboardButton(text="💎 Забрать Elite", callback_data="admin_take_elite")],
        [InlineKeyboardButton(text="🚫 Бан", callback_data="admin_ban_user")],
        [InlineKeyboardButton(text="🔓 Разбан", callback_data="admin_unban_user")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_caption(caption="👤 Пользователи:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data in ["admin_find_user", "admin_give_coins", "admin_take_coins", "admin_give_elite", "admin_take_elite", "admin_ban_user", "admin_unban_user"])
@admin_only
async def admin_user_action(callback: CallbackQuery, state: FSMContext):
    action = callback.data.replace("admin_", "")
    await state.update_data(action=action)
    await callback.message.edit_caption(caption="🔍 Введите ID пользователя:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_users")]]))
    await state.set_state(AdminState.waiting_user_id)
    await callback.answer()

@dp.message(AdminState.waiting_user_id)
async def admin_user_id(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("❌ ID.")
        return
    
    user = get_user(user_id)
    if not user:
        await message.answer("❌ Не найден.")
        await state.clear()
        return
    
    await state.update_data(target_user_id=user_id)
    data = await state.get_data()
    action = data['action']
    
    if action == "find_user":
        text = f"👤 ID: {user[0]}\n📛 @{user[1] or '—'}\n💰 {format_number(user[3])} баллов\n💎 Elite: {'✅' if is_elite_active(user_id) else '❌'}\n🚫 Бан: {'✅' if user[12] else '❌'}"
        await message.answer(text)
        await state.clear()
    elif action in ["give_coins", "take_coins"]:
        await message.answer("💰 Количество монет:")
        await state.set_state(AdminState.waiting_user_amount)
    elif action == "give_elite":
        until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE users SET elite_sub_until = ? WHERE user_id = ?", (until, user_id))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Elite выдана {user_id}!")
        await state.clear()
    elif action == "take_elite":
        cursor.execute("UPDATE users SET elite_sub_until = NULL WHERE user_id = ?", (user_id,))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Elite забрана у {user_id}!")
        await state.clear()
    elif action == "ban_user":
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        backup_db()
        await message.answer(f"✅ {user_id} забанен!")
        await state.clear()
    elif action == "unban_user":
        cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        backup_db()
        await message.answer(f"✅ {user_id} разбанен!")
        await state.clear()

@dp.message(AdminState.waiting_user_amount)
async def admin_user_amount(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        amount = int(message.text.strip())
    except:
        await message.answer("❌ Число.")
        return
    
    data = await state.get_data()
    user_id = data['target_user_id']
    action = data['action']
    
    if action == "give_coins":
        update_balance(user_id, amount, f"Выдано админом", "admin")
        await message.answer(f"✅ +{amount} монет → {user_id}")
    else:
        update_balance(user_id, -amount, f"Забрано админом", "admin")
        await message.answer(f"✅ -{amount} монет у {user_id}")
    await state.clear()

# --- Рассылка ---
@dp.callback_query(lambda c: c.data == "admin_broadcast")
@admin_only
async def admin_broadcast(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📢 Всем", callback_data="admin_broadcast_all")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_caption(caption="📨 Рассылка:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_broadcast_all")
@admin_only
async def admin_broadcast_all(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_caption(caption="📝 Текст рассылки:", reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_broadcast")]]))
    await state.set_state(AdminState.waiting_broadcast_text)
    await callback.answer()

@dp.message(AdminState.waiting_broadcast_text)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    
    text = message.text
    cursor.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = cursor.fetchall()
    success = fail = 0
    
    for u in users:
        try:
            await bot.send_message(u[0], text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            fail += 1
    
    await message.answer(f"✅ Рассылка:\n📨 {success}\n❌ {fail}")
    await state.clear()

# --- Статистика ---
@dp.callback_query(lambda c: c.data == "admin_stats")
@admin_only
async def admin_stats(callback: CallbackQuery):
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 1")
    banned = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM task_executions WHERE is_verified = 1")
    tasks = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type = 'earn'")
    earned = cursor.fetchone()[0] or 0
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type = 'spend'")
    spent = cursor.fetchone()[0] or 0
    
    text = f"📊 СТАТИСТИКА\n👥 Всего: {total}\n🚫 Банов: {banned}\n📋 Заданий: {format_number(tasks)}\n💰 Заработано: {format_number(earned)}\n💸 Потрачено: {format_number(spent)}"
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]))
    await callback.answer()

# --- Настройки ---
@dp.callback_query(lambda c: c.data == "admin_settings")
@admin_only
async def admin_settings(callback: CallbackQuery):
    text = "💰 Цены:\n• Подписка: 21₿ / 15₿\n• Лайк: 5₿ / 3₿\n• Просмотр: 3₿ / 1.5₿\n💎 Elite Sub: 25,000₿\n🎁 Спонсор: 3,500₿\n💸 Комиссия: 2%"
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]))
    await callback.answer()

# --- Розыгрыш ---
@dp.callback_query(lambda c: c.data == "admin_giveaway")
@admin_only
async def admin_giveaway(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🏆 Запустить", callback_data="admin_run_giveaway")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]
    ])
    await callback.message.edit_caption(caption="🏆 Розыгрыш\nПризы: 🥇10,000 🥈5,000 🥉3,000", reply_markup=kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_run_giveaway")
@admin_only
async def admin_run_giveaway(callback: CallbackQuery):
    cursor.execute("SELECT user_id, referrals_weekly FROM users WHERE is_banned = 0 AND referrals_weekly > 0 ORDER BY referrals_weekly DESC LIMIT 3")
    winners = cursor.fetchall()
    if len(winners) < 3:
        await callback.answer("❌ Мало участников (нужно 3).", show_alert=True)
        return
    
    prizes = [10000, 5000, 3000]
    medals = ["🥇", "🥈", "🥉"]
    text = "🏆 РЕЗУЛЬТАТЫ:\n\n"
    for i, (uid, refs) in enumerate(winners):
        user = get_user(uid)
        name = f"@{user[1]}" if user and user[1] else f"ID:{uid}"
        text += f"{medals[i]} {name} — {refs} реф.\n"
        update_balance(uid, prizes[i], f"Розыгрыш {i+1} место", "bonus")
        cursor.execute("INSERT INTO giveaway_winners (user_id, place, reward) VALUES (?, ?, ?)", (uid, i+1, prizes[i]))
    conn.commit()
    backup_db()
    
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]))
    await callback.answer()

# --- Задания ---
@dp.callback_query(lambda c: c.data == "admin_tasks")
@admin_only
async def admin_tasks(callback: CallbackQuery):
    cursor.execute("SELECT id, creator_id, task_type, link, status, current_executors, max_executors FROM tasks ORDER BY id DESC LIMIT 10")
    tasks = cursor.fetchall()
    text = "📋 Последние задания:\n\n"
    if tasks:
        for t in tasks:
            text += f"#{t[0]} {t[2]}: {t[3][:30]}...\n  {t[4]} | {t[5]}/{t[6]} | Создатель: {t[1]}\n\n"
    else:
        text += "Пока нет."
    await callback.message.edit_caption(caption=text, reply_markup=InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_back")]]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_back")
@admin_only
async def admin_back(callback: CallbackQuery):
    await admin_cmd(callback.message)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_exit")
@admin_only
async def admin_exit(callback: CallbackQuery):
    await callback.message.delete()
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

# ========== ФОНОВЫЕ ЗАДАЧИ ==========
async def check_unsubscribes():
    while True:
        try:
            cursor.execute("SELECT te.id, te.task_id, te.user_id, t.creator_id, t.link, t.reward_per_unit FROM task_executions te JOIN tasks t ON te.task_id = t.id WHERE te.is_verified = 1 AND t.status = 'active'")
            for exec_id, task_id, user_id, creator_id, link, reward in cursor.fetchall():
                cursor.execute("SELECT id FROM pending_penalties WHERE exec_id = ? AND is_active = 1", (exec_id,))
                if cursor.fetchone():
                    continue
                channel = extract_channel_from_link(link)
                if not channel:
                    continue
                try:
                    member = await bot.get_chat_member(f"@{channel}", user_id)
                    if member.status in ['left', 'kicked']:
                        cursor.execute("INSERT INTO pending_penalties (user_id, task_id, exec_id, creator_id, reward, channel) VALUES (?, ?, ?, ?, ?, ?)",
                                       (user_id, task_id, exec_id, creator_id, reward, channel))
                        conn.commit()
                        backup_db()
                        try:
                            await bot.send_message(user_id, f"⚠️ Отписка от @{channel}!\nШтраф через 10 мин: {reward*2}₿\n👉 https://t.me/{channel}")
                        except:
                            pass
                except:
                    pass
            
            cursor.execute("SELECT id, user_id, task_id, exec_id, creator_id, reward, channel, start_time FROM pending_penalties WHERE is_active = 1")
            for pen_id, user_id, task_id, exec_id, creator_id, reward, channel, start_time in cursor.fetchall():
                if (datetime.now() - datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")).total_seconds() >= 600:
                    try:
                        member = await bot.get_chat_member(f"@{channel}", user_id)
                        if member.status in ['left', 'kicked']:
                            penalty = reward * 2
                            update_balance(user_id, -penalty, f"Штраф за отписку", "penalty")
                            update_balance(creator_id, reward, f"Возврат за отписку", "refund")
                            cursor.execute("UPDATE task_executions SET is_penalized = 1 WHERE id = ?", (exec_id,))
                            try:
                                await bot.send_message(user_id, f"❌ ШТРАФ: -{penalty}₿")
                            except:
                                pass
                    except:
                        pass
                    cursor.execute("UPDATE pending_penalties SET is_active = 0 WHERE id = ?", (pen_id,))
                    conn.commit()
                    backup_db()
            
            # Авто-принятие Elite (2 дня)
            cursor.execute("SELECT es.id, es.task_id, es.user_id, t.reward_per_unit FROM elite_submissions es JOIN tasks t ON es.task_id = t.id WHERE es.status = 'pending' AND datetime(es.submitted_at) < datetime('now', '-2 days')")
            for sub_id, task_id, user_id, reward in cursor.fetchall():
                commission = math.ceil(reward * 0.1)
                final_reward = reward - commission
                update_balance(user_id, final_reward, f"Elite #{task_id} авто-принято", "earn")
                cursor.execute("UPDATE elite_submissions SET status = 'auto_approved' WHERE id = ?", (sub_id,))
                conn.commit()
                backup_db()
            
            # Закрытие старых заданий
            cursor.execute("UPDATE tasks SET status = 'completed' WHERE (is_elite = 1 AND datetime(created_at) < datetime('now', '-365 days')) OR (is_elite = 0 AND datetime(created_at) < datetime('now', '-5 days'))")
            conn.commit()
            backup_db()
            
            await asyncio.sleep(30)
        except Exception as e:
            logger.error(f"Ошибка фона: {e}")
            await asyncio.sleep(60)

async def reset_weekly_stats():
    while True:
        now = datetime.now()
        if now.weekday() == 0 and now.hour == 0 and now.minute == 0:
            cursor.execute("UPDATE users SET referrals_weekly = 0, spent_weekly = 0")
            conn.commit()
            backup_db()
            logger.info("✅ Weekly сброшен")
            await asyncio.sleep(86400)
        else:
            await asyncio.sleep(60)

# ========== ОБРАБОТЧИК ВСЕХ СООБЩЕНИЙ (последний) ==========
@dp.message()
async def handle_any_message(message: Message, state: FSMContext):
    # Не обрабатываем, если есть активное FSM-состояние
    if await state.get_state():
        return
    
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        await message.answer("👋 Зарегистрирован! /start", reply_markup=main_kb())
    else:
        await message.answer("❓ Используй кнопки меню или /start")

# ========== ЗАПУСК ==========
async def main():
    await bot.delete_webhook(drop_pending_updates=True)
    asyncio.create_task(check_unsubscribes())
    asyncio.create_task(reset_weekly_stats())
    logger.info("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
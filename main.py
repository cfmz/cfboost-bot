import asyncio
import logging
import sqlite3
import os
import shutil
import math
import requests
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

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
''')
conn.commit()
backup_db()

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def create_user(user_id, username=None, full_name=None):
    ref_code = f"ref{user_id}"
    cursor.execute(
        "INSERT OR IGNORE INTO users (user_id, username, full_name, ref_code) VALUES (?, ?, ?, ?)",
        (user_id, username, full_name, ref_code)
    )
    conn.commit()
    backup_db()
    return get_user(user_id)

def update_balance(user_id, amount, description, txn_type):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                   (user_id, amount, txn_type, description))
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

def extract_channel_from_link(link):
    pattern = r'(?:https?://)?(?:www\.)?t\.me/([a-zA-Z0-9_]+)'
    match = re.search(pattern, link)
    if match:
        return match.group(1)
    if link.startswith('@'):
        return link[1:]
    return None

def check_bot_in_channel(channel_username):
    try:
        url = f"{TELEGRAM_API_URL}/getChat"
        response = requests.get(url, params={"chat_id": f"@{channel_username}"})
        data = response.json()
        if not data.get('ok'):
            return False, "❌ Бот не найден в канале. Добавьте бота в канал как администратора."
        
        url = f"{TELEGRAM_API_URL}/getChatMember"
        response = requests.get(url, params={"chat_id": f"@{channel_username}", "user_id": bot.id})
        data = response.json()
        if not data.get('ok'):
            return False, "❌ Бот не является администратором канала. Дайте ему права."
        
        member = data.get('result', {})
        if member.get('status') not in ['administrator', 'creator']:
            return False, "❌ Бот не является администратором канала. Дайте ему права администратора."
        
        rights = member.get('can_invite_users', False) or member.get('can_manage_chat', False)
        if not rights:
            return False, "❌ У бота нет прав на управление каналом. Дайте права: 'Просмотр участников'."
        
        return True, "✅ Бот добавлен в канал и имеет права!"
    except Exception as e:
        logger.error(f"Ошибка проверки бота в канале: {e}")
        return False, f"❌ Ошибка проверки: {str(e)}"

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

class AdminState(StatesGroup):
    waiting_channel_username = State()
    waiting_channel_name = State()
    waiting_promo_code = State()
    waiting_promo_bonus = State()
    waiting_promo_uses = State()
    waiting_user_id = State()
    waiting_user_amount = State()
    waiting_broadcast_text = State()

# ========== СОЗДАЁМ БОТА ==========
bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ========== ФУНКЦИИ ДЛЯ ЦВЕТНЫХ КНОПОК ==========
def send_colored_keyboard(chat_id, text, buttons, parse_mode="HTML"):
    keyboard = {"inline_keyboard": []}
    for row in buttons:
        keyboard_row = []
        for btn in row:
            btn_data = {"text": btn["text"]}
            if "url" in btn:
                btn_data["url"] = btn["url"]
            else:
                btn_data["callback_data"] = btn["callback_data"]
                btn_data["style"] = btn.get("style", "default")
            keyboard_row.append(btn_data)
        keyboard["inline_keyboard"].append(keyboard_row)
    
    payload = {"chat_id": chat_id, "text": text, "reply_markup": keyboard, "parse_mode": parse_mode}
    try:
        requests.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
    except Exception as e:
        logger.error(f"Ошибка отправки цветных кнопок: {e}")

def edit_colored_keyboard(chat_id, message_id, text, buttons, parse_mode="HTML"):
    keyboard = {"inline_keyboard": []}
    for row in buttons:
        keyboard_row = []
        for btn in row:
            btn_data = {"text": btn["text"]}
            if "url" in btn:
                btn_data["url"] = btn["url"]
            else:
                btn_data["callback_data"] = btn["callback_data"]
                btn_data["style"] = btn.get("style", "default")
            keyboard_row.append(btn_data)
        keyboard["inline_keyboard"].append(keyboard_row)
    
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "reply_markup": keyboard, "parse_mode": parse_mode}
    try:
        requests.post(f"{TELEGRAM_API_URL}/editMessageText", json=payload)
    except Exception as e:
        logger.error(f"Ошибка редактирования цветных кнопок: {e}")

def delete_message(chat_id, message_id):
    try:
        requests.post(f"{TELEGRAM_API_URL}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id})
    except:
        pass

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
        create_user(user_id, username, full_name)
        user = get_user(user_id)

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

    welcome_text = (
        f"🚀 Раскрутка соцсетей — Free Bot\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"🤖 Сервис для продвижения:\n"
        f"подписчики • лайки • просмотры\n\n"
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
        f"⚠️ Telegram — пока что единственная доступная платформа. Остальные в разработке."
    )

    if channels:
        kb = []
        for ch, name in channels:
            kb.append([{"text": f"📢 {name}", "url": f"https://t.me/{ch}", "style": "primary"}])
        kb.append([{"text": "✅ Проверить подписки", "callback_data": "check_required", "style": "success"}])
        kb.append([{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}])
        
        send_colored_keyboard(
            message.chat.id,
            welcome_text + "\n\n🎁 Получите бонус после обязательных подписок.",
            kb
        )
    else:
        if not user or user[13] == 0:
            update_balance(user_id, 5000, "Бонус за регистрацию", "bonus")
            cursor.execute("UPDATE users SET bonus_received = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            backup_db()
            welcome_text += "\n\n🎁 Вы получили 5000 баллов за регистрацию!"
        
        await message.answer(welcome_text, reply_markup=main_kb())

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
            kb.append([{"text": f"📢 {name}", "url": f"https://t.me/{ch}", "style": "primary"}])
        kb.append([{"text": "✅ Проверить снова", "callback_data": "check_required", "style": "success"}])
        kb.append([{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}])
        
        edit_colored_keyboard(
            callback.message.chat.id,
            callback.message.message_id,
            f"❌ Вы не подписаны на: {', '.join(not_sub)}\n\nПодпишитесь и проверьте снова.",
            kb
        )
    else:
        user = get_user(user_id)
        if not user or user[13] == 0:
            update_balance(user_id, 5000, "Бонус за обязательные подписки", "bonus")
            cursor.execute("UPDATE users SET bonus_received = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            backup_db()
            
            kb = [[{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]]
            edit_colored_keyboard(
                callback.message.chat.id,
                callback.message.message_id,
                "✅ Вы подписаны на все каналы!\n🎁 Вы получили 5000 баллов!",
                kb
            )
        else:
            kb = [[{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]]
            edit_colored_keyboard(
                callback.message.chat.id,
                callback.message.message_id,
                "✅ Вы уже получили бонус.",
                kb
            )
    await callback.answer()

# ---- ПРОФИЛЬ ----
@dp.message(F.text == "👤 Профиль")
async def profile_cmd(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        user = get_user(message.from_user.id)

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
    kb = [
        [{"text": "🔄 Обновить", "callback_data": "refresh_profile", "style": "primary"}],
        [{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]
    ]
    send_colored_keyboard(message.chat.id, text, kb)

@dp.callback_query(lambda c: c.data == "refresh_profile")
async def refresh_profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
        user = get_user(callback.from_user.id)

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
    kb = [
        [{"text": "🔄 Обновить", "callback_data": "refresh_profile", "style": "primary"}],
        [{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]
    ]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        text,
        kb
    )
    await callback.answer()

# ---- ELITE SUB ----
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

    kb = [
        [{"text": "💎 Купить за 25,000 монет", "callback_data": "buy_elite", "style": "success"}],
        [{"text": "🔙 Назад", "callback_data": "main_menu", "style": "default"}]
    ]
    send_colored_keyboard(message.chat.id, text, kb)

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
    
    kb = [[{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "✅ Elite Sub активирована на 30 дней!",
        kb
    )
    await callback.answer()

# ---- ТАРИФЫ ----
@dp.message(F.text == "💰 Тарифы")
async def tariffs_cmd(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
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
    kb = [[{"text": "🔙 Назад", "callback_data": "back_to_extra", "style": "default"}]]
    send_colored_keyboard(message.chat.id, text, kb)

# ---- РЕФЕРАЛЫ ----
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
    kb = [
        [{"text": "📤 Пригласить", "callback_data": "invite", "style": "success"}],
        [{"text": "🔄 Обновить", "callback_data": "refresh_refs", "style": "primary"}],
        [{"text": "🔙 Назад", "callback_data": "back_to_extra", "style": "default"}]
    ]
    send_colored_keyboard(message.chat.id, text, kb)

@dp.callback_query(lambda c: c.data == "invite")
async def invite_cmd(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
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
    kb = [
        [{"text": "👥 Топ рефералов", "callback_data": "rating_refs", "style": "primary"}],
        [{"text": "💰 Топ трат", "callback_data": "rating_spent", "style": "primary"}],
        [{"text": "👑 Мой титул", "callback_data": "rating_title", "style": "primary"}],
        [{"text": "🔙 Назад", "callback_data": "back_to_extra", "style": "default"}]
    ]
    send_colored_keyboard(message.chat.id, "🏆 Выберите категорию:", kb)

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
    
    kb = [[{"text": "🔙 Назад", "callback_data": "rating_back", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
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
    
    kb = [[{"text": "🔙 Назад", "callback_data": "rating_back", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
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
    
    kb = [[{"text": "🔙 Назад", "callback_data": "rating_back", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
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
    kb = [
        [{"text": "🏆 Топ рефералов", "callback_data": "giveaway_top", "style": "primary"}],
        [{"text": "📋 Условия", "callback_data": "giveaway_rules", "style": "primary"}],
        [{"text": "🔙 Назад", "callback_data": "back_to_extra", "style": "default"}]
    ]
    send_colored_keyboard(message.chat.id, "🎉 Розыгрыш:", kb)

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
    
    kb = [[{"text": "🔙 Назад", "callback_data": "giveaway_back", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
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
    kb = [[{"text": "🔙 Назад", "callback_data": "giveaway_back", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
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
        kb.append([{"text": f"📢 {name}", "url": f"https://t.me/{ch}", "style": "primary"}])
    kb.append([{"text": "✅ Проверить", "callback_data": "check_earn", "style": "success"}])
    kb.append([{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}])

    text = "🪙 Выполните задания:\nНаграда: 3500 монет\n\n"
    for ch, name in channels:
        text += f"• {name} (@{ch})\n"

    send_colored_keyboard(message.chat.id, text, kb)

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
        kb = [[{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]]
        edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, "✅ +3500 баллов!", kb)
    else:
        await callback.answer("✅ Вы уже получили награду.", show_alert=True)
    await callback.answer()

# ---- БОЛЬШЕ ЗАДАНИЙ ----
@dp.message(F.text == "➕ Больше заданий")
async def more_cmd(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        user = get_user(user_id)

    if not is_elite_active(user_id):
        kb = [
            [{"text": "💎 Купить Elite Sub", "callback_data": "buy_elite", "style": "success"}],
            [{"text": "🔙 Назад", "callback_data": "main_menu", "style": "default"}]
        ]
        send_colored_keyboard(message.chat.id, "🔒 Доступно только с Elite Sub.", kb)
        return

    cursor.execute("SELECT channel_username, channel_name FROM sponsor_extra_channels WHERE is_active = 1")
    channels = cursor.fetchall()

    if not channels:
        await message.answer("➕ Пока нет заданий.")
        return

    kb = []
    for ch, name in channels:
        kb.append([{"text": f"📢 {name}", "url": f"https://t.me/{ch}", "style": "primary"}])
    kb.append([{"text": "✅ Проверить", "callback_data": "check_extra", "style": "success"}])
    kb.append([{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}])

    text = "➕ Дополнительные задания:\nНаграда: 3500 монет\n\n"
    for ch, name in channels:
        text += f"• {name} (@{ch})\n"

    send_colored_keyboard(message.chat.id, text, kb)

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
        kb = [[{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]]
        edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, "✅ +3500 баллов!", kb)
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
    kb = [
        [{"text": "📩 Написать", "url": "https://t.me/cf_mz", "style": "primary"}],
        [{"text": "🔙 Назад", "callback_data": "main_menu", "style": "default"}]
    ]
    send_colored_keyboard(message.chat.id, text, kb)

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
    kb = [[{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]]
    send_colored_keyboard(message.chat.id, text, kb)

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
    delete_message(callback.message.chat.id, callback.message.message_id)
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_extra")
async def cb_extra(callback: CallbackQuery):
    delete_message(callback.message.chat.id, callback.message.message_id)
    await callback.message.answer("⚡ Дополнительное меню:", reply_markup=extra_kb())
    await callback.answer()

# ---- ЗАДАНИЯ ----
@dp.message(F.text == "📋 Задания")
async def tasks_menu(message: Message):
    user_id = message.from_user.id
    user = get_user(user_id)
    if not user:
        create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        user = get_user(user_id)
    
    cursor.execute("""
        SELECT id, creator_id, task_type, link, description, reward_per_unit, max_executors, current_executors, is_elite
        FROM tasks 
        WHERE status = 'active' AND current_executors < max_executors
    """)
    tasks = cursor.fetchall()
    
    if not tasks:
        kb = [
            [{"text": "➕ Создать задание", "callback_data": "create_task", "style": "success"}],
            [{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]
        ]
        send_colored_keyboard(message.chat.id, "📋 Задания\n\nПока нет активных заданий. Создайте своё!", kb)
        return
    
    text = "📋 Доступные задания:\n\n"
    kb = []
    
    for i, task in enumerate(tasks[:10]):
        task_id, creator_id, task_type, link, description, reward, max_exec, current_exec, is_elite = task
        free = max_exec - current_exec
        
        cursor.execute("SELECT id FROM task_executions WHERE task_id = ? AND user_id = ?", (task_id, user_id))
        already_done = cursor.fetchone()
        
        elite_label = "🏷 Elite (365 дней) 🔒" if is_elite else "🏷 Обычное (5 дней)"
        text += f"{i+1}. {task_type.capitalize()}: {link[:30]}...\n"
        text += f"   💰 Награда: {reward} монет\n"
        text += f"   🏷 {elite_label}\n"
        text += f"   📊 Свободно: {free}/{max_exec}\n\n"
        
        if free > 0 and not already_done:
            kb.append([{"text": f"✅ Взять задание #{i+1}", "callback_data": f"take_task_{task_id}", "style": "success"}])
    
    kb.append([{"text": "🔄 Обновить", "callback_data": "refresh_tasks", "style": "primary"}])
    kb.append([{"text": "➕ Создать задание", "callback_data": "create_task", "style": "success"}])
    kb.append([{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}])
    
    send_colored_keyboard(message.chat.id, text, kb)

@dp.callback_query(lambda c: c.data == "refresh_tasks")
async def refresh_tasks(callback: CallbackQuery):
    await tasks_menu(callback.message)
    await callback.answer()

# ---- ВЗЯТЬ ЗАДАНИЕ С УВЕДОМЛЕНИЯМИ ----
@dp.callback_query(lambda c: c.data.startswith("take_task_"))
async def take_task(callback: CallbackQuery):
    user_id = callback.from_user.id
    task_id = int(callback.data.replace("take_task_", ""))
    
    cursor.execute("""
        SELECT id, creator_id, task_type, link, reward_per_unit, max_executors, current_executors, is_elite
        FROM tasks WHERE id = ? AND status = 'active'
    """, (task_id,))
    task = cursor.fetchone()
    
    if not task:
        await callback.answer("❌ Задание уже неактивно.", show_alert=True)
        await tasks_menu(callback.message)
        return
    
    task_id, creator_id, task_type, link, reward, max_exec, current_exec, is_elite = task
    
    cursor.execute("SELECT id FROM task_executions WHERE task_id = ? AND user_id = ?", (task_id, user_id))
    if cursor.fetchone():
        await callback.answer("❌ Вы уже выполнили это задание.", show_alert=True)
        return
    
    if current_exec >= max_exec:
        await callback.answer("❌ Все места уже заняты.", show_alert=True)
        await tasks_menu(callback.message)
        return
    
    if is_elite and not is_elite_active(user_id):
        kb = [[{"text": "💎 Купить Elite Sub", "callback_data": "buy_elite", "style": "success"}]]
        edit_colored_keyboard(
            callback.message.chat.id,
            callback.message.message_id,
            "🔒 Это Elite-задание. Требуется подписка Elite Sub.",
            kb
        )
        await callback.answer()
        return
    
    channel = extract_channel_from_link(link)
    if channel:
        try:
            member = await bot.get_chat_member(f"@{channel}", user_id)
            if member.status in ['left', 'kicked']:
                kb = [[{"text": "🔙 Назад", "callback_data": "tasks_menu_back", "style": "default"}]]
                edit_colored_keyboard(
                    callback.message.chat.id,
                    callback.message.message_id,
                    f"❌ Вы не подписаны на канал @{channel}. Подпишитесь и попробуйте снова.",
                    kb
                )
                await callback.answer()
                return
        except Exception as e:
            await callback.answer(f"❌ Ошибка проверки: {str(e)}", show_alert=True)
            return
    
    # Начисляем награду
    update_balance(user_id, reward, f"Выполнение задания #{task_id}", "earn")
    
    cursor.execute("UPDATE tasks SET current_executors = current_executors + 1 WHERE id = ?", (task_id,))
    cursor.execute("INSERT INTO task_executions (task_id, user_id, is_verified) VALUES (?, ?, ?)", (task_id, user_id, 1))
    conn.commit()
    backup_db()
    
    # ======== УВЕДОМЛЕНИЕ ЗАКАЗЧИКУ ========
    creator = get_user(creator_id)
    if creator:
        try:
            await bot.send_message(
                creator_id,
                f"✅ НОВОЕ ВЫПОЛНЕНИЕ ЗАДАНИЯ!\n\n"
                f"📋 Задание #{task_id}\n"
                f"👤 Исполнитель: @{callback.from_user.username or user_id}\n"
                f"💰 Награда: {reward} монет\n"
                f"📊 Прогресс: {current_exec + 1}/{max_exec}\n"
                f"🔗 Ссылка: {link}"
            )
        except:
            pass
    
    # ======== УВЕДОМЛЕНИЕ ИСПОЛНИТЕЛЮ ========
    kb = [[{"text": "🔙 К заданиям", "callback_data": "tasks_menu_back", "style": "default"}]]
    await edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        f"✅ ВЫПОЛНЕНО! +{reward} монет!\n\n"
        f"📋 Задание #{task_id}\n"
        f"📊 Осталось мест: {max_exec - (current_exec + 1)}",
        kb
    )
    
    # Дополнительное уведомление в ЛС
    try:
        await bot.send_message(
            user_id,
            f"✅ Вы выполнили задание #{task_id}!\n"
            f"💰 Награда: +{reward} монет\n"
            f"📊 Осталось мест: {max_exec - (current_exec + 1)}"
        )
    except:
        pass
    
    await callback.answer()

@dp.callback_query(lambda c: c.data == "create_task")
async def create_task_start(callback: CallbackQuery, state: FSMContext):
    user = get_user(callback.from_user.id)
    if not user:
        create_user(callback.from_user.id, callback.from_user.username, callback.from_user.full_name)
        user = get_user(callback.from_user.id)
    if user[3] < 100:
        await callback.answer("❌ Недостаточно монет! Минимум 100 монет.", show_alert=True)
        return
    
    kb = [
        [{"text": "📱 Подписка", "callback_data": "task_type_subscribe", "style": "primary"}],
        [{"text": "❤️ Лайк", "callback_data": "task_type_like", "style": "primary"}],
        [{"text": "👁 Просмотр", "callback_data": "task_type_view", "style": "primary"}],
        [{"text": "🔙 Назад", "callback_data": "tasks_menu_back", "style": "default"}]
    ]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "➕ Создание задания\n\nВыберите тип:",
        kb
    )
    await state.set_state(TaskState.waiting_type)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("task_type_"))
async def task_type_selected(callback: CallbackQuery, state: FSMContext):
    task_type = callback.data.replace("task_type_", "")
    await state.update_data(task_type=task_type)
    
    kb = [[{"text": "🔙 Назад", "callback_data": "tasks_menu_back", "style": "default"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "📎 Введите ссылку (канал, пост или видео):",
        kb
    )
    await state.set_state(TaskState.waiting_link)
    await callback.answer()

@dp.message(TaskState.waiting_link)
async def task_link(message: Message, state: FSMContext):
    await state.update_data(link=message.text)
    await message.answer("📝 Введите описание задания (коротко):")
    await state.set_state(TaskState.waiting_description)

@dp.message(TaskState.waiting_description)
async def task_description(message: Message, state: FSMContext):
    await state.update_data(description=message.text)
    await message.answer("👥 Введите количество исполнителей (1-1000):")
    await state.set_state(TaskState.waiting_count)

@dp.message(TaskState.waiting_count)
async def task_count(message: Message, state: FSMContext):
    try:
        count = int(message.text.strip())
        if count < 1 or count > 1000:
            await message.answer("❌ Введите число от 1 до 1000.")
            return
    except:
        await message.answer("❌ Введите корректное число.")
        return
    
    await state.update_data(count=count)
    data = await state.get_data()
    task_type = data['task_type']
    link = data['link']
    description = data['description']
    
    channel = extract_channel_from_link(link)
    if not channel:
        await message.answer("❌ Не удалось определить канал из ссылки. Убедитесь, что ссылка правильная.")
        return
    
    is_ok, msg = check_bot_in_channel(channel)
    if not is_ok:
        kb = [[{"text": "🔙 Назад", "callback_data": "tasks_menu_back", "style": "default"}]]
        send_colored_keyboard(
            message.chat.id,
            f"❌ {msg}\n\n"
            f"📌 Инструкция:\n"
            f"1. Добавьте бота @{BOT_USERNAME} в канал @{channel}\n"
            f"2. Дайте ему права администратора (минимум: 'Просмотр участников')\n"
            f"3. После этого попробуйте снова",
            kb
        )
        await state.clear()
        return
    
    prices = {'subscribe': 21, 'like': 5, 'view': 3}
    price_per = prices.get(task_type, 21)
    total_cost = price_per * count
    
    user = get_user(message.from_user.id)
    if user[3] < total_cost:
        await message.answer(f"❌ Недостаточно монет! Нужно {total_cost} монет.")
        await state.clear()
        return
    
    text = f"""
📋 Подтверждение создания задания:

Тип: {task_type.capitalize()}
Ссылка: {link}
Описание: {description}
Количество: {count}
Стоимость за шт: {price_per} монет
Итого: {total_cost} монет

✅ {msg}
"""
    kb = [
        [{"text": "✅ Создать", "callback_data": "task_confirm", "style": "success"}],
        [{"text": "❌ Отмена", "callback_data": "task_cancel", "style": "danger"}]
    ]
    send_colored_keyboard(message.chat.id, text, kb)
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
    price_per = prices.get(task_type, 21)
    total_cost = price_per * count
    
    update_balance(user_id, -total_cost, f"Создание задания: {task_type}", "spend")
    
    cursor.execute("""
        INSERT INTO tasks (creator_id, task_type, link, description, reward_per_unit, max_executors, is_elite)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, task_type, link, description, price_per, count, 0))
    conn.commit()
    backup_db()
    
    kb = [[{"text": "🔙 Главное меню", "callback_data": "main_menu", "style": "default"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "✅ Задание создано! Ожидайте исполнителей.",
        kb
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "task_cancel")
async def task_cancel(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Назад", "callback_data": "tasks_menu_back", "style": "default"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "❌ Создание задания отменено.",
        kb
    )
    await state.clear()
    await callback.answer()

@dp.callback_query(lambda c: c.data == "tasks_menu_back")
async def tasks_menu_back(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await tasks_menu(callback.message)
    await callback.answer()

# ========== АДМИН-ПАНЕЛЬ ==========
@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("⛔ Доступ запрещён.")
        return
    
    kb = [
        [{"text": "📢 Каналы", "callback_data": "admin_channels", "style": "primary"}],
        [{"text": "🎟 Промокоды", "callback_data": "admin_promocodes", "style": "primary"}],
        [{"text": "📋 Задания", "callback_data": "admin_tasks", "style": "primary"}],
        [{"text": "👤 Пользователи", "callback_data": "admin_users", "style": "primary"}],
        [{"text": "📨 Рассылка", "callback_data": "admin_broadcast", "style": "primary"}],
        [{"text": "💰 Настройки", "callback_data": "admin_settings", "style": "primary"}],
        [{"text": "🏆 Розыгрыш", "callback_data": "admin_giveaway", "style": "primary"}],
        [{"text": "📊 Статистика", "callback_data": "admin_stats", "style": "primary"}],
        [{"text": "🔙 Выход", "callback_data": "admin_exit", "style": "danger"}]
    ]
    send_colored_keyboard(message.chat.id, "⚙️ Админ-панель:", kb)

# ---------- КАНАЛЫ ----------
@dp.callback_query(lambda c: c.data == "admin_channels")
async def admin_channels(callback: CallbackQuery):
    kb = [
        [{"text": "📢 Обязательные", "callback_data": "admin_required_channels"}],
        [{"text": "🪙 Спонсоры (Заработать)", "callback_data": "admin_earn_channels"}],
        [{"text": "👑 Спонсоры (Elite)", "callback_data": "admin_extra_channels"}],
        [{"text": "🔙 Назад", "callback_data": "admin_back"}]
    ]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "📢 Управление каналами:\n\nВыберите тип:",
        kb
    )
    await callback.answer()

# --- Обязательные каналы ---
@dp.callback_query(lambda c: c.data == "admin_required_channels")
async def admin_required_channels(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM required_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    
    if channels:
        text = "📢 Обязательные каналы:\n\n"
        for ch_id, username, name in channels:
            text += f"• {name} (@{username})\n"
    else:
        text = "📢 Обязательные каналы:\n\nПока нет каналов."
    
    kb = [
        [{"text": "➕ Добавить", "callback_data": "admin_add_required"}],
        [{"text": "➖ Удалить", "callback_data": "admin_remove_required"}],
        [{"text": "🔙 Назад", "callback_data": "admin_channels"}]
    ]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        text,
        kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_add_required")
async def admin_add_required(callback: CallbackQuery, state: FSMContext):
    await state.update_data(channel_type="required")
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_required_channels"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "📝 Введите username канала (без @):",
        kb
    )
    await state.set_state(AdminState.waiting_channel_username)
    await callback.answer()

@dp.message(AdminState.waiting_channel_username)
async def admin_channel_username(message: Message, state: FSMContext):
    username = message.text.strip().replace('@', '')
    await state.update_data(channel_username=username)
    await message.answer("📝 Введите название канала (как будет отображаться):")
    await state.set_state(AdminState.waiting_channel_name)

@dp.message(AdminState.waiting_channel_name)
async def admin_channel_name(message: Message, state: FSMContext):
    name = message.text.strip()
    data = await state.get_data()
    username = data['channel_username']
    channel_type = data.get('channel_type', 'required')
    
    if channel_type == 'required':
        cursor.execute("INSERT INTO required_channels (channel_username, channel_name) VALUES (?, ?)", (username, name))
    elif channel_type == 'earn':
        cursor.execute("INSERT INTO sponsor_earn_channels (channel_username, channel_name) VALUES (?, ?)", (username, name))
    elif channel_type == 'extra':
        cursor.execute("INSERT INTO sponsor_extra_channels (channel_username, channel_name) VALUES (?, ?)", (username, name))
    conn.commit()
    backup_db()
    
    await message.answer(f"✅ Канал @{username} добавлен!")
    await state.clear()
    await admin_cmd(message)

@dp.callback_query(lambda c: c.data == "admin_remove_required")
async def admin_remove_required(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM required_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    if not channels:
        await callback.answer("❌ Нет каналов.", show_alert=True)
        return
    kb = []
    for ch_id, username, name in channels:
        kb.append([{"text": f"🗑 {name} (@{username})", "callback_data": f"admin_remove_required_{ch_id}", "style": "danger"}])
    kb.append([{"text": "🔙 Назад", "callback_data": "admin_required_channels", "style": "default"}])
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "🗑 Выберите канал для удаления:",
        kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_remove_required_"))
async def admin_remove_required_confirm(callback: CallbackQuery):
    ch_id = int(callback.data.replace("admin_remove_required_", ""))
    cursor.execute("UPDATE required_channels SET is_active = 0 WHERE id = ?", (ch_id,))
    conn.commit()
    backup_db()
    await callback.answer("✅ Канал удалён!", show_alert=True)
    await admin_required_channels(callback)

# --- Спонсоры Заработать ---
@dp.callback_query(lambda c: c.data == "admin_earn_channels")
async def admin_earn_channels(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM sponsor_earn_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    if channels:
        text = "🪙 Спонсоры (Заработать):\n\n"
        for ch_id, username, name in channels:
            text += f"• {name} (@{username})\n"
    else:
        text = "🪙 Пока нет каналов."
    kb = [
        [{"text": "➕ Добавить", "callback_data": "admin_add_earn"}],
        [{"text": "➖ Удалить", "callback_data": "admin_remove_earn"}],
        [{"text": "🔙 Назад", "callback_data": "admin_channels"}]
    ]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_add_earn")
async def admin_add_earn(callback: CallbackQuery, state: FSMContext):
    await state.update_data(channel_type="earn")
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_earn_channels"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "📝 Введите username канала (без @):",
        kb
    )
    await state.set_state(AdminState.waiting_channel_username)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_remove_earn")
async def admin_remove_earn(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM sponsor_earn_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    if not channels:
        await callback.answer("❌ Нет каналов.", show_alert=True)
        return
    kb = []
    for ch_id, username, name in channels:
        kb.append([{"text": f"🗑 {name} (@{username})", "callback_data": f"admin_remove_earn_{ch_id}", "style": "danger"}])
    kb.append([{"text": "🔙 Назад", "callback_data": "admin_earn_channels", "style": "default"}])
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, "🗑 Выберите канал для удаления:", kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_remove_earn_"))
async def admin_remove_earn_confirm(callback: CallbackQuery):
    ch_id = int(callback.data.replace("admin_remove_earn_", ""))
    cursor.execute("UPDATE sponsor_earn_channels SET is_active = 0 WHERE id = ?", (ch_id,))
    conn.commit()
    backup_db()
    await callback.answer("✅ Канал удалён!", show_alert=True)
    await admin_earn_channels(callback)

# --- Спонсоры Elite ---
@dp.callback_query(lambda c: c.data == "admin_extra_channels")
async def admin_extra_channels(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM sponsor_extra_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    if channels:
        text = "👑 Спонсоры (Elite):\n\n"
        for ch_id, username, name in channels:
            text += f"• {name} (@{username})\n"
    else:
        text = "👑 Пока нет каналов."
    kb = [
        [{"text": "➕ Добавить", "callback_data": "admin_add_extra"}],
        [{"text": "➖ Удалить", "callback_data": "admin_remove_extra"}],
        [{"text": "🔙 Назад", "callback_data": "admin_channels"}]
    ]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_add_extra")
async def admin_add_extra(callback: CallbackQuery, state: FSMContext):
    await state.update_data(channel_type="extra")
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_extra_channels"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "📝 Введите username канала (без @):",
        kb
    )
    await state.set_state(AdminState.waiting_channel_username)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_remove_extra")
async def admin_remove_extra(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM sponsor_extra_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    if not channels:
        await callback.answer("❌ Нет каналов.", show_alert=True)
        return
    kb = []
    for ch_id, username, name in channels:
        kb.append([{"text": f"🗑 {name} (@{username})", "callback_data": f"admin_remove_extra_{ch_id}", "style": "danger"}])
    kb.append([{"text": "🔙 Назад", "callback_data": "admin_extra_channels", "style": "default"}])
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, "🗑 Выберите канал для удаления:", kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_remove_extra_"))
async def admin_remove_extra_confirm(callback: CallbackQuery):
    ch_id = int(callback.data.replace("admin_remove_extra_", ""))
    cursor.execute("UPDATE sponsor_extra_channels SET is_active = 0 WHERE id = ?", (ch_id,))
    conn.commit()
    backup_db()
    await callback.answer("✅ Канал удалён!", show_alert=True)
    await admin_extra_channels(callback)

# ---------- ПРОМОКОДЫ ----------
@dp.callback_query(lambda c: c.data == "admin_promocodes")
async def admin_promocodes(callback: CallbackQuery):
    kb = [
        [{"text": "➕ Создать промокод", "callback_data": "admin_create_promo"}],
        [{"text": "📋 Список промокодов", "callback_data": "admin_list_promo"}],
        [{"text": "🔙 Назад", "callback_data": "admin_back"}]
    ]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "🎟 Управление промокодами:",
        kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_create_promo")
async def admin_create_promo(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_promocodes"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "📝 Введите код промокода (латиница, цифры):",
        kb
    )
    await state.set_state(AdminState.waiting_promo_code)
    await callback.answer()

@dp.message(AdminState.waiting_promo_code)
async def admin_promo_code(message: Message, state: FSMContext):
    code = message.text.strip().upper()
    await state.update_data(promo_code=code)
    await message.answer("💰 Введите бонус (количество монет):")
    await state.set_state(AdminState.waiting_promo_bonus)

@dp.message(AdminState.waiting_promo_bonus)
async def admin_promo_bonus(message: Message, state: FSMContext):
    try:
        bonus = int(message.text.strip())
    except:
        await message.answer("❌ Введите число.")
        return
    await state.update_data(promo_bonus=bonus)
    await message.answer("👥 Введите лимит использований (0 = безлимит):")
    await state.set_state(AdminState.waiting_promo_uses)

@dp.message(AdminState.waiting_promo_uses)
async def admin_promo_uses(message: Message, state: FSMContext):
    try:
        max_uses = int(message.text.strip())
    except:
        await message.answer("❌ Введите число.")
        return
    data = await state.get_data()
    code = data['promo_code']
    bonus = data['promo_bonus']
    
    cursor.execute("INSERT INTO promocodes (code, bonus, max_uses, created_by) VALUES (?, ?, ?, ?)",
                   (code, bonus, max_uses, ADMIN_ID))
    conn.commit()
    backup_db()
    
    await message.answer(f"✅ Промокод {code} создан! Бонус: {bonus} монет, лимит: {max_uses if max_uses > 0 else '∞'}")
    await state.clear()
    await admin_cmd(message)

@dp.callback_query(lambda c: c.data == "admin_list_promo")
async def admin_list_promo(callback: CallbackQuery):
    cursor.execute("SELECT id, code, bonus, max_uses, used_count, is_active FROM promocodes")
    promos = cursor.fetchall()
    if promos:
        text = "📋 Список промокодов:\n\n"
        for pid, code, bonus, max_uses, used, is_active in promos:
            status = "✅ Активен" if is_active else "❌ Неактивен"
            text += f"• {code}: {bonus} монет (использован {used}/{max_uses if max_uses > 0 else '∞'}) - {status}\n"
    else:
        text = "📋 Пока нет промокодов."
    kb = [[{"text": "🔙 Назад", "callback_data": "admin_promocodes", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

# ---------- ПОЛЬЗОВАТЕЛИ ----------
@dp.callback_query(lambda c: c.data == "admin_users")
async def admin_users(callback: CallbackQuery):
    kb = [
        [{"text": "🔍 Найти пользователя", "callback_data": "admin_find_user"}],
        [{"text": "💰 Выдать монеты", "callback_data": "admin_give_coins"}],
        [{"text": "💸 Забрать монеты", "callback_data": "admin_take_coins"}],
        [{"text": "💎 Выдать Elite", "callback_data": "admin_give_elite"}],
        [{"text": "💎 Забрать Elite", "callback_data": "admin_take_elite"}],
        [{"text": "🚫 Заблокировать", "callback_data": "admin_ban_user"}],
        [{"text": "🔓 Разблокировать", "callback_data": "admin_unban_user"}],
        [{"text": "🔙 Назад", "callback_data": "admin_back"}]
    ]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "👤 Управление пользователями:",
        kb
    )
    await callback.answer()

# ---- ВЫДАТЬ ELITE ----
@dp.callback_query(lambda c: c.data == "admin_give_elite")
async def admin_give_elite(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_users"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "💎 Введите ID пользователя для выдачи Elite Sub:",
        kb
    )
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="give_elite")
    await callback.answer()

# ---- ЗАБРАТЬ ELITE ----
@dp.callback_query(lambda c: c.data == "admin_take_elite")
async def admin_take_elite(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_users"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "💎 Введите ID пользователя для забора Elite Sub:",
        kb
    )
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="take_elite")
    await callback.answer()

# ---- ВЫДАТЬ МОНЕТЫ ----
@dp.callback_query(lambda c: c.data == "admin_give_coins")
async def admin_give_coins(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_users"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "💰 Введите ID пользователя:",
        kb
    )
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="give_coins")
    await callback.answer()

# ---- ЗАБРАТЬ МОНЕТЫ ----
@dp.callback_query(lambda c: c.data == "admin_take_coins")
async def admin_take_coins(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_users"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "💸 Введите ID пользователя:",
        kb
    )
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="take_coins")
    await callback.answer()

# ---- НАЙТИ ПОЛЬЗОВАТЕЛЯ ----
@dp.callback_query(lambda c: c.data == "admin_find_user")
async def admin_find_user(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_users"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "🔍 Введите ID пользователя:",
        kb
    )
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="find_user")
    await callback.answer()

# ---- БАН ----
@dp.callback_query(lambda c: c.data == "admin_ban_user")
async def admin_ban_user(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_users"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "🚫 Введите ID пользователя для блокировки:",
        kb
    )
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="ban_user")
    await callback.answer()

# ---- РАЗБАН ----
@dp.callback_query(lambda c: c.data == "admin_unban_user")
async def admin_unban_user(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_users"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "🔓 Введите ID пользователя для разблокировки:",
        kb
    )
    await state.set_state(AdminState.waiting_user_id)
    await state.update_data(action="unban_user")
    await callback.answer()

# ---- ОБЩИЙ ОБРАБОТЧИК ДЛЯ USER ID ----
@dp.message(AdminState.waiting_user_id)
async def admin_user_id(message: Message, state: FSMContext):
    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("❌ Введите корректный ID.")
        return
    user = get_user(user_id)
    if not user:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        return
    
    await state.update_data(target_user_id=user_id)
    data = await state.get_data()
    action = data.get('action')
    
    if action == "give_coins":
        await message.answer("💰 Введите количество монет для выдачи:")
        await state.set_state(AdminState.waiting_user_amount)
    elif action == "take_coins":
        await message.answer("💸 Введите количество монет для забора:")
        await state.set_state(AdminState.waiting_user_amount)
    elif action == "give_elite":
        until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE users SET elite_sub_until = ? WHERE user_id = ?", (until, user_id))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Elite Sub выдана пользователю {user_id} на 30 дней!")
        await state.clear()
        await admin_cmd(message)
    elif action == "take_elite":
        cursor.execute("UPDATE users SET elite_sub_until = NULL WHERE user_id = ?", (user_id,))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Elite Sub забрана у пользователя {user_id}!")
        await state.clear()
        await admin_cmd(message)
    elif action == "ban_user":
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Пользователь {user_id} заблокирован!")
        await state.clear()
        await admin_cmd(message)
    elif action == "unban_user":
        cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Пользователь {user_id} разблокирован!")
        await state.clear()
        await admin_cmd(message)
    elif action == "find_user":
        text = f"""
👤 Пользователь: {user[0]}
📛 Username: @{user[1] if user[1] else 'Нет'}
💰 Баланс: {format_number(user[3])} баллов
💸 Потрачено: {format_number(user[4])} баллов
👥 Рефералов: {user[8]}
💎 Elite: {'✅ Активна' if is_elite_active(user[0]) else '❌ Не активна'}
🚫 Забанен: {'✅ Да' if user[12] else '❌ Нет'}
"""
        kb = [[{"text": "🔙 Назад", "callback_data": "admin_users", "style": "default"}]]
        send_colored_keyboard(message.chat.id, text, kb)
        await state.clear()

@dp.message(AdminState.waiting_user_amount)
async def admin_user_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
    except:
        await message.answer("❌ Введите число.")
        return
    data = await state.get_data()
    user_id = data['target_user_id']
    action = data.get('action', '')
    
    if action == "give_coins":
        update_balance(user_id, amount, f"Выдано админом: {amount} монет", "admin")
        await message.answer(f"✅ {amount} монет выдано пользователю {user_id}!")
    elif action == "take_coins":
        update_balance(user_id, -amount, f"Забрано админом: {amount} монет", "admin")
        await message.answer(f"✅ {amount} монет забрано у пользователя {user_id}!")
    
    await state.clear()
    await admin_cmd(message)

# ---------- РАССЫЛКА ----------
@dp.callback_query(lambda c: c.data == "admin_broadcast")
async def admin_broadcast(callback: CallbackQuery):
    kb = [
        [{"text": "📢 Всем пользователям", "callback_data": "admin_broadcast_all"}],
        [{"text": "🔙 Назад", "callback_data": "admin_back"}]
    ]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "📨 Рассылка:\n\nВыберите тип:",
        kb
    )
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_broadcast_all")
async def admin_broadcast_all(callback: CallbackQuery, state: FSMContext):
    kb = [[{"text": "🔙 Отмена", "callback_data": "admin_broadcast"}]]
    edit_colored_keyboard(
        callback.message.chat.id,
        callback.message.message_id,
        "📝 Введите текст рассылки:",
        kb
    )
    await state.set_state(AdminState.waiting_broadcast_text)
    await callback.answer()

@dp.message(AdminState.waiting_broadcast_text)
async def admin_broadcast_text(message: Message, state: FSMContext):
    text = message.text
    cursor.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = cursor.fetchall()
    success = 0
    fail = 0
    await message.answer(f"⏳ Начинаю рассылку для {len(users)} пользователей...")
    for user in users:
        try:
            await bot.send_message(user[0], text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            fail += 1
    await message.answer(f"✅ Рассылка завершена!\n📨 Отправлено: {success}\n❌ Не доставлено: {fail}")
    await state.clear()
    await admin_cmd(message)

# ---------- СТАТИСТИКА ----------
@dp.callback_query(lambda c: c.data == "admin_stats")
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
    cursor.execute("SELECT COUNT(*) FROM users WHERE elite_sub_until IS NOT NULL")
    elite = cursor.fetchone()[0]
    
    text = f"""
📊 ПОЛНАЯ СТАТИСТИКА

👥 Всего пользователей: {total}
🚫 Забанено: {banned}
💎 Elite Sub: {elite}

📋 Выполнено заданий: {format_number(tasks)}
💰 Всего заработано: {format_number(earned)} баллов
💸 Всего потрачено: {format_number(spent)} баллов
    """
    kb = [[{"text": "🔙 Назад", "callback_data": "admin_back", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

# ---------- НАСТРОЙКИ ----------
@dp.callback_query(lambda c: c.data == "admin_settings")
async def admin_settings(callback: CallbackQuery):
    text = """
💰 Настройки бота:

📱 Telegram цены:
• Подписка: 21₿ (покупка) / 15₿ (награда)
• Лайк: 5₿ / 3₿
• Просмотр: 3₿ / 1.5₿

💎 Elite Sub: 25,000₿ или 25⭐
🎁 Спонсор награда: 3,500₿
💸 Комиссия перевода: 2%
    """
    kb = [[{"text": "🔙 Назад", "callback_data": "admin_back", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

# ---------- РОЗЫГРЫШ ----------
@dp.callback_query(lambda c: c.data == "admin_giveaway")
async def admin_giveaway(callback: CallbackQuery):
    text = """
🏆 Управление розыгрышем:

• Розыгрыш проводится каждую неделю
• Победители: 1 место - 10,000 монет, 2 место - 5,000, 3 место - 3,000
• Топ обновляется в реальном времени
• Сброс каждый понедельник в 00:00
    """
    kb = [
        [{"text": "🏆 Запустить вручную", "callback_data": "admin_run_giveaway", "style": "success"}],
        [{"text": "🔙 Назад", "callback_data": "admin_back", "style": "default"}]
    ]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_run_giveaway")
async def admin_run_giveaway(callback: CallbackQuery):
    cursor.execute("""
        SELECT user_id, referrals_weekly FROM users 
        WHERE is_banned = 0 AND referrals_weekly > 0 
        ORDER BY referrals_weekly DESC LIMIT 3
    """)
    winners = cursor.fetchall()
    
    if len(winners) < 3:
        await callback.answer("❌ Недостаточно участников для розыгрыша (нужно минимум 3).", show_alert=True)
        return
    
    prizes = [10000, 5000, 3000]
    text = "🏆 РЕЗУЛЬТАТЫ РОЗЫГРЫША:\n\n"
    for i, (user_id, refs) in enumerate(winners):
        user = get_user(user_id)
        name = f"@{user[1]}" if user[1] else f"ID: {user_id}"
        text += f"{['🥇', '🥈', '🥉'][i]} {name} — {refs} рефералов\n"
        update_balance(user_id, prizes[i], f"Розыгрыш: {['1 место', '2 место', '3 место'][i]}", "bonus")
        cursor.execute("INSERT INTO giveaway_winners (user_id, place, reward) VALUES (?, ?, ?)",
                       (user_id, i+1, prizes[i]))
    conn.commit()
    backup_db()
    
    kb = [[{"text": "🔙 Назад", "callback_data": "admin_back", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

# ---------- ЗАДАНИЯ (АДМИНКА) ----------
@dp.callback_query(lambda c: c.data == "admin_tasks")
async def admin_tasks(callback: CallbackQuery):
    cursor.execute("""
        SELECT id, creator_id, task_type, link, status, current_executors, max_executors 
        FROM tasks ORDER BY id DESC LIMIT 10
    """)
    tasks = cursor.fetchall()
    if tasks:
        text = "📋 Последние задания:\n\n"
        for task in tasks:
            task_id, creator_id, task_type, link, status, current, max_exec = task
            text += f"• #{task_id} {task_type}: {link[:30]}...\n"
            text += f"  Статус: {status} | {current}/{max_exec} | Создатель: {creator_id}\n\n"
    else:
        text = "📋 Заданий пока нет."
    kb = [[{"text": "🔙 Назад", "callback_data": "admin_back", "style": "default"}]]
    edit_colored_keyboard(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

# ---------- НАЗАД ----------
@dp.callback_query(lambda c: c.data == "admin_back")
async def admin_back(callback: CallbackQuery):
    await admin_cmd(callback.message)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_exit")
async def admin_exit(callback: CallbackQuery):
    delete_message(callback.message.chat.id, callback.message.message_id)
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

# ========== ПРОВЕРКА ОТПИСОК (С УВЕДОМЛЕНИЯМИ) ==========
async def check_unsubscribes():
    unsubscribe_tracker = {}
    
    while True:
        try:
            cursor.execute("""
                SELECT te.id, te.task_id, te.user_id, t.creator_id, t.link, t.reward_per_unit, t.is_elite, te.is_penalized
                FROM task_executions te
                JOIN tasks t ON te.task_id = t.id
                WHERE te.is_verified = 1 AND t.status = 'active'
            """)
            executions = cursor.fetchall()
            
            for exec_id, task_id, user_id, creator_id, link, reward, is_elite, is_penalized in executions:
                if is_penalized == 1:
                    continue
                
                channel = extract_channel_from_link(link)
                if not channel:
                    continue
                
                try:
                    member = await bot.get_chat_member(f"@{channel}", user_id)
                    is_subscribed = member.status not in ['left', 'kicked']
                except:
                    is_subscribed = False
                
                tracker_key = f"{user_id}_{task_id}"
                
                if not is_subscribed:
                    if tracker_key not in unsubscribe_tracker:
                        unsubscribe_tracker[tracker_key] = {
                            'exec_id': exec_id,
                            'task_id': task_id,
                            'user_id': user_id,
                            'creator_id': creator_id,
                            'reward': reward,
                            'channel': channel,
                            'time': datetime.now()
                        }
                        logger.info(f"⏳ Пользователь {user_id} отписался от {channel}. Даём 10 минут.")
                        
                        try:
                            await bot.send_message(
                                user_id,
                                f"⚠️ ВНИМАНИЕ! Вы отписались от канала @{channel}!\n\n"
                                f"Вы выполнили задание и получили награду {reward} монет.\n"
                                f"Если вы НЕ подпишетесь обратно в течение 10 минут:\n"
                                f"❌ Штраф: {reward * 2} монет\n"
                                f"❌ Заказчику вернутся его монеты\n\n"
                                f"👉 Подпишитесь обратно: https://t.me/{channel}"
                            )
                        except:
                            pass
                        
                        try:
                            await bot.send_message(
                                creator_id,
                                f"⚠️ Пользователь @{user_id or user_id} отписался от вашего канала @{channel}!\n\n"
                                f"📋 Задание #{task_id}\n"
                                f"⏳ У него есть 10 минут, чтобы подписаться обратно."
                            )
                        except:
                            pass
                else:
                    if tracker_key in unsubscribe_tracker:
                        del unsubscribe_tracker[tracker_key]
                        logger.info(f"✅ Пользователь {user_id} подписался обратно на {channel}")
            
            now = datetime.now()
            to_penalize = []
            for tracker_key, data in unsubscribe_tracker.items():
                time_diff = (now - data['time']).total_seconds()
                if time_diff >= 600:
                    to_penalize.append(tracker_key)
            
            for tracker_key in to_penalize:
                data = unsubscribe_tracker[tracker_key]
                penalty = data['reward'] * 2
                
                update_balance(data['user_id'], -penalty, f"Штраф за отписку от {data['channel']}", "penalty")
                update_balance(data['creator_id'], data['reward'], f"Возврат за отписку пользователя {data['user_id']}", "refund")
                
                cursor.execute("INSERT INTO task_penalties (user_id, task_id, amount, reason) VALUES (?, ?, ?, ?)",
                               (data['user_id'], data['task_id'], penalty, f"Отписка от {data['channel']}"))
                cursor.execute("UPDATE task_executions SET is_penalized = 1 WHERE id = ?", (data['exec_id'],))
                conn.commit()
                backup_db()
                
                try:
                    await bot.send_message(
                        data['user_id'],
                        f"❌ ШТРАФ!\n\n"
                        f"Вы не подписались обратно на канал @{data['channel']} в течение 10 минут.\n"
                        f"💰 Штраф: -{penalty} монет\n"
                        f"📋 Задание #{data['task_id']}"
                    )
                except:
                    pass
                
                try:
                    await bot.send_message(
                        data['creator_id'],
                        f"✅ ВОЗВРАТ МОНЕТ!\n\n"
                        f"Пользователь @{data['user_id'] or data['user_id']} не подписался обратно на канал @{data['channel']}.\n"
                        f"💰 Вам возвращено: +{data['reward']} монет\n"
                        f"📋 Задание #{data['task_id']}"
                    )
                except:
                    pass
                
                logger.info(f"🚨 ШТРАФ: {penalty} монет у {data['user_id']} за отписку от {data['channel']}")
                del unsubscribe_tracker[tracker_key]
            
            # Закрываем истёкшие задания
            cursor.execute("""
                SELECT id, is_elite, created_at
                FROM tasks WHERE status = 'active'
            """)
            tasks = cursor.fetchall()
            
            for task_id, is_elite, created_at in tasks:
                created_time = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                days_passed = (datetime.now() - created_time).days
                
                if (is_elite and days_passed >= 365) or (not is_elite and days_passed >= 5):
                    cursor.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
                    conn.commit()
                    backup_db()
                    logger.info(f"Задание #{task_id} закрыто (истекло)")
            
            await asyncio.sleep(1)
            
        except Exception as e:
            logger.error(f"Ошибка в проверке отписок: {e}")
            await asyncio.sleep(5)

# ========== ОБРАБОТЧИК ЛЮБЫХ СООБЩЕНИЙ (В КОНЦЕ) ==========
@dp.message()
async def handle_any_message(message: Message):
    user = get_user(message.from_user.id)
    if not user:
        create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        await message.answer(
            f"👋 Привет! Ты автоматически зарегистрирован.\n"
            f"Напиши /start, чтобы увидеть главное меню.",
            reply_markup=main_kb()
        )
    else:
        await message.answer("❓ Используй кнопки меню или напиши /start")

# ========== ЗАПУСК ==========
async def main():
    asyncio.create_task(check_unsubscribes())
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
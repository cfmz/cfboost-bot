import asyncio, logging, sqlite3, os, shutil, math, re, html, gc
from datetime import datetime, timedelta
from functools import wraps
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.storage.base import StorageKey
import aiohttp

API_TOKEN = "8630282287:AAEKQoNz5Y3mMDiDI1QbrUGk42ObFRG4q-A"
ADMIN_ID = 7113397602
BOT_USERNAME = "mzboost_bot"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{API_TOKEN}"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DB_FILE = "cfboost.db"
BACKUP_FILE = "backup.db"

async def backup_db_async():
    try:
        if os.path.exists(DB_FILE):
            await asyncio.to_thread(shutil.copy2, DB_FILE, BACKUP_FILE)
    except Exception as e:
        logger.error(f"Backup failed: {e}")

def restore_db():
    if not os.path.exists(DB_FILE) and os.path.exists(BACKUP_FILE):
        shutil.copy2(BACKUP_FILE, DB_FILE)

restore_db()
conn = sqlite3.connect(DB_FILE, check_same_thread=False)
cursor = conn.cursor()
cursor.execute("PRAGMA foreign_keys = ON;")
conn.commit()

cursor.executescript('''
CREATE TABLE IF NOT EXISTS users (
    user_id INTEGER PRIMARY KEY, username TEXT, full_name TEXT,
    balance INTEGER DEFAULT 1000, total_spent INTEGER DEFAULT 0,
    total_earned INTEGER DEFAULT 0, ref_code TEXT UNIQUE,
    referred_by INTEGER DEFAULT NULL, referrals_count INTEGER DEFAULT 0,
    referrals_weekly INTEGER DEFAULT 0, spent_weekly INTEGER DEFAULT 0,
    elite_sub_until TEXT DEFAULT NULL, is_banned INTEGER DEFAULT 0,
    bonus_received INTEGER DEFAULT 0, registration_date TEXT DEFAULT CURRENT_TIMESTAMP,
    total_refs_lifetime INTEGER DEFAULT 0, last_menu TEXT DEFAULT 'main'
);

CREATE TABLE IF NOT EXISTS required_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT NOT NULL,
    channel_name TEXT NOT NULL, is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sponsor_earn_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT NOT NULL,
    channel_name TEXT NOT NULL, is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS sponsor_extra_channels (
    id INTEGER PRIMARY KEY AUTOINCREMENT, channel_username TEXT NOT NULL,
    channel_name TEXT NOT NULL, is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS promocodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT, code TEXT UNIQUE NOT NULL,
    bonus INTEGER NOT NULL, max_uses INTEGER DEFAULT 0,
    used_count INTEGER DEFAULT 0, created_by INTEGER,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, is_active INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS promocode_activations (
    id INTEGER PRIMARY KEY AUTOINCREMENT, promocode_id INTEGER,
    user_id INTEGER, activated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (promocode_id) REFERENCES promocodes(id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT, creator_id INTEGER,
    task_type TEXT CHECK(task_type IN ('subscribe','like','view')),
    link TEXT NOT NULL, description TEXT, reward_per_unit INTEGER NOT NULL,
    max_executors INTEGER NOT NULL, current_executors INTEGER DEFAULT 0,
    is_elite INTEGER DEFAULT 0, status TEXT DEFAULT 'active',
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    actual_cost INTEGER DEFAULT NULL,
    FOREIGN KEY (creator_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS task_executions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, user_id INTEGER,
    executed_at TEXT DEFAULT CURRENT_TIMESTAMP, checked_at TEXT,
    is_checked INTEGER DEFAULT 0, is_verified INTEGER DEFAULT 0,
    is_penalized INTEGER DEFAULT 0,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount INTEGER,
    type TEXT CHECK(type IN ('earn','spend','transfer','penalty','refund','bonus','admin')),
    description TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS admin_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, from_admin INTEGER DEFAULT 0,
    message TEXT, reply_to INTEGER DEFAULT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP, is_read INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS giveaway_winners (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, place INTEGER,
    reward INTEGER, week_start TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS task_penalties (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task_id INTEGER,
    amount INTEGER, reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE IF NOT EXISTS pending_penalties (
    id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, task_id INTEGER,
    exec_id INTEGER, creator_id INTEGER, reward INTEGER, channel TEXT,
    start_time TEXT DEFAULT CURRENT_TIMESTAMP, is_active INTEGER DEFAULT 1,
    FOREIGN KEY (user_id) REFERENCES users(user_id),
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (exec_id) REFERENCES task_executions(id)
);

CREATE TABLE IF NOT EXISTS elite_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, user_id INTEGER,
    screenshot_file_id TEXT, message_id INTEGER, status TEXT DEFAULT 'pending',
    rework_count INTEGER DEFAULT 0, rework_message TEXT,
    submitted_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS elite_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT, task_id INTEGER, user_id INTEGER,
    action TEXT, message TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (task_id) REFERENCES tasks(id),
    FOREIGN KEY (user_id) REFERENCES users(user_id)
);

CREATE TABLE IF NOT EXISTS weekly_reset (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    last_reset_date TEXT
);

INSERT OR IGNORE INTO weekly_reset (id, last_reset_date) VALUES (1, NULL);

CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_elite ON tasks(is_elite);
CREATE INDEX IF NOT EXISTS idx_executions_user ON task_executions(user_id, task_id);
CREATE INDEX IF NOT EXISTS idx_transactions_user ON transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(type);
CREATE INDEX IF NOT EXISTS idx_elite_submissions_status ON elite_submissions(status);
CREATE INDEX IF NOT EXISTS idx_elite_submissions_submitted_at ON elite_submissions(submitted_at);
CREATE INDEX IF NOT EXISTS idx_pending_penalties_active ON pending_penalties(is_active);
''')
conn.commit()
# backup_db() replaced with async version later
def get_user(user_id):
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    return cursor.fetchone()

def create_user(user_id, username=None, full_name=None):
    cursor.execute("INSERT OR IGNORE INTO users (user_id, username, full_name, ref_code) VALUES (?, ?, ?, ?)",
                   (user_id, username, full_name, str(user_id)))
    conn.commit()
    backup_db()
    return get_user(user_id)

def update_balance(user_id, amount, description, txn_type, commit=True):
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    if amount > 0:
        cursor.execute("UPDATE users SET total_earned = total_earned + ? WHERE user_id = ?", (amount, user_id))
    else:
        abs_amount = abs(amount)
        cursor.execute("UPDATE users SET total_spent = total_spent + ? WHERE user_id = ?", (abs_amount, user_id))
        if txn_type != 'admin':
            cursor.execute("UPDATE users SET spent_weekly = spent_weekly + ? WHERE user_id = ?", (abs_amount, user_id))
    cursor.execute("INSERT INTO transactions (user_id, amount, type, description) VALUES (?, ?, ?, ?)",
                   (user_id, amount, txn_type, description))
    if commit:
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
            if i < len(levels)-1:
                next_lvl = levels[i+1]
    return current, next_lvl

def format_number(n):
    if n is None:
        return "0"
    return f"{n:,}".replace(",", " ")

def extract_channel_from_link(link):
    if not link:
        return None
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

def safe_html(text):
    if text is None:
        return ""
    return html.escape(str(text))

async def async_post(url, data=None, json_data=None):
    async with aiohttp.ClientSession() as session:
        async with session.post(url, data=data, json=json_data) as resp:
            return await resp.json()

async def async_get(url, params=None):
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params) as resp:
            return await resp.json()

async def check_bot_in_channel_async(channel_username):
    try:
        data = await async_get(f"{TELEGRAM_API_URL}/getChat", {"chat_id": f"@{channel_username}"})
        if not data.get('ok'):
            return False, "❌ Бот не найден в канале."
        data = await async_get(f"{TELEGRAM_API_URL}/getChatMember",
                              {"chat_id": f"@{channel_username}", "user_id": bot.id})
        if not data.get('ok'):
            return False, "❌ Бот не администратор."
        member = data.get('result', {})
        if member.get('status') not in ['administrator', 'creator']:
            return False, "❌ Нет прав администратора."
        return True, "✅ Бот в канале."
    except Exception as e:
        return False, f"❌ Ошибка: {str(e)}"

def color_btn(text, callback_data=None, url=None, style="default"):
    btn = {"text": text}
    if url:
        btn["url"] = url
    else:
        btn["callback_data"] = callback_data
    # style игнорируется Telegram API, но оставим для ясности
    return btn

def build_keyboard(*rows):
    # Очистка от лишних полей
    clean_rows = []
    for row in rows:
        clean_row = []
        for btn in row:
            clean_btn = {}
            if "text" in btn:
                clean_btn["text"] = btn["text"]
            if "url" in btn:
                clean_btn["url"] = btn["url"]
            elif "callback_data" in btn:
                clean_btn["callback_data"] = btn["callback_data"]
            clean_row.append(clean_btn)
        clean_rows.append(clean_row)
    return {"inline_keyboard": clean_rows}

def back_btn(cd="back_to_main"):
    return color_btn("🔙 Назад", cd, style="default")

async def send_photo_api(chat_id, photo_url, caption="", reply_markup=None):
    params = {"chat_id": chat_id, "photo": photo_url, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return await async_post(f"{TELEGRAM_API_URL}/sendPhoto", json_data=params)

async def edit_caption_api(chat_id, message_id, caption="", reply_markup=None):
    params = {"chat_id": chat_id, "message_id": message_id, "caption": caption, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return await async_post(f"{TELEGRAM_API_URL}/editMessageCaption", json_data=params)

async def send_message_api(chat_id, text, reply_markup=None):
    params = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return await async_post(f"{TELEGRAM_API_URL}/sendMessage", json_data=params)

async def edit_message_api(chat_id, message_id, text, reply_markup=None):
    params = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        params["reply_markup"] = reply_markup
    return await async_post(f"{TELEGRAM_API_URL}/editMessageText", json_data=params)

async def delete_msg_api(chat_id, message_id):
    try:
        await async_post(f"{TELEGRAM_API_URL}/deleteMessage", json_data={"chat_id": chat_id, "message_id": message_id})
    except Exception:
        pass

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
    "promo": "https://raw.githubusercontent.com/cfmz/cfboost-bot/main/images/IMG_20260629_021528_210.jpg"
}

async def send_with_photo(chat_id, photo_key, text, kb=None):
    photo_url = PHOTOS.get(photo_key)
    if not photo_url:
        if kb:
            return await send_message_api(chat_id, text, kb)
        return await send_message_api(chat_id, text)
    try:
        if kb:
            return await send_photo_api(chat_id, photo_url, text, kb)
        else:
            return await send_photo_api(chat_id, photo_url, text)
    except Exception as e:
        logger.error(f"Ошибка отправки фото {photo_key}: {e}")
        if kb:
            return await send_message_api(chat_id, text, kb)
        return await send_message_api(chat_id, text)

async def edit_with_photo(chat_id, message_id, photo_key, text, kb=None):
    if photo_key and PHOTOS.get(photo_key):
        try:
            return await edit_caption_api(chat_id, message_id, text, kb)
        except Exception as e:
            logger.error(f"Ошибка edit_caption для {photo_key}: {e}")
    try:
        return await edit_caption_api(chat_id, message_id, text, kb)
    except Exception:
        pass
    try:
        return await edit_message_api(chat_id, message_id, text, kb)
    except Exception as e:
        logger.error(f"Ошибка edit_message: {e}")

# Состояния FSM
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

bot = Bot(token=API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

fsm_last_activity = {}
db_lock = asyncio.Lock()

async def update_fsm_activity(user_id: int):
    fsm_last_activity[user_id] = datetime.now()

def main_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💎 Elite Sub"), KeyboardButton(text="👤 Профиль")],
        [KeyboardButton(text="📋 Задания"), KeyboardButton(text="⚡ Меню")],
        [KeyboardButton(text="🪙 Заработать"), KeyboardButton(text="➕ Больше заданий")],
        [KeyboardButton(text="📢 Поддержка"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="💳 История")]
    ], resize_keyboard=True)

def extra_kb():
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text="💰 Тарифы"), KeyboardButton(text="👥 Рефералы")],
        [KeyboardButton(text="🎟 Промокод"), KeyboardButton(text="🏆 Рейтинг")],
        [KeyboardButton(text="💸 Перевести"), KeyboardButton(text="🎰 Розыгрыш")],
        [KeyboardButton(text="🔙 Главное меню")]
    ], resize_keyboard=True)

def admin_only(func):
    @wraps(func)
    async def wrapper(callback: CallbackQuery, *args, **kwargs):
        if not is_admin(callback.from_user.id):
            await callback.answer("⛔ Доступ запрещён.", show_alert=True)
            return
        return await func(callback, *args, **kwargs)
    return wrapper

# ========== ОБРАБОТЧИКИ МЕНЮ ==========
@dp.message(Command("start"))
async def start_cmd(message: Message, state: FSMContext, command: Command = None):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)

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

        ref = None
        if command and command.args:
            ref = command.args
            if ref.startswith("ref"):
                ref = ref[3:]

        if ref:
            cursor.execute("SELECT user_id FROM users WHERE ref_code = ?", (ref,))
            referrer = cursor.fetchone()
            if referrer and referrer[0] != user_id:
                cursor.execute("UPDATE users SET referred_by = ? WHERE user_id = ?", (referrer[0], user_id))
                update_balance(referrer[0], 7500, f"Реферал {user_id}", "bonus")
                update_balance(user_id, 1000, "Бонус за регистрацию", "bonus")
                cursor.execute("UPDATE users SET referrals_count = referrals_count + 1, referrals_weekly = referrals_weekly + 1, total_refs_lifetime = total_refs_lifetime + 1 WHERE user_id = ?", (referrer[0],))
                conn.commit()
                backup_db()

    if username:
        cursor.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
        conn.commit()
        backup_db()

    cursor.execute("SELECT channel_username, channel_name FROM required_channels WHERE is_active = 1")
    channels = cursor.fetchall()

    welcome_text = (
        f"🚀 <b>Раскрутка соцсетей — Free Bot</b>\n━━━━━━━━━━━━━━━\n\n"
        f"🤖 <b>Сервис для продвижения:</b>\n• подписчики • лайки • просмотры\n\n"
        f"🌐 <b>Доступные платформы:</b>\n✉️ Telegram — подписчики, реакции, просмотры\n"
        f"🟦 VK — в разработке\n💃 TikTok — в разработке\n📷 Instagram — в разработке\n▶️ YouTube — в разработке\n\n"
        f"━━━━━━━━━━━━━━━\n💎 <b>Elite Sub</b> — подписка с гарантией 365 дней и бонусами.\n\n"
        f"🏷️ <b>Ваш реферальный код:</b> REF{user_id}\nПриглашайте друзей и получайте бонусы!\n\n"
        f"📌 <b>Как начать:</b>\n1️⃣ Обязательно подпишитесь на каналы ниже.\n"
        f"2️⃣ Нажмите «Проверить подписки» и получите стартовый бонус.\n"
        f"3️⃣ Изучите меню: создавайте задания, зарабатывайте монеты.\n\n"
        f"⚠️ Telegram — пока единственная доступная платформа."
    )

    if channels:
        kb_rows = [[color_btn(f"📢 {name}", url=f"https://t.me/{ch}", style="primary")] for ch, name in channels]
        kb_rows.append([color_btn("✅ Проверить подписки", "check_required", style="success")])
        kb_rows.append([back_btn("main_menu")])
        kb = build_keyboard(*kb_rows)
        await send_with_photo(user_id, "start", welcome_text + "\n\n🎁 Подпишитесь и получите бонус!", kb)
    else:
        if not user or user[13] == 0:
            update_balance(user_id, 5000, "Бонус за регистрацию", "bonus")
            cursor.execute("UPDATE users SET bonus_received = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            backup_db()
            welcome_text += "\n\n🎁 Вы получили 5000 баллов!"
        await send_with_photo(user_id, "start", welcome_text)

@dp.message(lambda m: m.text and m.text.lower() in ["отмена", "/cancel", "🔙 отмена", "❌ отмена"])
async def cancel_fsm(message: Message, state: FSMContext):
    if await state.get_state():
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
    await message.answer("❌ Действие отменено.", reply_markup=main_kb())

@dp.callback_query(lambda c: c.data == "check_required")
async def check_required(callback: CallbackQuery):
    if get_user(callback.from_user.id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
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
        kb_rows = [[color_btn(f"📢 {name}", url=f"https://t.me/{ch}", style="primary")] for ch, name in channels]
        kb_rows.append([color_btn("✅ Проверить снова", "check_required", style="success")])
        kb_rows.append([back_btn("main_menu")])
        await edit_with_photo(callback.message.chat.id, callback.message.message_id, None,
                              f"❌ Вы не подписаны на: {', '.join(not_sub)}\n\nПодпишитесь и нажмите «Проверить снова».",
                              build_keyboard(*kb_rows))
    else:
        user = get_user(user_id)
        if not user or user[13] == 0:
            update_balance(user_id, 5000, "Бонус за подписки", "bonus")
            cursor.execute("UPDATE users SET bonus_received = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            backup_db()
            await edit_with_photo(callback.message.chat.id, callback.message.message_id, None,
                                  "✅ Вы подписаны на все обязательные каналы!\n\n🎁 Ваш бонус: +5000 баллов.",
                                  build_keyboard([back_btn("main_menu")]))
        else:
            await edit_with_photo(callback.message.chat.id, callback.message.message_id, None,
                                  "✅ Вы уже получили бонус за подписки.",
                                  build_keyboard([back_btn("main_menu")]))
    await callback.answer()

@dp.message(F.text == "👤 Профиль")
async def profile_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await show_profile(message.from_user.id, message.chat.id)

async def show_profile(user_id, chat_id, edit_msg_id=None):
    user = get_user(user_id)
    if not user:
        user = create_user(user_id)
    level, next_lvl = get_user_level(user[4])
    elite = "✅ Активна" if is_elite_active(user_id) else "❌ Не активна"
    discount = get_referral_discount(user[8])
    text = (
        f"📊 <b>Ваш профиль</b>\n━━━━━━━━━━━━━━━\n"
        f"#️⃣ <b>ID:</b> {user[0]}\n👑 <b>Титул:</b> {level[1]}\n"
        f"   └ Чем больше монет потрачено, тем выше титул.\n"
        f"💎 <b>Elite Sub:</b> {elite}\n"
        f"   └ Даёт скидки и доступ к особым заданиям.\n"
        f"━━━━━━━━━━━━━━━\n"
        f"💰 <b>Баланс:</b> {format_number(user[3])} баллов\n"
        f"💸 <b>Потрачено всего:</b> {format_number(user[4])} баллов\n"
        f"👥 <b>Рефералов:</b> {user[8]}\n"
        f"🏷 <b>Скидка за рефералов:</b> {discount}%\n"
        f"   └ 5% за 20, 10% за 50, 15% за 100, 25% за 500.\n"
        f"🗓 <b>Дата регистрации:</b> {user[14][:10] if user[14] else '—'}\n"
        f"🤝 <b>Вас пригласил:</b> {user[7] if user[7] else 'Нет'}\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🔗 <b>Ваша реферальная ссылка:</b>\nhttps://t.me/{BOT_USERNAME}?start=ref{user[0]}\n"
        f"Поделитесь ею с друзьями, чтобы получать бонусы!"
    )
    kb = build_keyboard([color_btn("🔄 Обновить", "refresh_profile", style="primary")], [back_btn("main_menu")])
    if edit_msg_id:
        await edit_with_photo(chat_id, edit_msg_id, "profile", text, kb)
    else:
        await send_with_photo(chat_id, "profile", text, kb)

@dp.callback_query(lambda c: c.data == "refresh_profile")
async def refresh_profile(callback: CallbackQuery):
    await show_profile(callback.from_user.id, callback.message.chat.id, callback.message.message_id)
    await callback.answer()

@dp.message(F.text == "💎 Elite Sub")
async def elite_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    user = get_user(message.from_user.id)
    if not user:
        user = create_user(message.from_user.id)
    if is_elite_active(user[0]):
        text = f"💎 <b>Elite Sub активна</b>\nДействует до: {user[11][:10]}\n\n📊 <b>Ваши бонусы:</b>\n• Скидка 16% на создание\n• Награда +16%\n• Доступ к Elite-заданиям"
    else:
        text = "💎 <b>Elite Sub — премиум подписка</b>\nСтоимость: 25,000 монет или 25 звёзд\n\n📊 <b>Что вы получите:</b>\n• Скидка 16% на создание\n• Бонус +16% к награде\n• Доступ к Elite-заданиям\n\nНажмите кнопку, чтобы активировать."
    kb = build_keyboard(
        [color_btn("💎 Купить за 25,000 монет", "buy_elite", style="success")],
        [color_btn("⭐ Купить за 25 звёзд", "buy_elite_stars", style="primary")],
        [back_btn("main_menu")]
    )
    await send_with_photo(message.from_user.id, "elite", text, kb)

@dp.callback_query(lambda c: c.data == "buy_elite")
async def buy_elite(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        user = create_user(callback.from_user.id)
    if user[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    if user[3] < 25000:
        await callback.answer("❌ Недостаточно монет!", show_alert=True)
        return
    async with db_lock:
        update_balance(user[0], -25000, "Покупка Elite Sub", "spend")
        until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE users SET elite_sub_until = ? WHERE user_id = ?", (until, user[0]))
        conn.commit()
        backup_db()
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None,
                          "✅ Elite Sub активирована на 30 дней!", build_keyboard([back_btn("main_menu")]))
    await callback.answer()

@dp.callback_query(lambda c: c.data == "buy_elite_stars")
async def buy_elite_stars(callback: CallbackQuery):
    await callback.answer("Оплата звёздами пока в разработке.", show_alert=True)

@dp.message(F.text == "💰 Тарифы")
async def tariffs_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    user = get_user(message.from_user.id)
    text = (
        f"💰 <b>Ваш баланс:</b> {format_number(user[3] if user else 0)} баллов\n\n"
        f"📊 <b>Тарифы на услуги:</b>\n"
        f"📱 Telegram:\n"
        f"• Подписчики — 21 балл\n"
        f"• Реакции — 5 баллов\n"
        f"• Просмотры — 3 балла\n"
        f"👑 Elite — 250 баллов"
    )
    kb = build_keyboard([back_btn("back_to_extra")])
    await send_with_photo(message.from_user.id, "tariffs", text, kb)

@dp.message(F.text == "👥 Рефералы")
async def referrals_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    user_id = message.chat.id
    user = get_user(user_id)
    if not user:
        user = create_user(user_id)

    cursor.execute("SELECT username FROM users WHERE referred_by = ?", (user[0],))
    refs = cursor.fetchall()
    ref_list = "\n".join([f"• @{r[0]}" if r[0] else "• скрыт" for r in refs[:10]])
    if len(refs) > 10:
        ref_list += f"\n... и ещё {len(refs)-10}"

    discount = get_referral_discount(user[8])
    remaining = max(0, 20 - user[8])

    text = (
        f"🎁 <b>Реферальная программа</b>\n━━━━━━━━━━━━━━━\n"
        f"👥 Приглашено: {user[8]}\n💰 Заработано: {format_number(user[5])}\n"
        f"🏷 Скидка: {discount}%\nДо 5% осталось: {remaining} чел.\n"
        f"🔗 https://t.me/{BOT_USERNAME}?start=ref{user[0]}\n\n📋 Рефералы:\n{ref_list or 'Пока нет'}"
    )
    kb = build_keyboard(
        [color_btn("📤 Пригласить", "invite", style="primary")],
        [color_btn("🔄 Обновить", "refresh_refs", style="primary")],
        [back_btn("back_to_extra")]
    )
    await send_with_photo(message.chat.id, "referrals", text, kb)

@dp.callback_query(lambda c: c.data == "invite")
async def invite_cmd(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    text = f"🎁 <b>Пригласите друга!</b>\nОтправьте ему ссылку:\nhttps://t.me/{BOT_USERNAME}?start=ref{user[0]}\nЗа каждого вы получите 7500 баллов, а друг — 1000 баллов."
    await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "refresh_refs")
async def refresh_refs(callback: CallbackQuery):
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await referrals_cmd(callback.message)  # referrals_cmd теперь использует chat.id
    await callback.answer()

@dp.message(F.text == "🎟 Промокод")
async def promo_cmd(message: Message, state: FSMContext):
    if get_user(message.from_user.id)[12] == 1:
        await message.answer("🚫 Вы забанены.")
        return
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await update_fsm_activity(message.from_user.id)
    kb = build_keyboard([back_btn("back_to_extra")])
    await send_with_photo(message.from_user.id, "promo",
                          "🎟 <b>Активация промокода</b>\n\nВведите ваш промокод и получите бонусные монеты.", kb)
    await state.set_state(PromoState.waiting_code)

@dp.message(PromoState.waiting_code)
async def promo_process(message: Message, state: FSMContext):
    if get_user(message.from_user.id)[12] == 1:
        await message.answer("🚫 Вы забанены.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    code = message.text.strip().upper()
    user_id = message.from_user.id
    cursor.execute("SELECT id, bonus, max_uses, used_count FROM promocodes WHERE code = ? AND is_active = 1", (code,))
    promo = cursor.fetchone()
    if not promo:
        await message.answer("❌ Промокод не найден.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return
    pid, bonus, max_uses, used = promo
    if max_uses > 0 and used >= max_uses:
        await message.answer("❌ Промокод использован.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return
    cursor.execute("SELECT id FROM promocode_activations WHERE promocode_id = ? AND user_id = ?", (pid, user_id))
    if cursor.fetchone():
        await message.answer("❌ Вы уже активировали этот промокод.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return
    update_balance(user_id, bonus, f"Промокод: {code}", "bonus")
    cursor.execute("INSERT INTO promocode_activations (promocode_id, user_id) VALUES (?, ?)", (pid, user_id))
    cursor.execute("UPDATE promocodes SET used_count = used_count + 1 WHERE id = ?", (pid,))
    conn.commit()
    backup_db()
    await message.answer(f"✅ Промокод активирован!\n🎁 На ваш баланс зачислено {bonus} баллов.")
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)

@dp.message(F.text == "💳 История")
async def transaction_history_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    user_id = message.from_user.id
    cursor.execute("SELECT amount, type, description, created_at FROM transactions WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,))
    txns = cursor.fetchall()
    if not txns:
        await message.answer("📊 У вас пока нет транзакций.", reply_markup=main_kb())
        return
    emoji = {'earn':'💰','spend':'💸','transfer':'↔️','penalty':'❌','refund':'🔄','bonus':'🎁','admin':'⚙️'}
    text = "📊 <b>Последние транзакции:</b>\n\n"
    for amount, txn_type, desc, created in txns:
        sign = "+" if amount > 0 else ""
        text += f"{emoji.get(txn_type,'•')} {sign}{amount}₿ — {desc}\n  📅 {created[:16] if created else '—'}\n\n"
    kb = build_keyboard([back_btn("main_menu")])
    await send_message_api(user_id, text, kb)

@dp.message(F.text == "📢 Поддержка")
async def support_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    text = (
        "📢 <b>Техническая поддержка</b>\n━━━━━━━━━━━━━━━\n"
        "💬 Контакт: @cf_mz\n⏰ Режим работы: 12:00 – 00:00 (МСК)\n\n"
        "❓ <b>Часто задаваемые вопросы:</b>\n"
        "• Как пополнить баланс? – Пока только через выполнение заданий.\n"
        "• Сколько ждать выполнения? – Обычно сразу, но до 5 дней.\n"
        "• Что делать, если заказ не выполнился? – Напишите в поддержку.\n\n"
        "Нажмите кнопку ниже, чтобы открыть чат."
    )
    kb = build_keyboard([color_btn("📩 Написать в поддержку", url="https://t.me/cf_mz", style="primary")], [back_btn("main_menu")])
    await send_with_photo(message.from_user.id, "support", text, kb)

@dp.message(F.text == "📊 Статистика")
async def stats_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_banned = 0")
    total = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM task_executions WHERE is_verified = 1")
    tasks = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(amount) FROM transactions WHERE type = 'earn'")
    earned = cursor.fetchone()[0] or 0
    text = f"📊 <b>Общая статистика бота</b>\n👥 Пользователей: {total}\n📋 Выполнено заданий: {format_number(tasks)}\n💰 Всего заработано: {format_number(earned)} баллов"
    kb = build_keyboard([back_btn("main_menu")])
    await send_with_photo(message.from_user.id, "stats", text, kb)

@dp.message(F.text == "⚡ Меню")
async def menu_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await send_with_photo(message.from_user.id, "menu", "⚡ <b>Дополнительное меню</b>\n\nЗдесь собраны все дополнительные возможности бота.", None)
    await message.answer("Выберите действие:", reply_markup=extra_kb())

@dp.message(F.text == "🔙 Главное меню")
async def back_main(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await message.answer("🔙 Главное меню:", reply_markup=main_kb())

@dp.callback_query(lambda c: c.data == "main_menu")
async def cb_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(callback.from_user.id, None)
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_main")
async def cb_back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(callback.from_user.id, None)
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()

@dp.callback_query(lambda c: c.data == "back_to_extra")
async def cb_extra(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(callback.from_user.id, None)
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await callback.message.answer("⚡ Дополнительное меню:", reply_markup=extra_kb())
    await callback.answer()

@dp.message(F.text == "🏆 Рейтинг")
async def rating_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    kb = build_keyboard(
        [color_btn("👥 Топ рефералов", "rating_refs", style="primary")],
        [color_btn("💰 Топ трат", "rating_spent", style="primary")],
        [color_btn("👑 Мой титул", "rating_title", style="primary")],
        [back_btn("back_to_extra")]
    )
    await send_with_photo(message.from_user.id, "rating", "🏆 <b>Рейтинг участников</b>\n\nВыберите категорию для просмотра:", kb)

@dp.callback_query(lambda c: c.data == "rating_refs")
async def rating_refs(callback: CallbackQuery):
    cursor.execute("SELECT username, referrals_weekly FROM users WHERE is_banned = 0 AND referrals_weekly > 0 ORDER BY referrals_weekly DESC LIMIT 10")
    top = cursor.fetchall()
    medals = ["🥇","🥈","🥉","4.","5.","6.","7.","8.","9.","10."]
    text = "🏆 <b>Топ рефералов за неделю:</b>\n\n"
    for i, (un, cnt) in enumerate(top):
        text += f"{medals[i]} @{un or 'скрыт'} — {cnt} чел.\n"
    if not top:
        text += "Пока нет данных."
    kb = build_keyboard([back_btn("rating_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "rating_spent")
async def rating_spent(callback: CallbackQuery):
    cursor.execute("SELECT username, spent_weekly FROM users WHERE is_banned = 0 AND spent_weekly > 0 ORDER BY spent_weekly DESC LIMIT 10")
    top = cursor.fetchall()
    medals = ["🥇","🥈","🥉","4.","5.","6.","7.","8.","9.","10."]
    text = "💰 <b>Топ трат за неделю:</b>\n\n"
    for i, (un, amt) in enumerate(top):
        text += f"{medals[i]} @{un or 'скрыт'} — {format_number(amt)} баллов\n"
    if not top:
        text += "Пока нет данных."
    kb = build_keyboard([back_btn("rating_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "rating_title")
async def rating_title(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    if not user:
        user = create_user(callback.from_user.id)
    level, next_lvl = get_user_level(user[4])
    text = f"👑 <b>Ваш титул:</b> {level[1]}\nПотрачено всего: {format_number(user[4])} баллов\n"
    if next_lvl:
        text += f"До следующего титула «{next_lvl[1]}» осталось {format_number(max(0, next_lvl[0] - user[4]))} баллов."
    kb = build_keyboard([back_btn("rating_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "rating_back")
async def rating_back(callback: CallbackQuery):
    await rating_cmd(callback.message)
    await callback.answer()

@dp.message(F.text == "💸 Перевести")
async def transfer_cmd(message: Message, state: FSMContext):
    if get_user(message.from_user.id)[12] == 1:
        await message.answer("🚫 Вы забанены.")
        return
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await update_fsm_activity(message.from_user.id)
    kb = build_keyboard([back_btn("back_to_extra")])
    await send_message_api(message.from_user.id,
        "💸 <b>Перевод монет</b>\n\nВведите ID пользователя, которому хотите перевести баллы.\nКомиссия за перевод составляет 2% (идет в фонд бота).", kb)
    await state.set_state(TransferState.waiting_id)

@dp.message(TransferState.waiting_id)
async def transfer_id(message: Message, state: FSMContext):
    if get_user(message.from_user.id)[12] == 1:
        await message.answer("🚫 Вы забанены.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        to_id = int(message.text.strip())
    except:
        await message.answer("❌ Введите корректный ID.")
        return
    if to_id == message.from_user.id:
        await message.answer("❌ Нельзя перевести самому себе.")
        return
    if not get_user(to_id):
        await message.answer("❌ Пользователь с таким ID не найден.")
        return
    await state.update_data(to_id=to_id)
    await message.answer("💰 Введите сумму перевода (минимум 100 баллов):")
    await state.set_state(TransferState.waiting_amount)

@dp.message(TransferState.waiting_amount)
async def transfer_amount(message: Message, state: FSMContext):
    if get_user(message.from_user.id)[12] == 1:
        await message.answer("🚫 Вы забанены.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        amount = int(message.text.strip())
    except:
        await message.answer("❌ Введите число.")
        return
    if amount < 100:
        await message.answer("❌ Минимальная сумма перевода — 100 баллов.")
        return
    user = get_user(message.from_user.id)
    commission = math.ceil(amount * 0.02)
    total = amount + commission
    if user[3] < total:
        await message.answer(f"❌ Недостаточно средств. Сумма с комиссией 2%: {total} баллов.")
        return
    data = await state.get_data()
    to_id = data['to_id']
    # Комиссия переводится админу (фонд бота)
    async with db_lock:
        update_balance(ADMIN_ID, commission, f"Комиссия за перевод от {user[0]} к {to_id}", "bonus")
        update_balance(user[0], -total, f"Перевод пользователю {to_id}", "transfer")
        update_balance(to_id, amount, f"Перевод от пользователя {user[0]}", "transfer")
    await message.answer(f"✅ Перевод выполнен!\n💰 Сумма: {amount} баллов\n💸 Комиссия: {commission} баллов\n👤 Получатель: {to_id}")
    try:
        await bot.send_message(to_id, f"💰 Вам перевели баллы!\n👤 Отправитель: @{message.from_user.username or user[0]}\n💵 Сумма: +{amount} баллов\n📊 Ваш баланс: {format_number(get_user(to_id)[3])} баллов")
    except:
        pass
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)

@dp.message(F.text == "🎰 Розыгрыш")
async def giveaway_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    kb = build_keyboard(
        [color_btn("🏆 Текущий топ", "giveaway_top", style="primary")],
        [color_btn("📋 Условия", "giveaway_rules", style="primary")],
        [back_btn("back_to_extra")]
    )
    await send_with_photo(message.from_user.id, "giveaway",
        "🎉 <b>Еженедельный розыгрыш</b>\n\nКаждый понедельник в 00:00 бот выбирает трёх лучших рефереров.\n🏆 Призы:\n🥇 1 место — 10,000 монет\n🥈 2 место — 5,000 монет\n🥉 3 место — 3,000 монет\n\nЧем больше приглашённых за неделю, тем выше ваш шанс победить!", kb)

@dp.callback_query(lambda c: c.data == "giveaway_top")
async def giveaway_top(callback: CallbackQuery):
    if get_user(callback.from_user.id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    cursor.execute("SELECT username, referrals_weekly FROM users WHERE is_banned = 0 AND referrals_weekly > 0 ORDER BY referrals_weekly DESC LIMIT 10")
    top = cursor.fetchall()
    medals = ["🥇","🥈","🥉","4.","5.","6.","7.","8.","9.","10."]
    text = "🎉 <b>Текущий топ рефералов:</b>\n\n"
    for i, (un, cnt) in enumerate(top):
        text += f"{medals[i]} @{un or 'скрыт'} — {cnt} реф.\n"
    if not top:
        text += "Пока нет участников."
    text += "\n\n🏆 Призы:\n🥇 10,000\n🥈 5,000\n🥉 3,000"
    kb = build_keyboard([back_btn("giveaway_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "giveaway_rules")
async def giveaway_rules(callback: CallbackQuery):
    text = (
        "📌 <b>Правила розыгрыша</b>\n\n"
        "✅ Чтобы участвовать, приглашайте друзей по своей реферальной ссылке.\n"
        "✅ Победители определяются каждый понедельник в 00:00 по количеству рефералов за неделю.\n"
        "✅ Призы начисляются автоматически.\n\n"
        "🏆 Призы:\n🥇 1 место — 10,000 монет\n🥈 2 место — 5,000 монет\n🥉 3 место — 3,000 монет"
    )
    kb = build_keyboard([back_btn("giveaway_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "giveaway_back")
async def giveaway_back(callback: CallbackQuery):
    await giveaway_cmd(callback.message)
    await callback.answer()
# ========== ЗАРАБОТАТЬ ==========
@dp.message(F.text == "🪙 Заработать")
async def earn_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    user_id = message.chat.id
    cursor.execute("SELECT channel_username, channel_name FROM sponsor_earn_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    if not channels:
        kb = build_keyboard([back_btn("main_menu")])
        await send_with_photo(user_id, "earn", "🪙 Пока нет доступных заданий для заработка.", kb)
        return
    kb_rows = [[color_btn(f"📢 {name}", url=f"https://t.me/{ch}")] for ch, name in channels]
    kb_rows.append([color_btn("✅ Проверить подписки", "check_earn")])
    kb_rows.append([back_btn("main_menu")])
    text = (
        "🪙 <b>Заработок на спонсорских каналах</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "Подпишитесь на все каналы ниже и нажмите «Проверить подписки».\n"
        "Награда: 3,500 монет (единоразово).\n\nКаналы:\n"
    )
    for ch, name in channels:
        text += f"• {name} (@{ch})\n"
    await send_with_photo(user_id, "earn", text, build_keyboard(*kb_rows))

@dp.callback_query(lambda c: c.data == "check_earn")
async def check_earn(callback: CallbackQuery):
    if get_user(callback.from_user.id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    user_id = callback.from_user.id
    cursor.execute("SELECT channel_username, channel_name FROM sponsor_earn_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    not_sub = []
    for ch, name in channels:
        try:
            member = await bot.get_chat_member(f"@{ch}", user_id)
            if member.status in ['left', 'kicked']:
                not_sub.append(name)
        except Exception:
            not_sub.append(name)
    if not_sub:
        await callback.answer(f"❌ Вы не подписаны на: {', '.join(not_sub)}", show_alert=True)
        return
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ? AND description LIKE '%спонсор%' AND type = 'earn'", (user_id,))
    if cursor.fetchone()[0] == 0:
        update_balance(user_id, 3500, "Спонсорские каналы", "earn")
        await edit_with_photo(callback.message.chat.id, callback.message.message_id, None,
                              "✅ Вы подписаны на все каналы!\n🎁 Награда +3500 баллов зачислена на ваш баланс.",
                              build_keyboard([back_btn("main_menu")]))
    else:
        await callback.answer("✅ Вы уже получили эту награду.", show_alert=True)

# ========== БОЛЬШЕ ЗАДАНИЙ (Elite-вход) ==========
@dp.message(F.text == "➕ Больше заданий")
async def more_cmd(message: Message, state: FSMContext):
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    user_id = message.chat.id
    user = get_user(user_id)
    if not user:
        user = create_user(user_id)
    cursor.execute("SELECT channel_username, channel_name FROM sponsor_extra_channels WHERE is_active = 1")
    sponsor_channels = cursor.fetchall()
    cursor.execute("SELECT COUNT(*) FROM tasks WHERE is_elite = 1 AND status = 'active' AND current_executors < max_executors")
    elite_count = cursor.fetchone()[0]
    text = (
        "👑 <b>ELITE-РАЗДЕЛ</b>\n━━━━━━━━━━━━━━━\n\n"
        "Здесь собраны задания с повышенной оплатой.\nЧтобы брать и создавать их, нужна активная Elite Sub.\n\n"
        "⚠️ <b>Правила:</b>\n• Заказчик проверяет скриншот вручную\n• На проверку даётся 2 дня\n"
        "• Максимум 3 доработки, после – авто-зачисление\n• Злоупотребление доработками ведёт к блокировке\n\n"
    )
    if sponsor_channels:
        text += "📢 <b>Спонсорские каналы:</b>\n"
        for ch, name in sponsor_channels:
            text += f"• {name} (@{ch})\n"
        text += "\n"
    text += f"📋 <b>Доступно Elite-заданий:</b> {elite_count} шт."
    can_create = is_elite_active(user_id)
    kb_rows = []
    if sponsor_channels:
        kb_rows.append([color_btn("✅ Проверить подписки (спонсоры)", "check_extra_earn")])
    kb_rows.append([color_btn("📋 Список заданий", "more_tasks_list")])
    if can_create:
        kb_rows.append([color_btn("➕ Создать Elite-задание", "create_elite_task")])
    else:
        kb_rows.append([color_btn("🔒 Купить Elite Sub", "buy_elite")])
    kb_rows.append([color_btn("📤 Мои задания", "more_my_tasks")])
    kb_rows.append([color_btn("📥 Мои выполнения", "more_my_executions")])
    kb_rows.append([back_btn("main_menu")])
    await send_with_photo(user_id, "more", text, build_keyboard(*kb_rows))

@dp.callback_query(lambda c: c.data == "check_extra_earn")
async def check_extra_earn(callback: CallbackQuery):
    if get_user(callback.from_user.id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    user_id = callback.from_user.id
    if not is_elite_active(user_id):
        await callback.answer("❌ Требуется активный Elite Sub!", show_alert=True)
        return
    cursor.execute("SELECT channel_username, channel_name FROM sponsor_extra_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    if not channels:
        await callback.answer("❌ Нет доступных спонсорских каналов.", show_alert=True)
        return
    not_sub = []
    for ch, name in channels:
        try:
            member = await bot.get_chat_member(f"@{ch}", user_id)
            if member.status in ['left', 'kicked']:
                not_sub.append(name)
        except Exception:
            not_sub.append(name)
    if not_sub:
        await callback.answer(f"❌ Вы не подписаны на: {', '.join(not_sub)}", show_alert=True)
        return
    cursor.execute("SELECT COUNT(*) FROM transactions WHERE user_id = ? AND description = 'Спонсорские каналы (Elite)'", (user_id,))
    if cursor.fetchone()[0] == 0:
        update_balance(user_id, 3500, "Спонсорские каналы (Elite)", "earn")
        await edit_with_photo(callback.message.chat.id, callback.message.message_id, None,
                              "✅ Вы подписаны на все спонсорские каналы!\n🎁 Награда +3500 баллов зачислена.",
                              build_keyboard([back_btn("more_back")]))
    else:
        await callback.answer("✅ Вы уже получили эту награду.", show_alert=True)

# ========== ОБЫЧНЫЕ ЗАДАНИЯ (список с пагинацией) ==========
@dp.message(F.text == "📋 Задания")
async def tasks_menu(message: Message, page: int = 0):
    user_id = message.chat.id
    user = get_user(user_id)
    if not user:
        create_user(user_id, message.from_user.username, message.from_user.full_name)
        user = get_user(user_id)

    per_page = 5
    offset = page * per_page

    cursor.execute("SELECT COUNT(*) FROM tasks WHERE status = 'active' AND current_executors < max_executors AND is_elite = 0")
    total = cursor.fetchone()[0]
    total_pages = max(1, (total + per_page - 1) // per_page)

    cursor.execute("SELECT id, creator_id, task_type, link, description, reward_per_unit, max_executors, current_executors, is_elite FROM tasks WHERE status = 'active' AND current_executors < max_executors AND is_elite = 0 LIMIT ? OFFSET ?", (per_page, offset))
    tasks = cursor.fetchall()

    if not tasks:
        kb = build_keyboard(
            [color_btn("➕ Создать задание", "create_task")],
            [back_btn("main_menu")]
        )
        await send_with_photo(message.chat.id, "tasks",
                              "📋 <b>Обычные задания</b>\n\nПока нет активных заданий. Вы можете создать своё!", kb)
        return

    text = (
        f"📋 <b>Доступные задания</b> (стр. {page+1}/{total_pages})\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Выберите задание и выполните его. Награда зачисляется сразу.\n"
        f"⚠️ Если отпишетесь от канала в течение 5 дней — штраф x2.\n\n"
    )
    kb_rows = []
    for i, task in enumerate(tasks):
        task_id, creator_id, task_type, link, description, reward, max_exec, current_exec, is_elite = task
        free = max_exec - current_exec
        cursor.execute("SELECT id FROM task_executions WHERE task_id = ? AND user_id = ?", (task_id, user_id))
        already_done = cursor.fetchone()
        elite_label = "🏷 Elite (365 дней) 🔒" if is_elite else "🏷 Обычное (5 дней)"
        text += f"{offset+i+1}. {task_type.capitalize()}: {link[:30]}...\n   💰 Награда: {reward} монет\n   🏷 {elite_label}\n   📊 Свободно: {free}/{max_exec}\n\n"
        if free > 0 and not already_done:
            kb_rows.append([color_btn(f"✅ Взять задание #{task_id}", f"take_task_{task_id}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(color_btn("⬅️ Назад", f"tasks_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(color_btn("➡️ Вперёд", f"tasks_page_{page+1}"))
    if nav_buttons:
        kb_rows.append(nav_buttons)

    kb_rows.append([color_btn("🔄 Обновить", "refresh_tasks")])
    kb_rows.append([color_btn("➕ Создать задание", "create_task")])
    kb_rows.append([back_btn("main_menu")])
    await send_with_photo(message.chat.id, "tasks", text, build_keyboard(*kb_rows))

@dp.callback_query(lambda c: c.data == "refresh_tasks")
async def refresh_tasks(callback: CallbackQuery):
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await tasks_menu(callback.message)  # использует chat.id
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("tasks_page_"))
async def tasks_page(callback: CallbackQuery):
    page = int(callback.data.replace("tasks_page_", ""))
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await tasks_menu(callback.message, page)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "tasks_menu_back")
async def tasks_menu_back(callback: CallbackQuery, state: FSMContext = None):
    if state:
        await state.clear()
        fsm_last_activity.pop(callback.from_user.id, None)
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await tasks_menu(callback.message)
    await callback.answer()

# ========== ВЗЯТЬ ЗАДАНИЕ (с блокировкой и предварительной проверкой) ==========
@dp.callback_query(lambda c: c.data.startswith("take_task_"))
async def take_task(callback: CallbackQuery):
    user_id = callback.from_user.id
    if get_user(user_id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    task_id = int(callback.data.replace("take_task_", ""))

    # Предварительная проверка вне транзакции
    cursor.execute("SELECT id, creator_id, task_type, link, reward_per_unit, max_executors, current_executors, is_elite, status FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task or task[8] != 'active':
        await callback.answer("❌ Задание неактивно.", show_alert=True)
        return
    if task[6] >= task[5]:
        await callback.answer("❌ Все места заняты.", show_alert=True)
        return
    if task[7] and not is_elite_active(user_id):
        await callback.answer("❌ Требуется Elite Sub.", show_alert=True)
        return

    # Проверка подписки до транзакции
    channel = extract_channel_from_link(task[3])
    if channel:
        try:
            member = await bot.get_chat_member(f"@{channel}", user_id)
            if member.status in ['left', 'kicked']:
                await callback.answer("❌ Вы не подписаны на канал.", show_alert=True)
                return
        except Exception:
            await callback.answer("❌ Ошибка проверки канала.", show_alert=True)
            return

    # Транзакция с блокировкой
    async with db_lock:
        cursor.execute("BEGIN IMMEDIATE")
        try:
            # Повторная проверка в транзакции
            cursor.execute("SELECT current_executors FROM tasks WHERE id = ? AND status = 'active'", (task_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("ROLLBACK")
                await callback.answer("❌ Задание уже неактивно.", show_alert=True)
                return
            current_exec = row[0]
            if current_exec >= task[5]:
                cursor.execute("ROLLBACK")
                await callback.answer("❌ Все места уже заняты.", show_alert=True)
                return

            cursor.execute("UPDATE tasks SET current_executors = current_executors + 1 WHERE id = ? AND current_executors < max_executors", (task_id,))
            if cursor.rowcount == 0:
                cursor.execute("ROLLBACK")
                await callback.answer("❌ Место только что заняли.", show_alert=True)
                return

            base_reward = task[4]
            reward = base_reward
            if is_elite_active(user_id):
                reward = int(reward * 1.16)

            update_balance(user_id, reward, f"Выполнение задания #{task_id}", "earn", commit=False)
            cursor.execute("INSERT INTO task_executions (task_id, user_id, is_checked, is_verified) VALUES (?, ?, 0, 1)", (task_id, user_id))
            cursor.execute("COMMIT")
            conn.commit()
            backup_db()
        except Exception as e:
            cursor.execute("ROLLBACK")
            logger.error(f"Ошибка в take_task: {e}")
            await callback.answer("❌ Произошла ошибка.", show_alert=True)
            return

    # Уведомление создателю
    creator = get_user(task[1])
    if creator:
        try:
            await bot.send_message(creator[0], f"✅ <b>Новое выполнение задания!</b>\n\n📋 Задание #{task_id}\n👤 Исполнитель: @{callback.from_user.username or user_id}\n💰 Награда: {base_reward} монет\n📊 Прогресс: {current_exec+1}/{task[5]}\n🔗 Ссылка: {task[3]}")
        except Exception:
            pass

    kb = build_keyboard([back_btn("tasks_menu_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None,
                          f"✅ Задание выполнено!\n\n💰 Награда: +{reward} монет\n📋 Задание #{task_id}\n📊 Осталось мест: {task[5] - (current_exec+1)}", kb)
    try:
        await bot.send_message(user_id, f"✅ Вы выполнили задание #{task_id}!\n💰 Награда: +{reward} монет\n📊 Осталось мест: {task[5] - (current_exec+1)}")
    except Exception:
        pass
    await callback.answer()

# ========== СОЗДАНИЕ ОБЫЧНОГО ЗАДАНИЯ (с учётом скидок рефералов и Elite) ==========
@dp.callback_query(lambda c: c.data == "create_task")
async def create_task_start(callback: CallbackQuery, state: FSMContext):
    if get_user(callback.from_user.id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    user = get_user(callback.from_user.id)
    if not user:
        user = create_user(callback.from_user.id)
    await update_fsm_activity(callback.from_user.id)
    kb = build_keyboard(
        [color_btn("📱 Подписка", "task_type_subscribe")],
        [color_btn("❤️ Лайк", "task_type_like")],
        [color_btn("👁 Просмотр", "task_type_view")],
        [back_btn("tasks_menu_back")]
    )
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await send_with_photo(callback.message.chat.id, "create_task",
                          "➕ <b>Создание задания</b>\n\nВыберите тип задания, которое хотите создать.", kb)
    await state.set_state(TaskState.waiting_type)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("task_type_"))
async def task_type_selected(callback: CallbackQuery, state: FSMContext):
    await update_fsm_activity(callback.from_user.id)
    task_type = callback.data.replace("task_type_", "")
    await state.update_data(task_type=task_type)
    kb = build_keyboard([back_btn("tasks_menu_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, "create_task",
                          "📎 Введите ссылку (канал, пост или видео):\n\nПример: https://t.me/username", kb)
    await state.set_state(TaskState.waiting_link)
    await callback.answer()

@dp.message(TaskState.waiting_link)
async def task_link(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(link=message.text)
    await message.answer("📝 Введите описание задания (что нужно сделать исполнителю):")
    await state.set_state(TaskState.waiting_description)

@dp.message(TaskState.waiting_description)
async def task_description(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(description=safe_html(message.text))
    await message.answer("👥 Введите количество исполнителей (от 1 до 1000):")
    await state.set_state(TaskState.waiting_count)

@dp.message(TaskState.waiting_count)
async def task_count(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
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
        await message.answer("❌ Не удалось определить канал из ссылки.\n\n📌 Формат: https://t.me/username или @username")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    if channel.lower() == BOT_USERNAME.lower():
        await message.answer("❌ Нельзя создать задание на этого бота.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    cursor.execute("SELECT id FROM tasks WHERE creator_id = ? AND link = ? AND status = 'active'", (message.from_user.id, link))
    if cursor.fetchone():
        await message.answer("❌ У вас уже есть активное задание с такой же ссылкой.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    is_ok, msg = await check_bot_in_channel_async(channel)
    if not is_ok:
        await send_message_api(message.from_user.id,
            f"❌ {msg}\n\n📌 Инструкция:\n1. Добавьте бота @{BOT_USERNAME} в канал @{channel}\n2. Дайте права администратора\n3. Попробуйте снова",
            build_keyboard([back_btn("tasks_menu_back")]))
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    prices = {'subscribe': 21, 'like': 5, 'view': 3}
    rewards = {'subscribe': 15, 'like': 3, 'view': 1}
    price_per = prices.get(task_type, 21)
    reward_per = rewards.get(task_type, 15)
    total_cost = price_per * count

    # Скидка Elite Sub -16%
    if is_elite_active(message.from_user.id):
        total_cost = int(total_cost * 0.84)

    # Скидка за рефералов
    user = get_user(message.from_user.id)
    if not user:
        user = create_user(message.from_user.id)
    discount = get_referral_discount(user[8])
    if discount > 0:
        total_cost = int(total_cost * (1 - discount / 100))

    if user[3] < total_cost:
        await message.answer(f"❌ Недостаточно монет! Нужно {format_number(total_cost)} монет.\n💰 Ваш баланс: {format_number(user[3])} монет")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    text = (
        f"📋 <b>Подтверждение создания задания</b>\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Тип: {task_type.capitalize()}\n"
        f"Ссылка: {link}\n"
        f"Описание: {description}\n"
        f"Количество мест: {count}\n"
        f"Цена за место: {price_per} ₿\n"
        f"Награда исполнителю: {reward_per} ₿\n"
        f"Общая стоимость: {format_number(total_cost)} ₿\n"
    )
    if is_elite_active(message.from_user.id):
        text += "💎 Скидка Elite Sub 16% учтена.\n"
    if discount > 0:
        text += f"👥 Скидка за рефералов {discount}% учтена.\n"
    text += f"✅ {msg}\n\nНажмите «Создать» для подтверждения."

    kb = build_keyboard(
        [color_btn("✅ Создать", "task_confirm")],
        [color_btn("❌ Отмена", "task_cancel")]
    )
    await send_message_api(message.from_user.id, text, kb)
    await state.set_state(TaskState.waiting_confirmation)

@dp.callback_query(lambda c: c.data == "task_confirm")
async def task_confirm(callback: CallbackQuery, state: FSMContext):
    await update_fsm_activity(callback.from_user.id)
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

    if is_elite_active(user_id):
        total_cost = int(total_cost * 0.84)

    user = get_user(user_id)
    if not user:
        user = create_user(user_id)
    discount = get_referral_discount(user[8])
    if discount > 0:
        total_cost = int(total_cost * (1 - discount / 100))

    async with db_lock:
        # Повторная проверка баланса
        user = get_user(user_id)
        if user[3] < total_cost:
            await edit_message_api(callback.message.chat.id, callback.message.message_id,
                                   "❌ Недостаточно монет! Баланс изменился.",
                                   build_keyboard([back_btn("main_menu")]))
            await state.clear()
            fsm_last_activity.pop(callback.from_user.id, None)
            await callback.answer()
            return

        update_balance(user_id, -total_cost, f"Создание задания: {task_type}", "spend")
        cursor.execute("INSERT INTO tasks (creator_id, task_type, link, description, reward_per_unit, max_executors, is_elite, actual_cost) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                       (user_id, task_type, link, description, reward_per, count, 0, total_cost))
        conn.commit()
        backup_db()

    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "✅ Задание успешно создано! Ожидайте исполнителей.",
                           build_keyboard([back_btn("main_menu")]))
    await state.clear()
    fsm_last_activity.pop(callback.from_user.id, None)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "task_cancel")
async def task_cancel(callback: CallbackQuery, state: FSMContext):
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "❌ Создание задания отменено.",
                           build_keyboard([back_btn("tasks_menu_back")]))
    await state.clear()
    fsm_last_activity.pop(callback.from_user.id, None)
    await callback.answer()
# ========== СПИСОК ELITE-ЗАДАНИЙ (с пагинацией) ==========
@dp.callback_query(lambda c: c.data == "more_tasks_list" or c.data.startswith("more_tasks_page_"))
async def more_tasks_list(callback: CallbackQuery):
    user_id = callback.from_user.id
    if get_user(user_id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return

    page = 0
    if callback.data.startswith("more_tasks_page_"):
        page = int(callback.data.replace("more_tasks_page_", ""))

    per_page = 5
    offset = page * per_page

    cursor.execute(
        "SELECT COUNT(*) FROM tasks WHERE status = 'active' AND current_executors < max_executors AND is_elite = 1"
    )
    total_tasks = cursor.fetchone()[0]
    total_pages = max(1, (total_tasks + per_page - 1) // per_page)

    cursor.execute(
        "SELECT id, creator_id, task_type, link, description, reward_per_unit, max_executors, current_executors, is_elite "
        "FROM tasks WHERE status = 'active' AND current_executors < max_executors AND is_elite = 1 "
        "LIMIT ? OFFSET ?",
        (per_page, offset)
    )
    tasks = cursor.fetchall()

    if not tasks:
        kb = build_keyboard([back_btn("more_back")])
        await edit_with_photo(
            callback.message.chat.id, callback.message.message_id, None,
            "👑 <b>ELITE-ЗАДАНИЯ</b>\n\nПока нет активных заданий. Загляните позже или создайте своё!",
            kb
        )
        await callback.answer()
        return

    text = (
        f"👑 <b>ELITE-ЗАДАНИЯ</b> (стр. {page+1}/{total_pages})\n"
        f"━━━━━━━━━━━━━━━\n"
        f"Здесь задания с повышенной оплатой и ручной проверкой.\n"
        f"Для выполнения требуется активная Elite Sub.\n\n"
    )
    kb_rows = []
    for i, task in enumerate(tasks):
        task_id, creator_id, task_type, link, description, reward, max_exec, current_exec, is_elite = task
        free = max_exec - current_exec
        cursor.execute(
            "SELECT id FROM elite_submissions WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'rework')",
            (task_id, user_id)
        )
        already_taken = cursor.fetchone()
        text += f"{offset+i+1}. {task_type.capitalize()}: {link[:30]}...\n   💰 Награда: {reward} монет\n   📊 Свободно: {free}/{max_exec}\n"
        if not already_taken and free > 0:
            kb_rows.append([color_btn(f"✅ Взять задание #{task_id}", f"take_elite_task_{task_id}")])

    nav_buttons = []
    if page > 0:
        nav_buttons.append(color_btn("⬅️ Назад", f"more_tasks_page_{page-1}"))
    if page < total_pages - 1:
        nav_buttons.append(color_btn("➡️ Вперёд", f"more_tasks_page_{page+1}"))
    if nav_buttons:
        kb_rows.append(nav_buttons)

    kb_rows.append([color_btn("🔄 Обновить", "more_tasks_list")])
    kb_rows.append([back_btn("more_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None, text, build_keyboard(*kb_rows))
    await callback.answer()

# ========== ВЗЯТЬ ELITE-ЗАДАНИЕ ==========
@dp.callback_query(lambda c: c.data.startswith("take_elite_task_"))
async def take_elite_task(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if get_user(user_id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    task_id = int(callback.data.replace("take_elite_task_", ""))

    if not is_elite_active(user_id):
        await callback.answer("❌ Требуется активная Elite Sub!", show_alert=True)
        return

    # Предварительная проверка
    cursor.execute(
        "SELECT id, creator_id, task_type, link, description, reward_per_unit, max_executors, current_executors, is_elite, status "
        "FROM tasks WHERE id = ?",
        (task_id,)
    )
    task = cursor.fetchone()
    if not task or task[9] != 'active':
        await callback.answer("❌ Задание неактивно.", show_alert=True)
        return
    if task[6] >= task[5]:
        await callback.answer("❌ Все места заняты.", show_alert=True)
        return

    cursor.execute(
        "SELECT id FROM elite_submissions WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'rework')",
        (task_id, user_id)
    )
    if cursor.fetchone():
        await callback.answer("❌ Вы уже взяли это задание.", show_alert=True)
        return

    async with db_lock:
        cursor.execute("BEGIN IMMEDIATE")
        try:
            cursor.execute("SELECT current_executors FROM tasks WHERE id = ? AND status = 'active'", (task_id,))
            row = cursor.fetchone()
            if not row:
                cursor.execute("ROLLBACK")
                await callback.answer("❌ Задание уже неактивно.", show_alert=True)
                return
            current_exec = row[0]
            if current_exec >= task[5]:
                cursor.execute("ROLLBACK")
                await callback.answer("❌ Все места уже заняты.", show_alert=True)
                return

            cursor.execute(
                "UPDATE tasks SET current_executors = current_executors + 1 WHERE id = ? AND current_executors < max_executors",
                (task_id,)
            )
            if cursor.rowcount == 0:
                cursor.execute("ROLLBACK")
                await callback.answer("❌ Место только что заняли.", show_alert=True)
                return

            cursor.execute(
                "INSERT INTO elite_submissions (task_id, user_id, status) VALUES (?, ?, 'pending')",
                (task_id, user_id)
            )
            cursor.execute("COMMIT")
            conn.commit()
            backup_db()
        except Exception as e:
            cursor.execute("ROLLBACK")
            logger.error(f"Ошибка в take_elite_task: {e}")
            await callback.answer("❌ Произошла ошибка.", show_alert=True)
            return

    await callback.answer("✅ Задание взято! Отправьте скриншот.")
    kb = build_keyboard(
        [color_btn("📸 Отправить скриншот", f"elite_submit_{task_id}")],
        [back_btn("more_tasks_list")]
    )
    await edit_with_photo(
        callback.message.chat.id, callback.message.message_id, None,
        f"👑 <b>Задание #{task_id} взято!</b>\n\n"
        f"📌 Отправьте скриншот выполнения.\n"
        f"💰 Награда: {task[4]} монет (базовая, +16% с Elite Sub)\n"
        f"📝 Описание: {task[3]}",
        kb
    )
    await callback.answer()

# ========== ОТПРАВКА СКРИНШОТА ==========
@dp.callback_query(lambda c: c.data.startswith("elite_submit_"))
async def elite_submit(callback: CallbackQuery, state: FSMContext):
    task_id = int(callback.data.replace("elite_submit_", ""))
    await state.update_data(task_id=task_id)
    await update_fsm_activity(callback.from_user.id)
    kb = build_keyboard([back_btn("more_tasks_list")])
    await edit_with_photo(
        callback.message.chat.id, callback.message.message_id, None,
        "📸 <b>Отправьте скриншот выполнения</b>\n\nПрикрепите фото или документ, подтверждающий выполнение задания.",
        kb
    )
    await state.set_state(EliteSubmitState.waiting_screenshot)
    await callback.answer()

@dp.message(EliteSubmitState.waiting_screenshot, F.photo)
async def elite_screenshot_photo(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    data = await state.get_data()
    task_id = data['task_id']
    user_id = message.from_user.id
    file_id = message.photo[-1].file_id

    cursor.execute("SELECT creator_id, reward_per_unit, status FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task or task[2] != 'active':
        await message.answer("❌ Задание неактивно.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    creator_id, reward, _ = task
    cursor.execute(
        "SELECT id FROM elite_submissions WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'rework')",
        (task_id, user_id)
    )
    sub = cursor.fetchone()
    if not sub:
        await message.answer("❌ У вас нет активной заявки на это задание.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    cursor.execute(
        "UPDATE elite_submissions SET screenshot_file_id = ?, status = 'pending', submitted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (file_id, sub[0])
    )
    conn.commit()
    backup_db()

    kb_for_creator = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"elite_approve_{task_id}_{user_id}"),
            InlineKeyboardButton(text="🔄 Доработка", callback_data=f"elite_rework_{task_id}_{user_id}")
        ],
        [InlineKeyboardButton(text="📝 Написать", callback_data=f"elite_message_{task_id}_{user_id}")]
    ])

    try:
        await bot.send_photo(
            creator_id, file_id,
            caption=f"📸 Новый скриншот от @{message.from_user.username or user_id}\n\n"
                    f"📋 Задание #{task_id}\n💰 Награда: {reward} монет\n\n"
                    f"Подтвердите выполнение или отправьте на доработку.",
            reply_markup=kb_for_creator
        )
    except Exception:
        try:
            await bot.send_message(
                creator_id,
                f"📸 Новый скриншот от @{message.from_user.username or user_id}\n\n"
                f"📋 Задание #{task_id}\n💰 Награда: {reward} монет\n\n"
                f"Подтвердите выполнение или отправьте на доработку.",
                reply_markup=kb_for_creator
            )
        except Exception:
            pass

    await message.answer("✅ Скриншот отправлен! Ожидайте подтверждения от заказчика.")
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)

@dp.message(EliteSubmitState.waiting_screenshot, F.document)
async def elite_screenshot_doc(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    data = await state.get_data()
    task_id = data['task_id']
    user_id = message.from_user.id
    file_id = message.document.file_id

    cursor.execute("SELECT creator_id, reward_per_unit, status FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task or task[2] != 'active':
        await message.answer("❌ Задание неактивно.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    creator_id, reward, _ = task
    cursor.execute(
        "SELECT id FROM elite_submissions WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'rework')",
        (task_id, user_id)
    )
    sub = cursor.fetchone()
    if not sub:
        await message.answer("❌ У вас нет активной заявки на это задание.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    cursor.execute(
        "UPDATE elite_submissions SET screenshot_file_id = ?, status = 'pending', submitted_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP "
        "WHERE id = ?",
        (file_id, sub[0])
    )
    conn.commit()
    backup_db()

    kb_for_creator = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Подтвердить", callback_data=f"elite_approve_{task_id}_{user_id}"),
            InlineKeyboardButton(text="🔄 Доработка", callback_data=f"elite_rework_{task_id}_{user_id}")
        ],
        [InlineKeyboardButton(text="📝 Написать", callback_data=f"elite_message_{task_id}_{user_id}")]
    ])

    try:
        await bot.send_document(
            creator_id, file_id,
            caption=f"📸 Новый скриншот от @{message.from_user.username or user_id}\n\n"
                    f"📋 Задание #{task_id}\n💰 Награда: {reward} монет\n\n"
                    f"Подтвердите выполнение или отправьте на доработку.",
            reply_markup=kb_for_creator
        )
    except Exception:
        try:
            await bot.send_message(
                creator_id,
                f"📸 Новый скриншот от @{message.from_user.username or user_id}\n\n"
                f"📋 Задание #{task_id}\n💰 Награда: {reward} монет\n\n"
                f"Подтвердите выполнение или отправьте на доработку.",
                reply_markup=kb_for_creator
            )
        except Exception:
            pass

    await message.answer("✅ Скриншот отправлен! Ожидайте подтверждения от заказчика.")
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)

@dp.message(EliteSubmitState.waiting_screenshot)
async def elite_screenshot_other(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text and message.text.lower() in ["отмена", "🔙 отмена", "назад", "🔙 назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await more_cmd(message)
        return
    await message.answer("❌ Пожалуйста, отправьте скриншот (фото или документ).\nИли напишите «Отмена» для возврата.")

# ========== ПОДТВЕРЖДЕНИЕ И ДОРАБОТКА ==========
@dp.callback_query(lambda c: c.data.startswith("elite_approve_"))
async def elite_approve(callback: CallbackQuery):
    parts = callback.data.split("_")
    task_id = int(parts[2])
    user_id = int(parts[3])

    cursor.execute("SELECT creator_id, reward_per_unit, status FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task or task[2] != 'active':
        await callback.answer("❌ Задание неактивно.", show_alert=True)
        return

    creator_id, reward, _ = task
    if not is_admin(callback.from_user.id) and callback.from_user.id != creator_id:
        await callback.answer("⛔ Только заказчик может подтвердить.", show_alert=True)
        return

    cursor.execute(
        "SELECT id, status FROM elite_submissions WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'rework')",
        (task_id, user_id)
    )
    sub = cursor.fetchone()
    if not sub:
        await callback.answer("❌ Заявка уже обработана.", show_alert=True)
        return

    # Бонус Elite-исполнителя +16%
    if is_elite_active(user_id):
        reward = int(reward * 1.16)

    commission = math.ceil(reward * 0.1)
    final_reward = reward - commission
    async with db_lock:
        update_balance(user_id, final_reward, f"Elite-задание #{task_id} выполнено", "earn")
        cursor.execute(
            "UPDATE elite_submissions SET status = 'approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (sub[0],)
        )
        conn.commit()
        backup_db()

    await callback.answer("✅ Задание подтверждено!")
    try:
        await bot.send_message(
            user_id,
            f"✅ Заказчик подтвердил выполнение задания #{task_id}!\n"
            f"💰 Награда: +{final_reward} монет (комиссия 10%)"
        )
    except Exception:
        pass
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)

@dp.callback_query(lambda c: c.data.startswith("elite_rework_"))
async def elite_rework(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    task_id = int(parts[2])
    user_id = int(parts[3])

    cursor.execute("SELECT creator_id, reward_per_unit, status FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task or task[2] != 'active':
        await callback.answer("❌ Задание неактивно.", show_alert=True)
        return

    creator_id, reward, _ = task
    if not is_admin(callback.from_user.id) and callback.from_user.id != creator_id:
        await callback.answer("⛔ Только заказчик может отправить на доработку.", show_alert=True)
        return

    cursor.execute(
        "SELECT id, rework_count FROM elite_submissions WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'rework')",
        (task_id, user_id)
    )
    sub = cursor.fetchone()
    if not sub:
        await callback.answer("❌ Заявка не найдена или уже обработана.", show_alert=True)
        return

    sub_id, rework_count = sub
    if rework_count >= 3:
        # Авто-зачисление
        if is_elite_active(user_id):
            reward = int(reward * 1.16)
        commission = math.ceil(reward * 0.1)
        final_reward = reward - commission
        async with db_lock:
            update_balance(user_id, final_reward, f"Elite-задание #{task_id} авто-принято (превышен лимит доработок)", "earn")
            cursor.execute(
                "UPDATE elite_submissions SET status = 'auto_approved', updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (sub_id,)
            )
            conn.commit()
            backup_db()
        await callback.answer("✅ Превышен лимит доработок. Баллы автоматически зачислены исполнителю.", show_alert=True)
        try:
            await bot.send_message(
                user_id,
                f"✅ Баллы зачислены! Заказчик превысил лимит доработок.\n"
                f"💰 Награда: +{final_reward} монет (комиссия 10%)"
            )
        except Exception:
            pass
        await delete_msg_api(callback.message.chat.id, callback.message.message_id)
        return

    if rework_count == 2:
        try:
            await bot.send_message(
                creator_id,
                "⚠️ ВНИМАНИЕ! Это 3-я доработка!\n\n"
                "Следующая доработка приведёт к автоматическому зачислению баллов исполнителю.\n"
                "Злоупотребление доработками → блокировка аккаунта."
            )
        except Exception:
            pass

    await update_fsm_activity(callback.from_user.id)
    await state.update_data(task_id=task_id, user_id=user_id, rework_count=rework_count)
    kb = build_keyboard([back_btn("more_tasks_list")])
    await edit_with_photo(
        callback.message.chat.id, callback.message.message_id, None,
        "📝 <b>Отправка на доработку</b>\n\nВведите сообщение для исполнителя (что нужно исправить):",
        kb
    )
    await state.set_state(EliteSubmitState.waiting_rework_message)
    await callback.answer()

@dp.message(EliteSubmitState.waiting_rework_message)
async def elite_rework_message(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return

    data = await state.get_data()
    task_id = data['task_id']
    user_id = data['user_id']
    rework_count = data['rework_count'] + 1

    cursor.execute(
        "UPDATE elite_submissions SET rework_count = ?, rework_message = ?, status = 'rework', updated_at = CURRENT_TIMESTAMP "
        "WHERE task_id = ? AND user_id = ? AND status IN ('pending', 'rework')",
        (rework_count, safe_html(message.text), task_id, user_id)
    )
    conn.commit()
    backup_db()

    warning = ""
    if rework_count == 3:
        warning = "\n\n⚠️ ЭТО ПОСЛЕДНЯЯ ДОРАБОТКА! После следующей — баллы будут зачислены АВТОМАТИЧЕСКИ."

    try:
        await bot.send_message(
            user_id,
            f"🔄 Заказчик отправил задание на доработку ({rework_count}/3):\n\n{message.text}{warning}"
        )
    except Exception:
        pass

    await message.answer("✅ Сообщение отправлено исполнителю.")
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await more_cmd(message)

# ========== НАПИСАТЬ СООБЩЕНИЕ ИСПОЛНИТЕЛЮ ==========
@dp.callback_query(lambda c: c.data.startswith("elite_message_"))
async def elite_message(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    task_id = int(parts[2])
    user_id = int(parts[3])

    cursor.execute("SELECT creator_id, status FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task or task[1] != 'active':
        await callback.answer("❌ Задание неактивно.", show_alert=True)
        return

    if not is_admin(callback.from_user.id) and callback.from_user.id != task[0]:
        await callback.answer("⛔ Только заказчик может писать.", show_alert=True)
        return

    await update_fsm_activity(callback.from_user.id)
    await state.update_data(task_id=task_id, user_id=user_id)
    kb = build_keyboard([back_btn("more_tasks_list")])
    await edit_with_photo(
        callback.message.chat.id, callback.message.message_id, None,
        "📝 <b>Сообщение исполнителю</b>\n\nВведите текст сообщения:",
        kb
    )
    await state.set_state(EliteSubmitState.waiting_custom_message)
    await callback.answer()

@dp.message(EliteSubmitState.waiting_custom_message)
async def elite_send_message(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return

    data = await state.get_data()
    task_id = data['task_id']
    user_id = data['user_id']

    try:
        await bot.send_message(
            user_id,
            f"📝 Сообщение от заказчика по заданию #{task_id}:\n\n{message.text}"
        )
    except Exception:
        pass

    await message.answer("✅ Сообщение отправлено.")
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await more_cmd(message)

# ========== МОИ ЗАДАНИЯ / ВЫПОЛНЕНИЯ ==========
@dp.callback_query(lambda c: c.data == "more_my_tasks")
async def more_my_tasks(callback: CallbackQuery):
    if get_user(callback.from_user.id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    user_id = callback.from_user.id
    cursor.execute(
        "SELECT id, task_type, link, description, reward_per_unit, max_executors, current_executors, status "
        "FROM tasks WHERE creator_id = ? AND is_elite = 1 ORDER BY id DESC LIMIT 10",
        (user_id,)
    )
    tasks = cursor.fetchall()
    if not tasks:
        await callback.answer("❌ У вас нет созданных Elite-заданий.", show_alert=True)
        return
    text = "📤 <b>Мои Elite-задания (заказчик):</b>\n\n"
    for task in tasks:
        task_id, task_type, link, description, reward, max_exec, current_exec, status = task
        text += f"#{task_id} {task_type}: {current_exec}/{max_exec} | {status}\n"
    kb = build_keyboard([back_btn("more_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "more_my_executions")
async def more_my_executions(callback: CallbackQuery):
    if get_user(callback.from_user.id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    user_id = callback.from_user.id
    cursor.execute(
        "SELECT es.id, es.task_id, t.task_type, t.link, es.status, es.rework_count "
        "FROM elite_submissions es JOIN tasks t ON es.task_id = t.id "
        "WHERE es.user_id = ? ORDER BY es.id DESC LIMIT 10",
        (user_id,)
    )
    submissions = cursor.fetchall()
    if not submissions:
        await callback.answer("❌ У вас нет выполненных Elite-заданий.", show_alert=True)
        return
    text = "📥 <b>Мои выполнения (исполнитель):</b>\n\n"
    for sub in submissions:
        sub_id, task_id, task_type, link, status, rework_count = sub
        text += f"#{task_id} {task_type}: {status} | Доработок: {rework_count}/3\n"
    kb = build_keyboard([back_btn("more_back")])
    await edit_with_photo(callback.message.chat.id, callback.message.message_id, None, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "more_back")
async def more_back(callback: CallbackQuery):
    await more_cmd(callback.message)  # использует chat.id
    await callback.answer()

# ========== СОЗДАНИЕ ELITE-ЗАДАНИЯ ==========
@dp.callback_query(lambda c: c.data == "create_elite_task")
async def create_elite_task_start(callback: CallbackQuery, state: FSMContext):
    if get_user(callback.from_user.id)[12] == 1:
        await callback.answer("🚫 Вы забанены.", show_alert=True)
        return
    user_id = callback.from_user.id
    if not is_elite_active(user_id):
        await callback.answer("❌ Требуется активная Elite Sub!", show_alert=True)
        return
    user = get_user(user_id)
    if user[3] < 250:
        await callback.answer("❌ Минимум 250 монет для создания Elite-задания!", show_alert=True)
        return

    await update_fsm_activity(user_id)
    kb = build_keyboard(
        [color_btn("📱 Подписка", "elite_type_subscribe")],
        [color_btn("❤️ Лайк", "elite_type_like")],
        [color_btn("👁 Просмотр", "elite_type_view")],
        [back_btn("more_back")]
    )
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await send_with_photo(
        callback.message.chat.id,
        "create_task",
        "👑 <b>Создание Elite-задания</b>\n\nВыберите тип задания. Цена за место: 250₿.",
        kb
    )
    await state.set_state(EliteTaskState.waiting_type)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("elite_type_"))
async def elite_type_selected(callback: CallbackQuery, state: FSMContext):
    await update_fsm_activity(callback.from_user.id)
    task_type = callback.data.replace("elite_type_", "")
    await state.update_data(task_type=task_type)
    kb = build_keyboard([back_btn("more_back")])
    await edit_with_photo(
        callback.message.chat.id, callback.message.message_id, None,
        "📎 Введите ссылку (канал, пост или видео):",
        kb
    )
    await state.set_state(EliteTaskState.waiting_link)
    await callback.answer()

@dp.message(EliteTaskState.waiting_link)
async def elite_task_link(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(link=message.text)
    await message.answer("📝 Введите описание задания (что делать, какой скриншот):")
    await state.set_state(EliteTaskState.waiting_description)

@dp.message(EliteTaskState.waiting_description)
async def elite_task_description(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    await state.update_data(description=safe_html(message.text))
    await message.answer("💰 Введите награду для исполнителя (минимум 30₿):")
    await state.set_state(EliteTaskState.waiting_reward)

@dp.message(EliteTaskState.waiting_reward)
async def elite_task_reward(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        reward = int(message.text.strip())
        if reward < 30:
            await message.answer("❌ Минимальная награда — 30₿.")
            return
    except:
        await message.answer("❌ Введите число.")
        return
    await state.update_data(reward=reward)
    await message.answer("👥 Введите количество исполнителей (1-1000):")
    await state.set_state(EliteTaskState.waiting_count)

@dp.message(EliteTaskState.waiting_count)
async def elite_task_count(message: Message, state: FSMContext):
    await update_fsm_activity(message.from_user.id)
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
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
    reward = data['reward']
    count = data['count']

    channel = extract_channel_from_link(link)
    if not channel:
        await message.answer("❌ Неверная ссылка.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    total_cost = 250 * count
    if is_elite_active(message.from_user.id):
        total_cost = int(total_cost * 0.84)
    user = get_user(message.from_user.id)
    if not user:
        user = create_user(message.from_user.id)
    discount = get_referral_discount(user[8])
    if discount > 0:
        total_cost = int(total_cost * (1 - discount / 100))

    if user[3] < total_cost:
        await message.answer(f"❌ Недостаточно монет! Нужно {total_cost}₿.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    text = (
        f"👑 <b>Подтверждение Elite-задания</b>\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"Тип: {task_type.capitalize()}\n"
        f"Ссылка: {link}\n"
        f"Описание: {description}\n"
        f"Количество мест: {count}\n"
        f"Награда: {reward}₿\n"
        f"Цена заказчика: 250₿ × {count} = {total_cost}₿\n"
        f"Комиссия: 10% от награды\n\n"
        f"⚠️ ПРАВИЛА:\n"
        f"• Максимум 3 доработки\n"
        f"• После 3-й — авто-зачисление\n"
        f"• Злоупотребление — блокировка"
    )
    if is_elite_active(message.from_user.id):
        text += "\n💎 Скидка Elite Sub 16% учтена."
    if discount > 0:
        text += f"\n👥 Скидка за рефералов {discount}% учтена."

    kb = build_keyboard(
        [color_btn("✅ Создать", "elite_task_confirm")],
        [color_btn("❌ Отмена", "elite_task_cancel")]
    )
    await send_message_api(message.from_user.id, text, kb)
    await state.set_state(EliteTaskState.waiting_confirmation)

@dp.callback_query(lambda c: c.data == "elite_task_confirm")
async def elite_task_confirm(callback: CallbackQuery, state: FSMContext):
    await update_fsm_activity(callback.from_user.id)
    user_id = callback.from_user.id
    data = await state.get_data()
    task_type = data['task_type']
    link = data['link']
    description = data['description']
    reward = data['reward']
    count = data['count']

    total_cost = 250 * count
    if is_elite_active(user_id):
        total_cost = int(total_cost * 0.84)
    user = get_user(user_id)
    if not user:
        user = create_user(user_id)
    discount = get_referral_discount(user[8])
    if discount > 0:
        total_cost = int(total_cost * (1 - discount / 100))

    async with db_lock:
        user = get_user(user_id)
        if user[3] < total_cost:
            await edit_message_api(
                callback.message.chat.id, callback.message.message_id,
                "❌ Недостаточно монет!",
                build_keyboard([back_btn("main_menu")])
            )
            await state.clear()
            fsm_last_activity.pop(callback.from_user.id, None)
            await callback.answer()
            return

        update_balance(user_id, -total_cost, f"Создание Elite-задания: {task_type}", "spend")
        cursor.execute(
            "INSERT INTO tasks (creator_id, task_type, link, description, reward_per_unit, max_executors, is_elite, actual_cost) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, task_type, link, description, reward, count, 1, total_cost)
        )
        conn.commit()
        backup_db()

    await edit_message_api(
        callback.message.chat.id, callback.message.message_id,
        "✅ Elite-задание создано! Ожидайте исполнителей.",
        build_keyboard([back_btn("main_menu")])
    )
    await state.clear()
    fsm_last_activity.pop(callback.from_user.id, None)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "elite_task_cancel")
async def elite_task_cancel(callback: CallbackQuery, state: FSMContext):
    await edit_message_api(
        callback.message.chat.id, callback.message.message_id,
        "❌ Создание отменено.",
        build_keyboard([back_btn("more_back")])
    )
    await state.clear()
    fsm_last_activity.pop(callback.from_user.id, None)
    await callback.answer()
# ========== АДМИН-ПАНЕЛЬ ==========
@dp.message(Command("admin"))
async def admin_cmd(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return

    text = (
        "⚙️ <b>Админ-панель</b>\n"
        "━━━━━━━━━━━━━━━\n"
        "Выберите раздел для управления:\n"
        "📢 <b>Каналы</b> — обязательные и спонсорские\n"
        "🎟 <b>Промокоды</b> — создание, список, удаление\n"
        "📋 <b>Задания</b> — просмотр и управление\n"
        "👤 <b>Пользователи</b> — поиск, монеты, Elite, бан\n"
        "📨 <b>Рассылка</b> — сообщение всем пользователям\n"
        "💰 <b>Настройки</b> — текущие тарифы\n"
        "🏆 <b>Розыгрыш</b> — ручной запуск\n"
        "📊 <b>Статистика</b> — общие показатели"
    )

    kb = build_keyboard(
        [
            color_btn("📢 Каналы", "admin_channels"),
            color_btn("🎟 Промокоды", "admin_promocodes")
        ],
        [
            color_btn("📋 Задания", "admin_tasks"),
            color_btn("👤 Пользователи", "admin_users")
        ],
        [
            color_btn("📨 Рассылка", "admin_broadcast"),
            color_btn("💰 Настройки", "admin_settings")
        ],
        [
            color_btn("🏆 Розыгрыш", "admin_giveaway"),
            color_btn("📊 Статистика", "admin_stats")
        ],
        [color_btn("🔙 Выход", "admin_exit")]
    )
    await send_message_api(message.from_user.id, text, kb)

# ----------  УПРАВЛЕНИЕ КАНАЛАМИ  ----------
@dp.callback_query(lambda c: c.data == "admin_channels")
@admin_only
async def admin_channels_menu(callback: CallbackQuery):
    kb = build_keyboard(
        [color_btn("📢 Обязательные каналы", "admin_required_channels")],
        [color_btn("🪙 Спонсоры (Заработать)", "admin_earn_channels")],
        [color_btn("👑 Спонсоры (Elite)", "admin_extra_channels")],
        [back_btn("admin_back")]
    )
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "📢 <b>Управление каналами</b>\n\n"
                           "• Обязательные — на них нужно подписаться новым пользователям\n"
                           "• Спонсоры (Заработать) — за подписку даётся бонус\n"
                           "• Спонсоры (Elite) — отображаются в Elite-разделе", kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_required_channels")
@admin_only
async def admin_required_channels_list(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM required_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    text = "📢 <b>Обязательные каналы</b>\n\n"
    if channels:
        for ch_id, username, name in channels:
            text += f"• {name} (@{username})\n"
    else:
        text += "Пока нет каналов."
    kb = build_keyboard(
        [color_btn("➕ Добавить", "admin_add_required")],
        [color_btn("➖ Удалить", "admin_remove_required")],
        [back_btn("admin_channels")]
    )
    await edit_message_api(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_add_required")
@admin_only
async def admin_add_required_start(callback: CallbackQuery, state: FSMContext):
    await state.update_data(channel_type="required")
    kb = build_keyboard([back_btn("admin_required_channels")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "📝 Введите username канала (без @):", kb)
    await state.set_state(AdminState.waiting_channel_username)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_remove_required")
@admin_only
async def admin_remove_required_list(callback: CallbackQuery):
    cursor.execute("SELECT id, channel_username, channel_name FROM required_channels WHERE is_active = 1")
    channels = cursor.fetchall()
    if not channels:
        await callback.answer("❌ Нет каналов для удаления.", show_alert=True)
        return
    kb_rows = [[color_btn(f"🗑 {name} (@{username})", f"admin_remove_required_{ch_id}")] for ch_id, username, name in channels]
    kb_rows.append([back_btn("admin_required_channels")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "🗑 Выберите канал для удаления:", build_keyboard(*kb_rows))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_remove_required_"))
@admin_only
async def admin_remove_required_confirm(callback: CallbackQuery):
    ch_id = int(callback.data.replace("admin_remove_required_", ""))
    cursor.execute("UPDATE required_channels SET is_active = 0 WHERE id = ?", (ch_id,))
    conn.commit()
    backup_db()
    await callback.answer("✅ Канал удалён!", show_alert=True)
    # Просто обновим список
    await admin_required_channels_list(callback)

# --- Спонсорские каналы (Earn / Extra) ---
async def show_sponsor_channels(callback: CallbackQuery, ch_type: str):
    table = "sponsor_earn_channels" if ch_type == "earn" else "sponsor_extra_channels"
    label = "🪙 Спонсоры (Заработать)" if ch_type == "earn" else "👑 Спонсоры (Elite)"
    prefix = f"admin_{ch_type}"
    cursor.execute(f"SELECT id, channel_username, channel_name FROM {table} WHERE is_active = 1")
    channels = cursor.fetchall()
    text = f"{label}:\n\n"
    if channels:
        for ch_id, username, name in channels:
            text += f"• {name} (@{username})\n"
    else:
        text += "Пока нет каналов."
    kb = build_keyboard(
        [color_btn("➕ Добавить", f"{prefix}_add")],
        [color_btn("➖ Удалить", f"{prefix}_remove")],
        [back_btn("admin_channels")]
    )
    await edit_message_api(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_earn_channels")
@admin_only
async def admin_earn_channels_list(callback: CallbackQuery):
    await show_sponsor_channels(callback, "earn")

@dp.callback_query(lambda c: c.data == "admin_extra_channels")
@admin_only
async def admin_extra_channels_list(callback: CallbackQuery):
    await show_sponsor_channels(callback, "extra")

@dp.callback_query(lambda c: c.data in ["admin_earn_add", "admin_extra_add"])
@admin_only
async def admin_sponsor_add_start(callback: CallbackQuery, state: FSMContext):
    ch_type = "earn" if "earn" in callback.data else "extra"
    await state.update_data(channel_type=ch_type)
    prefix = f"admin_{ch_type}"
    kb = build_keyboard([back_btn(f"{prefix}_channels")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "📝 Введите username канала (без @):", kb)
    await state.set_state(AdminState.waiting_channel_username)
    await callback.answer()

@dp.callback_query(lambda c: c.data in ["admin_earn_remove", "admin_extra_remove"])
@admin_only
async def admin_sponsor_remove_list(callback: CallbackQuery):
    ch_type = "earn" if "earn" in callback.data else "extra"
    table = "sponsor_earn_channels" if ch_type == "earn" else "sponsor_extra_channels"
    prefix = f"admin_{ch_type}"
    cursor.execute(f"SELECT id, channel_username, channel_name FROM {table} WHERE is_active = 1")
    channels = cursor.fetchall()
    if not channels:
        await callback.answer("❌ Нет каналов для удаления.", show_alert=True)
        return
    kb_rows = [[color_btn(f"🗑 {name} (@{username})", f"{prefix}_remove_{ch_id}")] for ch_id, username, name in channels]
    kb_rows.append([back_btn(f"{prefix}_channels")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "🗑 Выберите канал для удаления:", build_keyboard(*kb_rows))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_earn_remove_") or c.data.startswith("admin_extra_remove_"))
@admin_only
async def admin_sponsor_remove_confirm(callback: CallbackQuery):
    parts = callback.data.split("_remove_")
    ch_type = parts[0].replace("admin_", "")
    ch_id = int(parts[1])
    table = "sponsor_earn_channels" if ch_type == "earn" else "sponsor_extra_channels"
    cursor.execute(f"UPDATE {table} SET is_active = 0 WHERE id = ?", (ch_id,))
    conn.commit()
    backup_db()
    await callback.answer("✅ Канал удалён!", show_alert=True)
    if ch_type == "earn":
        await admin_earn_channels_list(callback)
    else:
        await admin_extra_channels_list(callback)

# --- Общие обработчики ввода username и названия канала (с проверкой админа) ---
@dp.message(AdminState.waiting_channel_username)
async def admin_channel_username_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    username = message.text.strip().replace('@', '')
    await state.update_data(channel_username=username)
    await message.answer("📝 Введите название канала:")
    await state.set_state(AdminState.waiting_channel_name)

@dp.message(AdminState.waiting_channel_name)
async def admin_channel_name_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    name = message.text.strip()
    data = await state.get_data()
    username = data['channel_username']
    ch_type = data.get('channel_type', 'required')
    table_map = {'required': 'required_channels', 'earn': 'sponsor_earn_channels', 'extra': 'sponsor_extra_channels'}
    table = table_map.get(ch_type, 'required_channels')
    cursor.execute(f"INSERT INTO {table} (channel_username, channel_name) VALUES (?, ?)", (username, name))
    conn.commit()
    backup_db()
    await message.answer(f"✅ Канал @{username} добавлен!")
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await admin_cmd(message)

# ----------  УПРАВЛЕНИЕ ПРОМОКОДАМИ  ----------
@dp.callback_query(lambda c: c.data == "admin_promocodes")
@admin_only
async def admin_promocodes_menu(callback: CallbackQuery):
    kb = build_keyboard(
        [color_btn("➕ Создать промокод", "admin_create_promo")],
        [color_btn("📋 Список промокодов", "admin_list_promo")],
        [color_btn("🗑 Удалить промокод", "admin_delete_promo")],
        [back_btn("admin_back")]
    )
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "🎟 <b>Управление промокодами</b>", kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_create_promo")
@admin_only
async def admin_create_promo_start(callback: CallbackQuery, state: FSMContext):
    kb = build_keyboard([back_btn("admin_promocodes")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "📝 Введите код промокода (латиница, цифры):", kb)
    await state.set_state(AdminState.waiting_promo_code)
    await callback.answer()

@dp.message(AdminState.waiting_promo_code)
async def admin_promo_code_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    code = message.text.strip().upper()
    await state.update_data(promo_code=code)
    await message.answer("💰 Введите бонус (количество монет):")
    await state.set_state(AdminState.waiting_promo_bonus)

@dp.message(AdminState.waiting_promo_bonus)
async def admin_promo_bonus_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        bonus = int(message.text.strip())
    except:
        await message.answer("❌ Введите число.")
        return
    await state.update_data(promo_bonus=bonus)
    await message.answer("👥 Введите лимит использований (0 = безлимит):")
    await state.set_state(AdminState.waiting_promo_uses)

@dp.message(AdminState.waiting_promo_uses)
async def admin_promo_uses_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        max_uses = int(message.text.strip())
    except:
        await message.answer("❌ Введите число.")
        return

    data = await state.get_data()
    code = data['promo_code']
    bonus = data['promo_bonus']
    try:
        cursor.execute("INSERT INTO promocodes (code, bonus, max_uses, created_by) VALUES (?, ?, ?, ?)",
                       (code, bonus, max_uses, ADMIN_ID))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Промокод {code} создан! Бонус: {bonus} монет, лимит: {max_uses if max_uses > 0 else '∞'}")
    except sqlite3.IntegrityError:
        await message.answer(f"❌ Промокод {code} уже существует.")
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await admin_cmd(message)

@dp.callback_query(lambda c: c.data == "admin_list_promo")
@admin_only
async def admin_list_promo(callback: CallbackQuery):
    cursor.execute("SELECT id, code, bonus, max_uses, used_count, is_active FROM promocodes")
    promos = cursor.fetchall()
    if promos:
        text = "📋 <b>Список промокодов:</b>\n\n"
        for pid, code, bonus, max_uses, used, is_active in promos:
            status = "✅" if is_active else "❌"
            text += f"{status} {code}: {bonus}₿ (исп. {used}/{max_uses if max_uses else '∞'})\n"
    else:
        text = "Пока нет промокодов."
    kb = build_keyboard([back_btn("admin_promocodes")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_delete_promo")
@admin_only
async def admin_delete_promo_list(callback: CallbackQuery):
    cursor.execute("SELECT id, code, bonus FROM promocodes")
    promos = cursor.fetchall()
    if not promos:
        await callback.answer("❌ Нет промокодов.", show_alert=True)
        return
    kb_rows = [
        [color_btn(f"🗑 {code} ({bonus}₿)", f"admin_delete_promo_{pid}")]
        for pid, code, bonus, *_ in promos
    ]
    kb_rows.append([back_btn("admin_promocodes")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "🗑 Выберите промокод для удаления:", build_keyboard(*kb_rows))
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_delete_promo_"))
@admin_only
async def admin_delete_promo_confirm(callback: CallbackQuery):
    promo_id = int(callback.data.replace("admin_delete_promo_", ""))
    cursor.execute("SELECT code FROM promocodes WHERE id = ?", (promo_id,))
    promo = cursor.fetchone()
    if not promo:
        await callback.answer("❌ Не найден.", show_alert=True)
        return
    code = promo[0]
    cursor.execute("UPDATE promocodes SET is_active = 0 WHERE id = ?", (promo_id,))
    conn.commit()
    backup_db()
    await callback.answer(f"✅ Промокод {code} удалён!", show_alert=True)
    await admin_promocodes_menu(callback)

# ----------  УПРАВЛЕНИЕ ПОЛЬЗОВАТЕЛЯМИ  ----------
@dp.callback_query(lambda c: c.data == "admin_users")
@admin_only
async def admin_users_menu(callback: CallbackQuery):
    kb = build_keyboard(
        [color_btn("🔍 Найти", "admin_find_user")],
        [color_btn("💰 Выдать монеты", "admin_give_coins"),
         color_btn("💸 Забрать монеты", "admin_take_coins")],
        [color_btn("💎 Выдать Elite", "admin_give_elite"),
         color_btn("💎 Забрать Elite", "admin_take_elite")],
        [color_btn("🚫 Бан", "admin_ban_user"),
         color_btn("🔓 Разбан", "admin_unban_user")],
        [back_btn("admin_back")]
    )
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "👤 <b>Управление пользователями</b>", kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data in [
    "admin_find_user","admin_give_coins","admin_take_coins",
    "admin_give_elite","admin_take_elite","admin_ban_user","admin_unban_user"
])
@admin_only
async def admin_user_action_start(callback: CallbackQuery, state: FSMContext):
    action = callback.data.replace("admin_", "")
    await state.update_data(action=action)
    kb = build_keyboard([back_btn("admin_users")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "🔍 Введите ID пользователя:", kb)
    await state.set_state(AdminState.waiting_user_id)
    await callback.answer()

@dp.message(AdminState.waiting_user_id)
async def admin_user_id_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        user_id = int(message.text.strip())
    except:
        await message.answer("❌ Введите корректный ID.")
        return
    user = get_user(user_id)
    if not user:
        await message.answer("❌ Пользователь не найден.")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        return

    await state.update_data(target_user_id=user_id)
    data = await state.get_data()
    action = data['action']

    if action == "find_user":
        text = (
            f"👤 ID: {user[0]}\n📛 @{user[1] or '—'}\n"
            f"💰 Баланс: {format_number(user[3])}₿\n"
            f"💸 Потрачено: {format_number(user[4])}₿\n"
            f"👥 Рефералов: {user[8]}\n"
            f"💎 Elite: {'✅' if is_elite_active(user_id) else '❌'}\n"
            f"🚫 Бан: {'✅' if user[12] else '❌'}"
        )
        kb = build_keyboard([back_btn("admin_users")])
        await send_message_api(message.from_user.id, text, kb)
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)

    elif action in ["give_coins","take_coins"]:
        await message.answer("💰 Введите количество монет:")
        await state.set_state(AdminState.waiting_user_amount)

    elif action == "give_elite":
        until = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute("UPDATE users SET elite_sub_until = ? WHERE user_id = ?", (until, user_id))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Elite Sub выдана пользователю {user_id} на 30 дней!")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await admin_cmd(message)

    elif action == "take_elite":
        cursor.execute("UPDATE users SET elite_sub_until = NULL WHERE user_id = ?", (user_id,))
        conn.commit()
        backup_db()
        await message.answer(f"✅ Elite Sub забрана у {user_id}")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await admin_cmd(message)

    elif action == "ban_user":
        cursor.execute("UPDATE users SET is_banned = 1 WHERE user_id = ?", (user_id,))
        conn.commit()
        backup_db()
        try:
            await bot.send_message(user_id, "🚫 Вы были заблокированы администратором.")
        except:
            pass
        await message.answer(f"✅ Пользователь {user_id} заблокирован!")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await admin_cmd(message)

    elif action == "unban_user":
        cursor.execute("UPDATE users SET is_banned = 0 WHERE user_id = ?", (user_id,))
        conn.commit()
        backup_db()
        try:
            await bot.send_message(user_id, "✅ Вы были разблокированы администратором.")
        except:
            pass
        await message.answer(f"✅ Пользователь {user_id} разблокирован!")
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await admin_cmd(message)

@dp.message(AdminState.waiting_user_amount)
async def admin_user_amount_input(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    try:
        amount = int(message.text.strip())
    except:
        await message.answer("❌ Введите число.")
        return
    data = await state.get_data()
    user_id = data['target_user_id']
    action = data['action']
    if action == "give_coins":
        update_balance(user_id, amount, "Выдано админом", "admin")
        await message.answer(f"✅ +{amount} → {user_id}")
    else:
        user = get_user(user_id)
        if user[3] < amount:
            await message.answer(f"❌ Недостаточно монет (баланс: {user[3]}).")
        else:
            update_balance(user_id, -amount, "Забрано админом", "admin")
            await message.answer(f"✅ -{amount} у {user_id}")
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await admin_cmd(message)
# ========== УПРАВЛЕНИЕ ЗАДАНИЯМИ (АДМИН) ==========
async def admin_tasks_show(message: Message):
    cursor.execute("SELECT id, creator_id, task_type, link, status, current_executors, max_executors, is_elite FROM tasks ORDER BY id DESC LIMIT 15")
    tasks = cursor.fetchall()
    if tasks:
        text = "📋 <b>Последние задания:</b>\n\n"
        kb_rows = []
        for task in tasks:
            tid, cid, ttype, link, status, cur, max_, elite = task
            mark = "👑" if elite else "📋"
            text += f"{mark} #{tid} {ttype}: {link[:25]}...\n  Статус: {status} | {cur}/{max_} | Создатель: {cid}\n\n"
            kb_rows.append([color_btn(f"⚙️ Управлять #{tid}", f"admin_task_detail_{tid}")])
        kb_rows.append([back_btn("admin_back")])
    else:
        text = "Заданий пока нет."
        kb_rows = [[back_btn("admin_back")]]
    kb = build_keyboard(*kb_rows)
    await edit_message_api(message.chat.id, message.message_id, text, kb)

@dp.callback_query(lambda c: c.data == "admin_tasks")
@admin_only
async def admin_tasks_handler(callback: CallbackQuery):
    await admin_tasks_show(callback.message)
    # callback.answer не вызываем, так как редактирование сообщения уже происходит

@dp.callback_query(lambda c: c.data.startswith("admin_task_detail_"))
@admin_only
async def admin_task_detail(callback: CallbackQuery):
    task_id = int(callback.data.replace("admin_task_detail_", ""))
    cursor.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if not task:
        await callback.answer("❌ Не найдено.", show_alert=True)
        return
    tid, cid, ttype, link, desc, reward, max_exec, cur_exec, is_elite, status, created, actual_cost = task
    mark = "👑 Elite" if is_elite else "📋 Обычное"
    text = (
        f"⚙️ <b>Задание #{tid}</b>\n"
        f"Тип: {ttype} | {mark}\n"
        f"Ссылка: {link}\n"
        f"Описание: {desc}\n"
        f"Награда: {reward}₿\n"
        f"Прогресс: {cur_exec}/{max_exec}\n"
        f"Статус: {status}\n"
        f"Создатель: {cid}\n"
    )
    kb_rows = []
    if status == 'active':
        kb_rows.append([color_btn("✅ Завершить", f"admin_task_complete_{tid}")])
        kb_rows.append([color_btn("⏸ Приостановить", f"admin_task_pause_{tid}")])
    elif status == 'paused':
        kb_rows.append([color_btn("▶️ Возобновить", f"admin_task_resume_{tid}")])
    kb_rows.append([color_btn("🗑 Удалить", f"admin_task_delete_{tid}")])
    kb_rows.append([back_btn("admin_tasks")])
    kb = build_keyboard(*kb_rows)
    await edit_message_api(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data.startswith("admin_task_complete_"))
@admin_only
async def admin_task_complete(callback: CallbackQuery):
    task_id = int(callback.data.replace("admin_task_complete_", ""))
    cursor.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
    conn.commit()
    backup_db()
    await callback.answer("✅ Завершено!", show_alert=True)
    await admin_tasks_show(callback.message)

@dp.callback_query(lambda c: c.data.startswith("admin_task_pause_"))
@admin_only
async def admin_task_pause(callback: CallbackQuery):
    task_id = int(callback.data.replace("admin_task_pause_", ""))
    cursor.execute("UPDATE tasks SET status = 'paused' WHERE id = ?", (task_id,))
    conn.commit()
    backup_db()
    await callback.answer("⏸ Приостановлено!", show_alert=True)
    await admin_tasks_show(callback.message)

@dp.callback_query(lambda c: c.data.startswith("admin_task_resume_"))
@admin_only
async def admin_task_resume(callback: CallbackQuery):
    task_id = int(callback.data.replace("admin_task_resume_", ""))
    cursor.execute("UPDATE tasks SET status = 'active' WHERE id = ?", (task_id,))
    conn.commit()
    backup_db()
    await callback.answer("▶️ Возобновлено!", show_alert=True)
    await admin_tasks_show(callback.message)

@dp.callback_query(lambda c: c.data.startswith("admin_task_delete_"))
@admin_only
async def admin_task_delete(callback: CallbackQuery):
    task_id = int(callback.data.replace("admin_task_delete_", ""))
    cursor.execute("SELECT creator_id, max_executors, current_executors, actual_cost FROM tasks WHERE id = ?", (task_id,))
    task = cursor.fetchone()
    if task:
        creator_id, max_exec, cur_exec, actual_cost = task
        unused = max_exec - cur_exec
        if unused > 0 and actual_cost:
            refund_per_place = actual_cost // max_exec
            total_refund = refund_per_place * unused
            update_balance(creator_id, total_refund, f"Возврат за удаление задания #{task_id}", "refund")
    cursor.execute("UPDATE tasks SET status = 'deleted' WHERE id = ?", (task_id,))
    conn.commit()
    backup_db()
    await callback.answer("🗑 Задание удалено!", show_alert=True)
    await admin_tasks_show(callback.message)

# ========== РАССЫЛКА ==========
@dp.callback_query(lambda c: c.data == "admin_broadcast")
@admin_only
async def admin_broadcast_menu(callback: CallbackQuery):
    kb = build_keyboard(
        [color_btn("📢 Всем пользователям", "admin_broadcast_all")],
        [back_btn("admin_back")]
    )
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "📨 <b>Рассылка</b>\n\nОтправить сообщение всем пользователям бота.", kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_broadcast_all")
@admin_only
async def admin_broadcast_all_start(callback: CallbackQuery, state: FSMContext):
    kb = build_keyboard([back_btn("admin_broadcast")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id,
                           "📝 Введите текст рассылки:", kb)
    await state.set_state(AdminState.waiting_broadcast_text)
    await callback.answer()

@dp.message(AdminState.waiting_broadcast_text)
async def admin_broadcast_send(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    if message.text in ["🔙 Главное меню", "🔙 Назад"]:
        await state.clear()
        fsm_last_activity.pop(message.from_user.id, None)
        await message.answer("🔙 Главное меню:", reply_markup=main_kb())
        return
    text = message.text
    cursor.execute("SELECT user_id FROM users WHERE is_banned = 0")
    users = cursor.fetchall()
    success = fail = 0
    await message.answer(f"⏳ Начинаю рассылку на {len(users)} пользователей...")
    for user in users:
        try:
            await bot.send_message(user[0], text)
            success += 1
            await asyncio.sleep(0.05)
        except:
            fail += 1
    await message.answer(f"✅ Рассылка завершена!\n📨 Отправлено: {success}\n❌ Не доставлено: {fail}")
    await state.clear()
    fsm_last_activity.pop(message.from_user.id, None)
    await admin_cmd(message)

# ========== НАСТРОЙКИ ==========
@dp.callback_query(lambda c: c.data == "admin_settings")
@admin_only
async def admin_settings_show(callback: CallbackQuery):
    text = (
        "💰 <b>Текущие тарифы</b>\n"
        "📱 Подписка: 21₿ (покупка) / 15₿ (награда)\n"
        "❤️ Лайк: 5₿ / 3₿\n"
        "👁 Просмотр: 3₿ / 1₿\n"
        "💎 Elite Sub: 25,000₿\n"
        "🎁 Спонсор: 3,500₿\n"
        "💸 Комиссия перевода: 2%"
    )
    kb = build_keyboard([back_btn("admin_back")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

# ========== СТАТИСТИКА (АДМИН) ==========
@dp.callback_query(lambda c: c.data == "admin_stats")
@admin_only
async def admin_stats_show_handler(callback: CallbackQuery):
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

    text = (
        "📊 <b>Полная статистика</b>\n"
        f"👥 Пользователей: {total}\n"
        f"🚫 Забанено: {banned}\n"
        f"💎 Elite Sub: {elite}\n"
        f"📋 Выполнено заданий: {format_number(tasks)}\n"
        f"💰 Заработано: {format_number(earned)}₿\n"
        f"💸 Потрачено: {format_number(spent)}₿"
    )
    kb = build_keyboard([back_btn("admin_back")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

# ========== РОЗЫГРЫШ (АДМИН) ==========
async def run_giveaway_and_notify():
    cursor.execute("SELECT user_id, referrals_weekly FROM users WHERE is_banned = 0 AND referrals_weekly > 0 ORDER BY referrals_weekly DESC LIMIT 3")
    winners = cursor.fetchall()
    if len(winners) < 3:
        return
    prizes = [10000, 5000, 3000]
    for i, (uid, refs) in enumerate(winners):
        async with db_lock:
            update_balance(uid, prizes[i], f"Розыгрыш {i+1} место", "bonus")
            cursor.execute("INSERT INTO giveaway_winners (user_id, place, reward) VALUES (?, ?, ?)", (uid, i+1, prizes[i]))
            conn.commit()
            await backup_db_async()
        try:
            user = get_user(uid)
            name = f"@{user[1]}" if user and user[1] else str(uid)
            await bot.send_message(uid, f"🎉 Поздравляем! Вы заняли {i+1} место в еженедельном розыгрыше и получаете {prizes[i]} монет!")
        except Exception:
            pass

@dp.callback_query(lambda c: c.data == "admin_giveaway")
@admin_only
async def admin_giveaway_menu(callback: CallbackQuery):
    text = (
        "🏆 <b>Управление розыгрышем</b>\n"
        "• Проводится каждый понедельник в 00:00\n"
        "• Призы: 🥇10,000 🥈5,000 🥉3,000\n"
        "• Можно запустить вручную"
    )
    kb = build_keyboard(
        [color_btn("🏆 Запустить вручную", "admin_run_giveaway")],
        [back_btn("admin_back")]
    )
    await edit_message_api(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

@dp.callback_query(lambda c: c.data == "admin_run_giveaway")
@admin_only
async def admin_run_giveaway(callback: CallbackQuery):
    await run_giveaway_and_notify()
    cursor.execute("SELECT user_id, referrals_weekly FROM users WHERE is_banned = 0 AND referrals_weekly > 0 ORDER BY referrals_weekly DESC LIMIT 3")
    winners = cursor.fetchall()
    medals = ["🥇","🥈","🥉"]
    text = "🏆 Результаты розыгрыша:\n\n" if winners else "Нет участников."
    for i, (uid, refs) in enumerate(winners):
        user = get_user(uid)
        name = f"@{user[1]}" if user and user[1] else f"ID:{uid}"
        text += f"{medals[i]} {name} — {refs} реф.\n"
    kb = build_keyboard([back_btn("admin_back")])
    await edit_message_api(callback.message.chat.id, callback.message.message_id, text, kb)
    await callback.answer()

# ========== ВЫХОД / ВОЗВРАТ ==========
@dp.callback_query(lambda c: c.data == "admin_back")
@admin_only
async def admin_back(callback: CallbackQuery):
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await admin_cmd(callback.message)
    # не вызываем callback.answer, так как admin_cmd шлёт новое сообщение

@dp.callback_query(lambda c: c.data == "admin_exit")
@admin_only
async def admin_exit(callback: CallbackQuery):
    await delete_msg_api(callback.message.chat.id, callback.message.message_id)
    await callback.message.answer("🔙 Главное меню:", reply_markup=main_kb())
    await callback.answer()
# ========== ФОНОВЫЕ ПРОЦЕССЫ ==========

async def run_giveaway_and_notify():
    """Выполняет розыгрыш и начисляет призы (используется в админке и по расписанию)"""
    cursor.execute("SELECT user_id, referrals_weekly FROM users WHERE is_banned = 0 AND referrals_weekly > 0 ORDER BY referrals_weekly DESC LIMIT 3")
    winners = cursor.fetchall()
    if len(winners) < 3:
        return
    prizes = [10000, 5000, 3000]
    for i, (uid, refs) in enumerate(winners):
        async with db_lock:
            update_balance(uid, prizes[i], f"Розыгрыш {i+1} место", "bonus")
            cursor.execute("INSERT INTO giveaway_winners (user_id, place, reward) VALUES (?, ?, ?)", (uid, i+1, prizes[i]))
            conn.commit()
            await backup_db_async()
        try:
            user = get_user(uid)
            name = f"@{user[1]}" if user and user[1] else str(uid)
            await bot.send_message(uid, f"🎉 Поздравляем! Вы заняли {i+1} место в еженедельном розыгрыше и получаете {prizes[i]} монет!")
        except Exception:
            pass

async def check_unsubscribes():
    """Проверка отписок, авто-закрытие заданий и авто-принятие Elite-заявок"""
    cycle_count = 0
    while True:
        try:
            # 1. Проверка выполнений на отписки
            cursor.execute("SELECT te.id, te.task_id, te.user_id, t.creator_id, t.link, t.reward_per_unit, t.is_elite FROM task_executions te JOIN tasks t ON te.task_id = t.id WHERE te.is_verified = 1 AND t.status = 'active'")
            executions = cursor.fetchall()

            for exec_id, task_id, user_id, creator_id, link, reward, is_elite in executions:
                # Пропускаем, если уже есть активный отложенный штраф
                cursor.execute("SELECT id FROM pending_penalties WHERE exec_id = ? AND is_active = 1", (exec_id,))
                if cursor.fetchone():
                    continue

                channel = extract_channel_from_link(link)
                if not channel:
                    continue

                try:
                    member = await bot.get_chat_member(f"@{channel}", user_id)
                    is_subscribed = member.status not in ['left', 'kicked']
                except Exception:
                    is_subscribed = False

                if not is_subscribed:
                    cursor.execute("INSERT INTO pending_penalties (user_id, task_id, exec_id, creator_id, reward, channel) VALUES (?, ?, ?, ?, ?, ?)",
                                   (user_id, task_id, exec_id, creator_id, reward, channel))
                    conn.commit()
                    await backup_db_async()

                    try:
                        await bot.send_message(user_id,
                            f"⚠️ ВНИМАНИЕ! Вы отписались от канала @{channel}!\n\n"
                            f"Вы выполнили задание и получили награду {reward} монет.\n"
                            f"Если вы НЕ подпишетесь обратно в течение 10 минут:\n"
                            f"❌ Штраф: {reward * 2} монет\n"
                            f"❌ Заказчику вернутся его монеты\n\n"
                            f"👉 Подпишитесь обратно: https://t.me/{channel}")
                    except Exception:
                        pass

                    try:
                        await bot.send_message(creator_id,
                            f"⚠️ Пользователь @{user_id} отписался от вашего канала @{channel}!\n\n"
                            f"📋 Задание #{task_id}\n"
                            f"⏳ У него есть 10 минут, чтобы подписаться обратно.")
                    except Exception:
                        pass

            # 2. Проверка отложенных штрафов
            cursor.execute("SELECT id, user_id, task_id, exec_id, creator_id, reward, channel, start_time FROM pending_penalties WHERE is_active = 1")
            pending = cursor.fetchall()

            for pen_id, user_id, task_id, exec_id, creator_id, reward, channel, start_time in pending:
                start = datetime.strptime(start_time, "%Y-%m-%d %H:%M:%S")
                if (datetime.now() - start).total_seconds() >= 600:
                    try:
                        member = await bot.get_chat_member(f"@{channel}", user_id)
                        is_subscribed = member.status not in ['left', 'kicked']
                    except Exception:
                        is_subscribed = False

                    if not is_subscribed:
                        penalty = reward * 2
                        async with db_lock:
                            update_balance(user_id, -penalty, f"Штраф за отписку от {channel}", "penalty")
                            update_balance(creator_id, reward, f"Возврат за отписку пользователя {user_id}", "refund")
                            cursor.execute("INSERT INTO task_penalties (user_id, task_id, amount, reason) VALUES (?, ?, ?, ?)",
                                           (user_id, task_id, penalty, f"Отписка от {channel}"))
                            cursor.execute("UPDATE task_executions SET is_penalized = 1 WHERE id = ?", (exec_id,))
                            conn.commit()
                            await backup_db_async()
                        try:
                            await bot.send_message(user_id,
                                f"❌ ШТРАФ!\n\n"
                                f"Вы не подписались обратно на канал @{channel} в течение 10 минут.\n"
                                f"💰 Штраф: -{penalty} монет\n"
                                f"📋 Задание #{task_id}")
                        except Exception:
                            pass
                        try:
                            await bot.send_message(creator_id,
                                f"✅ ВОЗВРАТ МОНЕТ!\n\n"
                                f"Пользователь @{user_id} не подписался обратно на канал @{channel}.\n"
                                f"💰 Вам возвращено: +{reward} монет\n"
                                f"📋 Задание #{task_id}")
                        except Exception:
                            pass
                    else:
                        try:
                            await bot.send_message(user_id, f"✅ Вы подписались обратно на канал @{channel}! Штрафа нет.")
                        except Exception:
                            pass

                    cursor.execute("UPDATE pending_penalties SET is_active = 0 WHERE id = ?", (pen_id,))
                    conn.commit()
                    await backup_db_async()

            # 3. Авто-закрытие просроченных заданий
            cursor.execute("SELECT id, is_elite, created_at FROM tasks WHERE status = 'active'")
            tasks = cursor.fetchall()
            for task_id, is_elite, created_at in tasks:
                created_time = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
                days_passed = (datetime.now() - created_time).days
                if (is_elite and days_passed >= 365) or (not is_elite and days_passed >= 5):
                    cursor.execute("UPDATE tasks SET status = 'completed' WHERE id = ?", (task_id,))
                    conn.commit()
                    await backup_db_async()

            # 4. Авто-принятие Elite-заявок (через 2 дня, только если есть скриншот)
            cursor.execute("SELECT es.id, es.task_id, es.user_id, t.reward_per_unit FROM elite_submissions es JOIN tasks t ON es.task_id = t.id WHERE es.status = 'pending' AND es.screenshot_file_id IS NOT NULL AND datetime(es.submitted_at) < datetime('now', '-2 days')")
            auto_approve = cursor.fetchall()
            for sub_id, task_id, user_id, reward in auto_approve:
                if is_elite_active(user_id):
                    reward = int(reward * 1.16)
                commission = math.ceil(reward * 0.1)
                final_reward = reward - commission
                async with db_lock:
                    update_balance(user_id, final_reward, f"Elite-задание #{task_id} авто-принято (2 дня)", "earn")
                    cursor.execute("UPDATE elite_submissions SET status = 'auto_approved' WHERE id = ?", (sub_id,))
                    conn.commit()
                    await backup_db_async()
                try:
                    await bot.send_message(user_id, f"✅ Задание #{task_id} автоматически принято! Награда: {final_reward} монет.")
                except Exception:
                    pass

            await asyncio.sleep(30)
            cycle_count += 1
            if cycle_count >= 100:
                gc.collect()
                cycle_count = 0

        except Exception as e:
            logger.error(f"Ошибка в check_unsubscribes: {e}")
            gc.collect()
            await asyncio.sleep(60)

async def reset_weekly_stats():
    """Сброс недельной статистики и авто-розыгрыш каждый понедельник в 00:00"""
    while True:
        now = datetime.now()
        if now.weekday() == 0 and now.hour == 0 and now.minute == 0:
            cursor.execute("SELECT last_reset_date FROM weekly_reset WHERE id = 1")
            last_reset = cursor.fetchone()[0]
            today_str = now.strftime("%Y-%m-%d")
            if last_reset == today_str:
                await asyncio.sleep(60)
                continue

            await run_giveaway_and_notify()

            async with db_lock:
                cursor.execute("UPDATE users SET referrals_weekly = 0, spent_weekly = 0")
                cursor.execute("UPDATE weekly_reset SET last_reset_date = ? WHERE id = 1", (today_str,))
                conn.commit()
                await backup_db_async()

            logger.info("✅ Еженедельная статистика сброшена")
            await asyncio.sleep(60)
        else:
            await asyncio.sleep(60)

async def check_fsm_timeouts():
    """Сброс FSM-состояний при неактивности более 10 минут"""
    while True:
        now = datetime.now()
        to_clear = [uid for uid, t in list(fsm_last_activity.items()) if (now - t).total_seconds() > 600]
        for uid in to_clear:
            fsm_last_activity.pop(uid, None)
            try:
                state = FSMContext(dp.storage, StorageKey(bot.id, uid, uid))
                await state.clear()
                await bot.send_message(uid, "⏰ Время ожидания истекло. Действие отменено.", reply_markup=main_kb())
            except Exception:
                pass
        await asyncio.sleep(30)

# ========== ОБРАБОТЧИК ВСЕХ ОСТАЛЬНЫХ СООБЩЕНИЙ ==========
@dp.message()
async def handle_any_message(message: Message, state: FSMContext):
    if await state.get_state():
        return

    user = get_user(message.from_user.id)

    if not user:
        create_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
        await message.answer("👋 Привет! Ты автоматически зарегистрирован.\nНапиши /start, чтобы увидеть главное меню.", reply_markup=main_kb())
    else:
        if user[12] == 1:
            await message.answer("🚫 Вы забанены.")
            return
        await message.answer("❓ Используй кнопки меню или напиши /start", reply_markup=main_kb())

# ========== ЗАПУСК ==========
async def main():
    await bot.delete_webhook(drop_pending_updates=True)

    asyncio.create_task(check_unsubscribes())
    asyncio.create_task(reset_weekly_stats())
    asyncio.create_task(check_fsm_timeouts())

    logger.info("✅ Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⛔ Бот остановлен")
    except Exception as e:
        logger.error(f"❌ Критическая ошибка: {e}")

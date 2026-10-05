"""
TirfMarket Telegram Bot - Layer 20 (Channel Announcer & Review Approval Engine)
"""

import asyncio
import json
import logging
import os
import sqlite3
import uuid
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ContentType
from aiogram.filters import CommandStart, Command, CommandObject, BaseFilter, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup, default_state
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
    Message,
    CallbackQuery,
    BotCommand,
    BotCommandScopeChat,
)
from aiogram.exceptions import TelegramAPIError

# 1. Environment & Logging Setup
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_admin_id = os.getenv("ADMIN_ID", "")
ADMIN_ID = int(raw_admin_id.strip()) if raw_admin_id.strip().isdigit() else None

# New Environment Variable for the Public Channel
CHANNEL_ID = "-1004375364133"  # e.g., "@TirfMarketAAU" or "-100123456789"
BOT_USERNAME = ""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tirfmarket-bot")

DB_FILE = "tirfmarket.db"


# Multiple Admin Support
# We can load admins from ADMIN_ID in .env (comma-separated if multiple, e.g. ADMIN_ID=123,456) or an admin table.
def get_admin_ids() -> set[int]:
    raw = os.getenv("ADMIN_ID", "")
    admins = set()
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit():
            admins.add(int(part))
    
    # Also fetch any dynamically added admins from the database if table exists
    try:
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT telegram_id FROM admins")
            for row in cursor.fetchall():
                admins.add(int(row[0]))
    except Exception:
        pass
        
    return admins

class IsAdmin(BaseFilter):
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        admin_set = get_admin_ids()
        if not admin_set:
            return False
        user = event.from_user
        return bool(user and user.id in admin_set)

CAMPUS_ZONES = {
    "4_kilo": "4 Kilo Campus",
    "5_kilo": "5 Kilo Campus",
    "6_kilo": "6 Kilo Campus",
}

CAMPUS_SHORT_NAMES = {
    "4_kilo": "4 Kilo",
    "5_kilo": "5 Kilo",
    "6_kilo": "6 Kilo",
}

class NewDealStates(StatesGroup):
    waiting_for_restaurant = State()
    waiting_for_photo = State()
    waiting_for_price = State()
    waiting_for_stock = State()
    waiting_for_valid_until = State()
    waiting_for_map_link = State()
    waiting_for_zone = State()

class ReopenStates(StatesGroup):
    waiting_for_stock = State()

class ShareStates(StatesGroup):
    waiting_for_feedback = State()

class RatingStates(StatesGroup):
    waiting_for_deal_rating = State()
    waiting_for_product_rating = State()

def init_db():
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                zone TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS active_deals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT UNIQUE NOT NULL,
                restaurant_name TEXT NOT NULL,
                photo_file_id TEXT NOT NULL,
                price INTEGER NOT NULL,
                initial_stock INTEGER NOT NULL,
                remaining_stock INTEGER NOT NULL,
                zone TEXT NOT NULL,
                zones TEXT DEFAULT '',
                map_link TEXT DEFAULT '',
                valid_until TEXT DEFAULT '9:30 PM Tonight (3:30 ከሰዓት በኋላ)',
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cursor.execute("PRAGMA table_info(active_deals)")
        existing_cols = [col[1] for col in cursor.fetchall()]
        if "zones" not in existing_cols:
            cursor.execute("ALTER TABLE active_deals ADD COLUMN zones TEXT DEFAULT ''")
        if "map_link" not in existing_cols:
            cursor.execute("ALTER TABLE active_deals ADD COLUMN map_link TEXT DEFAULT ''")
        if "valid_until" not in existing_cols:
            cursor.execute("ALTER TABLE active_deals ADD COLUMN valid_until TEXT DEFAULT '9:30 PM Tonight (3:30 ከሰዓት በኋላ)'")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT NOT NULL,
                telegram_id INTEGER NOT NULL,
                voucher_code TEXT NOT NULL,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(deal_id) REFERENCES active_deals(deal_id),
                UNIQUE(deal_id, telegram_id)
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ratings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT NOT NULL,
                telegram_id INTEGER NOT NULL,
                deal_rating INTEGER NOT NULL,
                product_rating INTEGER NOT NULL,
                rated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(deal_id, telegram_id)
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS restaurant_scores (
                restaurant_name TEXT PRIMARY KEY,
                total_deal_score REAL DEFAULT 0,
                total_product_score REAL DEFAULT 0,
                rating_count INTEGER DEFAULT 0,
                avg_score REAL DEFAULT 0
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                telegram_id INTEGER PRIMARY KEY,
                added_by INTEGER,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS pending_reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                user_handle TEXT,
                deal_name TEXT DEFAULT 'TirfMarket Deal',
                media_type TEXT,
                file_id TEXT,
                text_content TEXT,
                status TEXT DEFAULT 'pending'
            )
        """)

def save_user_zone(telegram_id: int, username: str | None, full_name: str | None, zone: str):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO users (telegram_id, username, full_name, zone, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                zone = excluded.zone,
                updated_at = CURRENT_TIMESTAMP
            """, (telegram_id, username, full_name, zone))
        
        cursor.execute("PRAGMA table_info(active_deals)")
        existing_deal_cols = [col[1] for col in cursor.fetchall()]
        if "valid_until" not in existing_deal_cols:
            cursor.execute("ALTER TABLE active_deals ADD COLUMN valid_until TEXT DEFAULT '9:30 PM Tonight (3:30 ከሰዓት በኋላ)'")

        conn.commit()

def get_user(telegram_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone()

def get_users_by_zones(target_zones: list[str]):
    if not target_zones: return []
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in target_zones)
        cursor.execute(f"SELECT telegram_id, full_name, username, zone FROM users WHERE zone IN ({placeholders})", target_zones)
        return cursor.fetchall()

def save_active_deal(deal_id: str, restaurant_name: str, photo_file_id: str, price: int, stock: int, target_zones: list[str], map_link: str, valid_until: str):
    zones_joined = ", ".join(target_zones)
    primary_zone = target_zones[0] if target_zones else "4 Kilo Campus"
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO active_deals (deal_id, restaurant_name, photo_file_id, price, initial_stock, remaining_stock, zone, zones, map_link, valid_until, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """, (deal_id, restaurant_name, photo_file_id, price, stock, stock, primary_zone, zones_joined, map_link, valid_until))
        conn.commit()

def get_all_active_deals():
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_deals WHERE is_active = 1 ORDER BY id DESC")
        return cursor.fetchall()

def get_recent_closed_deals(limit=10):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_deals WHERE is_active = 0 ORDER BY id DESC LIMIT ?", (limit,))
        return cursor.fetchall()

def get_recent_deals_for_zone(zone: str, limit: int = 5):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM active_deals 
            WHERE (zones LIKE ? OR zone = ? OR zones = '')
            ORDER BY id DESC LIMIT ?
            """, (f"%{zone}%", zone, limit))
        return cursor.fetchall()

def get_deal_by_id(deal_id: str):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_deals WHERE deal_id = ?", (deal_id,))
        return cursor.fetchone()

def process_claim_transaction(deal_id: str, telegram_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT voucher_code FROM claims WHERE deal_id = ? AND telegram_id = ?", (deal_id, telegram_id))
        existing = cursor.fetchone()
        if existing: return {"status": "already_claimed", "voucher": existing["voucher_code"]}

        cursor.execute("UPDATE active_deals SET remaining_stock = remaining_stock - 1 WHERE deal_id = ? AND is_active = 1 AND remaining_stock > 0", (deal_id,))
        if cursor.rowcount == 0:
            cursor.execute("SELECT remaining_stock, is_active FROM active_deals WHERE deal_id = ?", (deal_id,))
            deal = cursor.fetchone()
            if not deal or deal["is_active"] != 1: return {"status": "inactive"}
            return {"status": "sold_out"}

        voucher_code = "SHOW AAU ID"
        cursor.execute("INSERT INTO claims (deal_id, telegram_id, voucher_code) VALUES (?, ?, ?)", (deal_id, telegram_id, voucher_code))
        
        cursor.execute("SELECT remaining_stock FROM active_deals WHERE deal_id = ?", (deal_id,))
        new_stock = cursor.fetchone()["remaining_stock"]
        
        if new_stock == 0:
            cursor.execute("UPDATE active_deals SET is_active = 0 WHERE deal_id = ?", (deal_id,))

        conn.commit()
        return {"status": "success", "new_stock": new_stock, "voucher": voucher_code}


def save_ratings(deal_id: str, telegram_id: int, deal_rating: int, product_rating: int):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Save or update individual user rating
        cursor.execute("""
            INSERT INTO ratings (deal_id, telegram_id, deal_rating, product_rating)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(deal_id, telegram_id) DO UPDATE SET
                deal_rating = excluded.deal_rating,
                product_rating = excluded.product_rating,
                rated_at = CURRENT_TIMESTAMP
        """, (deal_id, telegram_id, deal_rating, product_rating))
        
        deal = get_deal_by_id(deal_id)
        if deal:
            rest_name = deal["restaurant_name"]
            comb_score = (deal_rating + product_rating) / 2.0
            
            cursor.execute("""
                INSERT INTO restaurant_scores (restaurant_name, total_deal_score, total_product_score, rating_count, avg_score)
                VALUES (?, ?, ?, 1, ?)
                ON CONFLICT(restaurant_name) DO UPDATE SET
                    total_deal_score = total_deal_score + ?,
                    total_product_score = total_product_score + ?,
                    rating_count = rating_count + 1,
                    avg_score = (total_deal_score + total_product_score) / (2.0 * (rating_count + 1))
            """, (rest_name, deal_rating, product_rating, comb_score, deal_rating, product_rating))
        conn.commit()

def get_leaderboard_data(limit=5):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM restaurant_scores ORDER BY avg_score DESC LIMIT ?", (limit,))
        return cursor.fetchall()

def return_claim_transaction(deal_id: str, telegram_id: int):
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM claims WHERE deal_id = ? AND telegram_id = ?", (deal_id, telegram_id))
        if cursor.rowcount == 0:
            return False 
        
        cursor.execute("""
            UPDATE active_deals 
            SET remaining_stock = remaining_stock + 1, is_active = 1 
            WHERE deal_id = ?
        """, (deal_id,))
        conn.commit()
        return True



def get_student_reply_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📡 Active Radar"), KeyboardButton(text="⭐ Rate Deals")],
            [KeyboardButton(text="📸 Share Review"), KeyboardButton(text="🏆 Leaderboard")],
            [KeyboardButton(text="📍 Change Campus Zone")]
        ],
        resize_keyboard=True,
        is_persistent=True
    )

def get_campus_selection_keyboard() -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton(text="[ 4 Kilo Campus ]", callback_data="zone:4_kilo")],
        [InlineKeyboardButton(text="[ 5 Kilo Campus ]", callback_data="zone:5_kilo")],
        [InlineKeyboardButton(text="[ 6 Kilo Campus ]", callback_data="zone:6_kilo")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_fsm_multi_zone_keyboard(selected_keys: list[str] | None = None) -> InlineKeyboardMarkup:
    selected_set = set(selected_keys or [])
    buttons = []
    for key in ["4_kilo", "5_kilo", "6_kilo"]:
        short_name = CAMPUS_SHORT_NAMES[key]
        label = f"[ ✅ {short_name} ]" if key in selected_set else f"[ {short_name} ]"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"fsm_toggle_zone:{key}")])
    buttons.append([InlineKeyboardButton(text="[ 🚀 Confirm & Broadcast ]", callback_data="fsm_confirm_broadcast")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_claim_deal_keyboard(deal_id: str, price: int, restaurant_name: str = "Angla Burger", zone: str = "4 Kilo Branch", map_link: str = "") -> InlineKeyboardMarkup:
    inline_keyboard = [[InlineKeyboardButton(text=f"⚡ 1-Tap Claim Voucher ({price} ETB)", callback_data=f"claim:{deal_id}")]]
    if map_link:
        inline_keyboard.append([InlineKeyboardButton(text="🗺️ View on Map", url=map_link)])
    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)

def get_voucher_action_keyboard(deal_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Accept & Redeem", callback_data=f"accept_deal:{deal_id}")],
        [InlineKeyboardButton(text="❌ Cancel & Return Deal", callback_data=f"return_deal:{deal_id}")]
    ])

def build_deal_caption(restaurant_name: str, zones_str: str, stock: int, price: int) -> str:
    stock_line = "🔴 SOLD OUT" if stock <= 0 else f"⚠️ Only {stock} available!"
    return f"🚨 FLASH DEAL: {restaurant_name}\n📍 Zones: {zones_str}\n{stock_line}\n💵 Price: {price} ETB"

dp = Dispatcher(storage=MemoryStorage())

@dp.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()
    if command.args and command.args.startswith("claim_"):
        deal_id = command.args[len("claim_"):]
        student_id = message.from_user.id
        result = process_claim_transaction(deal_id, student_id)
        if result["status"] == "already_claimed":
            await message.answer("⚠️ <b>You already locked this deal!</b>", parse_mode="HTML")
            return
        elif result["status"] == "sold_out":
            await message.answer("❌ <b>Sorry, this flash deal is completely sold out!</b>", parse_mode="HTML")
            return
        elif result["status"] == "inactive":
            await message.answer("This flash deal is no longer active.")
            return

        deal = get_deal_by_id(deal_id)
        restaurant = deal["restaurant_name"] if deal else "Restaurant"
        price = deal["price"] if deal else 360
        zones_display = (deal["zones"] if ("zones" in deal.keys() and deal["zones"]) else deal["zone"]) if deal else "AAU Campus"
        map_link_str = f"🗺️ <b>Map:</b> {deal['map_link']}\n" if deal and ("map_link" in deal.keys() and deal["map_link"]) else ""

        valid_until_str = deal["valid_until"] if deal and "valid_until" in deal.keys() and deal["valid_until"] else "9:30 PM Tonight (3:30 ከሰዓት በኋላ)"
        voucher_msg = (
            "✅ <b>DEAL LOCKED & CONFIRMED!</b>\n\n"
            "🎟️ <b>ACTION VOUCHER PASS:</b>\n"
            "👉 <code>[ SHOW AAU ID ]</code> 👈\n\n"
            f"🍔 <b>Deal:</b> 1x {restaurant} Flash Special\n"
            f"💵 <b>Price:</b> {price} ETB (Pay at counter)\n"
            f"📍 <b>Location:</b> {zones_display}\n"
            f"{map_link_str}"
            f"⏰ <b>Valid Until:</b> {valid_until_str}\n\n"
            "💡 <b>Instructions:</b>\n"
            f"Show this message and your physical AAU Student ID to the cashier."
        )
        await message.answer(voucher_msg, parse_mode="HTML", reply_markup=get_voucher_action_keyboard(deal_id))
        return

    welcome_text = "Welcome to TirfMarket! 🍔\nWe surface exclusive student flash deals from restaurants around campus.\n\nWhich campus are you near right now?"
    await message.answer(text=welcome_text, reply_markup=get_campus_selection_keyboard())

@dp.callback_query(F.data.startswith("zone:"))
async def handle_zone_selection(callback: CallbackQuery):
    zone_key = callback.data.split("zone:")[1]
    selected_zone = CAMPUS_ZONES.get(zone_key, "Unknown Campus")
    user = callback.from_user
    save_user_zone(telegram_id=user.id, username=user.username, full_name=user.full_name, zone=selected_zone)
    confirmation_text = f"✅ Zone set to {selected_zone}! Radar active. Use the menu buttons below to browse deals, rate, or share."
    if callback.message:
        await callback.message.edit_text(text=confirmation_text, reply_markup=None)
        # Send a prompt with the persistent reply keyboard
        await callback.message.answer("👇 <b>TirfMarket Quick Menu Activated</b>", parse_mode="HTML", reply_markup=get_student_reply_keyboard())
    else:
        await callback.answer(confirmation_text, show_alert=True)
    await callback.answer()


@dp.message(F.text == "📡 Active Radar")
async def handle_reply_radar(message: Message):
    # Simulate /radar command
    await handle_radar(message)

@dp.message(F.text == "⭐ Rate Deals")
async def handle_reply_rate(message: Message, state: FSMContext):
    await handle_rate_command(message, state)

@dp.message(F.text == "📸 Share Review")
async def handle_reply_share(message: Message, state: FSMContext):
    await handle_share_command(message, state)

@dp.message(F.text == "🏆 Leaderboard")
async def handle_reply_leaderboard(message: Message):
    await handle_leaderboard(message)

@dp.message(F.text == "📍 Change Campus Zone")
async def handle_reply_zone(message: Message, state: FSMContext):
    await state.clear()
    welcome_text = "Select your campus zone below to update your radar:"
    await message.answer(text=welcome_text, reply_markup=get_campus_selection_keyboard())

@dp.message(Command("radar"))
@dp.message(Command("status"))
async def handle_radar(message: Message):
    user_record = get_user(message.from_user.id)
    if not user_record or not user_record["zone"]:
        await message.answer("You haven't set your campus zone yet!\nTap /start to activate your discount radar.")
        return
    student_zone = user_record["zone"]
    
    recent_deals = get_recent_deals_for_zone(student_zone, limit=5)
    
    if not recent_deals:
        await message.answer("📡 Radar Status: No active or recent drops in your zone right now. We'll ping you when the next one hits!")
        return

    text_lines = [f"📡 <b>TirfMarket Radar: {student_zone}</b>\n"]
    inline_keyboard = []
    
    for idx, deal in enumerate(recent_deals, 1):
        name = deal["restaurant_name"]
        price = deal["price"]
        stock = deal["remaining_stock"]
        is_active = deal["is_active"]
        
        status_icon = "🔴 SOLD OUT" if stock <= 0 or is_active == 0 else f"🟢 {stock} Left"
        
        text_lines.append(f"<b>{idx}. {name}</b> - {price} ETB")
        text_lines.append(f"└ Status: {status_icon}\n")
        
        if stock > 0 and is_active == 1:
            inline_keyboard.append([InlineKeyboardButton(text=f"⚡ Claim: {name}", callback_data=f"claim:{deal['deal_id']}")])
            if ("map_link" in deal.keys() and deal["map_link"]):
                inline_keyboard.append([InlineKeyboardButton(text=f"🗺️ Map: {name}", url=deal["map_link"])])

    text_lines.append("<i>Tap an active deal below to claim it instantly!</i>")
    
    # Add navigation buttons for leaderboard and sharing feedback
    inline_keyboard.append([
        InlineKeyboardButton(text="🏆 Leaderboard", callback_data="nav:leaderboard"),
        InlineKeyboardButton(text="📸 Share Review", callback_data="nav:share")
    ])
    
    await message.answer("\n".join(text_lines), parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=inline_keyboard))

@dp.callback_query(F.data.startswith("nav:"))
async def handle_radar_navigation(callback: CallbackQuery, state: FSMContext):
    nav_action = callback.data.split("nav:")[1]
    if nav_action == "leaderboard":
        leaders = get_leaderboard_data(limit=5)
        if not leaders:
            await callback.answer("No restaurant ratings recorded yet!", show_alert=True)
            return
        text_lines = ["🏆 <b>TirfMarket Restaurant Leaderboard</b>\n"]
        for idx, r in enumerate(leaders, 1):
            name = r["restaurant_name"]
            avg = round(r["avg_score"], 1)
            count = r["rating_count"]
            medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
            text_lines.append(f"{medal} <b>{name}</b> - ⭐ {avg}/5.0 <i>({count} ratings)</i>")
        text_lines.append("\n<i>Rankings are updated in real-time!</i>")
        await callback.message.answer("\n".join(text_lines), parse_mode="HTML")
        await callback.answer()
    elif nav_action == "share":
        await callback.message.answer("📸 Tap /share to send your food photo and review!")
        await callback.answer()

@dp.message(Command("myid"))
@dp.message(Command("id"))
async def handle_myid(message: Message):
    user_id = message.from_user.id
    is_admin = (ADMIN_ID is not None and user_id == ADMIN_ID)
    if is_admin:
        await message.answer(
            f"Your Telegram ID: <code>{user_id}</code> 👑 (Verified Admin)\n\n"
            f"Configure in your <code>.env</code> file:\n"
            f"<code>ADMIN_ID={user_id}</code>\n"
            f"<code>CHANNEL_ID=@YourChannel</code>",
            parse_mode="HTML"
        )
    else:
        await message.answer(f"Your Telegram ID: <code>{user_id}</code> 🎓 (Student)", parse_mode="HTML")

@dp.message(Command("cancel"))
async def handle_cancel_fsm(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("✅ Action canceled. You are back to the main menu. Type /radar to scan for deals, or /start to change your zone.")


@dp.message(Command("addadmin"), IsAdmin())
async def handle_add_admin(message: Message, command: CommandObject):
    if not command.args or not command.args.strip().isdigit():
        await message.answer("⚠️ Please provide a valid Telegram ID to add as admin.\nExample: <code>/addadmin 123456789</code>", parse_mode="HTML")
        return
        
    new_admin_id = int(command.args.strip())
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("INSERT OR IGNORE INTO admins (telegram_id, added_by) VALUES (?, ?)", (new_admin_id, message.from_user.id))
        conn.commit()
        
    await message.answer(f"👑 Successfully added <code>{new_admin_id}</code> as a TirfMarket Admin!", parse_mode="HTML")

@dp.message(Command("removeadmin"), IsAdmin())
async def handle_remove_admin(message: Message, command: CommandObject):
    if not command.args or not command.args.strip().isdigit():
        await message.answer("⚠️ Please provide a valid Telegram ID to remove.\nExample: <code>/removeadmin 123456789</code>", parse_mode="HTML")
        return
        
    target_id = int(command.args.strip())
    raw_env = os.getenv("ADMIN_ID", "")
    if str(target_id) in [p.strip() for p in raw_env.split(",")]:
        await message.answer("⚠️ Cannot remove the primary root admin configured in <code>.env</code>.", parse_mode="HTML")
        return
        
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM admins WHERE telegram_id = ?", (target_id,))
        conn.commit()
        
    await message.answer(f"🛑 Removed <code>{target_id}</code> from admin privileges.", parse_mode="HTML")


@dp.message(Command("deletedeal"), IsAdmin())
@dp.message(Command("delete_deal"), IsAdmin())
async def handle_delete_deal_menu(message: Message):
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT deal_id, restaurant_name, price, is_active FROM active_deals ORDER BY id DESC LIMIT 15")
        deals = cursor.fetchall()
        
    if not deals:
        await message.answer("ℹ️ No deals found in the database to delete.")
        return
        
    keyboard = []
    for d in deals:
        status_txt = "🟢 Active" if d["is_active"] == 1 else "🔴 Closed"
        keyboard.append([InlineKeyboardButton(text=f"🗑️ Delete: {d['restaurant_name']} ({d['price']} ETB) [{status_txt}]", callback_data=f"admin_delete:{d['deal_id']}")])
        
    await message.answer("Select a deal to permanently delete from the database:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("admin_delete:"), IsAdmin())
async def handle_admin_delete_action(callback: CallbackQuery):
    deal_id = callback.data.split("admin_delete:")[1]
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        # Delete related claims and ratings first to maintain integrity
        cursor.execute("DELETE FROM claims WHERE deal_id = ?", (deal_id,))
        cursor.execute("DELETE FROM ratings WHERE deal_id = ?", (deal_id,))
        cursor.execute("DELETE FROM active_deals WHERE deal_id = ?", (deal_id,))
        conn.commit()
        
    await callback.message.edit_text("🗑️ Deal and its associated claim/rating records have been permanently deleted from the database.", reply_markup=None)
    await callback.answer("Deal deleted.")

@dp.message(Command("close_deal"), IsAdmin())
@dp.message(Command("closedeal"), IsAdmin())
async def handle_close_deal_menu(message: Message):
    deals = get_all_active_deals()
    if not deals:
        await message.answer("ℹ️ No active deals are currently open.")
        return
    
    keyboard = []
    for d in deals:
        keyboard.append([InlineKeyboardButton(text=f"🛑 Close: {d['restaurant_name']}", callback_data=f"admin_close:{d['deal_id']}")])
    
    await message.answer("Select an active deal to close:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("admin_close:"), IsAdmin())
async def handle_admin_close_action(callback: CallbackQuery):
    deal_id = callback.data.split("admin_close:")[1]
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE active_deals SET is_active = 0, remaining_stock = 0 WHERE deal_id = ?", (deal_id,))
        conn.commit()
    await callback.message.edit_text("🛑 Deal has been closed and removed from the active radar.", reply_markup=None)
    await callback.answer("Deal closed.")

@dp.message(Command("reopen"), IsAdmin())
async def handle_reopen_menu(message: Message):
    deals = get_recent_closed_deals(limit=10)
    if not deals:
        await message.answer("ℹ️ No closed deals found to reopen.")
        return
    
    keyboard = []
    for d in deals:
        keyboard.append([InlineKeyboardButton(text=f"♻️ Reopen: {d['restaurant_name']} ({d['price']} ETB)", callback_data=f"admin_reopen:{d['deal_id']}")])
        
    await message.answer("Select a previously closed deal to reopen:", reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard))

@dp.callback_query(F.data.startswith("admin_reopen:"), IsAdmin())
async def handle_admin_reopen_action(callback: CallbackQuery, state: FSMContext):
    deal_id = callback.data.split("admin_reopen:")[1]
    deal = get_deal_by_id(deal_id)
    if not deal:
        await callback.answer("Deal data not found.", show_alert=True)
        return
        
    await state.update_data(reopen_deal_id=deal_id)
    await state.set_state(ReopenStates.waiting_for_stock)
    await callback.message.edit_text(f"♻️ Reopening **{deal['restaurant_name']}**.\n\n📦 How many new deals are available for this drop?", parse_mode="Markdown")

@dp.message(ReopenStates.waiting_for_stock, F.text)
async def process_reopen_stock(message: Message, state: FSMContext, bot: Bot):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("⚠️ Please enter a valid stock quantity (e.g. 10):")
        return
        
    new_stock = int(text)
    data = await state.get_data()
    old_deal_id = data.get("reopen_deal_id")
    
    old_deal = get_deal_by_id(old_deal_id)
    if not old_deal:
        await state.clear()
        return
        
    await state.clear()
    
    new_deal_id = f"deal_{uuid.uuid4().hex[:8]}"
    restaurant_name = old_deal["restaurant_name"]
    photo_file_id = old_deal["photo_file_id"]
    price = old_deal["price"]
    map_link = old_deal["map_link"] if "map_link" in old_deal.keys() else ""
    valid_until = old_deal["valid_until"] if "valid_until" in old_deal.keys() and old_deal["valid_until"] else "9:30 PM Tonight (3:30 ከሰዓት በኋላ)"
    zones_str = old_deal["zones"]
    
    target_zone_names = [z.strip() for z in zones_str.split(",")]
    save_active_deal(new_deal_id, restaurant_name, photo_file_id, price, new_stock, target_zone_names, map_link, valid_until)
    await message.answer("Saving & broadcasting reopened deal...", show_alert=False)

    caption = build_deal_caption(restaurant_name, zones_str, new_stock, price)
    claim_keyboard = get_claim_deal_keyboard(new_deal_id, price, restaurant_name, zones_str, map_link)
    subscribers = get_users_by_zones(target_zone_names)
    
    sent_count = 0
    for student in subscribers:
        try:
            await bot.send_photo(chat_id=student["telegram_id"], photo=photo_file_id, caption=caption, reply_markup=claim_keyboard)
            sent_count += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError:
            pass

    await message.answer(f"✅ Reopen Broadcast Complete to {sent_count} students!")
    
    # Layer 20: Auto Announce to Channel
    if CHANNEL_ID:
        announcement = (
            f"🚨 <b>RESTOCK ALERT!</b>\n\n"
            f"A fresh drop for <b>{restaurant_name}</b> has just hit the radar!\n\n"
            f"👉 Head over to @{BOT_USERNAME} and type /radar to claim yours before it sells out again!"
        )
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=announcement, parse_mode="HTML")
        except TelegramAPIError as e:
            logger.warning(f"Could not announce to channel: {e}")

@dp.message(Command("newdeal"), IsAdmin())
async def start_new_deal(message: Message, state: FSMContext):
    await state.set_state(NewDealStates.waiting_for_restaurant)
    await message.answer("🍔 Let's drop a new deal. What is the name of the restaurant?")

@dp.message(NewDealStates.waiting_for_restaurant, F.text)
async def process_restaurant_name(message: Message, state: FSMContext):
    restaurant = message.text.strip()
    await state.update_data(restaurant_name=restaurant)
    await state.set_state(NewDealStates.waiting_for_photo)
    await message.answer("📸 Send me the picture or poster for this deal.")

@dp.message(NewDealStates.waiting_for_photo, F.photo)
async def process_deal_photo(message: Message, state: FSMContext):
    await state.update_data(photo_file_id=message.photo[-1].file_id)
    await state.set_state(NewDealStates.waiting_for_price)
    await message.answer("💵 What is the discounted price in ETB?")

@dp.message(NewDealStates.waiting_for_price, F.text)
async def process_deal_price(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("⚠️ Please enter a valid number for the price in ETB (e.g. 20):")
        return
    await state.update_data(price=int(text))
    await state.set_state(NewDealStates.waiting_for_stock)
    await message.answer("📦 How many deals are available right now? (e.g. 15)")

@dp.message(NewDealStates.waiting_for_stock, F.text)
async def process_deal_stock(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit():
        await message.answer("⚠️ Please enter a valid number for stock quantity (e.g. 15):")
        return
    await state.update_data(stock=int(text))
    await state.set_state(NewDealStates.waiting_for_valid_until)
    await message.answer(
        "⏰ Enter the <b>Valid Until</b> time in both English and Ethiopian time.\n"
        "<i>Example: 9:30 PM Tonight (3:30 ከሰዓት በኋላ)</i>",
        parse_mode="HTML"
    )

@dp.message(NewDealStates.waiting_for_valid_until, F.text)
async def process_valid_until(message: Message, state: FSMContext):
    valid_until = message.text.strip()
    await state.update_data(valid_until=valid_until)
    await state.set_state(NewDealStates.waiting_for_map_link)
    await message.answer("🗺️ Paste the Google Maps link for the restaurant (or type 'skip' if you don't have one):")

@dp.message(NewDealStates.waiting_for_map_link, F.text)
async def process_map_link(message: Message, state: FSMContext):
    link = message.text.strip()
    map_link = "" if link.lower() == 'skip' else link
    await state.update_data(map_link=map_link, selected_zones=[])
    await state.set_state(NewDealStates.waiting_for_zone)
    await message.answer("📍 Which campus zones should we blast this to? (Tap to select multiple)", reply_markup=get_fsm_multi_zone_keyboard([]))

@dp.callback_query(NewDealStates.waiting_for_zone, F.data.startswith("fsm_toggle_zone:"))
async def handle_toggle_zone(callback: CallbackQuery, state: FSMContext):
    zone_key = callback.data.split("fsm_toggle_zone:")[1]
    data = await state.get_data()
    selected_zones = list(data.get("selected_zones", []))
    if zone_key in selected_zones:
        selected_zones.remove(zone_key)
    else:
        selected_zones.append(zone_key)
    await state.update_data(selected_zones=selected_zones)
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=get_fsm_multi_zone_keyboard(selected_zones))
    await callback.answer()

@dp.callback_query(NewDealStates.waiting_for_zone, F.data == "fsm_confirm_broadcast")
async def handle_confirm_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    selected_keys = list(data.get("selected_zones", []))
    if not selected_keys:
        await callback.answer("Select at least one zone!", show_alert=True)
        return
    
    restaurant_name = data.get("restaurant_name", "Special Deal")
    photo_file_id = data.get("photo_file_id")
    price = data.get("price", 0)
    stock = data.get("stock", 0)
    map_link = data.get("map_link", "")
    valid_until = data.get("valid_until", "9:30 PM Tonight (3:30 ከሰዓት በኋላ)")
    target_zone_names = [CAMPUS_ZONES.get(k, k) for k in selected_keys]
    comma_separated_zones = ", ".join(target_zone_names)
    deal_id = f"deal_{uuid.uuid4().hex[:8]}"

    save_active_deal(deal_id, restaurant_name, photo_file_id, price, stock, target_zone_names, map_link, valid_until)
    await state.clear()
    await callback.answer("Saving & broadcasting...", show_alert=False)

    caption = build_deal_caption(restaurant_name, comma_separated_zones, stock, price)
    claim_keyboard = get_claim_deal_keyboard(deal_id, price, restaurant_name, comma_separated_zones, map_link)
    subscribers = get_users_by_zones(target_zone_names)
    
    for student in subscribers:
        try:
            await bot.send_photo(chat_id=student["telegram_id"], photo=photo_file_id, caption=caption, reply_markup=claim_keyboard)
            await asyncio.sleep(0.05)
        except TelegramAPIError:
            pass

    await callback.message.answer(f"✅ Broadcast Complete to {len(subscribers)} students!")
    
    # Layer 20: Auto Announce to Channel
    if CHANNEL_ID:
        announcement = (
            f"🚨 <b>NEW DEAL DROP!</b>\n\n"
            f"A new flash drop for <b>{restaurant_name}</b> has just been added!\n\n"
            f"👉 Head over to @{BOT_USERNAME} to claim yours before it sells out!"
        )
        try:
            await bot.send_message(chat_id=CHANNEL_ID, text=announcement, parse_mode="HTML")
        except TelegramAPIError as e:
            logger.warning(f"Could not announce to channel: {e}")

@dp.callback_query(F.data.startswith("claim:"))
async def handle_claim_deal(callback: CallbackQuery, bot: Bot):
    deal_id = callback.data.split("claim:")[1]
    student_id = callback.from_user.id
    result = process_claim_transaction(deal_id, student_id)

    if result["status"] == "already_claimed":
        await callback.answer("⚠️ You already claimed this deal!", show_alert=True)
        return
    if result["status"] == "sold_out":
        await callback.answer("❌ Sorry, this deal is completely sold out!", show_alert=True)
        return
    if result["status"] == "inactive":
        await callback.answer("This flash deal is no longer active.", show_alert=True)
        return

    new_stock = result["new_stock"]
    await callback.answer("⚡ Deal Locked! Check your voucher below.", show_alert=False)

    deal = get_deal_by_id(deal_id)
    restaurant = deal["restaurant_name"] if deal else "Restaurant"
    price = deal["price"] if deal else 360
    zones_display = (deal["zones"] if ("zones" in deal.keys() and deal["zones"]) else deal["zone"]) if deal else "Campus"
    map_link_str = f"🗺️ Map: {deal['map_link']}\n" if deal and ("map_link" in deal.keys() and deal["map_link"]) else ""

    if callback.message:
        try:
            updated_caption = build_deal_caption(restaurant, zones_display, new_stock, price)
            updated_keyboard = None if new_stock <= 0 else get_claim_deal_keyboard(deal_id, price, restaurant, zones_display, (deal["map_link"] if "map_link" in deal.keys() else ""))
            await callback.message.edit_caption(caption=updated_caption, reply_markup=updated_keyboard)
        except: pass

    valid_until_str = deal["valid_until"] if deal and "valid_until" in deal.keys() and deal["valid_until"] else "9:30 PM Tonight (3:30 ከሰዓት በኋላ)"
    voucher_msg = (
        "✅ <b>DEAL LOCKED & CONFIRMED!</b>\n\n"
        "🎟️ <b>ACTION VOUCHER PASS:</b>\n"
        "👉 <code>[ SHOW AAU ID ]</code> 👈\n\n"
        f"🍔 <b>Deal:</b> 1x {restaurant} Flash Special\n"
        f"💵 <b>Price:</b> {price} ETB (Pay at counter)\n"
        f"📍 <b>Location:</b> {zones_display}\n"
        f"{map_link_str}"
        f"⏰ <b>Valid Until:</b> {valid_until_str}\n\n"
        "💡 <b>Instructions:</b>\n"
        f"Show this message and your physical AAU Student ID to the cashier."
    )
    await bot.send_message(chat_id=student_id, text=voucher_msg, parse_mode="HTML", reply_markup=get_voucher_action_keyboard(deal_id))

@dp.callback_query(F.data.startswith("accept_deal:"))
async def handle_accept_deal(callback: CallbackQuery):
    deal_id = callback.data.split("accept_deal:")[1]
    deal = get_deal_by_id(deal_id)
    
    if not deal:
        await callback.answer("Deal data unavailable.", show_alert=True)
        return
        
    restaurant = deal["restaurant_name"]
    price = deal["price"]
    zones_display = (deal["zones"] if ("zones" in deal.keys() and deal["zones"]) else deal["zone"])
    map_link_str = f"🗺️ <b>Map:</b> {deal['map_link']}\n" if deal and ("map_link" in deal.keys() and deal["map_link"]) else ""
    
    valid_until_str = deal["valid_until"] if deal and "valid_until" in deal.keys() and deal["valid_until"] else "9:30 PM Tonight (3:30 ከሰዓት በኋላ)"
    redeemed_msg = (
        "🎉 <b>DEAL PERMANENTLY REDEEMED!</b>\n\n"
        "🎟️ <b>ACTION VOUCHER PASS:</b>\n"
        "👉 <code>[ SHOW AAU ID ]</code> 👈\n\n"
        f"🍔 <b>Deal:</b> 1x {restaurant} Flash Special\n"
        f"💵 <b>Price:</b> {price} ETB (Pay at counter)\n"
        f"📍 <b>Location:</b> {zones_display}\n"
        f"{map_link_str}"
        f"⏰ <b>Valid Until:</b> {valid_until_str} (Redeemed ✅)\n\n"
        "📸 <i>Enjoy your meal! Want to feature on our page? Tap /share to drop your food pics and feedback!</i>"
    )
    
    try:
        await callback.message.edit_text(redeemed_msg, parse_mode="HTML", reply_markup=None)
        await callback.answer("Deal accepted! Enjoy!", show_alert=True)
    except Exception:
        pass

@dp.callback_query(F.data.startswith("return_deal:"))
async def handle_return_deal(callback: CallbackQuery):
    deal_id = callback.data.split("return_deal:")[1]
    student_id = callback.from_user.id
    success = return_claim_transaction(deal_id, student_id)
    
    if success:
        void_msg = "🚫 <b>VOUCHER VOIDED.</b>\nYou have returned this deal to the marketplace."
        await callback.message.edit_text(void_msg, parse_mode="HTML", reply_markup=None)
        await callback.answer("Deal returned successfully! +1 Stock Added.", show_alert=True)
    else:
        await callback.answer("Could not return deal. It may have already been returned.", show_alert=True)


@dp.callback_query(RatingStates.waiting_for_deal_rating, F.data.startswith("rate_deal:"))
async def handle_deal_rating(callback: CallbackQuery, state: FSMContext):
    rating = int(callback.data.split("rate_deal:")[1])
    await state.update_data(deal_rating=rating)
    await state.set_state(RatingStates.waiting_for_product_rating)
    
    stars_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data="rate_prod:1"),
            InlineKeyboardButton(text="⭐ 2", callback_data="rate_prod:2"),
            InlineKeyboardButton(text="⭐ 3", callback_data="rate_prod:3"),
            InlineKeyboardButton(text="⭐ 4", callback_data="rate_prod:4"),
            InlineKeyboardButton(text="⭐ 5", callback_data="rate_prod:5"),
        ]
    ])
    
    await callback.message.edit_text(
        f"⭐ Deal Rated: {rating}/5 stars!\n\n"
        "⭐ <b>Step 2/2: How would you rate the food/product quality? (1-5 stars):</b>",
        parse_mode="HTML",
        reply_markup=stars_keyboard
    )
    await callback.answer()

@dp.callback_query(RatingStates.waiting_for_product_rating, F.data.startswith("rate_prod:"))
async def handle_product_rating(callback: CallbackQuery, state: FSMContext):
    prod_rating = int(callback.data.split("rate_prod:")[1])
    data = await state.get_data()
    deal_id = data.get("rating_deal_id")
    deal_rating = data.get("deal_rating", 5)
    
    await state.clear()
    
    if deal_id:
        save_ratings(deal_id, callback.from_user.id, deal_rating, prod_rating)
        
    success_msg = (
        "🎉 <b>THANK YOU FOR YOUR RATING!</b>\n\n"
        f"• Deal Rating: {deal_rating}/5 ⭐\n"
        f"• Product Quality: {prod_rating}/5 ⭐\n\n"
        "Your score has been added to the restaurant leaderboard! 🏆\n\n"
        "📸 <i>Want to share a photo or review? Type /share anytime! Or type /cancel if you're done.</i>"
    )
    
    await callback.message.edit_text(success_msg, parse_mode="HTML", reply_markup=None)
    await callback.answer("Rating submitted! Thank you!", show_alert=True)


@dp.message(Command("rate"))
async def handle_rate_command(message: Message, state: FSMContext):
    user_id = message.from_user.id
    # Find deals claimed by this user
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ad.deal_id, ad.restaurant_name, ad.price 
            FROM claims c 
            JOIN active_deals ad ON c.deal_id = ad.deal_id 
            WHERE c.telegram_id = ? 
            ORDER BY c.id DESC LIMIT 5
        """, (user_id,))
        claimed_deals = cursor.fetchall()
        
    if not claimed_deals:
        # Fallback to recent active deals if no claims found
        cursor.execute("SELECT deal_id, restaurant_name, price FROM active_deals ORDER BY id DESC LIMIT 5")
        claimed_deals = cursor.fetchall()
        
    if not claimed_deals:
        await message.answer("ℹ️ No deals available to rate right now. Claim a deal first!")
        return
        
    keyboard = []
    for d in claimed_deals:
        keyboard.append([InlineKeyboardButton(text=f"⭐ Rate: {d['restaurant_name']} ({d['price']} ETB)", callback_data=f"start_rate:{d['deal_id']}")])
        
    await message.answer(
        "⭐ <b>Rate Your Deal & Product Experience</b>\n\n"
        "Select the deal you want to rate below:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("start_rate:"))
async def handle_start_rate_callback(callback: CallbackQuery, state: FSMContext):
    deal_id = callback.data.split("start_rate:")[1]
    deal = get_deal_by_id(deal_id)
    if not deal:
        await callback.answer("Deal not found.", show_alert=True)
        return
        
    await state.update_data(rating_deal_id=deal_id)
    await state.set_state(RatingStates.waiting_for_deal_rating)
    
    stars_keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="⭐ 1", callback_data="rate_deal:1"),
            InlineKeyboardButton(text="⭐ 2", callback_data="rate_deal:2"),
            InlineKeyboardButton(text="⭐ 3", callback_data="rate_deal:3"),
            InlineKeyboardButton(text="⭐ 4", callback_data="rate_deal:4"),
            InlineKeyboardButton(text="⭐ 5", callback_data="rate_deal:5"),
        ]
    ])
    
    await callback.message.edit_text(
        f"⭐ <b>Rating: {deal['restaurant_name']}</b>\n\n"
        "Step 1/2: Please rate this overall deal experience (1-5 stars):",
        parse_mode="HTML",
        reply_markup=stars_keyboard
    )
    await callback.answer()

@dp.message(Command("leaderboard"))
async def handle_leaderboard(message: Message):
    leaders = get_leaderboard_data(limit=5)
    if not leaders:
        await message.answer("🏆 <b>TirfMarket Leaderboard</b>\n\nNo restaurant ratings recorded yet. Claim and rate deals to rank your favorite spots!", parse_mode="HTML")
        return
        
    text_lines = ["🏆 <b>TirfMarket Restaurant Leaderboard</b>\n"]
    for idx, r in enumerate(leaders, 1):
        name = r["restaurant_name"]
        avg = round(r["avg_score"], 1)
        count = r["rating_count"]
        
        medal = "🥇" if idx == 1 else "🥈" if idx == 2 else "🥉" if idx == 3 else f"{idx}."
        text_lines.append(f"{medal} <b>{name}</b> - ⭐ {avg}/5.0 <i>({count} ratings)</i>")
        
    text_lines.append("\n<i>Rankings are updated in real-time based on student ratings!</i>")
    await message.answer("\n".join(text_lines), parse_mode="HTML")

@dp.message(Command("share"))
async def handle_share_command(message: Message, state: FSMContext):
    user_id = message.from_user.id
    # Find deals claimed by this user
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT ad.deal_id, ad.restaurant_name, ad.price 
            FROM claims c 
            JOIN active_deals ad ON c.deal_id = ad.deal_id 
            WHERE c.telegram_id = ? 
            ORDER BY c.id DESC LIMIT 5
        """, (user_id,))
        claimed_deals = cursor.fetchall()
        
    if not claimed_deals:
        # Fallback to recent active deals if no claims found
        cursor.execute("SELECT deal_id, restaurant_name, price FROM active_deals ORDER BY id DESC LIMIT 5")
        claimed_deals = cursor.fetchall()
        
    if not claimed_deals:
        # Fallback default if no deals exist at all
        await state.update_data(deal_name="TirfMarket Deal")
        await state.set_state(ShareStates.waiting_for_feedback)
        await message.answer(
            "📸 <b>Share Your Experience!</b>\n\n"
            "Send your picture or text review below (or type /cancel to exit):",
            parse_mode="HTML"
        )
        return

    keyboard = []
    for d in claimed_deals:
        keyboard.append([InlineKeyboardButton(text=f"🍔 {d['restaurant_name']} ({d['price']} ETB)", callback_data=f"share_deal:{d['restaurant_name']}")])
    keyboard.append([InlineKeyboardButton(text="🏷️ General TirfMarket Feedback", callback_data="share_deal:TirfMarket Deal")])

    await message.answer(
        "📸 <b>Share Your Experience!</b>\n\n"
        "Which restaurant or deal are you reviewing today?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard),
        parse_mode="HTML"
    )

@dp.callback_query(F.data.startswith("share_deal:"))
async def handle_share_deal_selection(callback: CallbackQuery, state: FSMContext):
    deal_name = callback.data.split("share_deal:")[1]
    await state.update_data(deal_name=deal_name)
    await state.set_state(ShareStates.waiting_for_feedback)
    
    await callback.message.edit_text(
        f"✅ Reviewing: <b>{deal_name}</b>\n\n"
        "Now send your <b>picture</b>, type a <b>text review</b>, or send both together!\n\n"
        "<i>Drop your feedback below (or type /cancel to exit).</i>",
        parse_mode="HTML"
    )
    await callback.answer()

@dp.message(ShareStates.waiting_for_feedback, F.text | F.photo)
async def handle_feedback_submission(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    deal_name = data.get("deal_name", "TirfMarket Deal")
    await state.clear()
    
    await message.answer("🔥 Awesome! Thanks for your feedback. We might feature this in our next drop!\n(To send more, just type /share again)")
    
    admin_list = get_admin_ids()
    if admin_list:
        user = message.from_user
        user_handle = f"@{user.username}" if user.username else user.first_name
        
        media_type = "photo" if message.photo else "text"
        file_id = message.photo[-1].file_id if message.photo else ""
        text_content = message.caption if message.photo else message.text
        
        with sqlite3.connect(DB_FILE) as conn:
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(pending_reviews)")
            cols = [c[1] for c in cursor.fetchall()]
            if "deal_name" not in cols:
                cursor.execute("ALTER TABLE pending_reviews ADD COLUMN deal_name TEXT DEFAULT 'TirfMarket Deal'")
                
            cursor.execute(
                "INSERT INTO pending_reviews (user_id, user_handle, deal_name, media_type, file_id, text_content) VALUES (?, ?, ?, ?, ?, ?)",
                (user.id, user_handle, deal_name, media_type, file_id, text_content or "")
            )
            review_id = cursor.lastrowid
            conn.commit()
            
        approval_kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✅ Approve & Post", callback_data=f"approve_review:{review_id}")],
            [InlineKeyboardButton(text="❌ Reject", callback_data=f"reject_review:{review_id}")]
        ])
        
        for adm_id in admin_list:
            if media_type == "photo":
                admin_caption = f"📸 <b>Pending Photo Review (Shared under {deal_name})</b>\n👤 <b>From:</b> {user_handle} (<code>{user.id}</code>)\n🍔 <b>Deal:</b> {deal_name}\n📝 <b>Review:</b> {text_content or '(No text)'}"
                try: 
                    await bot.send_photo(chat_id=adm_id, photo=file_id, caption=admin_caption, parse_mode="HTML", reply_markup=approval_kb)
                except TelegramAPIError: 
                    pass
            else:
                admin_text = f"🗣️ <b>Pending Text Review (Shared under {deal_name})</b>\n👤 <b>From:</b> {user_handle} (<code>{user.id}</code>)\n🍔 <b>Deal:</b> {deal_name}\n📝 <b>Review:</b>\n{text_content}"
                try:
                    await bot.send_message(chat_id=adm_id, text=admin_text, parse_mode="HTML", reply_markup=approval_kb)
                except TelegramAPIError:
                    pass

@dp.callback_query(F.data.startswith("approve_review:"), IsAdmin())
async def handle_approve_review(callback: CallbackQuery, bot: Bot):
    review_id = callback.data.split(":")[1]
    
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM pending_reviews WHERE id = ?", (review_id,))
        review = cursor.fetchone()
        
    if not review or review["status"] != "pending":
        await callback.answer("Review already processed or not found.", show_alert=True)
        return
        
    if CHANNEL_ID:
        d_name = review["deal_name"] if "deal_name" in review.keys() and review["deal_name"] else "TirfMarket Deal"
        text_part = f"📝 <i>\"{review['text_content']}\"</i>\n\n" if review['text_content'] else ""
        
        public_caption = (
            f"📸 <b>Community Spotlight: {d_name}!</b>\n\n"
            f"{text_part}"
            f"👉 Grab student flash deals on @{BOT_USERNAME}"
        )
        try:
            if review["media_type"] == "photo":
                await bot.send_photo(chat_id=CHANNEL_ID, photo=review["file_id"], caption=public_caption, parse_mode="HTML")
            else:
                await bot.send_message(chat_id=CHANNEL_ID, text=public_caption, parse_mode="HTML")
        except TelegramAPIError as e:
            await callback.answer(f"Failed to post to channel. Ensure the bot is an admin there.", show_alert=True)
            return
            
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE pending_reviews SET status = 'approved' WHERE id = ?", (review_id,))
        conn.commit()
        
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n✅ <b>POSTED TO CHANNEL</b>", parse_mode="HTML", reply_markup=None)
        else:
            await callback.message.edit_text(text=callback.message.text + "\n\n✅ <b>POSTED TO CHANNEL</b>", parse_mode="HTML", reply_markup=None)
    except TelegramAPIError: pass
    await callback.answer("Review posted to channel successfully!")

@dp.callback_query(F.data.startswith("reject_review:"), IsAdmin())
async def handle_reject_review(callback: CallbackQuery):
    review_id = callback.data.split(":")[1]
    
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE pending_reviews SET status = 'rejected' WHERE id = ?", (review_id,))
        conn.commit()
        
    try:
        if callback.message.photo:
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n❌ <b>REJECTED</b>", parse_mode="HTML", reply_markup=None)
        else:
            await callback.message.edit_text(text=callback.message.text + "\n\n❌ <b>REJECTED</b>", parse_mode="HTML", reply_markup=None)
    except TelegramAPIError: pass
    await callback.answer("Review rejected.")

async def main():
    if not BOT_TOKEN: return
    init_db()
    bot = Bot(token=BOT_TOKEN)
    
    try:
        me = await bot.get_me()
        global BOT_USERNAME
        BOT_USERNAME = me.username or ""
    except Exception: pass
    
    public_commands = [
        BotCommand(command="start", description="Set or change campus zone"),
        BotCommand(command="radar", description="Scan active deals radar"),
        BotCommand(command="rate", description="Rate your claimed deals"),
        BotCommand(command="cancel", description="Cancel current action"),
        BotCommand(command="myid", description="Get your Telegram User ID"),
    ]
    await bot.set_my_commands(public_commands)
    
    admin_set = get_admin_ids()
    for adm_id in admin_set:
        admin_commands = [
            BotCommand(command="start", description="Set or change campus zone"),
            BotCommand(command="radar", description="Check active deals in your zone"),
            BotCommand(command="share", description="Share your food photo & review"),
            BotCommand(command="rate", description="Rate your claimed deals"),
            BotCommand(command="leaderboard", description="View restaurant ratings leaderboard"),
            BotCommand(command="newdeal", description="[Admin] Drop a new flash deal"),
            BotCommand(command="close_deal", description="[Admin] Close active deal"),
            BotCommand(command="reopen", description="[Admin] Reopen a closed deal"),
            BotCommand(command="deletedeal", description="[Admin] Delete a deal from database"),
            BotCommand(command="addadmin", description="[Admin] Add a new admin ID"),
            BotCommand(command="removeadmin", description="[Admin] Remove an admin ID"),
            BotCommand(command="cancel", description="Cancel current action"),
            BotCommand(command="myid", description="Get your Telegram User ID"),
        ]
        try:
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=adm_id))
        except Exception:
            pass

    while True:
        try:
            logger.info("Starting polling loop...")
            await dp.start_polling(bot, skip_updates=True)
        except Exception as e:
            logger.error(f"Polling error encountered: {e}. Reconnecting in 3 seconds...")
            await asyncio.sleep(3)

if __name__ == "__main__":
    asyncio.run(main())

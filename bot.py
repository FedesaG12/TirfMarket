"""
TirfMarket Telegram Bot - Layers 1, 2, 3, 4 & 6 (Admin Shield & Social Proof Engine)
Hyper-local student discount bot targeting Addis Ababa University (AAU) campuses.

Layer 1: Onboarding, campus zone selection (4 Kilo, 5 Kilo, 6 Kilo), SQLite DB.
Layer 2: Aiogram v3 FSM dynamic Deal Builder (/newdeal) with photo upload & multi-zone selection.
         - Interactive checkmark toggling [ ✅ 4 Kilo ] on inline keyboard
         - Multi-zone broadcast targeting with validation ("Select at least one zone!")
Layer 3: The FOMO Claim Engine, atomic stock decrements, live caption updates, Action Voucher pass,
         and The Latecomer Fix via /radar.
Layer 4: Telegram Mini App (TMA):
         - Clicking [ ⚡ Claim Deal ] opens the lightweight TMA overlay (index.html).
         - Listens for ContentType.WEB_APP_DATA / F.web_app_data.
         - Executes atomic stock reduction & issues Action Voucher pass.
Layer 6: The Admin Shield & Social Proof Engine:
         - IsAdmin filter silently drops unauthorized admin commands (/newdeal, /close_deal, /cancel).
         - Admin commands hidden from public Telegram Bot Menu.
         - /share prompt & photo review forwarder to ADMIN_ID with student attribution.

Stack: aiogram v3, SQLite3, python-dotenv
"""

import asyncio
import json
import logging
import os
import sqlite3
import urllib.parse
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
    Message,
    CallbackQuery,
    BotCommand,
    BotCommandScopeChat,
    WebAppInfo,
)
from aiogram.exceptions import TelegramAPIError

# 1. Environment & Logging Setup
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_admin_id = os.getenv("ADMIN_ID", "")
ADMIN_ID = int(raw_admin_id.strip()) if raw_admin_id.strip().isdigit() else None

# Layer 4: WebApp URL (must be HTTPS for Telegram Mini Apps)
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
BOT_USERNAME = ""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tirfmarket-bot")

DB_FILE = "tirfmarket.db"


# ---------------------------------------------------------
# LAYER 6: The Admin Shield (Custom Filter)
# ---------------------------------------------------------
class IsAdmin(BaseFilter):
    """
    Layer 6: The Admin Shield.
    Ensures that only the user matching ADMIN_ID from .env can trigger admin commands.
    If the user is not the admin, the filter returns False, causing the bot to
    completely ignore the message (silently drop it with no response).
    """
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        if ADMIN_ID is None:
            return False
        user = event.from_user
        return bool(user and user.id == ADMIN_ID)

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


# 2. Aiogram FSM States for /newdeal (Layer 2)
class NewDealStates(StatesGroup):
    waiting_for_restaurant = State()
    waiting_for_photo = State()
    waiting_for_price = State()
    waiting_for_stock = State()
    waiting_for_zone = State()  # Multi-select zone phase


# 3. Database Layer (SQLite)
def init_db():
    """Initializes tables for students, dynamic active deals, and claims."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # 1. Users Table (Layer 1)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                zone TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 2. Active Deals Table (Layer 2 & 3 with multi-zone support)
        cursor.execute(
            """
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
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute("PRAGMA table_info(active_deals)")
        existing_cols = [col[1] for col in cursor.fetchall()]
        if "zones" not in existing_cols:
            cursor.execute("ALTER TABLE active_deals ADD COLUMN zones TEXT DEFAULT ''")

        # 3. Claims Table (Layer 3: Prevents double claiming)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT NOT NULL,
                telegram_id INTEGER NOT NULL,
                voucher_code TEXT NOT NULL,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(deal_id) REFERENCES active_deals(deal_id),
                UNIQUE(deal_id, telegram_id)
            )
            """
        )
        conn.commit()
    logger.info(f"Database tables verified in {DB_FILE}")


def save_user_zone(telegram_id: int, username: str | None, full_name: str | None, zone: str):
    """Saves or updates user's campus zone using UPSERT."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (telegram_id, username, full_name, zone, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                zone = excluded.zone,
                updated_at = CURRENT_TIMESTAMP
            """,
            (telegram_id, username, full_name, zone),
        )
        conn.commit()


def get_user(telegram_id: int):
    """Retrieves user record by Telegram ID."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone()


def get_users_by_zones(target_zones: list[str]):
    """Retrieves all students registered in ANY of the chosen target campus zones."""
    if not target_zones:
        return []
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in target_zones)
        cursor.execute(
            f"SELECT telegram_id, full_name, username, zone FROM users WHERE zone IN ({placeholders})",
            target_zones,
        )
        return cursor.fetchall()


def save_active_deal(
    deal_id: str,
    restaurant_name: str,
    photo_file_id: str,
    price: int,
    stock: int,
    target_zones: list[str],
):
    """Saves a newly created dynamic deal from FSM into active_deals with multi-zone support."""
    zones_joined = ", ".join(target_zones)
    primary_zone = target_zones[0] if target_zones else "4 Kilo Campus"

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO active_deals (
                deal_id, restaurant_name, photo_file_id, price,
                initial_stock, remaining_stock, zone, zones, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (deal_id, restaurant_name, photo_file_id, price, stock, stock, primary_zone, zones_joined),
        )
        conn.commit()
    logger.info(f"Saved active deal {deal_id} ({restaurant_name}) for zones: {zones_joined}")


def get_active_deal_for_zone(zone: str):
    """
    Layer 3 (The Latecomer Fix):
    Queries active_deals for the latest deal matching student's zone with stock > 0.
    """
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM active_deals 
            WHERE (zones LIKE ? OR zone = ? OR zones = '')
              AND is_active = 1 
              AND remaining_stock > 0 
            ORDER BY id DESC LIMIT 1
            """,
            (f"%{zone}%", zone),
        )
        return cursor.fetchone()


def get_deal_by_id(deal_id: str):
    """Fetches deal record from active_deals table."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_deals WHERE deal_id = ?", (deal_id,))
        return cursor.fetchone()


def process_claim_transaction(deal_id: str, telegram_id: int):
    """Atomic claim engine preventing concurrency issues and duplicate claims."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Step 1: Prevent duplicate claims
        cursor.execute(
            "SELECT voucher_code FROM claims WHERE deal_id = ? AND telegram_id = ?",
            (deal_id, telegram_id),
        )
        existing = cursor.fetchone()
        if existing:
            return {"status": "already_claimed", "voucher": existing["voucher_code"]}

        # Step 2: Atomic stock decrement
        cursor.execute(
            """
            UPDATE active_deals 
            SET remaining_stock = remaining_stock - 1 
            WHERE deal_id = ? AND is_active = 1 AND remaining_stock > 0
            """,
            (deal_id,),
        )

        if cursor.rowcount == 0:
            cursor.execute("SELECT remaining_stock, is_active FROM active_deals WHERE deal_id = ?", (deal_id,))
            deal = cursor.fetchone()
            if not deal or deal["is_active"] != 1:
                return {"status": "inactive"}
            return {"status": "sold_out"}

        # Step 3: Record claim
        voucher_code = "SHOW AAU ID"
        cursor.execute(
            "INSERT INTO claims (deal_id, telegram_id, voucher_code) VALUES (?, ?, ?)",
            (deal_id, telegram_id, voucher_code),
        )

        cursor.execute("SELECT remaining_stock FROM active_deals WHERE deal_id = ?", (deal_id,))
        updated_deal = cursor.fetchone()
        new_stock = updated_deal["remaining_stock"]

        conn.commit()
        return {
            "status": "success",
            "new_stock": new_stock,
            "voucher": voucher_code,
        }


# 4. Keyboards & Builders
def get_campus_selection_keyboard() -> InlineKeyboardMarkup:
    """Inline buttons for Layer 1 campus selection."""
    buttons = [
        [InlineKeyboardButton(text="[ 4 Kilo Campus ]", callback_data="zone:4_kilo")],
        [InlineKeyboardButton(text="[ 5 Kilo Campus ]", callback_data="zone:5_kilo")],
        [InlineKeyboardButton(text="[ 6 Kilo Campus ]", callback_data="zone:6_kilo")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_fsm_multi_zone_keyboard(selected_keys: list[str] | None = None) -> InlineKeyboardMarkup:
    """
    Multi-select inline keyboard for Admin FSM to select broadcast target zones.
    Tapping toggles a checkmark (e.g., [ ✅ 4 Kilo ]).
    Bottom button: [ 🚀 Confirm & Broadcast ].
    """
    selected_set = set(selected_keys or [])
    buttons = []

    for key in ["4_kilo", "5_kilo", "6_kilo"]:
        short_name = CAMPUS_SHORT_NAMES[key]
        if key in selected_set:
            label = f"[ ✅ {short_name} ]"
        else:
            label = f"[ {short_name} ]"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"fsm_toggle_zone:{key}")])

    buttons.append([
        InlineKeyboardButton(
            text="[ 🚀 Confirm & Broadcast ]",
            callback_data="fsm_confirm_broadcast",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_claim_deal_keyboard(
    deal_id: str,
    price: int,
    restaurant_name: str = "Angla Burger",
    zone: str = "4 Kilo Branch",
) -> InlineKeyboardMarkup:
    """
    Returns an InlineKeyboardMarkup with:
    1. Direct 1-Tap claim button (callback_data) - guaranteed instant voucher delivery in chat
    2. Interactive Telegram Mini App button (if WEBAPP_URL is set)
    """
    inline_keyboard = []

    # Button 1: Instant 1-Tap Claim (Works 100% natively in Telegram chat without webview)
    inline_keyboard.append([
        InlineKeyboardButton(
            text=f"⚡ 1-Tap Claim Voucher ({price} ETB)",
            callback_data=f"claim:{deal_id}",
        )
    ])

    # Button 2: Telegram Mini App view (if WEBAPP_URL configured)
    if WEBAPP_URL:
        params = urllib.parse.urlencode({
            "deal_id": deal_id,
            "price": str(price),
            "restaurant": restaurant_name,
            "item": f"{restaurant_name} Flash Special",
            "original": str(round(price * 1.58)),
            "zone": zone,
            "bot": BOT_USERNAME,
        })
        separator = "&" if "?" in WEBAPP_URL else "?"
        full_webapp_url = f"{WEBAPP_URL}{separator}{params}"

        inline_keyboard.append([
            InlineKeyboardButton(
                text="📱 View in Mini App",
                web_app=WebAppInfo(url=full_webapp_url),
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def build_deal_caption(restaurant_name: str, zones_str: str, stock: int, price: int) -> str:
    """Builds standard deal caption with multi-zones and live FOMO stock."""
    stock_line = "🔴 SOLD OUT" if stock <= 0 else f"⚠️ Only {stock} available!"
    return (
        f"🚨 FLASH DEAL: {restaurant_name}\n"
        f"📍 Zones: {zones_str}\n"
        f"{stock_line}\n"
        f"💵 Price: {price} ETB"
    )


# 5. Bot & Dispatcher Setup
dp = Dispatcher(storage=MemoryStorage())


# ---------------------------------------------------------
# LAYER 1: Student Onboarding & Zone Radar
# ---------------------------------------------------------
@dp.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()

    # Check if launched with a deep-link from Mini App (e.g. /start claim_<deal_id>)
    if command.args and command.args.startswith("claim_"):
        deal_id = command.args[len("claim_"):]
        student_id = message.from_user.id

        result = process_claim_transaction(deal_id, student_id)

        if result["status"] == "already_claimed":
            await message.answer(
                "⚠️ <b>You already locked this deal!</b>\nHere is your active voucher pass below:",
                parse_mode="HTML"
            )
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

        voucher_msg = (
            "✅ <b>DEAL LOCKED & CONFIRMED!</b>\n\n"
            "🎟️ <b>ACTION VOUCHER PASS:</b>\n"
            "👉 <code>[ SHOW AAU ID ]</code> 👈\n\n"
            f"🍔 <b>Deal:</b> 1x {restaurant} Flash Special\n"
            f"💵 <b>Price:</b> {price} ETB (Pay at counter)\n"
            f"📍 <b>Location:</b> {zones_display}\n"
            "⏰ <b>Valid Until:</b> 9:30 PM Tonight\n\n"
            "💡 <b>Instructions:</b>\n"
            f"Show this message and your physical AAU Student ID to the cashier. Pay {price} ETB directly at the counter via Cash or Telebirr."
        )
        await message.answer(voucher_msg, parse_mode="HTML")
        logger.info(f"Student {student_id} claimed deal {deal_id} via Mini App deep link. Remaining stock: {result.get('new_stock')}")
        return

    welcome_text = (
        "Welcome to TirfMarket! 🍔\n"
        "We surface exclusive student flash deals from restaurants around campus.\n\n"
        "Which campus are you near right now?"
    )
    await message.answer(
        text=welcome_text,
        reply_markup=get_campus_selection_keyboard(),
    )


@dp.callback_query(F.data.startswith("zone:"))
async def handle_zone_selection(callback: CallbackQuery):
    zone_key = callback.data.split("zone:")[1]
    selected_zone = CAMPUS_ZONES.get(zone_key, "Unknown Campus")

    user = callback.from_user
    save_user_zone(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name,
        zone=selected_zone,
    )

    confirmation_text = (
        f"✅ Zone set to {selected_zone}! Radar active. "
        "We'll ping you when deals drop nearby."
    )

    if callback.message:
        await callback.message.edit_text(
            text=confirmation_text,
            reply_markup=None,
        )
    else:
        await callback.answer(confirmation_text, show_alert=True)

    await callback.answer()


# ---------------------------------------------------------
# LAYER 3: The Latecomer Fix (/radar)
# ---------------------------------------------------------
@dp.message(Command("radar"))
@dp.message(Command("status"))
async def handle_radar(message: Message):
    user_record = get_user(message.from_user.id)
    if not user_record or not user_record["zone"]:
        await message.answer(
            "You haven't set your campus zone yet!\n"
            "Tap /start to activate your discount radar."
        )
        return

    student_zone = user_record["zone"]
    active_deal = get_active_deal_for_zone(student_zone)

    if active_deal:
        deal_zones = active_deal["zones"] if ("zones" in active_deal.keys() and active_deal["zones"]) else active_deal["zone"]
        caption = build_deal_caption(
            restaurant_name=active_deal["restaurant_name"],
            zones_str=deal_zones,
            stock=active_deal["remaining_stock"],
            price=active_deal["price"],
        )
        keyboard = get_claim_deal_keyboard(
            deal_id=active_deal["deal_id"],
            price=active_deal["price"],
            restaurant_name=active_deal["restaurant_name"],
            zone=deal_zones,
        )

        try:
            await message.answer_photo(
                photo=active_deal["photo_file_id"],
                caption=caption,
                reply_markup=keyboard,
            )
        except TelegramAPIError as e:
            logger.warning(f"Could not deliver photo via /radar: {e}")
            await message.answer(caption, reply_markup=keyboard)
    else:
        await message.answer(
            "📡 Radar Status: No active drops in your zone right now. We'll ping you when the next one hits!"
        )


@dp.message(Command("myid"))
@dp.message(Command("id"))
async def handle_myid(message: Message):
    user_id = message.from_user.id
    is_admin = (ADMIN_ID is not None and user_id == ADMIN_ID)
    status_tag = "👑 (Verified Admin)" if is_admin else "🎓 (Student)"
    await message.answer(
        f"Your Telegram ID: <code>{user_id}</code> {status_tag}\n\n"
        f"Configure in your <code>.env</code> file:\n"
        f"<code>ADMIN_ID={user_id}</code>",
        parse_mode="HTML",
    )


# ---------------------------------------------------------
# LAYER 2 & 6: Admin Deal Builder & Admin Shield
# ---------------------------------------------------------
@dp.message(Command("cancel"), IsAdmin())
async def handle_cancel_fsm(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("No active deal creation to cancel.")
        return
    await state.clear()
    await message.answer("❌ Deal creation cancelled.")


# Admin Shield: /close_deal (Silently dropped if not admin)
@dp.message(Command("close_deal"), IsAdmin())
@dp.message(Command("closedeal"), IsAdmin())
async def handle_close_deal(message: Message):
    """
    Layer 6: The Admin Shield.
    Allows verified admin to instantly terminate any active flash deals.
    Silently ignored for all non-admins.
    """
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE active_deals
            SET is_active = 0, remaining_stock = 0
            WHERE is_active = 1
            """
        )
        closed_count = cursor.rowcount
        conn.commit()

    if closed_count > 0:
        await message.answer(f"🛑 Closed {closed_count} active deal(s). Radar is now clear.")
        logger.info(f"Admin {message.from_user.id} closed {closed_count} deal(s).")
    else:
        await message.answer("ℹ️ No active deals are currently open.")


# Step 1: /newdeal entrypoint (Admin Shielded: silently dropped for non-admins)
@dp.message(Command("newdeal"), IsAdmin())
async def start_new_deal(message: Message, state: FSMContext):
    await state.set_state(NewDealStates.waiting_for_restaurant)
    await message.answer("🍔 Let's drop a new deal. What is the name of the restaurant?")


# Step 2: Receive restaurant name
@dp.message(NewDealStates.waiting_for_restaurant, F.text)
async def process_restaurant_name(message: Message, state: FSMContext):
    restaurant = message.text.strip()
    if not restaurant:
        await message.answer("Please enter a valid restaurant name:")
        return

    await state.update_data(restaurant_name=restaurant)
    await state.set_state(NewDealStates.waiting_for_photo)
    await message.answer("📸 Send me the picture or poster for this deal.")


# Step 3: Receive photo
@dp.message(NewDealStates.waiting_for_photo, F.photo)
async def process_deal_photo(message: Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id

    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(NewDealStates.waiting_for_price)
    await message.answer("💵 What is the discounted price in ETB?")


@dp.message(NewDealStates.waiting_for_photo)
async def process_photo_invalid(message: Message):
    await message.answer("⚠️ Please upload a photo (image/poster) for this deal.")


# Step 4: Receive price
@dp.message(NewDealStates.waiting_for_price, F.text)
async def process_deal_price(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("⚠️ Please enter a valid positive number for price (e.g. 360):")
        return

    price = int(text)
    await state.update_data(price=price)
    await state.set_state(NewDealStates.waiting_for_stock)
    await message.answer("📦 How many deals are available right now?")


# Step 5: Receive stock
@dp.message(NewDealStates.waiting_for_stock, F.text)
async def process_deal_stock(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("⚠️ Please enter a valid stock quantity (e.g. 10):")
        return

    stock = int(text)
    await state.update_data(stock=stock, selected_zones=[])
    await state.set_state(NewDealStates.waiting_for_zone)
    await message.answer(
        "📍 Which campus zones should we blast this to? (Tap to select multiple)",
        reply_markup=get_fsm_multi_zone_keyboard([]),
    )


# Step 6a: Multi-Select Zone Toggle Callback Handler
@dp.callback_query(NewDealStates.waiting_for_zone, F.data.startswith("fsm_toggle_zone:"))
async def handle_toggle_zone(callback: CallbackQuery, state: FSMContext):
    zone_key = callback.data.split("fsm_toggle_zone:")[1]
    data = await state.get_data()
    selected_zones: list[str] = list(data.get("selected_zones", []))

    if zone_key in selected_zones:
        selected_zones.remove(zone_key)
    else:
        selected_zones.append(zone_key)

    await state.update_data(selected_zones=selected_zones)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=get_fsm_multi_zone_keyboard(selected_zones)
        )

    await callback.answer()


# Step 6b: Confirm & Broadcast Callback Handler
@dp.callback_query(NewDealStates.waiting_for_zone, F.data == "fsm_confirm_broadcast")
async def handle_confirm_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    selected_keys: list[str] = list(data.get("selected_zones", []))

    if not selected_keys:
        await callback.answer("Select at least one zone!", show_alert=True)
        return

    restaurant_name = data.get("restaurant_name", "Special Deal")
    photo_file_id = data.get("photo_file_id")
    price = data.get("price", 0)
    stock = data.get("stock", 0)

    target_zone_names = [CAMPUS_ZONES.get(k, k) for k in selected_keys]
    comma_separated_zones = ", ".join(target_zone_names)

    deal_id = f"deal_{uuid.uuid4().hex[:8]}"

    # Save to SQLite active_deals table
    save_active_deal(
        deal_id=deal_id,
        restaurant_name=restaurant_name,
        photo_file_id=photo_file_id,
        price=price,
        stock=stock,
        target_zones=target_zone_names,
    )

    await state.clear()
    await callback.answer("Saving & broadcasting...", show_alert=False)

    if callback.message:
        await callback.message.edit_text(
            f"🚀 <b>Blasting Deal!</b>\n\n"
            f"• <b>Restaurant:</b> {restaurant_name}\n"
            f"• <b>Target Zones:</b> {comma_separated_zones}\n"
            f"• <b>Stock:</b> {stock}\n"
            f"• <b>Price:</b> {price} ETB\n\n"
            f"Broadcasting photo cards to students...",
            parse_mode="HTML",
        )

    caption = build_deal_caption(
        restaurant_name=restaurant_name,
        zones_str=comma_separated_zones,
        stock=stock,
        price=price,
    )
    claim_keyboard = get_claim_deal_keyboard(
        deal_id=deal_id,
        price=price,
        restaurant_name=restaurant_name,
        zone=comma_separated_zones,
    )

    # Query all students registered in ANY of the chosen target zones
    subscribers = get_users_by_zones(target_zone_names)
    sent_count = 0
    failed_count = 0

    for student in subscribers:
        try:
            await bot.send_photo(
                chat_id=student["telegram_id"],
                photo=photo_file_id,
                caption=caption,
                reply_markup=claim_keyboard,
            )
            sent_count += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError as e:
            logger.warning(f"Could not send photo deal to {student['telegram_id']}: {e}")
            failed_count += 1

    summary_text = (
        f"✅ <b>Deal Live & Broadcast Complete!</b>\n\n"
        f"• <b>Restaurant:</b> {restaurant_name}\n"
        f"• <b>Target Zones:</b> {comma_separated_zones}\n"
        f"• <b>Delivered:</b> {sent_count} students on radar\n"
        f"• <b>Stock:</b> {stock} available\n"
        f"• <b>Price:</b> {price} ETB\n"
    )
    if failed_count > 0:
        summary_text += f"• <b>Failed:</b> {failed_count} students\n"

    await bot.send_message(
        chat_id=callback.from_user.id,
        text=summary_text,
        parse_mode="HTML",
    )


# ---------------------------------------------------------
# LAYER 4: The Telegram Mini App (TMA) Claim Handler
# ---------------------------------------------------------
@dp.message(F.content_type == ContentType.WEB_APP_DATA)
@dp.message(F.web_app_data)
async def handle_web_app_claim(message: Message, bot: Bot):
    """
    Layer 4: Telegram Mini App Claim Handler.
    Catches incoming JSON payload from Telegram.WebApp.sendData().
    Executes the exact same Layer 3 stock reduction and Action Voucher delivery.
    """
    student_id = message.from_user.id
    raw_data = message.web_app_data.data if message.web_app_data else "{}"
    logger.info(f"Received WebApp claim data from {student_id}: {raw_data}")

    try:
        payload = json.loads(raw_data)
    except Exception as e:
        logger.warning(f"Error parsing web_app_data: {e}")
        payload = {"action": "claim_deal"}

    if payload.get("action") == "claim_deal":
        deal_id = payload.get("deal_id")

        # Fallback if deal_id not passed: find latest active deal in user's zone
        if not deal_id or deal_id == "angla_1":
            user_record = get_user(student_id)
            zone = user_record["zone"] if user_record and user_record["zone"] else "4 Kilo Campus"
            active_deal = get_active_deal_for_zone(zone)
            if active_deal:
                deal_id = active_deal["deal_id"]

        if not deal_id:
            await message.answer("❌ No active flash deals currently available to claim.")
            return

        # Execute Layer 3 atomic transaction
        result = process_claim_transaction(deal_id, student_id)

        if result["status"] == "already_claimed":
            await message.answer(
                "⚠️ You already claimed this deal!\nCheck your voucher below."
            )
            return

        if result["status"] == "sold_out":
            await message.answer("❌ Sorry, this deal is completely sold out!")
            return

        if result["status"] == "inactive":
            await message.answer("This flash deal is no longer active.")
            return

        # Successful Claim from Mini App!
        new_stock = result["new_stock"]
        deal = get_deal_by_id(deal_id)
        restaurant = deal["restaurant_name"] if deal else "Angla Burger"
        price = deal["price"] if deal else 360
        zones_display = (deal["zones"] if ("zones" in deal.keys() and deal["zones"]) else deal["zone"]) if deal else "4 Kilo Branch"

        voucher_msg = (
            "✅ Deal Locked!\n\n"
            "VOUCHER CODE:\n"
            "👉 [ SHOW AAU ID ] 👈\n\n"
            f"1x {restaurant} ({price} ETB)\n"
            f"📍 {zones_display}\n"
            "⏰ Redeem Before: 9:30 PM Tonight\n\n"
            "💡 Instructions:\n"
            f"Show this message and your AAU ID to the cashier. Pay {price} ETB directly at the counter via Cash or Telebirr."
        )

        await message.answer(voucher_msg)
        logger.info(f"Student {student_id} claimed deal {deal_id} via Mini App. Remaining stock: {new_stock}")


# ---------------------------------------------------------
# LAYER 3: Direct Inline Button Fallback Claim Handler
# ---------------------------------------------------------
@dp.callback_query(F.data.startswith("claim:"))
async def handle_claim_deal(callback: CallbackQuery, bot: Bot):
    deal_id = callback.data.split("claim:")[1]
    student_id = callback.from_user.id

    result = process_claim_transaction(deal_id, student_id)

    if result["status"] == "already_claimed":
        await callback.answer(
            "⚠️ You already claimed this deal!\nCheck your voucher below.",
            show_alert=True,
        )
        return

    if result["status"] == "sold_out":
        await callback.answer(
            "❌ Sorry, this deal is completely sold out!",
            show_alert=True,
        )
        if callback.message:
            deal = get_deal_by_id(deal_id)
            if deal:
                try:
                    zones_display = deal["zones"] if ("zones" in deal.keys() and deal["zones"]) else deal["zone"]
                    sold_out_caption = build_deal_caption(
                        restaurant_name=deal["restaurant_name"],
                        zones_str=zones_display,
                        stock=0,
                        price=deal["price"],
                    )
                    await callback.message.edit_caption(
                        caption=sold_out_caption,
                        reply_markup=None,
                    )
                except TelegramAPIError:
                    pass
        return

    if result["status"] == "inactive":
        await callback.answer("This flash deal is no longer active.", show_alert=True)
        return

    # Successful Claim!
    new_stock = result["new_stock"]
    await callback.answer("⚡ Deal Locked! Check your voucher below.", show_alert=False)

    deal = get_deal_by_id(deal_id)
    restaurant = deal["restaurant_name"] if deal else "Restaurant"
    price = deal["price"] if deal else 360
    zones_display = (deal["zones"] if ("zones" in deal.keys() and deal["zones"]) else deal["zone"]) if deal else "Campus"

    # Live Message FOMO Updating
    if callback.message:
        try:
            updated_caption = build_deal_caption(
                restaurant_name=restaurant,
                zones_str=zones_display,
                stock=new_stock,
                price=price,
            )
            updated_keyboard = None if new_stock <= 0 else get_claim_deal_keyboard(
                deal_id=deal_id,
                price=price,
                restaurant_name=restaurant,
                zone=zones_display,
            )
            await callback.message.edit_caption(
                caption=updated_caption,
                reply_markup=updated_keyboard,
            )
        except TelegramAPIError as e:
            logger.debug(f"Caption edit skipped: {e}")

    # Action Voucher Pass
    voucher_msg = (
        "✅ Deal Locked!\n\n"
        "VOUCHER CODE:\n"
        "👉 [ SHOW AAU ID ] 👈\n\n"
        f"1x {restaurant} ({price} ETB)\n"
        f"📍 {zones_display}\n"
        "⏰ Redeem Before: 9:30 PM Tonight\n\n"
        "💡 Instructions:\n"
        f"Show this message and your AAU ID to the cashier. Pay {price} ETB directly at the counter via Cash or Telebirr."
    )

    await bot.send_message(
        chat_id=student_id,
        text=voucher_msg,
    )
    logger.info(f"Student {student_id} claimed deal {deal_id}. Remaining stock: {new_stock}")


# ---------------------------------------------------------
# LAYER 6: Social Proof Engine (Feedback & Food Photos)
# ---------------------------------------------------------
@dp.message(Command("share"))
async def handle_share_command(message: Message):
    """
    Layer 6: Social Proof Engine prompt.
    Invites students to share food photos and reviews.
    """
    await message.answer(
        "📸 Did you grab a deal today? Send us a picture of your food and a quick review!"
    )


@dp.message(F.photo, default_state)
async def handle_community_photo(message: Message, bot: Bot):
    """
    Layer 6: Community Photo & Review Listener.
    Catches photos sent by students outside the deal builder FSM:
    a) Replies to the student: '🔥 Awesome! Thanks for sharing. We might feature this in our next drop!'
    b) Automatically forwards that exact photo and caption directly to ADMIN_ID.
    c) Appends the user's @username or first name to the forwarded message so the admin knows who sent it.
    """
    user = message.from_user
    user_name = user.first_name if user else "Student"
    user_handle = f"@{user.username}" if (user and user.username) else user_name
    user_full = user.full_name if user else "AAU Student"
    user_id = user.id if user else "Unknown"

    # a) Reply to the student
    await message.answer("🔥 Awesome! Thanks for sharing. We might feature this in our next drop!")

    # b & c) Forward photo and caption directly to ADMIN_ID with student identity appended
    if ADMIN_ID:
        photo_file_id = message.photo[-1].file_id
        original_caption = message.caption.strip() if message.caption else "<i>(No review text provided)</i>"

        admin_caption = (
            f"📸 <b>Community Food Review / Proof</b>\n\n"
            f"👤 <b>Submitted By:</b> {user_handle} ({user_full})\n"
            f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n\n"
            f"📝 <b>Review / Caption:</b>\n{original_caption}"
        )

        try:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_file_id,
                caption=admin_caption,
                parse_mode="HTML",
            )
            logger.info(f"Forwarded community review photo from {user_handle} ({user_id}) to Admin {ADMIN_ID}")
        except TelegramAPIError as e:
            logger.warning(f"Could not forward community review to Admin {ADMIN_ID}: {e}")


# ---------------------------------------------------------
# 6. Startup Loop
# ---------------------------------------------------------
async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("ERROR: BOT_TOKEN is missing or not set in .env file!")
        return

    init_db()

    bot = Bot(token=BOT_TOKEN)

    # Fetch bot username for Mini App deep links
    try:
        me = await bot.get_me()
        global BOT_USERNAME
        BOT_USERNAME = me.username or ""
        logger.info(f"🤖 Connected as @{BOT_USERNAME}")
    except Exception as e:
        logger.warning(f"Could not retrieve bot info: {e}")

    # Public bot menu commands (seen by regular students - NO admin commands visible)
    public_commands = [
        BotCommand(command="start", description="Set or change campus zone"),
        BotCommand(command="radar", description="Check active deals in your zone"),
        BotCommand(command="share", description="Share your food photo & review"),
        BotCommand(command="myid", description="Get your Telegram User ID"),
    ]
    await bot.set_my_commands(public_commands)

    # Scoped admin commands (strictly visible only to the verified ADMIN_ID)
    if ADMIN_ID:
        try:
            admin_commands = [
                BotCommand(command="start", description="Set or change campus zone"),
                BotCommand(command="radar", description="Check active deals in your zone"),
                BotCommand(command="share", description="Share your food photo & review"),
                BotCommand(command="newdeal", description="[Admin] Drop a new flash deal"),
                BotCommand(command="close_deal", description="[Admin] Close active deal"),
                BotCommand(command="cancel", description="[Admin] Cancel deal creation"),
                BotCommand(command="myid", description="Get your Telegram User ID"),
            ]
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
            logger.info(f"👑 Admin commands scoped strictly to ADMIN_ID: {ADMIN_ID}")
        except Exception as e:
            logger.debug(f"Admin scope commands registration: {e}")

    logger.info("🚀 TirfMarket Bot (Layers 1-4 & 6 TMA + Shield Enabled) is live!")
    if ADMIN_ID:
        logger.info(f"👑 Admin ID: {ADMIN_ID} (Use /newdeal to build & drop a deal)")
    if WEBAPP_URL:
        logger.info(f"📱 Telegram Mini App URL active: {WEBAPP_URL}")
    else:
        logger.info("ℹ️ No WEBAPP_URL configured; inline buttons will use direct callback fallback.")

    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")
"""
TirfMarket Telegram Bot - Layers 1, 2, 3, 4 & 6 (Admin Shield & Social Proof Engine)
Hyper-local student discount bot targeting Addis Ababa University (AAU) campuses.

Layer 1: Onboarding, campus zone selection (4 Kilo, 5 Kilo, 6 Kilo), SQLite DB.
Layer 2: Aiogram v3 FSM dynamic Deal Builder (/newdeal) with photo upload & multi-zone selection.
         - Interactive checkmark toggling [ ✅ 4 Kilo ] on inline keyboard
         - Multi-zone broadcast targeting with validation ("Select at least one zone!")
Layer 3: The FOMO Claim Engine, atomic stock decrements, live caption updates, Action Voucher pass,
         and The Latecomer Fix via /radar.
Layer 4: Telegram Mini App (TMA):
         - Clicking [ ⚡ Claim Deal ] opens the lightweight TMA overlay (index.html).
         - Listens for ContentType.WEB_APP_DATA / F.web_app_data.
         - Executes atomic stock reduction & issues Action Voucher pass.
Layer 6: The Admin Shield & Social Proof Engine:
         - IsAdmin filter silently drops unauthorized admin commands (/newdeal, /close_deal, /cancel).
         - Admin commands hidden from public Telegram Bot Menu.
         - /share prompt & photo review forwarder to ADMIN_ID with student attribution.

Stack: aiogram v3, SQLite3, python-dotenv
"""

import asyncio
import json
import logging
import os
import sqlite3
import urllib.parse
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
    Message,
    CallbackQuery,
    BotCommand,
    BotCommandScopeChat,
    WebAppInfo,
)
from aiogram.exceptions import TelegramAPIError

# 1. Environment & Logging Setup
load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
raw_admin_id = os.getenv("ADMIN_ID", "")
ADMIN_ID = int(raw_admin_id.strip()) if raw_admin_id.strip().isdigit() else None

# Layer 4: WebApp URL (must be HTTPS for Telegram Mini Apps)
WEBAPP_URL = os.getenv("WEBAPP_URL", "")
BOT_USERNAME = ""

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("tirfmarket-bot")

DB_FILE = "tirfmarket.db"


# ---------------------------------------------------------
# LAYER 6: The Admin Shield (Custom Filter)
# ---------------------------------------------------------
class IsAdmin(BaseFilter):
    """
    Layer 6: The Admin Shield.
    Ensures that only the user matching ADMIN_ID from .env can trigger admin commands.
    If the user is not the admin, the filter returns False, causing the bot to
    completely ignore the message (silently drop it with no response).
    """
    async def __call__(self, event: Message | CallbackQuery) -> bool:
        if ADMIN_ID is None:
            return False
        user = event.from_user
        return bool(user and user.id == ADMIN_ID)

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


# 2. Aiogram FSM States for /newdeal (Layer 2)
class NewDealStates(StatesGroup):
    waiting_for_restaurant = State()
    waiting_for_photo = State()
    waiting_for_price = State()
    waiting_for_stock = State()
    waiting_for_zone = State()  # Multi-select zone phase


# 3. Database Layer (SQLite)
def init_db():
    """Initializes tables for students, dynamic active deals, and claims."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()

        # 1. Users Table (Layer 1)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                zone TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        # 2. Active Deals Table (Layer 2 & 3 with multi-zone support)
        cursor.execute(
            """
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
                is_active INTEGER DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )

        cursor.execute("PRAGMA table_info(active_deals)")
        existing_cols = [col[1] for col in cursor.fetchall()]
        if "zones" not in existing_cols:
            cursor.execute("ALTER TABLE active_deals ADD COLUMN zones TEXT DEFAULT ''")

        # 3. Claims Table (Layer 3: Prevents double claiming)
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS claims (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                deal_id TEXT NOT NULL,
                telegram_id INTEGER NOT NULL,
                voucher_code TEXT NOT NULL,
                claimed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY(deal_id) REFERENCES active_deals(deal_id),
                UNIQUE(deal_id, telegram_id)
            )
            """
        )
        conn.commit()
    logger.info(f"Database tables verified in {DB_FILE}")


def save_user_zone(telegram_id: int, username: str | None, full_name: str | None, zone: str):
    """Saves or updates user's campus zone using UPSERT."""
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO users (telegram_id, username, full_name, zone, updated_at)
            VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name,
                zone = excluded.zone,
                updated_at = CURRENT_TIMESTAMP
            """,
            (telegram_id, username, full_name, zone),
        )
        conn.commit()


def get_user(telegram_id: int):
    """Retrieves user record by Telegram ID."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        return cursor.fetchone()


def get_users_by_zones(target_zones: list[str]):
    """Retrieves all students registered in ANY of the chosen target campus zones."""
    if not target_zones:
        return []
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in target_zones)
        cursor.execute(
            f"SELECT telegram_id, full_name, username, zone FROM users WHERE zone IN ({placeholders})",
            target_zones,
        )
        return cursor.fetchall()


def save_active_deal(
    deal_id: str,
    restaurant_name: str,
    photo_file_id: str,
    price: int,
    stock: int,
    target_zones: list[str],
):
    """Saves a newly created dynamic deal from FSM into active_deals with multi-zone support."""
    zones_joined = ", ".join(target_zones)
    primary_zone = target_zones[0] if target_zones else "4 Kilo Campus"

    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO active_deals (
                deal_id, restaurant_name, photo_file_id, price,
                initial_stock, remaining_stock, zone, zones, is_active
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)
            """,
            (deal_id, restaurant_name, photo_file_id, price, stock, stock, primary_zone, zones_joined),
        )
        conn.commit()
    logger.info(f"Saved active deal {deal_id} ({restaurant_name}) for zones: {zones_joined}")


def get_active_deal_for_zone(zone: str):
    """
    Layer 3 (The Latecomer Fix):
    Queries active_deals for the latest deal matching student's zone with stock > 0.
    """
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT * FROM active_deals 
            WHERE (zones LIKE ? OR zone = ? OR zones = '')
              AND is_active = 1 
              AND remaining_stock > 0 
            ORDER BY id DESC LIMIT 1
            """,
            (f"%{zone}%", zone),
        )
        return cursor.fetchone()


def get_deal_by_id(deal_id: str):
    """Fetches deal record from active_deals table."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM active_deals WHERE deal_id = ?", (deal_id,))
        return cursor.fetchone()


def process_claim_transaction(deal_id: str, telegram_id: int):
    """Atomic claim engine preventing concurrency issues and duplicate claims."""
    with sqlite3.connect(DB_FILE) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        # Step 1: Prevent duplicate claims
        cursor.execute(
            "SELECT voucher_code FROM claims WHERE deal_id = ? AND telegram_id = ?",
            (deal_id, telegram_id),
        )
        existing = cursor.fetchone()
        if existing:
            return {"status": "already_claimed", "voucher": existing["voucher_code"]}

        # Step 2: Atomic stock decrement
        cursor.execute(
            """
            UPDATE active_deals 
            SET remaining_stock = remaining_stock - 1 
            WHERE deal_id = ? AND is_active = 1 AND remaining_stock > 0
            """,
            (deal_id,),
        )

        if cursor.rowcount == 0:
            cursor.execute("SELECT remaining_stock, is_active FROM active_deals WHERE deal_id = ?", (deal_id,))
            deal = cursor.fetchone()
            if not deal or deal["is_active"] != 1:
                return {"status": "inactive"}
            return {"status": "sold_out"}

        # Step 3: Record claim
        voucher_code = "SHOW AAU ID"
        cursor.execute(
            "INSERT INTO claims (deal_id, telegram_id, voucher_code) VALUES (?, ?, ?)",
            (deal_id, telegram_id, voucher_code),
        )

        cursor.execute("SELECT remaining_stock FROM active_deals WHERE deal_id = ?", (deal_id,))
        updated_deal = cursor.fetchone()
        new_stock = updated_deal["remaining_stock"]

        conn.commit()
        return {
            "status": "success",
            "new_stock": new_stock,
            "voucher": voucher_code,
        }


# 4. Keyboards & Builders
def get_campus_selection_keyboard() -> InlineKeyboardMarkup:
    """Inline buttons for Layer 1 campus selection."""
    buttons = [
        [InlineKeyboardButton(text="[ 4 Kilo Campus ]", callback_data="zone:4_kilo")],
        [InlineKeyboardButton(text="[ 5 Kilo Campus ]", callback_data="zone:5_kilo")],
        [InlineKeyboardButton(text="[ 6 Kilo Campus ]", callback_data="zone:6_kilo")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_fsm_multi_zone_keyboard(selected_keys: list[str] | None = None) -> InlineKeyboardMarkup:
    """
    Multi-select inline keyboard for Admin FSM to select broadcast target zones.
    Tapping toggles a checkmark (e.g., [ ✅ 4 Kilo ]).
    Bottom button: [ 🚀 Confirm & Broadcast ].
    """
    selected_set = set(selected_keys or [])
    buttons = []

    for key in ["4_kilo", "5_kilo", "6_kilo"]:
        short_name = CAMPUS_SHORT_NAMES[key]
        if key in selected_set:
            label = f"[ ✅ {short_name} ]"
        else:
            label = f"[ {short_name} ]"
        buttons.append([InlineKeyboardButton(text=label, callback_data=f"fsm_toggle_zone:{key}")])

    buttons.append([
        InlineKeyboardButton(
            text="[ 🚀 Confirm & Broadcast ]",
            callback_data="fsm_confirm_broadcast",
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_claim_deal_keyboard(
    deal_id: str,
    price: int,
    restaurant_name: str = "Angla Burger",
    zone: str = "4 Kilo Branch",
) -> InlineKeyboardMarkup:
    """
    Returns an InlineKeyboardMarkup with:
    1. Direct 1-Tap claim button (callback_data) - guaranteed instant voucher delivery in chat
    2. Interactive Telegram Mini App button (if WEBAPP_URL is set)
    """
    inline_keyboard = []

    # Button 1: Instant 1-Tap Claim (Works 100% natively in Telegram chat without webview)
    inline_keyboard.append([
        InlineKeyboardButton(
            text=f"⚡ 1-Tap Claim Voucher ({price} ETB)",
            callback_data=f"claim:{deal_id}",
        )
    ])

    # Button 2: Telegram Mini App view (if WEBAPP_URL configured)
    if WEBAPP_URL:
        params = urllib.parse.urlencode({
            "deal_id": deal_id,
            "price": str(price),
            "restaurant": restaurant_name,
            "item": f"{restaurant_name} Flash Special",
            "original": str(round(price * 1.58)),
            "zone": zone,
            "bot": BOT_USERNAME,
        })
        separator = "&" if "?" in WEBAPP_URL else "?"
        full_webapp_url = f"{WEBAPP_URL}{separator}{params}"

        inline_keyboard.append([
            InlineKeyboardButton(
                text="📱 View in Mini App",
                web_app=WebAppInfo(url=full_webapp_url),
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=inline_keyboard)


def build_deal_caption(restaurant_name: str, zones_str: str, stock: int, price: int) -> str:
    """Builds standard deal caption with multi-zones and live FOMO stock."""
    stock_line = "🔴 SOLD OUT" if stock <= 0 else f"⚠️ Only {stock} available!"
    return (
        f"🚨 FLASH DEAL: {restaurant_name}\n"
        f"📍 Zones: {zones_str}\n"
        f"{stock_line}\n"
        f"💵 Price: {price} ETB"
    )


# 5. Bot & Dispatcher Setup
dp = Dispatcher(storage=MemoryStorage())


# ---------------------------------------------------------
# LAYER 1: Student Onboarding & Zone Radar
# ---------------------------------------------------------
@dp.message(CommandStart())
async def handle_start(message: Message, command: CommandObject, state: FSMContext):
    await state.clear()

    # Check if launched with a deep-link from Mini App (e.g. /start claim_<deal_id>)
    if command.args and command.args.startswith("claim_"):
        deal_id = command.args[len("claim_"):]
        student_id = message.from_user.id

        result = process_claim_transaction(deal_id, student_id)

        if result["status"] == "already_claimed":
            await message.answer(
                "⚠️ <b>You already locked this deal!</b>\nHere is your active voucher pass below:",
                parse_mode="HTML"
            )
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

        voucher_msg = (
            "✅ <b>DEAL LOCKED & CONFIRMED!</b>\n\n"
            "🎟️ <b>ACTION VOUCHER PASS:</b>\n"
            "👉 <code>[ SHOW AAU ID ]</code> 👈\n\n"
            f"🍔 <b>Deal:</b> 1x {restaurant} Flash Special\n"
            f"💵 <b>Price:</b> {price} ETB (Pay at counter)\n"
            f"📍 <b>Location:</b> {zones_display}\n"
            "⏰ <b>Valid Until:</b> 9:30 PM Tonight\n\n"
            "💡 <b>Instructions:</b>\n"
            f"Show this message and your physical AAU Student ID to the cashier. Pay {price} ETB directly at the counter via Cash or Telebirr."
        )
        await message.answer(voucher_msg, parse_mode="HTML")
        logger.info(f"Student {student_id} claimed deal {deal_id} via Mini App deep link. Remaining stock: {result.get('new_stock')}")
        return

    welcome_text = (
        "Welcome to TirfMarket! 🍔\n"
        "We surface exclusive student flash deals from restaurants around campus.\n\n"
        "Which campus are you near right now?"
    )
    await message.answer(
        text=welcome_text,
        reply_markup=get_campus_selection_keyboard(),
    )


@dp.callback_query(F.data.startswith("zone:"))
async def handle_zone_selection(callback: CallbackQuery):
    zone_key = callback.data.split("zone:")[1]
    selected_zone = CAMPUS_ZONES.get(zone_key, "Unknown Campus")

    user = callback.from_user
    save_user_zone(
        telegram_id=user.id,
        username=user.username,
        full_name=user.full_name,
        zone=selected_zone,
    )

    confirmation_text = (
        f"✅ Zone set to {selected_zone}! Radar active. "
        "We'll ping you when deals drop nearby."
    )

    if callback.message:
        await callback.message.edit_text(
            text=confirmation_text,
            reply_markup=None,
        )
    else:
        await callback.answer(confirmation_text, show_alert=True)

    await callback.answer()


# ---------------------------------------------------------
# LAYER 3: The Latecomer Fix (/radar)
# ---------------------------------------------------------
@dp.message(Command("radar"))
@dp.message(Command("status"))
async def handle_radar(message: Message):
    user_record = get_user(message.from_user.id)
    if not user_record or not user_record["zone"]:
        await message.answer(
            "You haven't set your campus zone yet!\n"
            "Tap /start to activate your discount radar."
        )
        return

    student_zone = user_record["zone"]
    active_deal = get_active_deal_for_zone(student_zone)

    if active_deal:
        deal_zones = active_deal["zones"] if ("zones" in active_deal.keys() and active_deal["zones"]) else active_deal["zone"]
        caption = build_deal_caption(
            restaurant_name=active_deal["restaurant_name"],
            zones_str=deal_zones,
            stock=active_deal["remaining_stock"],
            price=active_deal["price"],
        )
        keyboard = get_claim_deal_keyboard(
            deal_id=active_deal["deal_id"],
            price=active_deal["price"],
            restaurant_name=active_deal["restaurant_name"],
            zone=deal_zones,
        )

        try:
            await message.answer_photo(
                photo=active_deal["photo_file_id"],
                caption=caption,
                reply_markup=keyboard,
            )
        except TelegramAPIError as e:
            logger.warning(f"Could not deliver photo via /radar: {e}")
            await message.answer(caption, reply_markup=keyboard)
    else:
        await message.answer(
            "📡 Radar Status: No active drops in your zone right now. We'll ping you when the next one hits!"
        )


@dp.message(Command("myid"))
@dp.message(Command("id"))
async def handle_myid(message: Message):
    user_id = message.from_user.id
    is_admin = (ADMIN_ID is not None and user_id == ADMIN_ID)
    status_tag = "👑 (Verified Admin)" if is_admin else "🎓 (Student)"
    await message.answer(
        f"Your Telegram ID: <code>{user_id}</code> {status_tag}\n\n"
        f"Configure in your <code>.env</code> file:\n"
        f"<code>ADMIN_ID={user_id}</code>",
        parse_mode="HTML",
    )


# ---------------------------------------------------------
# LAYER 2 & 6: Admin Deal Builder & Admin Shield
# ---------------------------------------------------------
@dp.message(Command("cancel"), IsAdmin())
async def handle_cancel_fsm(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("No active deal creation to cancel.")
        return
    await state.clear()
    await message.answer("❌ Deal creation cancelled.")


# Admin Shield: /close_deal (Silently dropped if not admin)
@dp.message(Command("close_deal"), IsAdmin())
@dp.message(Command("closedeal"), IsAdmin())
async def handle_close_deal(message: Message):
    """
    Layer 6: The Admin Shield.
    Allows verified admin to instantly terminate any active flash deals.
    Silently ignored for all non-admins.
    """
    with sqlite3.connect(DB_FILE) as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            UPDATE active_deals
            SET is_active = 0, remaining_stock = 0
            WHERE is_active = 1
            """
        )
        closed_count = cursor.rowcount
        conn.commit()

    if closed_count > 0:
        await message.answer(f"🛑 Closed {closed_count} active deal(s). Radar is now clear.")
        logger.info(f"Admin {message.from_user.id} closed {closed_count} deal(s).")
    else:
        await message.answer("ℹ️ No active deals are currently open.")


# Step 1: /newdeal entrypoint (Admin Shielded: silently dropped for non-admins)
@dp.message(Command("newdeal"), IsAdmin())
async def start_new_deal(message: Message, state: FSMContext):
    await state.set_state(NewDealStates.waiting_for_restaurant)
    await message.answer("🍔 Let's drop a new deal. What is the name of the restaurant?")


# Step 2: Receive restaurant name
@dp.message(NewDealStates.waiting_for_restaurant, F.text)
async def process_restaurant_name(message: Message, state: FSMContext):
    restaurant = message.text.strip()
    if not restaurant:
        await message.answer("Please enter a valid restaurant name:")
        return

    await state.update_data(restaurant_name=restaurant)
    await state.set_state(NewDealStates.waiting_for_photo)
    await message.answer("📸 Send me the picture or poster for this deal.")


# Step 3: Receive photo
@dp.message(NewDealStates.waiting_for_photo, F.photo)
async def process_deal_photo(message: Message, state: FSMContext):
    photo_file_id = message.photo[-1].file_id

    await state.update_data(photo_file_id=photo_file_id)
    await state.set_state(NewDealStates.waiting_for_price)
    await message.answer("💵 What is the discounted price in ETB?")


@dp.message(NewDealStates.waiting_for_photo)
async def process_photo_invalid(message: Message):
    await message.answer("⚠️ Please upload a photo (image/poster) for this deal.")


# Step 4: Receive price
@dp.message(NewDealStates.waiting_for_price, F.text)
async def process_deal_price(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("⚠️ Please enter a valid positive number for price (e.g. 360):")
        return

    price = int(text)
    await state.update_data(price=price)
    await state.set_state(NewDealStates.waiting_for_stock)
    await message.answer("📦 How many deals are available right now?")


# Step 5: Receive stock
@dp.message(NewDealStates.waiting_for_stock, F.text)
async def process_deal_stock(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.isdigit() or int(text) <= 0:
        await message.answer("⚠️ Please enter a valid stock quantity (e.g. 10):")
        return

    stock = int(text)
    await state.update_data(stock=stock, selected_zones=[])
    await state.set_state(NewDealStates.waiting_for_zone)
    await message.answer(
        "📍 Which campus zones should we blast this to? (Tap to select multiple)",
        reply_markup=get_fsm_multi_zone_keyboard([]),
    )


# Step 6a: Multi-Select Zone Toggle Callback Handler
@dp.callback_query(NewDealStates.waiting_for_zone, F.data.startswith("fsm_toggle_zone:"))
async def handle_toggle_zone(callback: CallbackQuery, state: FSMContext):
    zone_key = callback.data.split("fsm_toggle_zone:")[1]
    data = await state.get_data()
    selected_zones: list[str] = list(data.get("selected_zones", []))

    if zone_key in selected_zones:
        selected_zones.remove(zone_key)
    else:
        selected_zones.append(zone_key)

    await state.update_data(selected_zones=selected_zones)

    if callback.message:
        await callback.message.edit_reply_markup(
            reply_markup=get_fsm_multi_zone_keyboard(selected_zones)
        )

    await callback.answer()


# Step 6b: Confirm & Broadcast Callback Handler
@dp.callback_query(NewDealStates.waiting_for_zone, F.data == "fsm_confirm_broadcast")
async def handle_confirm_broadcast(callback: CallbackQuery, state: FSMContext, bot: Bot):
    data = await state.get_data()
    selected_keys: list[str] = list(data.get("selected_zones", []))

    if not selected_keys:
        await callback.answer("Select at least one zone!", show_alert=True)
        return

    restaurant_name = data.get("restaurant_name", "Special Deal")
    photo_file_id = data.get("photo_file_id")
    price = data.get("price", 0)
    stock = data.get("stock", 0)

    target_zone_names = [CAMPUS_ZONES.get(k, k) for k in selected_keys]
    comma_separated_zones = ", ".join(target_zone_names)

    deal_id = f"deal_{uuid.uuid4().hex[:8]}"

    # Save to SQLite active_deals table
    save_active_deal(
        deal_id=deal_id,
        restaurant_name=restaurant_name,
        photo_file_id=photo_file_id,
        price=price,
        stock=stock,
        target_zones=target_zone_names,
    )

    await state.clear()
    await callback.answer("Saving & broadcasting...", show_alert=False)

    if callback.message:
        await callback.message.edit_text(
            f"🚀 <b>Blasting Deal!</b>\n\n"
            f"• <b>Restaurant:</b> {restaurant_name}\n"
            f"• <b>Target Zones:</b> {comma_separated_zones}\n"
            f"• <b>Stock:</b> {stock}\n"
            f"• <b>Price:</b> {price} ETB\n\n"
            f"Broadcasting photo cards to students...",
            parse_mode="HTML",
        )

    caption = build_deal_caption(
        restaurant_name=restaurant_name,
        zones_str=comma_separated_zones,
        stock=stock,
        price=price,
    )
    claim_keyboard = get_claim_deal_keyboard(
        deal_id=deal_id,
        price=price,
        restaurant_name=restaurant_name,
        zone=comma_separated_zones,
    )

    # Query all students registered in ANY of the chosen target zones
    subscribers = get_users_by_zones(target_zone_names)
    sent_count = 0
    failed_count = 0

    for student in subscribers:
        try:
            await bot.send_photo(
                chat_id=student["telegram_id"],
                photo=photo_file_id,
                caption=caption,
                reply_markup=claim_keyboard,
            )
            sent_count += 1
            await asyncio.sleep(0.05)
        except TelegramAPIError as e:
            logger.warning(f"Could not send photo deal to {student['telegram_id']}: {e}")
            failed_count += 1

    summary_text = (
        f"✅ <b>Deal Live & Broadcast Complete!</b>\n\n"
        f"• <b>Restaurant:</b> {restaurant_name}\n"
        f"• <b>Target Zones:</b> {comma_separated_zones}\n"
        f"• <b>Delivered:</b> {sent_count} students on radar\n"
        f"• <b>Stock:</b> {stock} available\n"
        f"• <b>Price:</b> {price} ETB\n"
    )
    if failed_count > 0:
        summary_text += f"• <b>Failed:</b> {failed_count} students\n"

    await bot.send_message(
        chat_id=callback.from_user.id,
        text=summary_text,
        parse_mode="HTML",
    )


# ---------------------------------------------------------
# LAYER 4: The Telegram Mini App (TMA) Claim Handler
# ---------------------------------------------------------
@dp.message(F.content_type == ContentType.WEB_APP_DATA)
@dp.message(F.web_app_data)
async def handle_web_app_claim(message: Message, bot: Bot):
    """
    Layer 4: Telegram Mini App Claim Handler.
    Catches incoming JSON payload from Telegram.WebApp.sendData().
    Executes the exact same Layer 3 stock reduction and Action Voucher delivery.
    """
    student_id = message.from_user.id
    raw_data = message.web_app_data.data if message.web_app_data else "{}"
    logger.info(f"Received WebApp claim data from {student_id}: {raw_data}")

    try:
        payload = json.loads(raw_data)
    except Exception as e:
        logger.warning(f"Error parsing web_app_data: {e}")
        payload = {"action": "claim_deal"}

    if payload.get("action") == "claim_deal":
        deal_id = payload.get("deal_id")

        # Fallback if deal_id not passed: find latest active deal in user's zone
        if not deal_id or deal_id == "angla_1":
            user_record = get_user(student_id)
            zone = user_record["zone"] if user_record and user_record["zone"] else "4 Kilo Campus"
            active_deal = get_active_deal_for_zone(zone)
            if active_deal:
                deal_id = active_deal["deal_id"]

        if not deal_id:
            await message.answer("❌ No active flash deals currently available to claim.")
            return

        # Execute Layer 3 atomic transaction
        result = process_claim_transaction(deal_id, student_id)

        if result["status"] == "already_claimed":
            await message.answer(
                "⚠️ You already claimed this deal!\nCheck your voucher below."
            )
            return

        if result["status"] == "sold_out":
            await message.answer("❌ Sorry, this deal is completely sold out!")
            return

        if result["status"] == "inactive":
            await message.answer("This flash deal is no longer active.")
            return

        # Successful Claim from Mini App!
        new_stock = result["new_stock"]
        deal = get_deal_by_id(deal_id)
        restaurant = deal["restaurant_name"] if deal else "Angla Burger"
        price = deal["price"] if deal else 360
        zones_display = (deal["zones"] if ("zones" in deal.keys() and deal["zones"]) else deal["zone"]) if deal else "4 Kilo Branch"

        voucher_msg = (
            "✅ Deal Locked!\n\n"
            "VOUCHER CODE:\n"
            "👉 [ SHOW AAU ID ] 👈\n\n"
            f"1x {restaurant} ({price} ETB)\n"
            f"📍 {zones_display}\n"
            "⏰ Redeem Before: 9:30 PM Tonight\n\n"
            "💡 Instructions:\n"
            f"Show this message and your AAU ID to the cashier. Pay {price} ETB directly at the counter via Cash or Telebirr."
        )

        await message.answer(voucher_msg)
        logger.info(f"Student {student_id} claimed deal {deal_id} via Mini App. Remaining stock: {new_stock}")


# ---------------------------------------------------------
# LAYER 3: Direct Inline Button Fallback Claim Handler
# ---------------------------------------------------------
@dp.callback_query(F.data.startswith("claim:"))
async def handle_claim_deal(callback: CallbackQuery, bot: Bot):
    deal_id = callback.data.split("claim:")[1]
    student_id = callback.from_user.id

    result = process_claim_transaction(deal_id, student_id)

    if result["status"] == "already_claimed":
        await callback.answer(
            "⚠️ You already claimed this deal!\nCheck your voucher below.",
            show_alert=True,
        )
        return

    if result["status"] == "sold_out":
        await callback.answer(
            "❌ Sorry, this deal is completely sold out!",
            show_alert=True,
        )
        if callback.message:
            deal = get_deal_by_id(deal_id)
            if deal:
                try:
                    zones_display = deal["zones"] if ("zones" in deal.keys() and deal["zones"]) else deal["zone"]
                    sold_out_caption = build_deal_caption(
                        restaurant_name=deal["restaurant_name"],
                        zones_str=zones_display,
                        stock=0,
                        price=deal["price"],
                    )
                    await callback.message.edit_caption(
                        caption=sold_out_caption,
                        reply_markup=None,
                    )
                except TelegramAPIError:
                    pass
        return

    if result["status"] == "inactive":
        await callback.answer("This flash deal is no longer active.", show_alert=True)
        return

    # Successful Claim!
    new_stock = result["new_stock"]
    await callback.answer("⚡ Deal Locked! Check your voucher below.", show_alert=False)

    deal = get_deal_by_id(deal_id)
    restaurant = deal["restaurant_name"] if deal else "Restaurant"
    price = deal["price"] if deal else 360
    zones_display = (deal["zones"] if ("zones" in deal.keys() and deal["zones"]) else deal["zone"]) if deal else "Campus"

    # Live Message FOMO Updating
    if callback.message:
        try:
            updated_caption = build_deal_caption(
                restaurant_name=restaurant,
                zones_str=zones_display,
                stock=new_stock,
                price=price,
            )
            updated_keyboard = None if new_stock <= 0 else get_claim_deal_keyboard(
                deal_id=deal_id,
                price=price,
                restaurant_name=restaurant,
                zone=zones_display,
            )
            await callback.message.edit_caption(
                caption=updated_caption,
                reply_markup=updated_keyboard,
            )
        except TelegramAPIError as e:
            logger.debug(f"Caption edit skipped: {e}")

    # Action Voucher Pass
    voucher_msg = (
        "✅ Deal Locked!\n\n"
        "VOUCHER CODE:\n"
        "👉 [ SHOW AAU ID ] 👈\n\n"
        f"1x {restaurant} ({price} ETB)\n"
        f"📍 {zones_display}\n"
        "⏰ Redeem Before: 9:30 PM Tonight\n\n"
        "💡 Instructions:\n"
        f"Show this message and your AAU ID to the cashier. Pay {price} ETB directly at the counter via Cash or Telebirr."
    )

    await bot.send_message(
        chat_id=student_id,
        text=voucher_msg,
    )
    logger.info(f"Student {student_id} claimed deal {deal_id}. Remaining stock: {new_stock}")


# ---------------------------------------------------------
# LAYER 6: Social Proof Engine (Feedback & Food Photos)
# ---------------------------------------------------------
@dp.message(Command("share"))
async def handle_share_command(message: Message):
    """
    Layer 6: Social Proof Engine prompt.
    Invites students to share food photos and reviews.
    """
    await message.answer(
        "📸 Did you grab a deal today? Send us a picture of your food and a quick review!"
    )


@dp.message(F.photo, default_state)
async def handle_community_photo(message: Message, bot: Bot):
    """
    Layer 6: Community Photo & Review Listener.
    Catches photos sent by students outside the deal builder FSM:
    a) Replies to the student: '🔥 Awesome! Thanks for sharing. We might feature this in our next drop!'
    b) Automatically forwards that exact photo and caption directly to ADMIN_ID.
    c) Appends the user's @username or first name to the forwarded message so the admin knows who sent it.
    """
    user = message.from_user
    user_name = user.first_name if user else "Student"
    user_handle = f"@{user.username}" if (user and user.username) else user_name
    user_full = user.full_name if user else "AAU Student"
    user_id = user.id if user else "Unknown"

    # a) Reply to the student
    await message.answer("🔥 Awesome! Thanks for sharing. We might feature this in our next drop!")

    # b & c) Forward photo and caption directly to ADMIN_ID with student identity appended
    if ADMIN_ID:
        photo_file_id = message.photo[-1].file_id
        original_caption = message.caption.strip() if message.caption else "<i>(No review text provided)</i>"

        admin_caption = (
            f"📸 <b>Community Food Review / Proof</b>\n\n"
            f"👤 <b>Submitted By:</b> {user_handle} ({user_full})\n"
            f"🆔 <b>Telegram ID:</b> <code>{user_id}</code>\n\n"
            f"📝 <b>Review / Caption:</b>\n{original_caption}"
        )

        try:
            await bot.send_photo(
                chat_id=ADMIN_ID,
                photo=photo_file_id,
                caption=admin_caption,
                parse_mode="HTML",
            )
            logger.info(f"Forwarded community review photo from {user_handle} ({user_id}) to Admin {ADMIN_ID}")
        except TelegramAPIError as e:
            logger.warning(f"Could not forward community review to Admin {ADMIN_ID}: {e}")


# ---------------------------------------------------------
# 6. Startup Loop
# ---------------------------------------------------------
async def main():
    if not BOT_TOKEN or BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        logger.error("ERROR: BOT_TOKEN is missing or not set in .env file!")
        return

    init_db()

    bot = Bot(token=BOT_TOKEN)

    # Fetch bot username for Mini App deep links
    try:
        me = await bot.get_me()
        global BOT_USERNAME
        BOT_USERNAME = me.username or ""
        logger.info(f"🤖 Connected as @{BOT_USERNAME}")
    except Exception as e:
        logger.warning(f"Could not retrieve bot info: {e}")

    # Public bot menu commands (seen by regular students - NO admin commands visible)
    public_commands = [
        BotCommand(command="start", description="Set or change campus zone"),
        BotCommand(command="radar", description="Check active deals in your zone"),
        BotCommand(command="share", description="Share your food photo & review"),
        BotCommand(command="myid", description="Get your Telegram User ID"),
    ]
    await bot.set_my_commands(public_commands)

    # Scoped admin commands (strictly visible only to the verified ADMIN_ID)
    if ADMIN_ID:
        try:
            admin_commands = [
                BotCommand(command="start", description="Set or change campus zone"),
                BotCommand(command="radar", description="Check active deals in your zone"),
                BotCommand(command="share", description="Share your food photo & review"),
                BotCommand(command="newdeal", description="[Admin] Drop a new flash deal"),
                BotCommand(command="close_deal", description="[Admin] Close active deal"),
                BotCommand(command="cancel", description="[Admin] Cancel deal creation"),
                BotCommand(command="myid", description="Get your Telegram User ID"),
            ]
            await bot.set_my_commands(admin_commands, scope=BotCommandScopeChat(chat_id=ADMIN_ID))
            logger.info(f"👑 Admin commands scoped strictly to ADMIN_ID: {ADMIN_ID}")
        except Exception as e:
            logger.debug(f"Admin scope commands registration: {e}")

    logger.info("🚀 TirfMarket Bot (Layers 1-4 & 6 TMA + Shield Enabled) is live!")
    if ADMIN_ID:
        logger.info(f"👑 Admin ID: {ADMIN_ID} (Use /newdeal to build & drop a deal)")
    if WEBAPP_URL:
        logger.info(f"📱 Telegram Mini App URL active: {WEBAPP_URL}")
    else:
        logger.info("ℹ️ No WEBAPP_URL configured; inline buttons will use direct callback fallback.")

    try:
        await dp.start_polling(bot, skip_updates=True)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        logger.info("Bot stopped.")

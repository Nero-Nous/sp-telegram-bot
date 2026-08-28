import os
import logging
import re
import time
import threading
import asyncio
import requests
from typing import Dict, Any
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==========================================
# FLASK DUMMY SERVER (FOR RENDER KEEP-ALIVE)
# ==========================================
web_app = Flask(__name__)

@web_app.route("/")
def health_check():
    return "Bot is running live!", 200

def start_flask_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# ==========================================
# ENVIRONMENT VARIABLES & LOGGING
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
PLISIO_API_KEY = os.environ.get("PLISIO_API_KEY")
BANNER_IMAGE_URL = os.environ.get(
    "BANNER_IMAGE_URL",
    "https://i.postimg.cc/d3tvHSJf/Picsart-26-08-27-15-27-57-869.jpg"
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# State and session storage
user_data_store: Dict[int, Dict[str, Any]] = {}

def get_user_state(user_id: int) -> Dict[str, Any]:
    if user_id not in user_data_store:
        user_data_store[user_id] = {
            "experience": "Not Selected",
            "service": "Not Selected",
            "price": 200,
            "admin_card_id": None,
            "card_history": [],
            "temp_alert_ids": [],
            "last_intent": None,
            "last_intent_time": 0,
        }
    return user_data_store[user_id]

# ==========================================
# HELPER FUNCTIONS
# ==========================================
async def simulate_typing(context: ContextTypes.DEFAULT_TYPE, chat_id: int, duration_seconds: int):
    """Shows continuous typing status in the header for specified duration."""
    elapsed = 0
    while elapsed < duration_seconds:
        try:
            await context.bot.send_chat_action(chat_id=chat_id, action=ChatAction.TYPING)
        except Exception:
            pass
        sleep_time = min(4, duration_seconds - elapsed)
        await asyncio.sleep(sleep_time)
        elapsed += sleep_time

def generate_crypto_link(user_id: int, service_name: str, price: int) -> str:
    """Generates direct crypto invoice link behind the scenes."""
    if not PLISIO_API_KEY:
        return f"https://plisio.net/pay/checkout_{user_id}"

    url = "https://api.plisio.net/api/v1/invoices/new"
    params = {
        "api_key": PLISIO_API_KEY,
        "source_amount": str(price),
        "source_currency": "USD",
        "order_name": f"SP Trading - {service_name}",
        "order_number": f"{user_id}_{int(time.time())}",
    }
    try:
        res = requests.get(url, params=params, timeout=10).json()
        if res.get("status") == "success":
            return res["data"]["invoice_url"]
    except Exception as e:
        logger.error(f"Crypto invoice API error: {e}")
    
    return f"https://plisio.net/pay/checkout_{user_id}"

async def update_admin_log_card(context: ContextTypes.DEFAULT_TYPE, user_id: int, user_handle: str, new_entry: str):
    """Updates permanent conversation log card in admin chat."""
    if not ADMIN_CHAT_ID:
        return

    state = get_user_state(user_id)
    state["card_history"].append(new_entry)
    
    header = (
        f"<b>CONVERSATION LOG:</b> {user_handle} (ID: <code>{user_id}</code>)\n"
        f"<b>Exp:</b> {state['experience']} | <b>Selected:</b> {state['service']}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    )
    
    body = "\n".join(state["card_history"])
    full_card_text = header + body
    
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("💬 Reply to Client", callback_data=f"admin_reply:{user_id}")
    ]])
    
    if len(full_card_text) > 2000:
        state["card_history"] = [f"<i>[...Previous History Archived...]</i>", new_entry]
        body = "\n".join(state["card_history"])
        full_card_text = header + body
        state["admin_card_id"] = None

    if state["admin_card_id"] is None:
        msg = await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=full_card_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )
        state["admin_card_id"] = msg.message_id
    else:
        try:
            await context.bot.edit_message_text(
                chat_id=ADMIN_CHAT_ID,
                message_id=state["admin_card_id"],
                text=full_card_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
        except Exception:
            msg = await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=full_card_text,
                parse_mode="HTML",
                reply_markup=keyboard
            )
            state["admin_card_id"] = msg.message_id

# ==========================================
# AUTO-REPLY KNOWLEDGE BASE (FIRST PERSON)
# ==========================================
FAQ_KNOWLEDGE_BASE = [
    {
        "intent": "payment_options",
        "triggers": [r"how to pay", r"how do i pay", r"\bpayment\b", r"accept crypto", r"\bcrypto\b", r"\busdt\b", r"\bbtc\b", r"\beth\b", r"\bsol\b", r"pay with"],
        "response": "I accept major cryptocurrencies including USDT (TRC-20 / ERC-20), Bitcoin (BTC), Ethereum (ETH), and Solana (SOL).\n\nSimply tap the payment button above under your selected service to open your direct crypto checkout!"
    },
    {
        "intent": "pricing_rates",
        "triggers": [r"\bprice\b", r"\bpricing\b", r"\brate\b", r"\brates\b", r"\bcost\b", r"how much", r"\bfee\b", r"\bcharge\b"],
        "response": "Here are my current Ember Promo rates:\n• VIP Signals: $200 (4 Months Access)\n• Prop Firm Passing: $200\n• Prop Firm Management: $800\n• 1-on-1 Mentorship: $800\n• Signals + Mentorship Bundle: $800\n\nYou can pick your package directly from the main menu!"
    },
    {
        "intent": "authenticity_proof",
        "triggers": [r"are you real", r"how do i know", r"\bproof\b", r"\bresults\b", r"win rate", r"track record", r"\bscam\b", r"\blegit\b"],
        "response": "My reputation is built on pure market value, consistency, and the verified results of my students. You can follow my setups, check my public channel recaps, and review all breakdowns yourself. My entire focus is on chart analysis and delivering results."
    },
    {
        "intent": "gold_focus",
        "triggers": [r"\bgold\b", r"\bxauusd\b", r"\bpairs\b", r"\bforex\b", r"what do you trade"],
        "response": "I trade exclusively Gold (XAUUSD). Every setup I post comes with explicit entry points, stop losses, and take profit targets based on high-confluence price action."
    },
    {
        "intent": "mentorship_details",
        "triggers": [r"mentorship", r"1 on 1", r"1v1", r"coaching", r"\blearn\b", r"\bteach\b"],
        "response": "My 1-on-1 Mentorship gives you direct access to me, full strategy breakdowns, group call access, and personal guidance so you can master my Gold trading model step-by-step."
    },
    {
        "intent": "prop_firm_passing",
        "triggers": [r"prop firm", r"challenge", r"evaluation", r"\bpass\b", r"funding", r"\bftmo\b", r"goat funded"],
        "response": "I assist you with passing prop firm evaluation challenges on Gold using strict risk management rules to get your account funded safely."
    },
    {
        "intent": "prop_firm_management",
        "triggers": [r"account management", r"manage my account", r"prop firm management", r"pass and manage"],
        "response": "I offer professional prop firm account management on Gold. Once your account is funded, I execute setups strictly following risk parameters to build consistent gains and manage payouts."
    },
    {
        "intent": "bundle_details",
        "triggers": [r"\bbundle\b", r"signals and mentorship", r"\bcombo\b", r"package deal"],
        "response": "The Bundle package gives you full access to both my VIP Gold signals for instant trade copying AND 1-on-1 Mentorship for deep price action breakdowns and direct guidance."
    },
    {
        "intent": "access_duration",
        "triggers": [r"duration", r"how long", r"access period", r"4 months", r"ember promo"],
        "response": "The Ember Promo package grants you a full 4 months of continuous access to my service."
    },
    {
        "intent": "broker_recommendation",
        "triggers": [r"broker", r"spread", r"account type", r"leverage", r"where to trade"],
        "response": "I recommend using low-spread brokers with tight spreads on XAUUSD so your execution matches my setups as closely as possible."
    },
    {
        "intent": "signal_frequency",
        "triggers": [r"how many signals", r"daily signals", r"frequency", r"trades per day"],
        "response": "I focus on quality over quantity. I send high-confluence setups whenever the market presents clear structure and setup validation on Gold."
    },
    {
        "intent": "beginners",
        "triggers": [r"newbie", r"beginner", r"no experience", r"starter", r"new to trading"],
        "response": "Beginners are fully welcome! My service is designed to be easy to follow whether you are copying setups or learning the market model from scratch."
    },
    {
        "intent": "refund_terms",
        "triggers": [r"refund", r"guarantee", r"money back"],
        "response": "Due to the digital nature of my signals, mentorship, and trading insights, all sales are final once access is granted."
    },
    {
        "intent": "human_contact",
        "triggers": [r"talk to you", r"speak to sholly", r"admin", r"owner", r"human", r"\bdm\b"],
        "response": "I have been notified! Give me just a moment and I will reply to you directly right here."
    }
]

# ==========================================
# COMMAND & CALLBACK HANDLERS
# ==========================================
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_handle = f"@{user.username}" if user.username else user.first_name
    get_user_state(user.id)

    welcome_text_1 = (
        f"👋 <b>Welcome! My name is Sholly Pee.</b>\n\n"
        f"My entire focus is giving maximum value, teaching <b>real price action</b>, and helping you scale consistently on Gold.\n\n"
        f"Whether you're here to master my trading model, pass your prop firm challenges, or copy my high-confluence daily setups, this program is built to take your trading journey to a completely different level before the year ends. 📈⚡\n\n"
        f"<blockquote>I don't flaunt a fake lifestyle on social media to lure people in. You'll hardly see me do that, because my focus is strictly on delivering pure value. 🏆</blockquote>"
    )

    try:
        await update.message.reply_photo(
            photo=BANNER_IMAGE_URL,
            caption=welcome_text_1,
            parse_mode="HTML"
        )
    except Exception:
        await update.message.reply_text(welcome_text_1, parse_mode="HTML")

    await update_admin_log_card(context, user.id, user_handle, "<i>[User started the bot]</i>")

    # 15-second typing delay before Welcome Part 2
    await simulate_typing(context, user.id, 15)

    welcome_text_2 = (
        f"⚠️ <b>Trading involves risk. Proper risk management is advised.</b>\n\n"
        f"<blockquote><i>If you are looking for a flashy lifestyle or to make money quick, then unfortunately I can't help you. I believe in consistency, growth, and discipline.</i> 🎯</blockquote>\n\n"
        f"I cannot promise instant wealth, but what I can confidently promise you is a <b>complete transformation</b> of your trading experience. I have guided multiple students to profitability, and all proof is fully verifiable across my socials. ✨\n\n"
        f"To help me serve you best, please select your experience level below:"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔰 New to Trading", callback_data="exp_Newbie")],
        [InlineKeyboardButton("📈 Intermediate / Advanced", callback_data="exp_Intermediate")]
    ])

    await context.bot.send_message(
        chat_id=user.id,
        text=welcome_text_2,
        parse_mode="HTML",
        reply_markup=keyboard
    )

async def button_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user
    state = get_user_state(user.id)
    user_handle = f"@{user.username}" if user.username else user.first_name
    data = query.data

    if data.startswith("exp_"):
        exp_level = data.split("_")[1]
        state["experience"] = exp_level
        await update_admin_log_card(context, user.id, user_handle, f"<b>Selected Exp:</b> {exp_level}")

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 VIP Signals ($200)", callback_data="srv_VIP Signals")],
            [InlineKeyboardButton("🤝 1-on-1 Mentorship ($800)", callback_data="srv_1-on-1 Mentorship")],
            [InlineKeyboardButton("🛡️ Prop Firm Passing ($200)", callback_data="srv_Prop Firm Passing")],
            [InlineKeyboardButton("💼 Prop Firm Management ($800)", callback_data="srv_Prop Firm Management")],
            [InlineKeyboardButton("⚡ VIP Signals + Mentorship Bundle ($800)", callback_data="srv_Signals & Mentorship Bundle")]
        ])

        await query.edit_message_text(
            text=f"Experience set to: <b>{exp_level}</b>\n\nSelect the service you are interested in:",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data == "nav_services":
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📈 VIP Signals ($200)", callback_data="srv_VIP Signals")],
            [InlineKeyboardButton("🤝 1-on-1 Mentorship ($800)", callback_data="srv_1-on-1 Mentorship")],
            [InlineKeyboardButton("🛡️ Prop Firm Passing ($200)", callback_data="srv_Prop Firm Passing")],
            [InlineKeyboardButton("💼 Prop Firm Management ($800)", callback_data="srv_Prop Firm Management")],
            [InlineKeyboardButton("⚡ VIP Signals + Mentorship Bundle ($800)", callback_data="srv_Signals & Mentorship Bundle")]
        ])

        await query.edit_message_text(
            text="Select the service package you want to review:",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data.startswith("srv_"):
        service_name = data.split("_")[1]
        state["service"] = service_name
        
        if service_name in ["1-on-1 Mentorship", "Prop Firm Management", "Signals & Mentorship Bundle"]:
            state["price"] = 800
        else:
            state["price"] = 200

        await update_admin_log_card(context, user.id, user_handle, f"<b>Selected Service:</b> {service_name} (${state['price']})")

        # 15-second typing delay before rendering Profile Summary card
        await simulate_typing(context, user.id, 15)

        checkout_url = generate_crypto_link(user.id, service_name, state["price"])

        summary_text = (
            f"📋 <b>Profile Summary:</b>\n"
            f"• <b>Experience:</b> {state['experience']}\n"
            f"• <b>Selected Service:</b> {service_name}\n"
            f"• <b>Promo Fee:</b> ${state['price']} (4 Months Access)\n\n"
            f"Feel free to ask me any question before completing your setup.\n"
            f"<i>I reply to all DMs as soon as possible!</i>\n\n"
            f"Ready to proceed to payment?"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💳 Pay ${state['price']} with Crypto", url=checkout_url)],
            [InlineKeyboardButton("« Back to Services", callback_data="nav_services")]
        ])

        await context.bot.send_message(
            chat_id=user.id,
            text=summary_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data.startswith("admin_reply:"):
        target_user_id = int(data.split(":")[1])
        context.user_data["reply_target"] = target_user_id
        
        msg = await query.message.reply_text(
            text=f"<b>Reply Mode Active:</b> Type your message below to send directly to user <code>{target_user_id}</code>.",
            parse_mode="HTML"
        )
        # Track temporary prompt ID for deletion
        get_user_state(target_user_id)["temp_alert_ids"].append(msg.message_id)

# ==========================================
# UNIVERSAL MESSAGE HANDLER
# ==========================================
async def universal_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_handle = f"@{user.username}" if user.username else user.first_name
    state = get_user_state(user.id)

    # ------------------------------------------
    # ADMIN REPLY MODE EXECUTION
    # ------------------------------------------
    if user.id == ADMIN_CHAT_ID and "reply_target" in context.user_data:
        target_id = context.user_data.pop("reply_target")
        target_state = get_user_state(target_id)
        
        # Deliver response to client and log permanently
        if update.message.text:
            await context.bot.send_message(chat_id=target_id, text=update.message.text)
            await update_admin_log_card(context, target_id, f"User {target_id}", f"<b>Sholly Pee:</b> {update.message.text}")
        elif update.message.photo:
            photo_file_id = update.message.photo[-1].file_id
            caption = update.message.caption or ""
            await context.bot.send_photo(chat_id=target_id, photo=photo_file_id, caption=caption)
            await update_admin_log_card(context, target_id, f"User {target_id}", f"<b>Sholly Pee:</b> <i>[Sent Photo 📷]</i> {caption}")
        elif update.message.voice:
            await context.bot.send_voice(chat_id=target_id, voice=update.message.voice.file_id)
            await update_admin_log_card(context, target_id, f"User {target_id}", "<b>Sholly Pee:</b> <i>[Sent Voice Note]</i>")
        elif update.message.document:
            await context.bot.send_document(chat_id=target_id, document=update.message.document.file_id)
            await update_admin_log_card(context, target_id, f"User {target_id}", "<b>Sholly Pee:</b> <i>[Sent Document 📄]</i>")

        confirm_msg = await update.message.reply_text("✅ Message delivered.")

        # Cleanup temporary prompts and banners (Keep sent media intact!)
        if update.message.text:
            try:
                await update.message.delete()
            except Exception:
                pass

        await asyncio.sleep(2)
        try:
            await confirm_msg.delete()
        except Exception:
            pass

        for temp_id in target_state["temp_alert_ids"]:
            try:
                await context.bot.delete_message(chat_id=ADMIN_CHAT_ID, message_id=temp_id)
            except Exception:
                pass
        target_state["temp_alert_ids"] = []
        return

    # ------------------------------------------
    # CLIENT INBOUND MEDIA HANDLING (PERMANENT)
    # ------------------------------------------
    if update.message.voice or update.message.photo or update.message.document:
        caption = update.message.caption or ""
        media_type = "Voice Note" if update.message.voice else ("Photo 📷" if update.message.photo else "Document 📄")
        
        await update_admin_log_card(context, user.id, user_handle, f"<b>{user_handle}:</b> <i>[Sent {media_type}]</i> {caption}")
        
        # Forward media permanently to admin chat
        await context.bot.forward_message(
            chat_id=ADMIN_CHAT_ID,
            from_chat_id=user.id,
            message_id=update.message.message_id
        )
        
        # Sound alert ping (Temporary)
        alert_msg = await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"🔔 <b>New {media_type} from {user_handle}</b> (ID: <code>{user.id}</code>)",
            parse_mode="HTML"
        )
        state["temp_alert_ids"].append(alert_msg.message_id)
        return

    # ------------------------------------------
    # CLIENT TEXT & KEYWORD MATCHING
    # ------------------------------------------
    text = update.message.text
    if not text:
        return

    await update_admin_log_card(context, user.id, user_handle, f"<b>{user_handle}:</b> {text}")

    matched_intent = None
    matched_response = None

    for faq in FAQ_KNOWLEDGE_BASE:
        for pattern in faq["triggers"]:
            if re.search(pattern, text, re.IGNORECASE):
                matched_intent = faq["intent"]
                matched_response = faq["response"]
                break
        if matched_intent:
            break

    current_time = time.time()
    if matched_intent:
        # Prevent rapid repetitive spam triggers
        if state["last_intent"] == matched_intent and (current_time - state["last_intent_time"]) < 40:
            return
        
        state["last_intent"] = matched_intent
        state["last_intent_time"] = current_time

        # 20-second typing delay for matched auto-replies
        await simulate_typing(context, user.id, 20)
        await update.message.reply_text(matched_response)
        await update_admin_log_card(context, user.id, user_handle, f"<b>Sholly Pee:</b> {matched_response}")
        return

    # ------------------------------------------
    # SILENT FALLBACK FOR UNMATCHED QUESTIONS
    # ------------------------------------------
    # Bot stays completely silent. Only alerts admin via temporary sound ping.
    alert_msg = await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=f"🔔 <b>New message from {user_handle}:</b> \"{text}\"",
        parse_mode="HTML"
    )
    state["temp_alert_ids"].append(alert_msg.message_id)

# ==========================================
# MAIN EXECUTION
# ==========================================
def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing! Set it in Render Environment variables.")
        return

    # 1. Start background thread for Render Flask web server keep-alive
    threading.Thread(target=start_flask_server, daemon=True).start()

    # 2. Configure asyncio event loop for thread safety
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # 3. Build and configure Telegram Application handlers
    telegram_app = Application.builder().token(BOT_TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CallbackQueryHandler(button_callback_handler))
    telegram_app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, universal_message_handler)
    )

    logger.info("SP Assistant Bot started successfully.")
    
    # 4. Start polling
    telegram_app.run_polling()

if __name__ == "__main__":
    main()

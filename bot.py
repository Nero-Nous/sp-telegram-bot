import os
import logging
import re
import time
import threading
import requests
from typing import Dict, Any
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)

# ==========================================
# FLASK DUMMY SERVER (FOR RENDER FREE TIER)
# ==========================================
web_app = Flask(__name__)

@web_app.route("/")
def health_check():
    return "Bot is running live!", 200

def start_flask_server():
    port = int(os.environ.get("PORT", 10000))
    web_app.run(host="0.0.0.0", port=port)

# ==========================================
# ENVIRONMENT VARIABLES
# ==========================================
BOT_TOKEN = os.environ.get("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.environ.get("ADMIN_CHAT_ID", "0"))
CHANNEL_ID = os.environ.get("CHANNEL_ID")
PLISIO_API_KEY = os.environ.get("PLISIO_API_KEY")
BANNER_IMAGE_URL = os.environ.get(
    "BANNER_IMAGE_URL",
    "https://i.postimg.cc/d3tvHSJf/Picsart-26-08-27-15-27-57-869.jpg"
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

user_data_store: Dict[int, Dict[str, Any]] = {}

def get_user_state(user_id: int) -> Dict[str, Any]:
    if user_id not in user_data_store:
        user_data_store[user_id] = {
            "experience": "Not Selected",
            "service": "Not Selected",
            "price": 200,
            "admin_card_id": None,
            "card_history": [],
            "last_intent": None,
            "last_intent_time": 0,
            "unmatched_count": 0,
        }
    return user_data_store[user_id]

FAQ_KNOWLEDGE_BASE = [
    {
        "intent": "pricing_general",
        "triggers": [r"\bprice\b", r"\bcost\b", r"\bfee\b", r"\bamount\b", r"how much", r"\brate\b", r"\bcharges\b"],
        "response": "SP Trading current rates. Select your desired service in the main menu to generate a direct checkout link for the Ember Promo ($200 for most services, or $800 for 1-on-1 Mentorship)."
    },
    {
        "intent": "ember_promo_duration",
        "triggers": [r"until when", r"ember promo", r"limited time", r"september", r"october", r"november", r"december"],
        "response": "Promo pricing covers your full access for September, October, November, and December. Registration is time-limited."
    },
    {
        "intent": "discount_request",
        "triggers": [r"\bdiscount\b", r"\bcheaper\b", r"any reduction", r"lower price"],
        "response": "These rates ($200 / $800) are already the maximal Ember Discount. They are the lowest rates I will offer for the remainder of the year."
    },
    {
        "intent": "installment_plan",
        "triggers": [r"split payment", r"deposit first", r"pay in parts", r"installment"],
        "response": "To maintain these deeply discounted promotional rates, I require full payment upfront. I do not offer installment plans for the Ember Promo."
    },
    {
        "intent": "promo_pricing_structure",
        "triggers": [r"all services \$?200", r"is the promo for each", r"individual price", r"total price"],
        "response": "The Ember Promo of $200 applies to each individual service (VIP Signals, Group Mentorship, Prop Support, Weekly Analysis) for the entire 4-month period. My 1-on-1 Mentorship is $800 for the same period. Select your service in the menu to see the precise price."
    },
    {
        "intent": "signals_content",
        "triggers": [r"signals channel", r"included in signals", r"what do i get in vip"],
        "response": "Includes 3 to 5 daily High-Confluence Gold setups, real-time trade updates, weekend market reviews, and periodic Group Calls to break down the logic."
    },
    {
        "intent": "signals_frequency",
        "triggers": [r"daily signals", r"per day", r"trades a day", r"which sessions", r"time zones"],
        "response": "3 to 5 setups daily, primarily on Gold. I focus on high-volume market periods. All signals include Entry, SL, and TP parameters, so you can copy them in any time zone."
    },
    {
        "intent": "mentorship_models",
        "triggers": [r"what is mentorship", r"coaching details", r"training content"],
        "response": "VIP Group Mentorship ($200) covers access to educational materials, group Q&A, and market breakdowns. 1-on-1 Private Mentorship ($800) is personalized coaching, live trade monitoring, and direct line access."
    },
    {
        "intent": "mentorship_one_on_one",
        "triggers": [r"1 on 1 specifics", r"personal mentor", r"direct access"],
        "response": "Intensive training on my personal model, live calls with me, personal market insights, weekend summaries, direct monitoring and correction of your shared trades, and access to my personal skill and experience at arranged meeting times."
    },
    {
        "intent": "prop_challenge_support",
        "triggers": [r"\bftmo\b", r"prop firm", r"funded pips", r"pass challenge"],
        "response": "Dedicated guidance to help you pass prop firm challenges using signals formatted for strict prop risk parameters. Select 'Passing Prop Challenges' to get started."
    },
    {
        "intent": "weekly_analysis_details",
        "triggers": [r"weekly analysis", r"chart breakdowns", r"what do i get in weekly"],
        "response": "Includes deep multi-timeframe structural analysis on Gold, key institutional liquidity zones, and my personal market outlook delivered weekly to keep you prepared."
    },
    {
        "intent": "strategy_inquiry",
        "triggers": [r"what strategy", r"strategy details", r"teach me strategy", r"explain strategy"],
        "response": "Sorry, I cannot discuss the intimate details of my private strategy or model for free. To access that information and my extensive skills and experience, you must join my VIP community first."
    },
    {
        "intent": "win_rate_accuracy",
        "triggers": [r"win rate", r"accuracy", r"success rate", r"losing trades"],
        "response": "While no strategy wins 100% of the time, I maintain a consistent 75%+ win rate. I focus on giving you real market value and information, protecting your account. You can count on my consistency and experience."
    },
    {
        "intent": "guarantee_profits",
        "triggers": [r"\bguarantee\b", r"sure money", r"sure profits", r"get rich quick"],
        "response": "I cannot guarantee profits, and trading financial markets carries risk. Anyone promising guaranteed returns is likely a scammer. I do not offer a get rich quick strategy, but I promise after these 4 months, your trading journey will be on a very different level."
    },
    {
        "intent": "drawdown_risk_management",
        "triggers": [r"drawdown", r"max loss", r"how much risk", r"drawdown rules"],
        "response": "Losses are inevitable. I do not use static percentage risk rules. Risk management is dynamic based entirely on my market setup and current price action. To grow a trading account, you must manage risk carefully, following the rules I provide to keep your account safe."
    },
    {
        "intent": "minimum_capital",
        "triggers": [r"minimum capital", r"how much money to start", r"starter balance"],
        "response": "I specialize in Gold. You can start with as little as $100 on a standard broker, but utilize prop firm capital ($5k+) whenever possible to maximize returns while controlling your personal risk."
    },
    {
        "intent": "markets_traded",
        "triggers": [r"what markets", r"forex only", r"do you trade crypto", r"\bgold\b", r"xauusd"],
        "response": "I specialize exclusively in Gold (XAUUSD). It is the single highest-probability asset I track, allowing me to maintain deep focus and superior results."
    },
    {
        "intent": "newbie_suitability",
        "triggers": [r"newbie", r"no experience", r"beginner suitability", r"total starter"],
        "response": "You don't need prior experience. The VIP Signals are formatted simply so you can copy and paste them, and my Mentorship programs are designed to teach you step-by-step from zero."
    },
    {
        "intent": "crypto_reasoning",
        "triggers": [r"why only crypto", r"crypto payments", r"is card available", r"send to bank"],
        "response": "I accept Cryptocurrency securely via Plisio for Bitcoin, Ethereum, Solana, and USDT. This is primarily because my community is global, and Crypto allows the fastest, safest, lowest-fee processing from any country without reliance on unstable international banking systems."
    },
    {
        "intent": "usdt_network_warning",
        "triggers": [r"\busdt\b", r"tether network", r"\berc20\b", r"\btrc20\b"],
        "response": "IMPORTANT: If you are paying with USDT, you MUST use the TRON (TRC-20) network. This ensures the lowest gas fees and fastest verification. Sending via other networks like ERC-20 will result in permanent loss of your funds."
    },
    {
        "intent": "accepted_payment_methods",
        "triggers": [r"accepted payments", r"how to pay", r"can i pay paypal"],
        "response": "I accept Cryptocurrency securely via Plisio (Bitcoin, Ethereum, Solana, and USDT). Crypto allows the fastest, safest processing from anywhere in the world without traditional bank delays or network failures. Tap the payment button in the menu to generate your direct checkout link."
    },
    {
        "intent": "payment_verification",
        "triggers": [r"sent payment", r"confirm payment", r"did you receive", r"verification", r"receipt", r"screenshot"],
        "response": "The system automatically verifies your transaction on-chain (typically 5 to 30 mins). Once confirmed, the bot will instantly generate your unique VIP invite link. There is no need to send screenshots of your payment receipt."
    },
    {
        "intent": "recommended_broker",
        "triggers": [r"broker link", r"headway", r"regulated broker", r"goat funded"],
        "response": "I partner with Headway for standard brokerage accounts. For prop firm capital challenges, I recommend Goat Funded, as I have consistently excellent results with their execution and drawdown rules."
    },
    {
        "intent": "trading_platform",
        "triggers": [r"\bmt4\b", r"\bmt5\b", r"platform", r"metatrader", r"tradingview"],
        "response": "My signals are executed on MetaTrader 5 (MT5), which provides the speed and tools I need for Gold. For deep chart analysis and preparation, I use and recommend TradingView."
    },
    {
        "intent": "signal_execution",
        "triggers": [r"how do i copy", r"input signals", r"instruction"],
        "response": "Open XAUUSD on MT5, select the order type (Buy/Sell), carefully input the exact SL and TP prices I provide, and click execute."
    },
    {
        "intent": "identity_verification",
        "triggers": [r"are you real", r"is this scam", r"trustworthy", r"\blegit\b", r"real mentor"],
        "response": "Yes, I am real. My reputation is built on pure market value, consistency, and the results of my members. You can follow my setups, check my public channel recaps, and see the breakdown for yourself. I focus 100% of my energy on chart analysis and delivering value to my group."
    },
    {
        "intent": "proof_of_results",
        "triggers": [r"proof of profits", r"trade screenshots", r"withdrawals"],
        "response": "I post regular trade recaps, weekend market reviews, and client success feedback in my public channel. I prioritize real market information over flash, and I assure you after 4 months with me, your journey will be on a very different level."
    },
    {
        "intent": "contact_fallback",
        "triggers": [r"\bhelp\b", r"\boptions\b", r"talk to human", r"human support"],
        "response": "Use the /start menu to access pricing and services. If you have a complex technical question, just type it clearly in one message, and I will reply as soon as possible."
    },
    {
        "intent": "broker_regulation",
        "triggers": [r"regulated prop", r"broker regulated", r"safety of broker"],
        "response": "I do not operate as a broker or liquidity provider. I recommend Headway as a reputable brokerage."
    },
    {
        "intent": "multiple_accounts",
        "triggers": [r"multiple accounts", r"share signals", r"ban policy"],
        "response": "A single VIP subscription grants access for one user only. Sharing signals, account forwarding, or access sharing will result in an immediate permanent ban without refund."
    },
    {
        "intent": "refund_policy",
        "triggers": [r"money back", r"unhappy", r"refund policy", r"cancellation"],
        "response": "Due to the dynamic nature of digital services, signals, and private mentorship coaching, I maintain a strict No Refunds policy once access is granted."
    }
]

IMPATIENCE_PATTERN = re.compile(r"(\?{2,}|hello\??|🙄|please reply|sir\??|are you there)", re.IGNORECASE)

def generate_plisio_link(user_id: int, service_name: str, price: int) -> str:
    if not PLISIO_API_KEY:
        logger.error("PLISIO_API_KEY is missing from environment variables.")
        return f"https://plisio.net/pay/checkout_{user_id}"

    url = "https://api.plisio.net/api/v1/invoices/new"
    params = {
        "api_key": PLISIO_API_KEY,
        "amount": str(price),
        "currency": "USD",
        "order_name": f"SP Trading - {service_name}",
        "order_number": f"{user_id}_{int(time.time())}",
        "callback_url": "https://yourdomain.com/plisio_webhook"
    }
    try:
        res = requests.get(url, params=params, timeout=10).json()
        if res.get("status") == "success":
            return res["data"]["invoice_url"]
    except Exception as e:
        logger.error(f"Plisio API error: {e}")
    
    return f"https://plisio.net/pay/checkout_{user_id}"

async def update_admin_log_card(context: ContextTypes.DEFAULT_TYPE, user_id: int, user_handle: str, new_entry: str):
    if not ADMIN_CHAT_ID:
        logger.error("ADMIN_CHAT_ID is missing from environment variables.")
        return

    state = get_user_state(user_id)
    state["card_history"].append(new_entry)
    
    header = (
        f"<b>CONVERSATION LOG:</b> {user_handle} (ID: <code>{user_id}</code>)\n"
        f"<b>Exp:</b> {state['experience']} | <b>Interest:</b> {state['service']}\n"
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

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    state = get_user_state(user.id)
    user_handle = f"@{user.username}" if user.username else user.first_name

    welcome_text_1 = (
        f"<b>Welcome! I'm Sholly Pee.</b>\n\n"
        f"Most people enter these markets looking for quick gains, only to lose capital because they lack structure, patience, and real market guidance. "
        f"I don't flaunt a fake lifestyle on social media to lure people in, my entire focus is giving maximum value, teaching real price action, and helping you scale consistently on Gold.\n\n"
        f"Whether you're here to master my trading model, pass your prop firm challenges, or copy my high-confluence daily setups, this Ember Month program is built to take your trading journey to a completely different level before the year ends.\n\n"
        f"<i>Trading involves risk. Proper risk management is advised.</i>"
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

    welcome_text_2 = (
        "Feel free to type and ask me any questions, I reply to all DMs as soon as possible!\n\n"
        "To help me serve you best and get you set up, please select your experience level below:"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔰 New to Trading", callback_data="exp_Newbie")],
        [InlineKeyboardButton("📈 Intermediate", callback_data="exp_Intermediate")],
        [InlineKeyboardButton("⚡ Advanced", callback_data="exp_Advanced")]
    ])

    await context.bot.send_message(
        chat_id=user.id,
        text=welcome_text_2,
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
            [InlineKeyboardButton("📊 VIP Signals", callback_data="srv_VIP Signals")],
            [InlineKeyboardButton("👥 VIP Group Mentorship", callback_data="srv_VIP Group Mentorship")],
            [InlineKeyboardButton("🤝 1-on-1 Mentorship", callback_data="srv_1-on-1 Mentorship")],
            [InlineKeyboardButton("🏆 Passing Prop Challenges", callback_data="srv_Passing Prop Challenges")],
            [InlineKeyboardButton("📝 WEEKLY CHART ANALYSIS", callback_data="srv_WEEKLY CHART ANALYSIS")]
        ])

        await query.edit_message_text(
            text=f"Experience set to: <b>{exp_level}</b>\n\nNow, select the service you are interested in:",
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data.startswith("srv_"):
        service_name = data.split("_")[1]
        state["service"] = service_name
        
        if service_name == "1-on-1 Mentorship":
            state["price"] = 800
        else:
            state["price"] = 200

        await update_admin_log_card(context, user.id, user_handle, f"<b>Selected Service:</b> {service_name} (${state['price']})")

        checkout_url = generate_plisio_link(user.id, service_name, state["price"])

        summary_text = (
            f"<b>Profile Summary:</b>\n"
            f"• <b>Experience:</b> {state['experience']}\n"
            f"• <b>Service:</b> {service_name}\n"
            f"• <b>Promo Fee:</b> ${state['price']} (4 Months Access)\n\n"
            f"Feel free to ask any question before completing your setup.\n"
            f"<i>I reply to all DMs as soon as possible!</i>\n\n"
            f"Ready to proceed to payment?"
        )

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"💳 Pay ${state['price']} with Crypto (Plisio)", url=checkout_url)]
        ])

        await query.edit_message_text(
            text=summary_text,
            parse_mode="HTML",
            reply_markup=keyboard
        )

    elif data.startswith("admin_reply:"):
        target_user_id = int(data.split(":")[1])
        context.user_data["reply_target"] = target_user_id
        await query.message.reply_text(
            text=f"<b>Reply Mode Active:</b> Type your message below to send directly to user <code>{target_user_id}</code>.",
            parse_mode="HTML"
        )

async def universal_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_handle = f"@{user.username}" if user.username else user.first_name
    state = get_user_state(user.id)

    if user.id == ADMIN_CHAT_ID and "reply_target" in context.user_data:
        target_id = context.user_data.pop("reply_target")
        if update.message.text:
            await context.bot.send_message(chat_id=target_id, text=update.message.text)
            await update_admin_log_card(context, target_id, f"User {target_id}", f"<b>Sholly Pee:</b> {update.message.text}")
            await update.message.reply_text("✅ Message delivered.")
        elif update.message.voice:
            await context.bot.send_voice(chat_id=target_id, voice=update.message.voice.file_id)
            await update_admin_log_card(context, target_id, f"User {target_id}", "<b>Sholly Pee:</b> <i>[Sent Voice Note]</i>")
            await update.message.reply_text("✅ Voice note delivered.")
        return

    if update.message.voice or update.message.photo or update.message.document:
        caption = update.message.caption or ""
        media_type = "Voice Note" if update.message.voice else ("Photo" if update.message.photo else "Document")
        
        await update_admin_log_card(context, user.id, user_handle, f"<b>{user_handle}:</b> <i>[Sent {media_type}]</i> {caption}")
        
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("💬 Reply to Client", callback_data=f"admin_reply:{user.id}")
        ]])
        
        await context.bot.forward_message(
            chat_id=ADMIN_CHAT_ID,
            from_chat_id=user.id,
            message_id=update.message.message_id
        )
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"Media received from {user_handle} (ID: <code>{user.id}</code>)",
            parse_mode="HTML",
            reply_markup=keyboard
        )
        return

    text = update.message.text
    if not text:
        return

    await update_admin_log_card(context, user.id, user_handle, f"<b>{user_handle}:</b> {text}")

    if IMPATIENCE_PATTERN.search(text):
        state["unmatched_count"] += 1
        handoff_msg = "This is an automated response. I reply to all DMs as soon as possible!"
        await update.message.reply_text(handoff_msg)
        await update_admin_log_card(context, user.id, user_handle, f"<b>Bot (Handoff):</b> {handoff_msg}")
        return

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
        if state["last_intent"] == matched_intent and (current_time - state["last_intent_time"]) < 50:
            return
        
        state["last_intent"] = matched_intent
        state["last_intent_time"] = current_time
        state["unmatched_count"] = 0

        await update.message.reply_text(matched_response)
        await update_admin_log_card(context, user.id, user_handle, f"<b>Bot:</b> {matched_response}")
        return

    state["unmatched_count"] += 1
    if state["unmatched_count"] >= 4:
        handoff_msg = "This is an automated response. I reply to all DMs as soon as possible!"
        await update.message.reply_text(handoff_msg)
        await update_admin_log_card(context, user.id, user_handle, f"<b>Bot (Handoff):</b> {handoff_msg}")
        state["unmatched_count"] = 0

def main():
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN is missing! Set it in Render Environment variables.")
        return

    # Start Flask dummy web server on a background thread
    threading.Thread(target=start_flask_server, daemon=True).start()

    # Build and start Telegram Application cleanly
    telegram_app = Application.builder().token(BOT_TOKEN).build()

    telegram_app.add_handler(CommandHandler("start", start_command))
    telegram_app.add_handler(CallbackQueryHandler(button_callback_handler))
    telegram_app.add_handler(
        MessageHandler(filters.ALL & ~filters.COMMAND, universal_message_handler)
    )

    logger.info("SP Assistant Bot started successfully.")
    
    # Simple, standard polling start without loop overrides
    telegram_app.run_polling()

if __name__ == "__main__":
    main()

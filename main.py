import os
import io
import uuid
import asyncio
import threading
import requests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from datetime import datetime, timezone
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

COINGECKO_API = "https://api.coingecko.com/api/v3"
EXCHANGE_RATE_API = "https://api.exchangerate-api.com/v4/latest/USD"
PAGE_SIZE = 10
ALERT_CHECK_INTERVAL = 60
DAILY_UPDATE_HOUR = 9

# ---------------------------------------------------------------------------
# Global stores
# ---------------------------------------------------------------------------

alerts: dict[int, list[dict]] = {}
portfolios: dict[int, dict[str, dict]] = {}
user_prefs: dict[int, dict] = {}
subscribers: set[int] = set()
exchange_rates: dict[str, float] = {"RUB": 90.0, "UZS": 12500.0}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_pref(user_id: int, key: str, default=None):
    return user_prefs.get(user_id, {}).get(key, default)


def set_pref(user_id: int, key: str, value):
    user_prefs.setdefault(user_id, {})[key] = value


def get_lang(user_id: int) -> str:
    return get_pref(user_id, "lang", "en")


def t(user_id: int, key: str) -> str:
    lang = get_lang(user_id)
    return STRINGS.get(lang, STRINGS["en"]).get(key, STRINGS["en"].get(key, key))


def fmt_price(usd: float, user_id: int) -> str:
    currency = get_pref(user_id, "currency", "USD")
    rate = exchange_rates.get(currency, 1.0)
    value = usd * rate
    symbols = {"USD": "$", "RUB": "₽", "UZS": "so'm"}
    sym = symbols.get(currency, currency)
    if value >= 1:
        return f"{sym}{value:,.2f}"
    return f"{sym}{value:.6f}"


def refresh_exchange_rates():
    global exchange_rates
    try:
        r = requests.get(EXCHANGE_RATE_API, timeout=10)
        data = r.json()
        rates = data.get("rates", {})
        exchange_rates["RUB"] = rates.get("RUB", 90.0)
        exchange_rates["UZS"] = rates.get("UZS", 12500.0)
    except Exception:
        pass


def fetch_top_coins(page: int = 1, per_page: int = PAGE_SIZE) -> list[dict]:
    try:
        r = requests.get(
            f"{COINGECKO_API}/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": per_page,
                "page": page,
                "sparkline": False,
                "price_change_percentage": "24h",
            },
            timeout=15,
        )
        return r.json() if r.ok else []
    except Exception:
        return []


def fetch_coin(coin_id: str) -> dict | None:
    try:
        r = requests.get(
            f"{COINGECKO_API}/coins/{coin_id}",
            params={"localization": False, "tickers": False, "community_data": False},
            timeout=15,
        )
        return r.json() if r.ok else None
    except Exception:
        return None


def search_coins(query: str) -> list[dict]:
    try:
        r = requests.get(
            f"{COINGECKO_API}/search",
            params={"query": query},
            timeout=15,
        )
        return r.json().get("coins", [])[:10] if r.ok else []
    except Exception:
        return []


def fetch_chart(coin_id: str, days: int = 7) -> bytes | None:
    try:
        r = requests.get(
            f"{COINGECKO_API}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": days},
            timeout=20,
        )
        if not r.ok:
            return None
        prices = r.json().get("prices", [])
        if not prices:
            return None
        times = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in prices]
        values = [p[1] for p in prices]
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.plot(times, values, linewidth=1.5, color="#00b4d8")
        ax.fill_between(times, values, alpha=0.15, color="#00b4d8")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
        ax.xaxis.set_major_locator(mdates.AutoDateLocator())
        plt.xticks(rotation=30, ha="right")
        ax.set_title(f"{coin_id.upper()} — {days}d price (USD)", fontsize=13)
        ax.set_ylabel("USD")
        ax.grid(True, alpha=0.3)
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format="png", dpi=120)
        plt.close(fig)
        buf.seek(0)
        return buf.read()
    except Exception:
        return None


def fetch_gainers() -> list[dict]:
    coins = fetch_top_coins(page=1, per_page=100)
    return sorted(
        [c for c in coins if c.get("price_change_percentage_24h") is not None],
        key=lambda c: c["price_change_percentage_24h"],
        reverse=True,
    )[:10]


def fetch_losers() -> list[dict]:
    coins = fetch_top_coins(page=1, per_page=100)
    return sorted(
        [c for c in coins if c.get("price_change_percentage_24h") is not None],
        key=lambda c: c["price_change_percentage_24h"],
    )[:10]


# ---------------------------------------------------------------------------
# Language strings
# ---------------------------------------------------------------------------

STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "lang_name": "🇬🇧 English",
        "welcome_menu": (
            "👋 *Welcome to CryptoBot!*\n\n"
            "🔥 Real-time crypto prices in *USD, RUB & UZS*\n"
            "📊 Track top coins, search any coin, set alerts & more.\n\n"
            "_Choose an option below:_"
        ),
        "help_text": (
            "*📖 Available Commands*\n\n"
            "/prices — Top 50 crypto prices\n"
            "/search <coin> — Search any coin + chart\n"
            "/gainers — Top 10 gainers (24h)\n"
            "/losers — Top 10 losers (24h)\n"
            "/alert <coin> <above|below> <price> — Set price alert\n"
            "/myalerts — View your alerts\n"
            "/portfolio — View your portfolio\n"
            "/addcoin <coin> <amount> — Add coin to portfolio\n"
            "/removecoin <coin> — Remove coin from portfolio\n"
            "/subscribe — Subscribe to daily updates\n"
            "/unsubscribe — Unsubscribe from daily updates\n"
            "/currency — Change display currency\n"
            "/language — Change language\n"
            "/help — Show this help\n"
        ),
        "no_results": "❌ No results found.",
        "error": "⚠️ Something went wrong. Please try again.",
        "alert_set": "✅ Alert set: {coin} {direction} ${price:.4f}",
        "alert_triggered": "🔔 *Alert triggered!*\n{coin} is now ${price:.4f} ({direction} your target of ${target:.4f})",
        "no_alerts": "You have no active alerts.",
        "alerts_header": "*Your Alerts:*\n",
        "portfolio_empty": "Your portfolio is empty. Use /addcoin <coin> <amount>.",
        "portfolio_header": "*Your Portfolio:*\n",
        "portfolio_total": "\n💰 *Total value: {total}*",
        "coin_added": "✅ Added {amount} {coin} to your portfolio.",
        "coin_removed": "✅ Removed {coin} from your portfolio.",
        "coin_not_found_portfolio": "❌ {coin} not found in your portfolio.",
        "subscribed": "✅ Subscribed to daily updates at 09:00 UTC.",
        "unsubscribed": "✅ Unsubscribed from daily updates.",
        "currency_prompt": "Choose your display currency:",
        "currency_set": "✅ Currency set to {currency}.",
        "language_prompt": "Choose your language:",
        "prev": "⬅️ Prev",
        "next": "➡️ Next",
        "page": "Page {page}",
        "chart_7d": "📈 7d chart",
        "chart_30d": "📅 30d chart",
        "back": "🔙 Back",
        "gainers_header": "*🚀 Top 10 Gainers (24h):*\n",
        "losers_header": "*📉 Top 10 Losers (24h):*\n",
        "daily_update": "*📊 Daily Crypto Update*\n\n",
        "usage_search": "Usage: /search <coin name or symbol>",
        "usage_alert": "Usage: /alert <coin_id> <above|below> <price>",
        "usage_addcoin": "Usage: /addcoin <coin_id> <amount>",
        "usage_removecoin": "Usage: /removecoin <coin_id>",
        "invalid_price": "❌ Invalid price value.",
        "invalid_amount": "❌ Invalid amount value.",
        "invalid_direction": "❌ Direction must be 'above' or 'below'.",
    },
    "ru": {
        "lang_name": "🇷🇺 Русский",
        "welcome_menu": (
            "👋 *Добро пожаловать в CryptoBot!*\n\n"
            "🔥 Цены криптовалют в реальном времени в *USD, RUB и UZS*\n"
            "📊 Топ монет, поиск, алерты и многое другое.\n\n"
            "_Выберите опцию ниже:_"
        ),
        "help_text": (
            "*📖 Доступные команды*\n\n"
            "/prices — Топ 50 криптовалют\n"
            "/search <монета> — Поиск монеты + график\n"
            "/gainers — Топ 10 роста (24ч)\n"
            "/losers — Топ 10 падения (24ч)\n"
            "/alert <монета> <above|below> <цена> — Установить алерт\n"
            "/myalerts — Мои алерты\n"
            "/portfolio — Мой портфель\n"
            "/addcoin <монета> <количество> — Добавить монету\n"
            "/removecoin <монета> — Удалить монету\n"
            "/subscribe — Подписаться на ежедневные обновления\n"
            "/unsubscribe — Отписаться\n"
            "/currency — Изменить валюту\n"
            "/language — Изменить язык\n"
            "/help — Показать помощь\n"
        ),
        "no_results": "❌ Ничего не найдено.",
        "error": "⚠️ Что-то пошло не так. Попробуйте снова.",
        "alert_set": "✅ Алерт установлен: {coin} {direction} ${price:.4f}",
        "alert_triggered": "🔔 *Алерт сработал!*\n{coin} теперь ${price:.4f} ({direction} вашей цели ${target:.4f})",
        "no_alerts": "У вас нет активных алертов.",
        "alerts_header": "*Ваши алерты:*\n",
        "portfolio_empty": "Ваш портфель пуст. Используйте /addcoin <монета> <количество>.",
        "portfolio_header": "*Ваш портфель:*\n",
        "portfolio_total": "\n💰 *Итого: {total}*",
        "coin_added": "✅ Добавлено {amount} {coin} в портфель.",
        "coin_removed": "✅ {coin} удалён из портфеля.",
        "coin_not_found_portfolio": "❌ {coin} не найден в портфеле.",
        "subscribed": "✅ Подписка на ежедневные обновления в 09:00 UTC.",
        "unsubscribed": "✅ Вы отписались от ежедневных обновлений.",
        "currency_prompt": "Выберите валюту отображения:",
        "currency_set": "✅ Валюта изменена на {currency}.",
        "language_prompt": "Выберите язык:",
        "prev": "⬅️ Назад",
        "next": "➡️ Вперёд",
        "page": "Страница {page}",
        "chart_7d": "📈 График 7д",
        "chart_30d": "📅 График 30д",
        "back": "🔙 Назад",
        "gainers_header": "*🚀 Топ 10 роста (24ч):*\n",
        "losers_header": "*📉 Топ 10 падения (24ч):*\n",
        "daily_update": "*📊 Ежедневное обновление крипты*\n\n",
        "usage_search": "Использование: /search <название или символ монеты>",
        "usage_alert": "Использование: /alert <coin_id> <above|below> <цена>",
        "usage_addcoin": "Использование: /addcoin <coin_id> <количество>",
        "usage_removecoin": "Использование: /removecoin <coin_id>",
        "invalid_price": "❌ Неверное значение цены.",
        "invalid_amount": "❌ Неверное количество.",
        "invalid_direction": "❌ Направление должно быть 'above' или 'below'.",
    },
    "uz": {
        "lang_name": "🇺🇿 O'zbek",
        "welcome_menu": (
            "👋 *CryptoBotga xush kelibsiz!*\n\n"
            "🔥 Real vaqtda kripto narxlari *USD, RUB va UZS*da\n"
            "📊 Top tangalar, qidiruv, ogohlantirishlar va boshqalar.\n\n"
            "_Quyidagi variantni tanlang:_"
        ),
        "help_text": (
            "*📖 Mavjud buyruqlar*\n\n"
            "/prices — Top 50 kripto narxlari\n"
            "/search <tanga> — Tanga qidirish + grafik\n"
            "/gainers — Top 10 o'suvchi (24s)\n"
            "/losers — Top 10 tushuvchi (24s)\n"
            "/alert <tanga> <above|below> <narx> — Ogohlantirish o'rnatish\n"
            "/myalerts — Mening ogohlantirishlarim\n"
            "/portfolio — Mening portfoliom\n"
            "/addcoin <tanga> <miqdor> — Tanga qo'shish\n"
            "/removecoin <tanga> — Tangani o'chirish\n"
            "/subscribe — Kunlik yangilanishlarga obuna\n"
            "/unsubscribe — Obunani bekor qilish\n"
            "/currency — Valyutani o'zgartirish\n"
            "/language — Tilni o'zgartirish\n"
            "/help — Yordam ko'rsatish\n"
        ),
        "no_results": "❌ Hech narsa topilmadi.",
        "error": "⚠️ Xatolik yuz berdi. Qayta urinib ko'ring.",
        "alert_set": "✅ Ogohlantirish o'rnatildi: {coin} {direction} ${price:.4f}",
        "alert_triggered": "🔔 *Ogohlantirish ishga tushdi!*\n{coin} endi ${price:.4f} ({direction} maqsadingiz ${target:.4f})",
        "no_alerts": "Sizda faol ogohlantirishlar yo'q.",
        "alerts_header": "*Sizning ogohlantirishlaringiz:*\n",
        "portfolio_empty": "Portfoliongiz bo'sh. /addcoin <tanga> <miqdor> dan foydalaning.",
        "portfolio_header": "*Sizning portfoliongiz:*\n",
        "portfolio_total": "\n💰 *Jami: {total}*",
        "coin_added": "✅ {amount} {coin} portfolioga qo'shildi.",
        "coin_removed": "✅ {coin} portfoliodan o'chirildi.",
        "coin_not_found_portfolio": "❌ {coin} portfolioda topilmadi.",
        "subscribed": "✅ 09:00 UTC da kunlik yangilanishlarga obuna bo'ldingiz.",
        "unsubscribed": "✅ Kunlik yangilanishlardan obuna bekor qilindi.",
        "currency_prompt": "Ko'rsatish valyutasini tanlang:",
        "currency_set": "✅ Valyuta {currency} ga o'zgartirildi.",
        "language_prompt": "Tilni tanlang:",
        "prev": "⬅️ Oldingi",
        "next": "➡️ Keyingi",
        "page": "Sahifa {page}",
        "chart_7d": "📈 7k grafik",
        "chart_30d": "📅 30k grafik",
        "back": "🔙 Orqaga",
        "gainers_header": "*🚀 Top 10 o'suvchi (24s):*\n",
        "losers_header": "*📉 Top 10 tushuvchi (24s):*\n",
        "daily_update": "*📊 Kunlik kripto yangilanishi*\n\n",
        "usage_search": "Foydalanish: /search <tanga nomi yoki belgisi>",
        "usage_alert": "Foydalanish: /alert <coin_id> <above|below> <narx>",
        "usage_addcoin": "Foydalanish: /addcoin <coin_id> <miqdor>",
        "usage_removecoin": "Foydalanish: /removecoin <coin_id>",
        "invalid_price": "❌ Noto'g'ri narx qiymati.",
        "invalid_amount": "❌ Noto'g'ri miqdor.",
        "invalid_direction": "❌ Yo'nalish 'above' yoki 'below' bo'lishi kerak.",
    },
}

# ---------------------------------------------------------------------------
# Keyboards
# ---------------------------------------------------------------------------

def main_menu_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("💰 Prices", callback_data="menu_prices_1"),
            InlineKeyboardButton("🔍 Search", callback_data="menu_search"),
        ],
        [
            InlineKeyboardButton("🚀 Gainers", callback_data="menu_gainers"),
            InlineKeyboardButton("📉 Losers", callback_data="menu_losers"),
        ],
        [
            InlineKeyboardButton("🔔 My Alerts", callback_data="menu_alerts"),
            InlineKeyboardButton("💼 Portfolio", callback_data="menu_portfolio"),
        ],
        [
            InlineKeyboardButton("⚙️ Settings", callback_data="menu_settings"),
            InlineKeyboardButton("❓ Help", callback_data="menu_help"),
        ],
    ])


def prices_keyboard(page: int, total_pages: int, user_id: int) -> InlineKeyboardMarkup:
    buttons = []
    nav = []
    if page > 1:
        nav.append(InlineKeyboardButton(t(user_id, "prev"), callback_data=f"prices_{page - 1}"))
    nav.append(InlineKeyboardButton(t(user_id, "page").format(page=page), callback_data="noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(t(user_id, "next"), callback_data=f"prices_{page + 1}"))
    buttons.append(nav)
    buttons.append([InlineKeyboardButton(t(user_id, "back"), callback_data="menu_main")])
    return InlineKeyboardMarkup(buttons)


def coin_keyboard(coin_id: str, user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(user_id, "chart_7d"), callback_data=f"chart_{coin_id}_7"),
            InlineKeyboardButton(t(user_id, "chart_30d"), callback_data=f"chart_{coin_id}_30"),
        ],
        [InlineKeyboardButton(t(user_id, "back"), callback_data="menu_main")],
    ])


def settings_keyboard(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("💱 Currency", callback_data="settings_currency")],
        [InlineKeyboardButton("🌐 Language", callback_data="settings_language")],
        [InlineKeyboardButton(t(user_id, "back"), callback_data="menu_main")],
    ])


def currency_keyboard(user_id: int) -> InlineKeyboardMarkup:
    currencies = ["USD", "RUB", "UZS"]
    buttons = [[InlineKeyboardButton(c, callback_data=f"setcurrency_{c}") for c in currencies]]
    buttons.append([InlineKeyboardButton(t(user_id, "back"), callback_data="menu_settings")])
    return InlineKeyboardMarkup(buttons)


def language_keyboard(user_id: int) -> InlineKeyboardMarkup:
    langs = [("en", "🇬🇧 English"), ("ru", "🇷🇺 Русский"), ("uz", "🇺🇿 O'zbek")]
    buttons = [[InlineKeyboardButton(name, callback_data=f"setlang_{code}") for code, name in langs]]
    buttons.append([InlineKeyboardButton(t(user_id, "back"), callback_data="menu_settings")])
    return InlineKeyboardMarkup(buttons)


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

def build_prices_text(coins: list[dict], user_id: int) -> str:
    lines = []
    for i, c in enumerate(coins, 1):
        price = c.get("current_price", 0)
        change = c.get("price_change_percentage_24h", 0) or 0
        arrow = "🟢" if change >= 0 else "🔴"
        lines.append(
            f"{i}. *{c['name']}* ({c['symbol'].upper()})\n"
            f"   {fmt_price(price, user_id)} {arrow} {change:+.2f}%"
        )
    return "\n".join(lines)


def build_coin_text(data: dict, user_id: int) -> str:
    md = data.get("market_data", {})
    price = md.get("current_price", {}).get("usd", 0)
    change_24h = md.get("price_change_percentage_24h", 0) or 0
    change_7d = md.get("price_change_percentage_7d", 0) or 0
    market_cap = md.get("market_cap", {}).get("usd", 0)
    volume = md.get("total_volume", {}).get("usd", 0)
    high = md.get("high_24h", {}).get("usd", 0)
    low = md.get("low_24h", {}).get("usd", 0)
    arrow_24h = "🟢" if change_24h >= 0 else "🔴"
    arrow_7d = "🟢" if change_7d >= 0 else "🔴"
    return (
        f"*{data['name']}* ({data['symbol'].upper()})\n\n"
        f"💵 Price: {fmt_price(price, user_id)}\n"
        f"24h: {arrow_24h} {change_24h:+.2f}%\n"
        f"7d:  {arrow_7d} {change_7d:+.2f}%\n\n"
        f"📊 Market Cap: ${market_cap:,.0f}\n"
        f"📦 Volume 24h: ${volume:,.0f}\n"
        f"⬆️ High 24h: ${high:,.4f}\n"
        f"⬇️ Low 24h:  ${low:,.4f}"
    )


def build_gainers_losers_text(coins: list[dict], header: str, user_id: int) -> str:
    lines = [header]
    for i, c in enumerate(coins, 1):
        change = c.get("price_change_percentage_24h", 0) or 0
        price = c.get("current_price", 0)
        lines.append(
            f"{i}. *{c['name']}* ({c['symbol'].upper()}) — "
            f"{fmt_price(price, user_id)} ({change:+.2f}%)"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        t(user_id, "welcome_menu"),
        parse_mode="Markdown",
        reply_markup=main_menu_keyboard(user_id),
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(t(user_id, "help_text"), parse_mode="Markdown")


async def cmd_prices(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    page = 1
    coins = fetch_top_coins(page=page, per_page=PAGE_SIZE)
    if not coins:
        await update.message.reply_text(t(user_id, "error"))
        return
    total_pages = 5
    text = build_prices_text(coins, user_id)
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=prices_keyboard(page, total_pages, user_id),
    )


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(user_id, "usage_search"))
        return
    query = " ".join(context.args)
    results = search_coins(query)
    if not results:
        await update.message.reply_text(t(user_id, "no_results"))
        return
    coin_id = results[0]["id"]
    data = fetch_coin(coin_id)
    if not data:
        await update.message.reply_text(t(user_id, "error"))
        return
    text = build_coin_text(data, user_id)
    await update.message.reply_text(
        text,
        parse_mode="Markdown",
        reply_markup=coin_keyboard(coin_id, user_id),
    )


async def cmd_gainers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    coins = fetch_gainers()
    if not coins:
        await update.message.reply_text(t(user_id, "error"))
        return
    text = build_gainers_losers_text(coins, t(user_id, "gainers_header"), user_id)
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_losers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    coins = fetch_losers()
    if not coins:
        await update.message.reply_text(t(user_id, "error"))
        return
    text = build_gainers_losers_text(coins, t(user_id, "losers_header"), user_id)
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 3:
        await update.message.reply_text(t(user_id, "usage_alert"))
        return
    coin_id = context.args[0].lower()
    direction = context.args[1].lower()
    if direction not in ("above", "below"):
        await update.message.reply_text(t(user_id, "invalid_direction"))
        return
    try:
        price = float(context.args[2])
    except ValueError:
        await update.message.reply_text(t(user_id, "invalid_price"))
        return
    alerts.setdefault(user_id, []).append({
        "id": str(uuid.uuid4())[:8],
        "coin": coin_id,
        "direction": direction,
        "price": price,
    })
    await update.message.reply_text(
        t(user_id, "alert_set").format(coin=coin_id, direction=direction, price=price)
    )


async def cmd_myalerts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user_alerts = alerts.get(user_id, [])
    if not user_alerts:
        await update.message.reply_text(t(user_id, "no_alerts"))
        return
    lines = [t(user_id, "alerts_header")]
    for a in user_alerts:
        lines.append(f"• [{a['id']}] {a['coin']} {a['direction']} ${a['price']:.4f}")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    portfolio = portfolios.get(user_id, {})
    if not portfolio:
        await update.message.reply_text(t(user_id, "portfolio_empty"))
        return
    lines = [t(user_id, "portfolio_header")]
    total_usd = 0.0
    for coin_id, info in portfolio.items():
        amount = info.get("amount", 0)
        data = fetch_coin(coin_id)
        if data:
            price = data.get("market_data", {}).get("current_price", {}).get("usd", 0)
            value = price * amount
            total_usd += value
            lines.append(
                f"• *{coin_id.upper()}*: {amount} × {fmt_price(price, user_id)} = {fmt_price(value, user_id)}"
            )
        else:
            lines.append(f"• *{coin_id.upper()}*: {amount} (price unavailable)")
    lines.append(t(user_id, "portfolio_total").format(total=fmt_price(total_usd, user_id)))
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_addcoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if len(context.args) < 2:
        await update.message.reply_text(t(user_id, "usage_addcoin"))
        return
    coin_id = context.args[0].lower()
    try:
        amount = float(context.args[1])
    except ValueError:
        await update.message.reply_text(t(user_id, "invalid_amount"))
        return
    portfolios.setdefault(user_id, {})[coin_id] = {"amount": amount}
    await update.message.reply_text(
        t(user_id, "coin_added").format(amount=amount, coin=coin_id)
    )


async def cmd_removecoin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if not context.args:
        await update.message.reply_text(t(user_id, "usage_removecoin"))
        return
    coin_id = context.args[0].lower()
    if coin_id not in portfolios.get(user_id, {}):
        await update.message.reply_text(
            t(user_id, "coin_not_found_portfolio").format(coin=coin_id)
        )
        return
    del portfolios[user_id][coin_id]
    await update.message.reply_text(t(user_id, "coin_removed").format(coin=coin_id))


async def cmd_subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribers.add(user_id)
    await update.message.reply_text(t(user_id, "subscribed"))


async def cmd_unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    subscribers.discard(user_id)
    await update.message.reply_text(t(user_id, "unsubscribed"))


async def cmd_currency(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        t(user_id, "currency_prompt"),
        reply_markup=currency_keyboard(user_id),
    )


async def cmd_language(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    await update.message.reply_text(
        t(user_id, "language_prompt"),
        reply_markup=language_keyboard(user_id),
    )


# ---------------------------------------------------------------------------
# Callback query handler
# ---------------------------------------------------------------------------

async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    data = query.data

    if data == "noop":
        return

    if data == "menu_main":
        await query.edit_message_text(
            t(user_id, "welcome_menu"),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(user_id),
        )
        return

    if data == "menu_help":
        await query.edit_message_text(t(user_id, "help_text"), parse_mode="Markdown")
        return

    if data == "menu_settings":
        await query.edit_message_text(
            "⚙️ Settings",
            reply_markup=settings_keyboard(user_id),
        )
        return

    if data == "settings_currency":
        await query.edit_message_text(
            t(user_id, "currency_prompt"),
            reply_markup=currency_keyboard(user_id),
        )
        return

    if data == "settings_language":
        await query.edit_message_text(
            t(user_id, "language_prompt"),
            reply_markup=language_keyboard(user_id),
        )
        return

    if data.startswith("setcurrency_"):
        currency = data.split("_", 1)[1]
        set_pref(user_id, "currency", currency)
        await query.edit_message_text(
            t(user_id, "currency_set").format(currency=currency),
            reply_markup=settings_keyboard(user_id),
        )
        return

    if data.startswith("setlang_"):
        lang = data.split("_", 1)[1]
        set_pref(user_id, "lang", lang)
        await query.edit_message_text(
            t(user_id, "language_prompt"),
            reply_markup=language_keyboard(user_id),
        )
        return

    if data.startswith("menu_prices_") or data.startswith("prices_"):
        page = int(data.split("_")[-1])
        coins = fetch_top_coins(page=page, per_page=PAGE_SIZE)
        if not coins:
            await query.edit_message_text(t(user_id, "error"))
            return
        total_pages = 5
        text = build_prices_text(coins, user_id)
        await query.edit_message_text(
            text,
            parse_mode="Markdown",
            reply_markup=prices_keyboard(page, total_pages, user_id),
        )
        return

    if data == "menu_gainers":
        coins = fetch_gainers()
        if not coins:
            await query.edit_message_text(t(user_id, "error"))
            return
        text = build_gainers_losers_text(coins, t(user_id, "gainers_header"), user_id)
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    if data == "menu_losers":
        coins = fetch_losers()
        if not coins:
            await query.edit_message_text(t(user_id, "error"))
            return
        text = build_gainers_losers_text(coins, t(user_id, "losers_header"), user_id)
        await query.edit_message_text(text, parse_mode="Markdown")
        return

    if data == "menu_alerts":
        user_alerts = alerts.get(user_id, [])
        if not user_alerts:
            await query.edit_message_text(t(user_id, "no_alerts"))
            return
        lines = [t(user_id, "alerts_header")]
        for a in user_alerts:
            lines.append(f"• [{a['id']}] {a['coin']} {a['direction']} ${a['price']:.4f}")
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
        return

    if data == "menu_portfolio":
        portfolio = portfolios.get(user_id, {})
        if not portfolio:
            await query.edit_message_text(t(user_id, "portfolio_empty"))
            return
        lines = [t(user_id, "portfolio_header")]
        total_usd = 0.0
        for coin_id, info in portfolio.items():
            amount = info.get("amount", 0)
            coin_data = fetch_coin(coin_id)
            if coin_data:
                price = coin_data.get("market_data", {}).get("current_price", {}).get("usd", 0)
                value = price * amount
                total_usd += value
                lines.append(
                    f"• *{coin_id.upper()}*: {amount} × {fmt_price(price, user_id)} = {fmt_price(value, user_id)}"
                )
            else:
                lines.append(f"• *{coin_id.upper()}*: {amount} (price unavailable)")
        lines.append(t(user_id, "portfolio_total").format(total=fmt_price(total_usd, user_id)))
        await query.edit_message_text("\n".join(lines), parse_mode="Markdown")
        return

    if data == "menu_search":
        await query.edit_message_text(
            t(user_id, "usage_search"),
            parse_mode="Markdown",
        )
        return

    if data.startswith("chart_"):
        parts = data.split("_")
        coin_id = parts[1]
        days = int(parts[2])
        chart_bytes = fetch_chart(coin_id, days)
        if chart_bytes:
            await context.bot.send_photo(
                chat_id=query.message.chat_id,
                photo=io.BytesIO(chart_bytes),
                caption=f"{coin_id.upper()} — {days}d chart",
            )
        else:
            await query.edit_message_text(t(user_id, "error"))
        return


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------

async def check_alerts(app: Application):
    while True:
        await asyncio.sleep(ALERT_CHECK_INTERVAL)
        try:
            refresh_exchange_rates()
            all_coin_ids = set()
            for user_alerts in alerts.values():
                for a in user_alerts:
                    all_coin_ids.add(a["coin"])
            prices_map: dict[str, float] = {}
            for coin_id in all_coin_ids:
                data = fetch_coin(coin_id)
                if data:
                    price = data.get("market_data", {}).get("current_price", {}).get("usd", 0)
                    prices_map[coin_id] = price
            for user_id, user_alerts in list(alerts.items()):
                triggered = []
                remaining = []
                for a in user_alerts:
                    current = prices_map.get(a["coin"])
                    if current is None:
                        remaining.append(a)
                        continue
                    hit = (a["direction"] == "above" and current >= a["price"]) or \
                          (a["direction"] == "below" and current <= a["price"])
                    if hit:
                        triggered.append((a, current))
                    else:
                        remaining.append(a)
                alerts[user_id] = remaining
                for a, current in triggered:
                    try:
                        lang = get_lang(user_id)
                        msg = STRINGS.get(lang, STRINGS["en"])["alert_triggered"].format(
                            coin=a["coin"],
                            price=current,
                            direction=a["direction"],
                            target=a["price"],
                        )
                        await app.bot.send_message(user_id, msg, parse_mode="Markdown")
                    except Exception:
                        pass
        except Exception:
            pass


async def daily_updates(app: Application):
    while True:
        now = datetime.now(timezone.utc)
        seconds_until = ((DAILY_UPDATE_HOUR - now.hour) % 24) * 3600 - now.minute * 60 - now.second
        if seconds_until <= 0:
            seconds_until += 86400
        await asyncio.sleep(seconds_until)
        try:
            coins = fetch_top_coins(page=1, per_page=10)
            for user_id in list(subscribers):
                try:
                    lang = get_lang(user_id)
                    header = STRINGS.get(lang, STRINGS["en"])["daily_update"]
                    text = header + build_prices_text(coins, user_id)
                    await app.bot.send_message(user_id, text, parse_mode="Markdown")
                except Exception:
                    pass
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")
    refresh_exchange_rates()
    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("prices", cmd_prices))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("gainers", cmd_gainers))
    app.add_handler(CommandHandler("losers", cmd_losers))
    app.add_handler(CommandHandler("alert", cmd_alert))
    app.add_handler(CommandHandler("myalerts", cmd_myalerts))
    app.add_handler(CommandHandler("portfolio", cmd_portfolio))
    app.add_handler(CommandHandler("addcoin", cmd_addcoin))
    app.add_handler(CommandHandler("removecoin", cmd_removecoin))
    app.add_handler(CommandHandler("subscribe", cmd_subscribe))
    app.add_handler(CommandHandler("unsubscribe", cmd_unsubscribe))
    app.add_handler(CommandHandler("currency", cmd_currency))
    app.add_handler(CommandHandler("language", cmd_language))
    app.add_handler(CallbackQueryHandler(handle_callback))

    loop = asyncio.get_event_loop()
    loop.create_task(check_alerts(app))
    loop.create_task(daily_updates(app))

    app.run_polling()


if __name__ == "__main__":
    main()


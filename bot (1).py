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
# Language strings  (plain Markdown — no MarkdownV2 escaping needed)
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
            "/gainers — Top 10 gainers & losers (24h)\n"
            "/trending — Top 7 trending coins right now\n"
            "/dominance — Market cap & BTC/ETH dominance\n"
            "/compare <coin1> <coin2> — Side-by-side comparison\n"
            "/alert <coin> <price> — Set a price alert\n"
            "/alerts — List your active alerts\n"
            "/cancelalert <id> — Cancel an alert\n"
            "/portfolio — Your portfolio & total value\n"
            "/portfolioadd <coin> <amount> — Add/update holding\n"
            "/portfolioremove <coin> — Remove holding\n"
            "/subscribe — Subscribe to daily updates\n"
            "/unsubscribe — Unsubscribe from daily updates\n"
            "/language — Change language\n"
            "/help — Show this message\n\n"
            "_Prices shown in USD, RUB & UZS._"
        ),
        "fetching": "⏳ Fetching data...",
        "refreshing": "⏳ Refreshing...",
        "error_fetch": "❌ Failed to fetch data. Please try again later.",
        "error_coin_not_found": "❌ Could not find a coin matching *{query}*.",
        "error_search_no_results": "❌ No results found for *{query}*.",
        "search_prompt": "⚠️ Please provide a coin name or symbol.\nExample: `/search bitcoin` or `/search btc`",
        "searching": "🔍 Searching for *{query}*...",
        "session_expired": "❌ Session expired. Use /prices to start again.",
        "prices_title": "📊 Top 50 Cryptocurrencies — Page {page}/{total}",
        "top10_title": "📊 *Top 10 Cryptocurrencies*",
        "subscribed": "✅ Subscribed to daily updates at 09:00 UTC.",
        "already_subscribed": "ℹ️ You are already subscribed.",
        "unsubscribed": "✅ Unsubscribed from daily updates.",
        "not_subscribed": "ℹ️ You are not subscribed.",
        "daily_title": "📰 *Daily Crypto Update*",
        "language_choose": "🌐 Choose your language:",
        "language_changed_en": "✅ Language set to English.",
        "language_changed_uz": "✅ Til O'zbekchaga o'zgartirildi.",
        "menu_search_tip": (
            "🔍 *Search any coin!*\n\n"
            "Just send a message like:\n"
            "`/search bitcoin`\n"
            "`/search eth`\n"
            "`/search solana`\n\n"
            "_Returns price, chart, and full stats._"
        ),
        "alert_direction_above": "rises above",
        "alert_direction_below": "drops below",
        "alert_triggered_above": "risen above",
        "alert_triggered_below": "dropped below",
        "alert_set": (
            "🔔 *Alert set!*\n\n"
            "You'll be notified when *{name}* ({symbol}) {direction} *{target}*.\n\n"
            "Current price: {current}\n"
            "Alert ID: `{id}`\n\n"
            "_Checked every 60s · Use /alerts to manage_"
        ),
        "alert_triggered_msg": (
            "{arrow} *Price Alert Triggered!*\n\n"
            "*{name}* ({symbol}) has {direction} your target of *{target}*.\n\n"
            "Current price: *{current}*\n\n"
            "_Use /alert to set a new alert._"
        ),
        "no_alerts": "📭 You have no active alerts.\n\nUse `/alert <coin> <price>` to set one.",
        "alerts_title": "🔔 *Your Active Alerts*",
        "alert_cancelled": "✅ Alert `{id}` cancelled.",
        "alert_not_found": "❌ No alert with ID `{id}`.\nUse /alerts to see your alert IDs.",
        "alert_usage": "⚠️ Usage: `/alert <coin> <price>`\nExample: `/alert bitcoin 100000`",
        "cancelalert_usage": "⚠️ Usage: `/cancelalert <id>`\nUse /alerts to see your IDs.",
        "portfolio_empty": (
            "📭 Your portfolio is empty.\n\n"
            "Use `/portfolioadd <coin> <amount>` to add a holding.\n"
            "Example: `/portfolioadd bitcoin 0.5`"
        ),
        "portfolio_title": "💼 *Your Portfolio*",
        "portfolio_total": "Total Value",
        "portfolio_updated": (
            "✅ *Portfolio updated!*\n\n"
            "*{name}* ({symbol})\n"
            "Amount: {amount}\n"
            "Price: {price}\n"
            "Value: {value}\n\n"
            "_Use /portfolio to view your full portfolio._"
        ),
        "portfolio_removed": "✅ *{name}* ({symbol}) removed from portfolio.",
        "portfolio_not_found": "❌ *{query}* not found in your portfolio.\nUse /portfolio to see your holdings.",
        "portfolio_already_empty": "📭 Your portfolio is already empty.",
        "portfolioadd_usage": "⚠️ Usage: `/portfolioadd <coin> <amount>`\nExample: `/portfolioadd bitcoin 0.5`",
        "portfolioremove_usage": "⚠️ Usage: `/portfolioremove <coin>`\nExample: `/portfolioremove bitcoin`",
        "invalid_price": "⚠️ *{value}* is not a valid price. Enter a positive number.",
        "invalid_amount": "⚠️ *{value}* is not a valid amount. Enter a positive number.",
        "gainers_title": "📈 *Top Gainers & Losers — 24h (Top 100)*",
        "gainers_section": "🚀 Top 10 Gainers",
        "losers_section": "💀 Top 10 Losers",
        "chart_caption": "📊 {name} ({symbol}) — 1H Candlestick · 24h",
        "trending_title": "🔥 *Trending Coins — Most Searched 24h*",
        "trending_fetching": "🔍 Fetching trending coins...",
        "trending_no_data": "❌ Could not fetch trending data. Try again later.",
        "compare_usage": "⚠️ Usage: `/compare <coin1> <coin2>`\nExample: `/compare bitcoin ethereum`",
        "compare_fetching": "🔍 Fetching data for *{q1}* and *{q2}*...",
        "compare_title": "⚖️ *{name1} vs {name2}*",
        "compare_chart_caption": "📊 {name1} vs {name2} — 24h Performance (normalised %)",
        "btn_prev": "⬅️ Prev",
        "btn_next": "Next ➡️",
        "btn_refresh": "🔄 Refresh",
        "btn_top10": "📊 Top 10 Crypto",
        "btn_top50": "📈 Top 50 Crypto",
        "btn_search_coin": "🔍 Search Coin",
        "btn_subscribe_daily": "🔔 Subscribe Daily",
        "btn_language_menu": "🌐 Change Language",
        "btn_main_menu": "🏠 Main Menu",
        "powered_by": "Powered by CoinGecko · USD | RUB | UZS",
        "market_overview_title": "🌐 *Crypto Market Overview*",
        "market_dominance_title": "📊 *Market Dominance*",
        "looking_up": "🔍 Looking up *{query}*...",
    },
    "uz": {
        "lang_name": "🇺🇿 O'zbek",
        "welcome_menu": (
            "👋 *CryptoBotga xush kelibsiz!*\n\n"
            "🔥 Real-vaqt kripto narxlari *USD, RUB va UZSda*\n"
            "📊 Top coinlarni kuzating, qidiring, signallar o'rnating va boshqalar.\n\n"
            "_Quyidan tanlang:_"
        ),
        "help_text": (
            "*📖 Mavjud buyruqlar*\n\n"
            "/prices — Top 50 kripto narxlari\n"
            "/search <coin> — Coin qidirish + grafik\n"
            "/gainers — Top 10 o'sganlar & tushganlar\n"
            "/trending — Hozir top 7 trend coin\n"
            "/dominance — Bozor kapitalizatsiyasi\n"
            "/compare <coin1> <coin2> — Ikki coinni solishtirish\n"
            "/alert <coin> <narx> — Narx signali o'rnatish\n"
            "/alerts — Faol signallar\n"
            "/cancelalert <id> — Signalni bekor qilish\n"
            "/portfolio — Portfelingiz\n"
            "/portfolioadd <coin> <miqdor> — Qo'shish/yangilash\n"
            "/portfolioremove <coin> — O'chirish\n"
            "/subscribe — Kunlik yangilanishlarga obuna\n"
            "/unsubscribe — Obunani bekor qilish\n"
            "/language — Tilni o'zgartirish\n"
            "/help — Ushbu xabarni ko'rsatish\n\n"
            "_Narxlar USD, RUB va UZSda ko'rsatiladi._"
        ),
        "fetching": "⏳ Ma'lumotlar yuklanmoqda...",
        "refreshing": "⏳ Yangilanmoqda...",
        "error_fetch": "❌ Ma'lumotlarni yuklab bo'lmadi. Qayta urinib ko'ring.",
        "error_coin_not_found": "❌ *{query}* nomli coin topilmadi.",
        "error_search_no_results": "❌ *{query}* bo'yicha natijalar topilmadi.",
        "search_prompt": "⚠️ Coin nomi yoki belgisini kiriting.\nMisol: `/search bitcoin` yoki `/search btc`",
        "searching": "🔍 *{query}* qidirilmoqda...",
        "session_expired": "❌ Sessiya tugadi. Qayta boshlash uchun /prices yuboring.",
        "prices_title": "📊 Top 50 Kriptovalyutalar — Bet {page}/{total}",
        "top10_title": "📊 *Top 10 Kriptovalyutalar*",
        "subscribed": "✅ Kunlik yangilanishlarga obuna bo'ldingiz (har kuni 09:00 UTC).",
        "already_subscribed": "ℹ️ Siz allaqachon obuna bo'lgansiz.",
        "unsubscribed": "✅ Kunlik yangilanishlardan obuna bekor qilindi.",
        "not_subscribed": "ℹ️ Siz hozirda obuna emassiz.",
        "daily_title": "📰 *Kunlik Kripto Yangilanish*",
        "language_choose": "🌐 Tilni tanlang:",
        "language_changed_en": "✅ Language set to English.",
        "language_changed_uz": "✅ Til O'zbekchaga o'zgartirildi.",
        "menu_search_tip": (
            "🔍 *Istalgan coinni qidiring!*\n\n"
            "Quyidagicha yuboring:\n"
            "`/search bitcoin`\n"
            "`/search eth`\n"
            "`/search solana`\n\n"
            "_Narx, grafik va to'liq statistika qaytariladi._"
        ),
        "alert_direction_above": "ko'tarilganda",
        "alert_direction_below": "tushganda",
        "alert_triggered_above": "ko'tarildi",
        "alert_triggered_below": "tushdi",
        "alert_set": (
            "🔔 *Signal o'rnatildi!*\n\n"
            "*{name}* ({symbol}) narxi {direction} *{target}* bo'lganda xabar olasiz.\n\n"
            "Joriy narx: {current}\n"
            "Signal ID: `{id}`\n\n"
            "_Har 60 soniyada tekshiriladi · /alerts bilan boshqaring_"
        ),
        "alert_triggered_msg": (
            "{arrow} *Narx Signali Ishladi!*\n\n"
            "*{name}* ({symbol}) narxi sizning {target} maqsadingizdan {direction}.\n\n"
            "Joriy narx: *{current}*\n\n"
            "_Yangi signal o'rnatish uchun /alert yuboring._"
        ),
        "no_alerts": "📭 Sizda faol signallar yo'q.\n\nSignal o'rnatish uchun `/alert <coin> <narx>` yuboring.",
        "alerts_title": "🔔 *Faol Signallaringiz*",
        "alert_cancelled": "✅ `{id}` signali bekor qilindi.",
        "alert_not_found": "❌ `{id}` ID li signal topilmadi.\nID larni ko'rish uchun /alerts yuboring.",
        "alert_usage": "⚠️ Ishlatish: `/alert <coin> <narx>`\nMisol: `/alert bitcoin 100000`",
        "cancelalert_usage": "⚠️ Ishlatish: `/cancelalert <id>`\nID larni ko'rish uchun /alerts yuboring.",
        "portfolio_empty": (
            "📭 Portfelingiz bo'sh.\n\n"
            "Qo'shish uchun `/portfolioadd <coin> <miqdor>` yuboring.\n"
            "Misol: `/portfolioadd bitcoin 0.5`"
        ),
        "portfolio_title": "💼 *Sizning Portfelingiz*",
        "portfolio_total": "Umumiy qiymat",
        "portfolio_updated": (
            "✅ *Portfel yangilandi!*\n\n"
            "*{name}* ({symbol})\n"
            "Miqdor: {amount}\n"
            "Narx: {price}\n"
            "Qiymat: {value}\n\n"
            "_To'liq portfelni ko'rish uchun /portfolio yuboring._"
        ),
        "portfolio_removed": "✅ *{name}* ({symbol}) portfeldan o'chirildi.",
        "portfolio_not_found": "❌ *{query}* portfelingizda topilmadi.\nHoldinlarni ko'rish uchun /portfolio yuboring.",
        "portfolio_already_empty": "📭 Portfelingiz allaqachon bo'sh.",
        "portfolioadd_usage": "⚠️ Ishlatish: `/portfolioadd <coin> <miqdor>`\nMisol: `/portfolioadd bitcoin 0.5`",
        "portfolioremove_usage": "⚠️ Ishlatish: `/portfolioremove <coin>`\nMisol: `/portfolioremove bitcoin`",
        "invalid_price": "⚠️ *{value}* yaroqli narx emas. Musbat son kiriting.",
        "invalid_amount": "⚠️ *{value}* yaroqli miqdor emas. Musbat son kiriting.",
        "gainers_title": "📈 *Top O'sganlar & Tushganlar — 24s (Top 100)*",
        "gainers_section": "🚀 Top 10 O'sganlar",
        "losers_section": "💀 Top 10 Tushganlar",
        "chart_caption": "📊 {name} ({symbol}) — 1S Sham Grafigi · 24s",
        "trending_title": "🔥 *Trend Coinlar — 24s Eng Ko'p Qidirilgan*",
        "trending_fetching": "🔍 Trend coinlar yuklanmoqda...",
        "trending_no_data": "❌ Trend ma'lumotlarini yuklab bo'lmadi. Qayta urinib ko'ring.",
        "compare_usage": "⚠️ Ishlatish: `/compare <coin1> <coin2>`\nMisol: `/compare bitcoin ethereum`",
        "compare_fetching": "🔍 *{q1}* va *{q2}* ma'lumotlari yuklanmoqda...",
        "compare_title": "⚖️ *{name1} vs {name2}*",
        "compare_chart_caption": "📊 {name1} vs {name2} — 24 soatlik Natija (foizda)",
        "btn_prev": "⬅️ Oldingi",
        "btn_next": "Keyingi ➡️",
        "btn_refresh": "🔄 Yangilash",
        "btn_top10": "📊 Top 10 Kripto",
        "btn_top50": "📈 Top 50 Kripto",
        "btn_search_coin": "🔍 Coin Qidirish",
        "btn_subscribe_daily": "🔔 Kunlik Obuna",
        "btn_language_menu": "🌐 Tilni O'zgartirish",
        "btn_main_menu": "🏠 Asosiy Menyu",
        "powered_by": "CoinGecko · USD | RUB | UZS",
        "market_overview_title": "🌐 *Kripto Bozor Ko'rinishi*",
        "market_dominance_title": "📊 *Bozor Dominantligi*",
        "looking_up": "🔍 *{query}* qidirilmoqda...",
    },
}


# ---------------------------------------------------------------------------
# Language helpers
# ---------------------------------------------------------------------------

def get_lang(chat_id: int) -> str:
    return user_prefs.get(chat_id, {}).get("lang", "en")


def t(chat_id: int, key: str, **kwargs) -> str:
    lang = get_lang(chat_id)
    text = STRINGS.get(lang, STRINGS["en"]).get(key) or STRINGS["en"].get(key, key)
    return text.format(**kwargs) if kwargs else text


# ---------------------------------------------------------------------------
# Exchange rate helpers
# ---------------------------------------------------------------------------

def refresh_exchange_rates_sync() -> None:
    global exchange_rates
    try:
        resp = requests.get(EXCHANGE_RATE_API, timeout=10)
        resp.raise_for_status()
        rates = resp.json().get("rates", {})
        if "RUB" in rates:
            exchange_rates["RUB"] = rates["RUB"]
        if "UZS" in rates:
            exchange_rates["UZS"] = rates["UZS"]
        print(f"Exchange rates updated: RUB={exchange_rates['RUB']:.2f}, UZS={exchange_rates['UZS']:.2f}")
    except Exception as e:
        print(f"Failed to refresh exchange rates: {e}")


async def refresh_exchange_rates_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    await asyncio.to_thread(refresh_exchange_rates_sync)


# ---------------------------------------------------------------------------
# Data helpers
# ---------------------------------------------------------------------------

def fetch_top_n(n: int = 50) -> list[dict] | None:
    try:
        resp = requests.get(
            f"{COINGECKO_API}/coins/markets",
            params={
                "vs_currency": "usd",
                "order": "market_cap_desc",
                "per_page": n,
                "page": 1,
                "sparkline": False,
                "price_change_percentage": "24h",
            },
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException as e:
        print(f"Error fetching top {n}: {e}")
        return None


def search_coin(query: str) -> dict | None:
    try:
        sr = requests.get(f"{COINGECKO_API}/search", params={"query": query}, timeout=10)
        sr.raise_for_status()
        results = sr.json().get("coins", [])
        if not results:
            return None
        coin_id = results[0]["id"]
        dr = requests.get(
            f"{COINGECKO_API}/coins/{coin_id}",
            params={
                "localization": False,
                "tickers": False,
                "community_data": False,
                "developer_data": False,
                "sparkline": False,
            },
            timeout=10,
        )
        dr.raise_for_status()
        return dr.json()
    except requests.RequestException as e:
        print(f"Error searching coin: {e}")
        return None


def fetch_market_chart(coin_id: str) -> list | None:
    try:
        resp = requests.get(
            f"{COINGECKO_API}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": 1, "interval": "hourly"},
            timeout=10,
        )
        resp.raise_for_status()
        return resp.json().get("prices")
    except requests.RequestException as e:
        print(f"Error fetching market chart for {coin_id}: {e}")
        return None


def fetch_ohlcv_coinbase_sync(symbol: str) -> list | None:
    product_id = f"{symbol.upper()}-USD"
    try:
        resp = requests.get(
            f"https://api.exchange.coinbase.com/products/{product_id}/candles",
            params={"granularity": 3600},
            timeout=10,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.ok:
            data = resp.json()
            if isinstance(data, list) and len(data) >= 2:
                return data
    except Exception:
        pass
    return None


def fetch_global_data() -> dict | None:
    try:
        resp = requests.get(f"{COINGECKO_API}/global", timeout=10)
        resp.raise_for_status()
        return resp.json().get("data", {})
    except requests.RequestException as e:
        print(f"Error fetching global data: {e}")
        return None


def fetch_portfolio_prices(coin_ids: list[str]) -> dict[str, float]:
    if not coin_ids:
        return {}
    try:
        resp = requests.get(
            f"{COINGECKO_API}/simple/price",
            params={"ids": ",".join(coin_ids), "vs_currencies": "usd"},
            timeout=10,
        )
        resp.raise_for_status()
        return {cid: v.get("usd", 0) for cid, v in resp.json().items()}
    except requests.RequestException:
        return {}


def fetch_trending_sync() -> list[dict] | None:
    try:
        resp = requests.get(f"{COINGECKO_API}/search/trending", timeout=10)
        resp.raise_for_status()
        items = [entry["item"] for entry in resp.json().get("coins", [])]
        if not items:
            return None
        ids = ",".join(item["id"] for item in items)
        price_resp = requests.get(
            f"{COINGECKO_API}/simple/price",
            params={"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"},
            timeout=10,
        )
        price_data = price_resp.json() if price_resp.ok else {}
        for item in items:
            pd = price_data.get(item["id"], {})
            item["usd_price"] = pd.get("usd")
            item["usd_24h_change"] = pd.get("usd_24h_change")
        return items
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def format_price(price: float) -> str:
    if price >= 1000:
        return f"${price:,.2f}"
    elif price >= 1:
        return f"${price:.4f}"
    else:
        return f"${price:.8f}"


def format_price_multi(usd: float) -> str:
    rub = usd * exchange_rates["RUB"]
    uzs = usd * exchange_rates["UZS"]

    def fmt_local(val: float, symbol: str) -> str:
        if val >= 1000:
            return f"{symbol}{val:,.0f}"
        elif val >= 1:
            return f"{symbol}{val:.2f}"
        else:
            return f"{symbol}{val:.6f}"

    som = "so'm "
    return f"{format_price(usd)} | {fmt_local(rub, '₽')} | {fmt_local(uzs, som)}"


def format_change(change: float | None) -> str:
    if change is None:
        return "N/A"
    arrow = "▲" if change >= 0 else "▼"
    return f"{arrow} {abs(change):.2f}%"


def format_market_cap(mc: float) -> str:
    if mc >= 1_000_000_000:
        return f"${mc / 1_000_000_000:.2f}B"
    elif mc >= 1_000_000:
        return f"${mc / 1_000_000:.2f}M"
    return f"${mc:,.0f}"


# ---------------------------------------------------------------------------
# Chart generation
# ---------------------------------------------------------------------------

def _generate_chart_sync(prices: list, name: str, symbol: str) -> bytes:
    dates = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in prices]
    values = [p[1] for p in prices]
    color = "#00d4aa" if values[-1] >= values[0] else "#ff6b6b"

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")
    ax.plot(dates, values, color=color, linewidth=2)
    ax.fill_between(dates, values, min(values), alpha=0.18, color=color)

    for spine in ax.spines.values():
        spine.set_color("#333")
    ax.tick_params(colors="#aaa", labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(
        lambda x, _: f"${x:,.2f}" if x >= 1 else f"${x:.6f}"
    ))
    ax.set_title(f"{name} ({symbol.upper()}) — 24h", color="white", fontsize=12, pad=10)
    ax.grid(axis="y", color="#333", linewidth=0.5, linestyle="--")

    change_pct = ((values[-1] - values[0]) / values[0] * 100) if values[0] else 0
    sign = "+" if change_pct >= 0 else ""
    ax.text(0.01, 0.95, f"{sign}{change_pct:.2f}%",
            transform=ax.transAxes, color=color, fontsize=11, fontweight="bold", va="top")

    plt.tight_layout(pad=1.0)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def _generate_tradingview_chart_sync(candles: list, name: str, symbol: str) -> bytes:
    from datetime import timedelta
    candles = sorted(candles, key=lambda x: x[0])[-24:]

    ts      = [datetime.fromtimestamp(c[0], tz=timezone.utc) for c in candles]
    opens   = [c[3] for c in candles]
    highs   = [c[2] for c in candles]
    lows    = [c[1] for c in candles]
    closes  = [c[4] for c in candles]
    volumes = [c[5] for c in candles]

    BG          = "#131722"
    UP_COLOR    = "#26a69a"
    DOWN_COLOR  = "#ef5350"
    GRID_COLOR  = "#1e2230"
    TEXT_COLOR  = "#d1d4dc"
    SPINE_COLOR = "#2a2e39"

    fig, (ax, ax_v) = plt.subplots(
        2, 1, figsize=(12, 6),
        gridspec_kw={"height_ratios": [4, 1], "hspace": 0},
        sharex=True,
    )
    fig.patch.set_facecolor(BG)
    bar_width = timedelta(minutes=42)

    for t_val, o, h, l, c, v in zip(ts, opens, highs, lows, closes, volumes):
        is_up = c >= o
        color = UP_COLOR if is_up else DOWN_COLOR
        body_lo = min(o, c)
        body_hi = max(o, c)
        body_h = (body_hi - body_lo) or (h - l) * 0.005
        ax.bar(t_val, body_h, bottom=body_lo, width=bar_width, color=color, linewidth=0, zorder=3)
        ax.plot([t_val, t_val], [l, body_lo], color=color, linewidth=0.9, zorder=2)
        ax.plot([t_val, t_val], [body_hi, h], color=color, linewidth=0.9, zorder=2)
        ax_v.bar(t_val, v, width=bar_width, color=color, alpha=0.65, linewidth=0)

    last_price = closes[-1]
    ax.axhline(last_price, color=TEXT_COLOR, linewidth=0.6, linestyle="--", alpha=0.55, zorder=1)

    chg = (closes[-1] - opens[0]) / opens[0] * 100 if opens[0] else 0
    sign = "+" if chg >= 0 else ""
    chg_color = UP_COLOR if chg >= 0 else DOWN_COLOR
    ax.text(0.01, 0.97, f"{sign}{chg:.2f}%", transform=ax.transAxes,
            ha="left", va="top", color=chg_color, fontsize=12, fontweight="bold")

    pfmt = f"${last_price:,.2f}" if last_price >= 1 else f"${last_price:.6f}"
    ax.text(0.99, 0.97, pfmt, transform=ax.transAxes,
            ha="right", va="top", color=TEXT_COLOR, fontsize=11, fontweight="bold")

    ax.set_title(f"{name} ({symbol.upper()}) / USD  ·  1H  ·  24h",
                 color=TEXT_COLOR, fontsize=10, pad=6, loc="left", fontweight="bold")

    for a in (ax, ax_v):
        a.set_facecolor(BG)
        for spine in a.spines.values():
            spine.set_color(SPINE_COLOR)
        a.tick_params(colors=TEXT_COLOR, labelsize=8)
        a.grid(color=GRID_COLOR, linewidth=0.5, linestyle="-", zorder=0)

    ax.yaxis.set_major_formatter(plt.FuncFormatter(
        lambda x, _: f"${x:,.0f}" if x >= 1000 else (f"${x:.2f}" if x >= 1 else f"${x:.6f}")
    ))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    ax_v.set_ylabel("Vol", color=TEXT_COLOR, fontsize=7)
    ax_v.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: ""))

    plt.tight_layout(pad=0.8)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=120, facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


async def build_chart(coin_id: str, name: str, symbol: str) -> bytes | None:
    candles = await asyncio.to_thread(fetch_ohlcv_coinbase_sync, symbol)
    if candles and len(candles) >= 2:
        return await asyncio.to_thread(_generate_tradingview_chart_sync, candles, name, symbol)
    prices = await asyncio.to_thread(fetch_market_chart, coin_id)
    if not prices or len(prices) < 2:
        return None
    return await asyncio.to_thread(_generate_chart_sync, prices, name, symbol)


def _generate_compare_chart_sync(
    prices_a: list, prices_b: list, name_a: str, name_b: str
) -> bytes:
    def normalise(pts: list) -> list[float]:
        base = pts[0][1] if pts[0][1] else 1
        return [(p[1] - base) / base * 100 for p in pts]

    dates_a = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in prices_a]
    dates_b = [datetime.fromtimestamp(p[0] / 1000, tz=timezone.utc) for p in prices_b]
    vals_a = normalise(prices_a)
    vals_b = normalise(prices_b)

    color_a = "#00d4aa"
    color_b = "#f7a94b"

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")
    ax.plot(dates_a, vals_a, color=color_a, linewidth=2, label=name_a)
    ax.plot(dates_b, vals_b, color=color_b, linewidth=2, label=name_b)
    ax.axhline(0, color="#555", linewidth=0.8, linestyle="--")

    for spine in ax.spines.values():
        spine.set_color("#333")
    ax.tick_params(colors="#aaa", labelsize=8)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
    ax.xaxis.set_major_locator(mdates.HourLocator(interval=4))
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: f"{x:+.1f}%"))
    ax.set_title(f"{name_a} vs {name_b} — 24h Performance", color="white", fontsize=12, pad=10)
    ax.grid(axis="y", color="#333", linewidth=0.5, linestyle="--")
    ax.legend(facecolor="#1a1a2e", edgecolor="#444", labelcolor="white", fontsize=9)

    ax.annotate(f"{vals_a[-1]:+.2f}%", xy=(dates_a[-1], vals_a[-1]),
                color=color_a, fontsize=9, fontweight="bold",
                xytext=(5, 0), textcoords="offset points", va="center")
    ax.annotate(f"{vals_b[-1]:+.2f}%", xy=(dates_b[-1], vals_b[-1]),
                color=color_b, fontsize=9, fontweight="bold",
                xytext=(5, 0), textcoords="offset points", va="center")

    plt.tight_layout(pad=1.0)
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=110, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()


async def build_compare_chart(
    id_a: str, id_b: str, name_a: str, name_b: str
) -> bytes | None:
    prices_a, prices_b = await asyncio.gather(
        asyncio.to_thread(fetch_market_chart, id_a),
        asyncio.to_thread(fetch_market_chart, id_b),
    )
    if not prices_a or not prices_b or len(prices_a) < 2 or len(prices_b) < 2:
        return None
    return await asyncio.to_thread(
        _generate_compare_chart_sync, prices_a, prices_b, name_a, name_b
    )


# ---------------------------------------------------------------------------
# Message builders
# ---------------------------------------------------------------------------

MD = "Markdown"


def build_main_menu_keyboard(chat_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(chat_id, "btn_top10"), callback_data="menu:top10"),
            InlineKeyboardButton(t(chat_id, "btn_top50"), callback_data="menu:top50"),
        ],
        [
            InlineKeyboardButton(t(chat_id, "btn_search_coin"), callback_data="menu:search"),
            InlineKeyboardButton(t(chat_id, "btn_subscribe_daily"), callback_data="menu:subscribe"),
        ],
        [
            InlineKeyboardButton(t(chat_id, "btn_language_menu"), callback_data="menu:language"),
        ],
    ])


def build_prices_page(coins: list[dict], page: int, chat_id: int) -> str:
    total_pages = -(-len(coins) // PAGE_SIZE)
    start = page * PAGE_SIZE
    page_coins = coins[start: start + PAGE_SIZE]

    title = t(chat_id, "prices_title", page=page + 1, total=total_pages)
    lines = [f"*{title}*\n"]

    for coin in page_coins:
        rank = coin.get("market_cap_rank", "?")
        name = coin.get("name", "Unknown")
        symbol = coin.get("symbol", "").upper()
        price = coin.get("current_price", 0)
        change = coin.get("price_change_percentage_24h")
        market_cap = coin.get("market_cap", 0)
        emoji = "🟢" if (change or 0) >= 0 else "🔴"

        lines.append(
            f"*#{rank}* {name} ({symbol})\n"
            f"  💰 {format_price_multi(price)}\n"
            f"  {emoji} 24h: {format_change(change)}  ·  📈 {format_market_cap(market_cap)}\n"
        )

    lines.append(f"\n_{t(chat_id, 'powered_by')}_")
    return "\n".join(lines)


def build_prices_keyboard(page: int, total: int, chat_id: int) -> InlineKeyboardMarkup:
    total_pages = -(-total // PAGE_SIZE)
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(t(chat_id, "btn_prev"), callback_data=f"page:{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(t(chat_id, "btn_next"), callback_data=f"page:{page + 1}"))
    refresh = InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data=f"refresh:{page}")
    rows = []
    if nav:
        rows.append(nav)
    rows.append([refresh])
    return InlineKeyboardMarkup(rows)


def format_top10(coins: list[dict], chat_id: int) -> str:
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣", "8️⃣", "9️⃣", "🔟"]
    lines = [t(chat_id, "top10_title") + "\n"]
    for i, coin in enumerate(coins[:10]):
        name = coin.get("name", "?")
        symbol = coin.get("symbol", "").upper()
        price = coin.get("current_price", 0)
        change = coin.get("price_change_percentage_24h")
        mc = coin.get("market_cap", 0)
        medal = medals[i] if i < len(medals) else f"{i + 1}."
        emoji = "🟢" if (change or 0) >= 0 else "🔴"
        lines.append(
            f"{medal} *{name}* ({symbol})\n"
            f"  💰 {format_price_multi(price)}\n"
            f"  {emoji} 24h: {format_change(change)}  ·  📈 {format_market_cap(mc)}\n"
        )
    lines.append(f"\n_{t(chat_id, 'powered_by')}_")
    return "\n".join(lines)


def format_coin_detail(coin: dict, chat_id: int) -> str:
    name = coin.get("name", "Unknown")
    symbol = coin.get("symbol", "").upper()
    rank = str(coin.get("market_cap_rank") or "N/A")
    md = coin.get("market_data", {})

    price_usd = md.get("current_price", {}).get("usd", 0)
    change_24h = md.get("price_change_percentage_24h")
    change_7d = md.get("price_change_percentage_7d")
    change_30d = md.get("price_change_percentage_30d")
    market_cap = md.get("market_cap", {}).get("usd", 0)
    volume = md.get("total_volume", {}).get("usd", 0)
    high = md.get("high_24h", {}).get("usd", 0)
    low = md.get("low_24h", {}).get("usd", 0)
    ath = md.get("ath", {}).get("usd", 0)
    ath_change = md.get("ath_change_percentage", {}).get("usd")
    circulating = md.get("circulating_supply")
    max_supply = md.get("max_supply")

    def pct(val):
        if val is None:
            return "N/A"
        arrow = "▲" if val >= 0 else "▼"
        return f"{arrow} {abs(val):.2f}%"

    def supply_str(val):
        if val is None:
            return "∞"
        return f"{val / 1_000_000:.2f}M" if val >= 1_000_000 else f"{val:,.0f}"

    lines = [
        f"*🔍 {name} ({symbol})*",
        f"Rank: *#{rank}*\n",
        f"💰 *Price:*",
        f"  {format_price_multi(price_usd)}\n",
        f"📈 *24h High:* {format_price(high)}",
        f"📉 *24h Low:* {format_price(low)}",
        f"🏆 *ATH:* {format_price(ath)} ({pct(ath_change)} from ATH)\n",
        f"📊 *Price Change:*",
        f"  24h: {pct(change_24h)}",
        f"  7d:  {pct(change_7d)}",
        f"  30d: {pct(change_30d)}\n",
        f"📈 *Market Cap:* {format_market_cap(market_cap)}",
        f"💹 *24h Volume:* {format_market_cap(volume)}",
        f"🔄 *Circulating:* {supply_str(circulating)} {symbol}",
        f"🔒 *Max Supply:* {supply_str(max_supply)} {symbol}",
        f"\n_{t(chat_id, 'powered_by')}_",
    ]
    return "\n".join(lines)


def format_portfolio_text(holdings: dict[str, dict], prices: dict[str, float], chat_id: int) -> str:
    lines = [t(chat_id, "portfolio_title") + "\n"]
    total_usd = 0.0
    for entry in holdings.values():
        price_usd = prices.get(entry["coin_id"], 0)
        value_usd = price_usd * entry["amount"]
        total_usd += value_usd
        lines.append(
            f"• *{entry['coin_name']}* ({entry['coin_symbol']})\n"
            f"  Amount: {entry['amount']}\n"
            f"  Price: {format_price_multi(price_usd)}\n"
            f"  Value: {format_price(value_usd)}\n"
        )
    total_label = t(chat_id, "portfolio_total")
    lines.append(f"*{total_label}: {format_price_multi(total_usd)}*")
    lines.append(f"\n_{t(chat_id, 'powered_by')}_")
    return "\n".join(lines)


def format_dominance(data: dict, chat_id: int) -> str:
    total_mc = data.get("total_market_cap", {}).get("usd", 0)
    total_vol = data.get("total_volume", {}).get("usd", 0)
    dom = data.get("market_cap_percentage", {})
    btc_d = dom.get("btc", 0)
    eth_d = dom.get("eth", 0)
    others_d = max(0, 100 - btc_d - eth_d)
    active = data.get("active_cryptocurrencies", 0)
    markets = data.get("markets", 0)
    change_24h = data.get("market_cap_change_percentage_24h_usd")

    def bar(pct: float, w: int = 18) -> str:
        filled = round(pct / 100 * w)
        return "█" * filled + "░" * (w - filled)

    change_str = ""
    if change_24h is not None:
        arrow = "▲" if change_24h >= 0 else "▼"
        change_str = f" ({arrow} {abs(change_24h):.2f}% 24h)"

    lines = [
        t(chat_id, "market_overview_title") + "\n",
        f"💰 *Total Market Cap:* {format_market_cap(total_mc)}{change_str}",
        f"💹 *24h Volume:* {format_market_cap(total_vol)}",
        f"🪙 *Active Coins:* {active}",
        f"🏦 *Exchanges:* {markets}\n",
        t(chat_id, "market_dominance_title") + "\n",
        f"₿ *Bitcoin (BTC)*",
        f"  `{bar(btc_d)}` {btc_d:.1f}%",
        "",
        f"Ξ *Ethereum (ETH)*",
        f"  `{bar(eth_d)}` {eth_d:.1f}%",
        "",
        f"🔷 *Others*",
        f"  `{bar(others_d)}` {others_d:.1f}%",
        f"\n_{t(chat_id, 'powered_by')}_",
    ]
    return "\n".join(lines)


def format_gainers(coins: list[dict], chat_id: int) -> str:
    sorted_coins = sorted(
        [c for c in coins if c.get("price_change_percentage_24h") is not None],
        key=lambda c: c["price_change_percentage_24h"],
        reverse=True,
    )
    gainers = sorted_coins[:10]
    losers = sorted_coins[-10:][::-1]

    def coin_line(c: dict) -> str:
        name = c.get("name", "?")
        sym = c.get("symbol", "").upper()
        price = format_price(c.get("current_price", 0))
        chg = c.get("price_change_percentage_24h", 0)
        arrow = "▲" if chg >= 0 else "▼"
        return f"  {name} ({sym}) — {price} {arrow} {abs(chg):.2f}%"

    lines = [t(chat_id, "gainers_title") + "\n"]
    lines.append(f"*{t(chat_id, 'gainers_section')}*")
    for c in gainers:
        lines.append(coin_line(c))
    lines.append("")
    lines.append(f"*{t(chat_id, 'losers_section')}*")
    for c in losers:
        lines.append(coin_line(c))
    lines.append(f"\n_{t(chat_id, 'powered_by')}_")
    return "\n".join(lines)


def format_trending(coins: list[dict], chat_id: int) -> str:
    medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣", "6️⃣", "7️⃣"]
    lines = [t(chat_id, "trending_title"), ""]
    for i, coin in enumerate(coins):
        medal = medals[i] if i < len(medals) else f"{i + 1}."
        name = coin.get("name", "?")
        symbol = coin.get("symbol", "").upper()
        rank = coin.get("market_cap_rank")
        rank_str = f"#{rank}" if rank else "N/A"
        price = coin.get("usd_price")
        change = coin.get("usd_24h_change")
        price_str = format_price(price) if price else "N/A"
        if change is not None:
            arrow = "▲" if change >= 0 else "▼"
            change_str = f"{arrow}{abs(change):.2f}%"
            change_icon = "📈" if change >= 0 else "📉"
        else:
            change_str = "N/A"
            change_icon = "➖"
        lines.append(
            f"{medal} *{name}* ({symbol})\n"
            f"   Rank: {rank_str}  |  {price_str}  |  {change_icon} {change_str}"
        )
    lines.append(f"\n_{t(chat_id, 'powered_by')}_")
    return "\n".join(lines)


def format_compare(coin_a: dict, coin_b: dict, chat_id: int) -> str:
    def mdata(coin):
        return coin.get("market_data", {})

    def pct(val):
        if val is None:
            return "N/A"
        arrow = "▲" if val >= 0 else "▼"
        return f"{arrow}{abs(val):.2f}%"

    na = coin_a.get("name", "?")
    nb = coin_b.get("name", "?")

    mda, mdb = mdata(coin_a), mdata(coin_b)

    price_a = mda.get("current_price", {}).get("usd", 0)
    price_b = mdb.get("current_price", {}).get("usd", 0)
    rank_a = coin_a.get("market_cap_rank")
    rank_b = coin_b.get("market_cap_rank")
    mc_a = mda.get("market_cap", {}).get("usd", 0)
    mc_b = mdb.get("market_cap", {}).get("usd", 0)
    vol_a = mda.get("total_volume", {}).get("usd", 0)
    vol_b = mdb.get("total_volume", {}).get("usd", 0)
    chg24_a = mda.get("price_change_percentage_24h")
    chg24_b = mdb.get("price_change_percentage_24h")
    chg7_a = mda.get("price_change_percentage_7d")
    chg7_b = mdb.get("price_change_percentage_7d")
    chg30_a = mda.get("price_change_percentage_30d")
    chg30_b = mdb.get("price_change_percentage_30d")
    ath_a = mda.get("ath", {}).get("usd", 0)
    ath_b = mdb.get("ath", {}).get("usd", 0)
    ath_chg_a = mda.get("ath_change_percentage", {}).get("usd")
    ath_chg_b = mdb.get("ath_change_percentage", {}).get("usd")
    circ_a = mda.get("circulating_supply")
    circ_b = mdb.get("circulating_supply")

    def rank_win(ra, rb):
        if ra is None or rb is None: return "", ""
        return ("✅", "") if ra <= rb else ("", "✅")

    def bigger_win(a, b):
        if a is None or b is None: return "", ""
        return ("✅", "") if a >= b else ("", "✅")

    rwa, rwb = rank_win(rank_a, rank_b)
    mcwa, mcwb = bigger_win(mc_a, mc_b)
    c24wa, c24wb = bigger_win(chg24_a, chg24_b)
    c7wa, c7wb = bigger_win(chg7_a, chg7_b)
    c30wa, c30wb = bigger_win(chg30_a, chg30_b)

    def row(label, val_a, val_b, win_a="", win_b=""):
        return (
            f"*{label}*\n"
            f"  {na}: {val_a} {win_a}\n"
            f"  {nb}: {val_b} {win_b}"
        )

    title = t(chat_id, "compare_title", name1=na, name2=nb)
    lines = [title + "\n"]
    lines.append(row("🏅 Rank",
        f"#{rank_a}" if rank_a else "N/A",
        f"#{rank_b}" if rank_b else "N/A",
        rwa, rwb))
    lines.append(row("💰 Price (USD)", format_price(price_a), format_price(price_b)))
    lines.append(row("📈 24h Change", pct(chg24_a), pct(chg24_b), c24wa, c24wb))
    lines.append(row("📆 7d Change", pct(chg7_a), pct(chg7_b), c7wa, c7wb))
    lines.append(row("🗓 30d Change", pct(chg30_a), pct(chg30_b), c30wa, c30wb))
    lines.append(row("📊 Market Cap", format_market_cap(mc_a), format_market_cap(mc_b), mcwa, mcwb))
    lines.append(row("💹 24h Volume", format_market_cap(vol_a), format_market_cap(vol_b)))
    lines.append(row("🏆 ATH", format_price(ath_a), format_price(ath_b)))
    lines.append(row("📉 From ATH", pct(ath_chg_a), pct(ath_chg_b)))
    lines.append(row("🔄 Circulating",
        f"{circ_a / 1_000_000:.2f}M" if circ_a else "N/A",
        f"{circ_b / 1_000_000:.2f}M" if circ_b else "N/A"))
    lines.append(f"\n_{t(chat_id, 'powered_by')}_")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------

async def check_alerts(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not alerts:
        return
    coin_ids: set[str] = set()
    for user_alerts in alerts.values():
        for a in user_alerts:
            coin_ids.add(a["coin_id"])
    if not coin_ids:
        return
    try:
        resp = requests.get(
            f"{COINGECKO_API}/simple/price",
            params={"ids": ",".join(coin_ids), "vs_currencies": "usd"},
            timeout=10,
        )
        resp.raise_for_status()
        live = resp.json()
    except requests.RequestException as e:
        print(f"Alert check failed: {e}")
        return

    for chat_id, user_alerts in list(alerts.items()):
        triggered, remaining = [], []
        for a in user_alerts:
            current = live.get(a["coin_id"], {}).get("usd")
            if current is None:
                remaining.append(a)
                continue
            fired = (
                (a["direction"] == "above" and current >= a["target"])
                or (a["direction"] == "below" and current <= a["target"])
            )
            (triggered if fired else remaining).append((a, current) if fired else a)
        alerts[chat_id] = remaining
        for a, current in triggered:
            direction_key = f"alert_triggered_{a['direction']}"
            arrow = "🚀" if a["direction"] == "above" else "🔻"
            msg = t(
                chat_id, "alert_triggered_msg",
                arrow=arrow,
                name=a["coin_name"],
                symbol=a["coin_symbol"],
                direction=t(chat_id, direction_key),
                target=format_price(a["target"]),
                current=format_price(current),
            )
            try:
                await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode=MD)
            except Exception as e:
                print(f"Failed to send alert to {chat_id}: {e}")


async def send_daily_update(context: ContextTypes.DEFAULT_TYPE) -> None:
    if not subscribers:
        return
    coins = await asyncio.to_thread(fetch_top_n, 10)
    global_data = await asyncio.to_thread(fetch_global_data)
    if not coins:
        return

    for chat_id in list(subscribers):
        lines = [t(chat_id, "daily_title") + "\n"]
        for coin in coins[:5]:
            name = coin.get("name", "?")
            sym = coin.get("symbol", "").upper()
            price = format_price(coin.get("current_price", 0))
            chg = coin.get("price_change_percentage_24h")
            chg_str = format_change(chg)
            emoji = "🟢" if (chg or 0) >= 0 else "🔴"
            lines.append(f"{emoji} *{name}* ({sym}): {price} {chg_str}")

        if global_data:
            dom = global_data.get("market_cap_percentage", {})
            btc_d = dom.get("btc", 0)
            eth_d = dom.get("eth", 0)
            total_mc = global_data.get("total_market_cap", {}).get("usd", 0)
            lines.append(f"\n💰 Market Cap: {format_market_cap(total_mc)}")
            lines.append(f"₿ BTC: {btc_d:.1f}%  Ξ ETH: {eth_d:.1f}%")

        lines.append(f"\n_{t(chat_id, 'powered_by')}_")
        try:
            await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode=MD)
        except Exception as e:
            print(f"Failed to send daily update to {chat_id}: {e}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    keyboard = build_main_menu_keyboard(chat_id)
    await update.message.reply_text(t(chat_id, "welcome_menu"), parse_mode=MD, reply_markup=keyboard)


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    await update.message.reply_text(t(chat_id, "help_text"), parse_mode=MD)


async def language_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
            InlineKeyboardButton("🇺🇿 O'zbek", callback_data="lang:uz"),
        ]
    ])
    await update.message.reply_text(t(chat_id, "language_choose"), reply_markup=keyboard)


async def prices(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text(t(chat_id, "fetching"))
    coins = await asyncio.to_thread(fetch_top_n, 50)
    if coins is None:
        await msg.edit_text(t(chat_id, "error_fetch"))
        return
    context.user_data["coins"] = coins
    text = build_prices_page(coins, 0, chat_id)
    keyboard = build_prices_keyboard(0, len(coins), chat_id)
    await msg.edit_text(text, parse_mode=MD, reply_markup=keyboard)


async def search(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(t(chat_id, "search_prompt"), parse_mode=MD)
        return

    query = " ".join(context.args)
    msg = await update.message.reply_text(t(chat_id, "searching", query=query), parse_mode=MD)

    coin = await asyncio.to_thread(search_coin, query)
    if coin is None:
        await msg.edit_text(t(chat_id, "error_search_no_results", query=query), parse_mode=MD)
        return

    coin_id = coin.get("id", "")
    name = coin.get("name", coin_id)
    symbol = coin.get("symbol", "").upper()

    text = format_coin_detail(coin, chat_id)
    caption = t(chat_id, "chart_caption", name=name, symbol=symbol)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data=f"search_refresh:{coin_id}")]
    ])

    chart_bytes = await build_chart(coin_id, name, symbol)
    if chart_bytes:
        await msg.delete()
        await update.message.reply_photo(photo=chart_bytes, caption=caption)
        await update.message.reply_text(text, parse_mode=MD, reply_markup=keyboard)
    else:
        await msg.edit_text(text, parse_mode=MD, reply_markup=keyboard)


async def gainers(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text(t(chat_id, "fetching"))
    coins = await asyncio.to_thread(fetch_top_n, 100)
    if coins is None:
        await msg.edit_text(t(chat_id, "error_fetch"))
        return
    text = format_gainers(coins, chat_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="gainers_refresh")]
    ])
    await msg.edit_text(text, parse_mode=MD, reply_markup=keyboard)


async def dominance(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text(t(chat_id, "fetching"))
    data = await asyncio.to_thread(fetch_global_data)
    if data is None:
        await msg.edit_text(t(chat_id, "error_fetch"))
        return
    text = format_dominance(data, chat_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="dominance_refresh")]
    ])
    await msg.edit_text(text, parse_mode=MD, reply_markup=keyboard)


async def alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(t(chat_id, "alert_usage"), parse_mode=MD)
        return

    *coin_parts, price_str = context.args
    coin_query = " ".join(coin_parts)

    try:
        target = float(price_str.replace(",", ""))
        if target <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(chat_id, "invalid_price", value=price_str), parse_mode=MD)
        return

    msg = await update.message.reply_text(t(chat_id, "looking_up", query=coin_query), parse_mode=MD)
    coin = await asyncio.to_thread(search_coin, coin_query)
    if coin is None:
        await msg.edit_text(t(chat_id, "error_coin_not_found", query=coin_query), parse_mode=MD)
        return

    coin_id = coin["id"]
    coin_name = coin.get("name", coin_id)
    coin_symbol = coin.get("symbol", "").upper()
    current = coin.get("market_data", {}).get("current_price", {}).get("usd", 0)
    direction = "above" if target > current else "below"
    alert_id = str(uuid.uuid4())[:8]

    alerts.setdefault(chat_id, []).append({
        "id": alert_id,
        "coin_id": coin_id,
        "coin_name": coin_name,
        "coin_symbol": coin_symbol,
        "target": target,
        "direction": direction,
    })

    await msg.edit_text(
        t(chat_id, "alert_set",
          name=coin_name, symbol=coin_symbol,
          direction=t(chat_id, f"alert_direction_{direction}"),
          target=format_price(target), current=format_price(current), id=alert_id),
        parse_mode=MD,
    )


async def list_alerts(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    user_alerts = alerts.get(chat_id, [])
    if not user_alerts:
        await update.message.reply_text(t(chat_id, "no_alerts"), parse_mode=MD)
        return

    lines = [t(chat_id, "alerts_title") + "\n"]
    for a in user_alerts:
        dir_key = f"alert_direction_{a['direction']}"
        lines.append(
            f"• *{a['coin_name']}* ({a['coin_symbol']}) "
            f"{t(chat_id, dir_key)} *{format_price(a['target'])}*\n"
            f"  ID: `{a['id']}`"
        )
    lines.append(f"\n_Use `/cancelalert <id>` to remove_")
    await update.message.reply_text("\n".join(lines), parse_mode=MD)


async def cancel_alert(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(t(chat_id, "cancelalert_usage"), parse_mode=MD)
        return
    alert_id = context.args[0].strip()
    user_alerts = alerts.get(chat_id, [])
    new_list = [a for a in user_alerts if a["id"] != alert_id]
    if len(new_list) < len(user_alerts):
        alerts[chat_id] = new_list
        await update.message.reply_text(t(chat_id, "alert_cancelled", id=alert_id), parse_mode=MD)
    else:
        await update.message.reply_text(t(chat_id, "alert_not_found", id=alert_id), parse_mode=MD)


async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    holdings = portfolios.get(chat_id, {})
    if not holdings:
        await update.message.reply_text(t(chat_id, "portfolio_empty"), parse_mode=MD)
        return
    msg = await update.message.reply_text(t(chat_id, "fetching"))
    prices_map = await asyncio.to_thread(fetch_portfolio_prices, list(holdings.keys()))
    text = format_portfolio_text(holdings, prices_map, chat_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="portfolio_refresh")]
    ])
    await msg.edit_text(text, parse_mode=MD, reply_markup=keyboard)


async def portfolio_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if len(context.args) < 2:
        await update.message.reply_text(t(chat_id, "portfolioadd_usage"), parse_mode=MD)
        return

    *coin_parts, amount_str = context.args
    coin_query = " ".join(coin_parts)

    try:
        amount = float(amount_str.replace(",", ""))
        if amount <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text(t(chat_id, "invalid_amount", value=amount_str), parse_mode=MD)
        return

    msg = await update.message.reply_text(t(chat_id, "looking_up", query=coin_query), parse_mode=MD)
    coin = await asyncio.to_thread(search_coin, coin_query)
    if coin is None:
        await msg.edit_text(t(chat_id, "error_coin_not_found", query=coin_query), parse_mode=MD)
        return

    coin_id = coin["id"]
    coin_name = coin.get("name", coin_id)
    coin_symbol = coin.get("symbol", "").upper()
    price_usd = coin.get("market_data", {}).get("current_price", {}).get("usd", 0)
    value_usd = price_usd * amount

    portfolios.setdefault(chat_id, {})[coin_id] = {
        "coin_id": coin_id,
        "coin_name": coin_name,
        "coin_symbol": coin_symbol,
        "amount": amount,
    }

    await msg.edit_text(
        t(chat_id, "portfolio_updated",
          name=coin_name, symbol=coin_symbol, amount=amount,
          price=format_price_multi(price_usd), value=format_price(value_usd)),
        parse_mode=MD,
    )


async def portfolio_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args:
        await update.message.reply_text(t(chat_id, "portfolioremove_usage"), parse_mode=MD)
        return
    holdings = portfolios.get(chat_id, {})
    if not holdings:
        await update.message.reply_text(t(chat_id, "portfolio_already_empty"), parse_mode=MD)
        return

    query = " ".join(context.args).lower()
    match_id = next(
        (cid for cid, entry in holdings.items()
         if cid == query
         or entry["coin_symbol"].lower() == query
         or entry["coin_name"].lower() == query),
        None,
    )

    if match_id is None:
        await update.message.reply_text(t(chat_id, "portfolio_not_found", query=query), parse_mode=MD)
        return

    removed = holdings.pop(match_id)
    await update.message.reply_text(
        t(chat_id, "portfolio_removed",
          name=removed["coin_name"], symbol=removed["coin_symbol"]),
        parse_mode=MD,
    )


async def trending(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text(t(chat_id, "trending_fetching"))
    coins = await asyncio.to_thread(fetch_trending_sync)
    if not coins:
        await msg.edit_text(t(chat_id, "trending_no_data"))
        return
    text = format_trending(coins, chat_id)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="trending_refresh")]
    ])
    await msg.edit_text(text, parse_mode=MD, reply_markup=keyboard)


async def compare(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if not context.args or len(context.args) < 2:
        await update.message.reply_text(t(chat_id, "compare_usage"), parse_mode=MD)
        return

    q1 = context.args[0]
    q2 = " ".join(context.args[1:])

    msg = await update.message.reply_text(
        t(chat_id, "compare_fetching", q1=q1, q2=q2), parse_mode=MD
    )

    coin_a, coin_b = await asyncio.gather(
        asyncio.to_thread(search_coin, q1),
        asyncio.to_thread(search_coin, q2),
    )

    if coin_a is None:
        await msg.edit_text(t(chat_id, "error_coin_not_found", query=q1), parse_mode=MD)
        return
    if coin_b is None:
        await msg.edit_text(t(chat_id, "error_coin_not_found", query=q2), parse_mode=MD)
        return

    id_a, id_b = coin_a["id"], coin_b["id"]
    name_a = coin_a.get("name", id_a)
    name_b = coin_b.get("name", id_b)

    chart_bytes, text = await asyncio.gather(
        build_compare_chart(id_a, id_b, name_a, name_b),
        asyncio.to_thread(format_compare, coin_a, coin_b, chat_id),
    )

    refresh_data = f"compare_refresh:{id_a}|{id_b}"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data=refresh_data)]
    ])

    if chart_bytes:
        caption = t(chat_id, "compare_chart_caption", name1=name_a, name2=name_b)
        await msg.delete()
        await update.message.reply_photo(photo=chart_bytes, caption=caption)
        await update.message.reply_text(text, parse_mode=MD, reply_markup=keyboard)
    else:
        await msg.edit_text(text, parse_mode=MD, reply_markup=keyboard)


async def subscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id in subscribers:
        await update.message.reply_text(t(chat_id, "already_subscribed"))
    else:
        subscribers.add(chat_id)
        await update.message.reply_text(t(chat_id, "subscribed"))


async def unsubscribe(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if chat_id not in subscribers:
        await update.message.reply_text(t(chat_id, "not_subscribed"))
    else:
        subscribers.discard(chat_id)
        await update.message.reply_text(t(chat_id, "unsubscribed"))


# ---------------------------------------------------------------------------
# Callback button handler
# ---------------------------------------------------------------------------

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    data = query.data
    chat_id = update.effective_chat.id

    # ── Main menu ────────────────────────────────────────────────────────────
    if data.startswith("menu:"):
        action = data.split(":")[1]

        if action == "back":
            await query.edit_message_text(
                t(chat_id, "welcome_menu"), parse_mode=MD,
                reply_markup=build_main_menu_keyboard(chat_id)
            )
            return

        if action == "top10":
            await query.edit_message_text(t(chat_id, "fetching"))
            coins = await asyncio.to_thread(fetch_top_n, 10)
            if coins is None:
                await query.edit_message_text(t(chat_id, "error_fetch"))
                return
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="top10_refresh")],
                [InlineKeyboardButton(t(chat_id, "btn_main_menu"), callback_data="menu:back")],
            ])
            await query.edit_message_text(format_top10(coins, chat_id), parse_mode=MD, reply_markup=keyboard)
            return

        if action == "top50":
            await query.edit_message_text(t(chat_id, "fetching"))
            coins = await asyncio.to_thread(fetch_top_n, 50)
            if coins is None:
                await query.edit_message_text(t(chat_id, "error_fetch"))
                return
            context.user_data["coins"] = coins
            await query.edit_message_text(
                build_prices_page(coins, 0, chat_id), parse_mode=MD,
                reply_markup=build_prices_keyboard(0, len(coins), chat_id)
            )
            return

        if action == "search":
            await query.edit_message_text(
                t(chat_id, "menu_search_tip"), parse_mode=MD,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(chat_id, "btn_main_menu"), callback_data="menu:back")]
                ])
            )
            return

        if action == "subscribe":
            if chat_id in subscribers:
                text = t(chat_id, "already_subscribed")
            else:
                subscribers.add(chat_id)
                text = t(chat_id, "subscribed")
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(t(chat_id, "btn_main_menu"), callback_data="menu:back")]
                ])
            )
            return

        if action == "language":
            await query.edit_message_text(
                t(chat_id, "language_choose"),
                reply_markup=InlineKeyboardMarkup([
                    [
                        InlineKeyboardButton("🇬🇧 English", callback_data="lang:en"),
                        InlineKeyboardButton("🇺🇿 O'zbek", callback_data="lang:uz"),
                    ],
                    [InlineKeyboardButton(t(chat_id, "btn_main_menu"), callback_data="menu:back")],
                ])
            )
            return

    # ── Top 10 refresh ───────────────────────────────────────────────────────
    if data == "top10_refresh":
        await query.edit_message_text(t(chat_id, "refreshing"))
        coins = await asyncio.to_thread(fetch_top_n, 10)
        if coins is None:
            await query.edit_message_text(t(chat_id, "error_fetch"))
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="top10_refresh")],
            [InlineKeyboardButton(t(chat_id, "btn_main_menu"), callback_data="menu:back")],
        ])
        await query.edit_message_text(format_top10(coins, chat_id), parse_mode=MD, reply_markup=keyboard)
        return

    # ── Language selection ───────────────────────────────────────────────────
    if data.startswith("lang:"):
        lang = data.split(":")[1]
        user_prefs.setdefault(chat_id, {})["lang"] = lang
        key = f"language_changed_{lang}"
        await query.edit_message_text(t(chat_id, key))
        return

    # ── Prices pagination ────────────────────────────────────────────────────
    if data.startswith("page:"):
        page = int(data.split(":")[1])
        coins = context.user_data.get("coins")
        if coins is None:
            await query.edit_message_text(t(chat_id, "session_expired"))
            return
        await query.edit_message_text(
            build_prices_page(coins, page, chat_id), parse_mode=MD,
            reply_markup=build_prices_keyboard(page, len(coins), chat_id)
        )
        return

    # ── Prices refresh ───────────────────────────────────────────────────────
    if data.startswith("refresh:"):
        page = int(data.split(":")[1])
        await query.edit_message_text(t(chat_id, "refreshing"))
        coins = await asyncio.to_thread(fetch_top_n, 50)
        if coins is None:
            await query.edit_message_text(t(chat_id, "error_fetch"))
            return
        context.user_data["coins"] = coins
        await query.edit_message_text(
            build_prices_page(coins, page, chat_id), parse_mode=MD,
            reply_markup=build_prices_keyboard(page, len(coins), chat_id)
        )
        return

    # ── Coin detail refresh ──────────────────────────────────────────────────
    if data.startswith("search_refresh:"):
        coin_id = data.split(":", 1)[1]
        await query.edit_message_text(t(chat_id, "refreshing"))
        try:
            resp = requests.get(
                f"{COINGECKO_API}/coins/{coin_id}",
                params={"localization": False, "tickers": False,
                        "community_data": False, "developer_data": False, "sparkline": False},
                timeout=10,
            )
            resp.raise_for_status()
            coin = resp.json()
        except requests.RequestException:
            await query.edit_message_text(t(chat_id, "error_fetch"))
            return
        text = format_coin_detail(coin, chat_id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data=f"search_refresh:{coin_id}")]
        ])
        await query.edit_message_text(text, parse_mode=MD, reply_markup=keyboard)
        return

    # ── Gainers refresh ──────────────────────────────────────────────────────
    if data == "gainers_refresh":
        await query.edit_message_text(t(chat_id, "refreshing"))
        coins = await asyncio.to_thread(fetch_top_n, 100)
        if coins is None:
            await query.edit_message_text(t(chat_id, "error_fetch"))
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="gainers_refresh")]
        ])
        await query.edit_message_text(format_gainers(coins, chat_id), parse_mode=MD, reply_markup=keyboard)
        return

    # ── Dominance refresh ────────────────────────────────────────────────────
    if data == "dominance_refresh":
        await query.edit_message_text(t(chat_id, "refreshing"))
        global_data = await asyncio.to_thread(fetch_global_data)
        if global_data is None:
            await query.edit_message_text(t(chat_id, "error_fetch"))
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="dominance_refresh")]
        ])
        await query.edit_message_text(format_dominance(global_data, chat_id), parse_mode=MD, reply_markup=keyboard)
        return

    # ── Trending refresh ─────────────────────────────────────────────────────
    if data == "trending_refresh":
        await query.edit_message_text(t(chat_id, "trending_fetching"))
        coins = await asyncio.to_thread(fetch_trending_sync)
        if not coins:
            await query.edit_message_text(t(chat_id, "trending_no_data"))
            return
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="trending_refresh")]
        ])
        await query.edit_message_text(format_trending(coins, chat_id), parse_mode=MD, reply_markup=keyboard)
        return

    # ── Compare refresh ──────────────────────────────────────────────────────
    if data.startswith("compare_refresh:"):
        payload = data.split(":", 1)[1]
        id_a, id_b = payload.split("|", 1)
        await query.edit_message_text(t(chat_id, "refreshing"))
        coin_a, coin_b = await asyncio.gather(
            asyncio.to_thread(lambda: requests.get(
                f"{COINGECKO_API}/coins/{id_a}",
                params={"localization": False, "tickers": False,
                        "community_data": False, "developer_data": False, "sparkline": False},
                timeout=10,
            ).json()),
            asyncio.to_thread(lambda: requests.get(
                f"{COINGECKO_API}/coins/{id_b}",
                params={"localization": False, "tickers": False,
                        "community_data": False, "developer_data": False, "sparkline": False},
                timeout=10,
            ).json()),
        )
        text = format_compare(coin_a, coin_b, chat_id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data=data)]
        ])
        await query.edit_message_text(text, parse_mode=MD, reply_markup=keyboard)
        return

    # ── Portfolio refresh ────────────────────────────────────────────────────
    if data == "portfolio_refresh":
        holdings = portfolios.get(chat_id, {})
        if not holdings:
            await query.edit_message_text(t(chat_id, "portfolio_empty"), parse_mode=MD)
            return
        await query.edit_message_text(t(chat_id, "refreshing"))
        prices_map = await asyncio.to_thread(fetch_portfolio_prices, list(holdings.keys()))
        text = format_portfolio_text(holdings, prices_map, chat_id)
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(t(chat_id, "btn_refresh"), callback_data="portfolio_refresh")]
        ])
        await query.edit_message_text(text, parse_mode=MD, reply_markup=keyboard)
        return


# ---------------------------------------------------------------------------
# Keepalive web server (Flask)
# ---------------------------------------------------------------------------

def _run_flask() -> None:
    from flask import Flask
    server = Flask(__name__)

    @server.route("/")
    def home():
        return "🤖 CryptoBot is running!", 200

    @server.route("/health")
    def health():
        return {"status": "ok"}, 200

    server.run(host="0.0.0.0", port=5000, use_reloader=False)


def start_keepalive() -> None:
    t = threading.Thread(target=_run_flask, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is not set")

    start_keepalive()
    refresh_exchange_rates_sync()

    app = Application.builder().token(token).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("language", language_command))
    app.add_handler(CommandHandler("prices", prices))
    app.add_handler(CommandHandler("search", search))
    app.add_handler(CommandHandler("gainers", gainers))
    app.add_handler(CommandHandler("trending", trending))
    app.add_handler(CommandHandler("compare", compare))
    app.add_handler(CommandHandler("dominance", dominance))
    app.add_handler(CommandHandler("alert", alert))
    app.add_handler(CommandHandler("alerts", list_alerts))
    app.add_handler(CommandHandler("cancelalert", cancel_alert))
    app.add_handler(CommandHandler("portfolio", portfolio))
    app.add_handler(CommandHandler("portfolioadd", portfolio_add))
    app.add_handler(CommandHandler("portfolioremove", portfolio_remove))
    app.add_handler(CommandHandler("subscribe", subscribe))
    app.add_handler(CommandHandler("unsubscribe", unsubscribe))
    app.add_handler(CallbackQueryHandler(button_handler))

    app.job_queue.run_repeating(check_alerts, interval=ALERT_CHECK_INTERVAL, first=10)
    app.job_queue.run_repeating(refresh_exchange_rates_job, interval=3600, first=3600)
    app.job_queue.run_daily(send_daily_update, time=datetime.now(timezone.utc).replace(
        hour=DAILY_UPDATE_HOUR, minute=0, second=0, microsecond=0
    ).timetz())

    print("🤖 CryptoBot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

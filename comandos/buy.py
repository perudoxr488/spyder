import os
import json
import sqlite3
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from storage import db_path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")
DB_PATH = db_path("multiplataforma.db")

cfg = {}
if os.path.exists(CONFIG_FILE_PATH):
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"⚠️ Error leyendo config.json: {e}")
else:
    print(f"⚠️ No se encontró {CONFIG_FILE_PATH}")


def non_empty(s: str) -> bool:
    return isinstance(s, str) and s.strip() != ""


def btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, url=url)


def _get_buy_groups():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS buy_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK(kind IN ('credits', 'days')),
            group_slug TEXT NOT NULL,
            badge TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            subtitle TEXT DEFAULT '',
            line_text TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        SELECT kind, group_slug, badge, title, subtitle, line_text
        FROM buy_packages
        WHERE is_active = 1
        ORDER BY kind ASC, sort_order ASC, id ASC
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()

    grouped = {"credits": [], "days": []}
    seen = {}
    for row in rows:
        key = (row["kind"], row["group_slug"])
        if key not in seen:
            entry = {
                "badge": row["badge"],
                "title": row["title"],
                "subtitle": row["subtitle"],
                "items": [],
            }
            grouped[row["kind"]].append(entry)
            seen[key] = entry
        seen[key]["items"].append(row["line_text"])
    return grouped


def _get_panel_settings():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS panel_settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
        """
    )
    cur.execute("SELECT key, value FROM panel_settings")
    data = {row["key"]: row["value"] for row in cur.fetchall()}
    conn.close()
    return data


def _build_buy_text(bot_arroba: str) -> str:
    groups = _get_buy_groups()
    parts = [
        "✨ <b>PLANES Y TARIFAS</b> ✨",
        f"⚡️ <i>By:</i> <b>{bot_arroba}</b>",
        "",
        "💰 <b>PLAN POR CREDITOS</b> 💰",
        "",
    ]

    if groups["credits"]:
        for group in groups["credits"]:
            parts.append(f"⟦{group['badge']}⟧ <b>{group['title']} ({group['subtitle']})</b>")
            for item in group["items"]:
                parts.append(f"• {item}")
            parts.append("")
    else:
        parts.append("Sin paquetes de créditos configurados.")
        parts.append("")

    parts.append("⏳ <b>PLAN POR DIAS</b> ⏳")
    parts.append("")

    if groups["days"]:
        for group in groups["days"]:
            parts.append(f"⟦{group['badge']}⟧ <b>{group['title']} ({group['subtitle']})</b>")
            for item in group["items"]:
                parts.append(f"• {item}")
            parts.append("")
    else:
        parts.append("Sin paquetes por días configurados.")
        parts.append("")

    parts.append("[⚠️] <b>IMPORTANTE</b> ➩ Antes de comprar leer los terminos y condiciones usa /terminos")
    return "\n".join(parts).strip()


async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    me = await context.bot.get_me()
    bot_arroba = f"@{me.username}" if non_empty(me.username) else "bot"
    texto = _build_buy_text(bot_arroba)
    settings = _get_panel_settings()

    buttons = []

    owner_text = settings.get("BT_OWNER") or cfg.get("BT_OWNER")
    owner_link = settings.get("OWNER_LINK") or cfg.get("OWNER_LINK")
    if non_empty(owner_text) and non_empty(owner_link):
        buttons.append(btn(f"[❄️] {owner_text}", owner_link))

    sellers = [
        (settings.get("BT_SELLER") or cfg.get("BT_SELLER"), settings.get("SELLER_LINK") or cfg.get("SELLER_LINK")),
        (settings.get("BT_SELLER1") or cfg.get("BT_SELLER1"), settings.get("SELLER_LINK1") or cfg.get("SELLER_LINK1")),
        (settings.get("BT_SELLER2") or cfg.get("BT_SELLER2"), settings.get("SELLER_LINK2") or cfg.get("SELLER_LINK2")),
        (settings.get("BT_SELLER3") or cfg.get("BT_SELLER3"), settings.get("SELLER_LINK3") or cfg.get("SELLER_LINK3")),
    ]
    for text, url in sellers:
        if non_empty(text) and non_empty(url):
            buttons.append(btn(f"[❄️] {text}", url))

    rows = []
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i + 2])

    keyboard = InlineKeyboardMarkup(rows) if rows else None
    ft_buy = settings.get("FT_BUY") or (cfg.get("LOGO") or {}).get("FT_BUY")

    if non_empty(ft_buy):
        await update.message.reply_photo(
            photo=ft_buy,
            caption=texto,
            parse_mode="HTML",
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id,
        )
    else:
        await update.message.reply_text(
            text=texto,
            parse_mode="HTML",
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id,
        )

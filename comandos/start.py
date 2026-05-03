import os
import json
import sqlite3
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from storage import db_path

# --- Cargar config.json ---
CONFIG_FILE_PATH = 'config.json'
DB_PATH = db_path("multiplataforma.db")
cfg = {}
if os.path.exists(CONFIG_FILE_PATH):
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            cfg = json.load(f)
    except Exception as e:
        print(f"⚠️ Error leyendo config.json: {e}")
else:
    print(f"⚠️ No se encontró {CONFIG_FILE_PATH}")

def non_empty(s: str) -> bool:
    return isinstance(s, str) and s.strip() != ""

def btn(text: str, url: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, url=url)


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

# --- /start ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    settings = _get_panel_settings()

    MARCA       = cfg.get("MARCA")
    NAME        = cfg.get("NAME")
    VERSION     = cfg.get("VERSION")
    LOGO_URL    = settings.get("FT_START") or (cfg.get("LOGO") or {}).get("FT_START")

    GRUPO_LINK  = settings.get("GRUPO_LINK") or cfg.get("GRUPO_LINK")
    CANAL_LINK  = settings.get("CANAL_LINK") or cfg.get("CANAL_LINK")
    OWNER_LINK  = settings.get("OWNER_LINK") or cfg.get("OWNER_LINK")

    BT_OWNER    = settings.get("BT_OWNER") or cfg.get("BT_OWNER") or "OWNER"
    BT_CANAL    = settings.get("BT_CANAL") or cfg.get("BT_CANAL") or "CANAL"
    BT_GRUPO    = settings.get("BT_GRUPO") or cfg.get("BT_GRUPO") or "GRUPO"

    sellers_raw = [
        (settings.get("BT_SELLER") or cfg.get("BT_SELLER"),  settings.get("SELLER_LINK") or cfg.get("SELLER_LINK")),
        (settings.get("BT_SELLER1") or cfg.get("BT_SELLER1"), settings.get("SELLER_LINK1") or cfg.get("SELLER_LINK1")),
        (settings.get("BT_SELLER2") or cfg.get("BT_SELLER2"), settings.get("SELLER_LINK2") or cfg.get("SELLER_LINK2")),
        (settings.get("BT_SELLER3") or cfg.get("BT_SELLER3"), settings.get("SELLER_LINK3") or cfg.get("SELLER_LINK3")),
    ]

    if not (non_empty(GRUPO_LINK) and non_empty(CANAL_LINK) and non_empty(OWNER_LINK)):
        await update.message.reply_text(
            "⚠️ Config incompleta: faltan enlaces obligatorios (GRUPO_LINK, CANAL_LINK u OWNER_LINK) en config.json.",
            reply_to_message_id=update.message.message_id
        )
        return

    marca_visible = MARCA or NAME or "BOT"
    version_line = f" - <code>{VERSION}</code>" if non_empty(VERSION) else ""
    caption = (
        f"👋 Hola, <b><a href='tg://user?id={user.id}'>{user.first_name}</a></b>\n\n"
        f"Has ingresado a: <b>{marca_visible}</b>{version_line}\n"
        "Un espacio donde los datos se convierten en conocimiento útil.\n\n"
        "<b>Comandos principales</b>\n"
        "/register ➾ Registra tu cuenta\n"
        "/cmds ➾ Lista de comandos\n"
        "/me ➾ Revisa tu perfil y actividad\n"
        "/buy ➾ Compra Cred/Dias\n\n"
        "<b>Nota</b>\n"
        "El uso de la información recae bajo total responsabilidad del usuario."
    )

    # Botones obligatorios
    buttons = [
        btn(f"[💭] {BT_GRUPO}", GRUPO_LINK),
        btn(f"[📣] {BT_CANAL}", CANAL_LINK),
        btn(f"[❄️] {BT_OWNER}", OWNER_LINK),
    ]

    # Botones opcionales (sellers)
    for text, url in sellers_raw:
        if non_empty(text) and non_empty(url):
            buttons.append(btn(f"[❄️] {text}", url))

    # Distribuir en filas de 2 botones
    rows = []
    for i in range(0, len(buttons), 2):
        rows.append(buttons[i:i+2])

    keyboard = InlineKeyboardMarkup(rows)

    if non_empty(LOGO_URL):
        await update.message.reply_photo(
            photo=LOGO_URL,
            caption=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )
    else:
        await update.message.reply_text(
            text=caption,
            parse_mode="HTML",
            reply_markup=keyboard,
            reply_to_message_id=update.message.message_id
        )

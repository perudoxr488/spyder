import html
import json
import os
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError
from telegram import Update
from telegram.ext import ContextTypes

from comandos.precios_config import PRECIOS_COMANDOS

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")

CFG = {}
try:
    if os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f) or {}
except Exception:
    CFG = {}

API_BASE = (
    os.environ.get("SPIDERSYN_API_BASE")
    or os.environ.get("API_BASE")
    or os.environ.get("API_DB_BASE")
    or CFG.get("API_DB_BASE")
    or CFG.get("API_BASE")
    or ""
).rstrip("/")
INTERNAL_API_KEY = (
    os.environ.get("SPIDERSYN_INTERNAL_API_KEY")
    or os.environ.get("INTERNAL_API_KEY")
    or CFG.get("INTERNAL_API_KEY")
    or CFG.get("TOKEN_BOT")
    or ""
).strip()


def _fetch_catalog_prices():
    if not API_BASE:
        return []
    headers = {"User-Agent": "SpiderSynBot/1.0"}
    if INTERNAL_API_KEY:
        headers["X-Internal-Api-Key"] = INTERNAL_API_KEY
    req = _urlreq.Request(f"{API_BASE}/bot_catalog", headers=headers)
    try:
        with _urlreq.urlopen(req, timeout=12) as resp:
            js = json.loads(resp.read().decode("utf-8", errors="replace"))
    except (HTTPError, URLError, Exception):
        return []
    if (js or {}).get("status") != "ok":
        return []
    commands = ((js or {}).get("data") or {}).get("commands") or []
    rows = []
    for cmd in commands:
        if not bool(cmd.get("is_active", True)):
            continue
        rows.append(
            {
                "slug": str(cmd.get("slug") or "").strip().lower(),
                "name": str(cmd.get("name") or cmd.get("slug") or "").strip(),
                "cost": int(cmd.get("cost") or 0),
                "category": str(cmd.get("category_name") or "SIN CATEGORIA").strip(),
            }
        )
    return sorted(rows, key=lambda item: (item["category"], item["slug"]))


async def precios_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    catalog_rows = _fetch_catalog_prices()
    if catalog_rows:
        texto = ["💳 <b>PRECIOS DEL BOT</b>\n"]
        current = None
        for row in catalog_rows:
            if row["category"] != current:
                current = row["category"]
                texto.append(f"\n<b>{html.escape(current)}</b>")
            texto.append(f"• <code>/{html.escape(row['slug'])}</code> → <code>{row['cost']}</code> créditos")
        await msg.reply_text(
            "\n".join(texto),
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
        )
        return

    if not PRECIOS_COMANDOS:
        await msg.reply_text(
            "⚠️ No hay precios configurados.",
            reply_to_message_id=msg.message_id
        )
        return

    texto = []
    texto.append("💳 <b>PRECIOS DEL BOT</b>\n")

    for comando, precio in sorted(PRECIOS_COMANDOS.items()):
        texto.append(f"• <b>{html.escape(comando.upper())}</b> → <code>{precio}</code> créditos")

    await msg.reply_text(
        "\n".join(texto),
        parse_mode="HTML",
        reply_to_message_id=msg.message_id
    )

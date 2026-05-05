import os
import json
import html
import sqlite3
from urllib import parse as _urlparse
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import Update
from telegram.ext import ContextTypes
from storage import db_path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")
DB_PATH = db_path("multiplataforma.db")

CFG = {}
try:
    if os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f) or {}
except Exception:
    CFG = {}

_admin_raw = CFG.get("ADMIN_ID")
if isinstance(_admin_raw, list):
    ADMIN_IDS = {int(x) for x in _admin_raw if str(x).isdigit()}
elif _admin_raw is None:
    ADMIN_IDS = set()
else:
    ADMIN_IDS = {int(_admin_raw)} if str(_admin_raw).isdigit() else set()

BOT_BRAND = (CFG.get("BOT_NAME") or CFG.get("NAME") or "#BOT").strip()
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
CMDS = CFG.get("CMDS", {}) or {}
LOGO = CFG.get("LOGO", {}) or {}
_ALLOWED_VIEW = {"FUNDADOR", "CO-FUNDADOR", "SELLER"}


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
    rows = {row["key"]: row["value"] for row in cur.fetchall()}
    conn.close()
    return rows


def _fetch_json(url: str, timeout: int = 18):
    headers = {"User-Agent": "tussybot/1.0"}
    if INTERNAL_API_KEY:
        headers["X-Internal-Api-Key"] = INTERNAL_API_KEY
    req = _urlreq.Request(url, headers=headers)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            st = resp.getcode() or 200
            body = resp.read().decode("utf-8", errors="replace")
            return st, json.loads(body)
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            return e.code, {"status": "error"}
    except URLError:
        return 599, {"status": "error"}
    except Exception:
        return 500, {"status": "error"}


def _get_role(uid: int) -> str:
    if uid in ADMIN_IDS:
        return "ADMIN"
    if not API_BASE:
        return ""
    st, js = _fetch_json(f"{API_BASE}/tg_info?ID_TG={_urlparse.quote(str(uid))}")
    if st != 200:
        return ""
    return ((js.get("data") or {}).get("ROL_TG") or "").upper()


def _get_catalog():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS command_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS command_catalog (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category_id INTEGER,
            cost INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            usage_hint TEXT DEFAULT '',
            FOREIGN KEY (category_id) REFERENCES command_categories(id)
        )
        """
    )
    cur.execute(
        """
        SELECT cat.name AS category_name, cat.is_active AS category_active,
               c.slug, c.name, c.cost, c.is_active, c.usage_hint, c.description
        FROM command_catalog c
        LEFT JOIN command_categories cat ON cat.id = c.category_id
        ORDER BY COALESCE(cat.sort_order, 9999), COALESCE(cat.name, 'ZZZ'), c.sort_order ASC, c.name ASC
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    grouped = {}
    for row in rows:
        category = row["category_name"] or "SIN CATEGORIA"
        grouped.setdefault(category, []).append(row)
    return grouped


def _build_admin_menu() -> str:
    grouped = _get_catalog()
    lines = [
        f"🛠️ <b>{html.escape(BOT_BRAND)} • CMDS ADMIN</b>",
        "",
        "Panel web local: <code>http://127.0.0.1:8080/admin/panel</code>",
        "Créditos: <code>/setcred</code> <code>/cred</code> <code>/uncred</code>",
        "Días: <code>/setsub</code> <code>/sub</code> <code>/unsub</code>",
        "Rol: <code>/setrol ID|ROL</code>",
        "Anti-spam: <code>/setantispam ID|SEGUNDOS</code>",
        "Global: <code>/global mensaje</code> o responde un mensaje con <code>/global</code>",
        "",
    ]
    for category, commands in grouped.items():
        active_count = sum(1 for cmd in commands if cmd["is_active"])
        lines.append(f"📚 <b>{html.escape(category)}</b> · <code>{active_count}/{len(commands)}</code> activos")
        for cmd in commands:
            state = "✅ ACTIVO" if cmd["is_active"] else "⛔ INACTIVO"
            usage = cmd["usage_hint"] or f"/{cmd['slug']}"
            info = cmd["description"] or "Sin info"
            lines.append(
                f"• <code>/{html.escape(cmd['slug'])}</code> | {state} | <code>{int(cmd['cost'])} cr</code> | "
                f"<code>{html.escape(usage)}</code> | <i>{html.escape(info)}</i>"
            )
        lines.append("")
    return "\n".join(lines).strip()


async def cmdsadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    settings = _get_panel_settings()
    ft_cmdsadmin = (
        (settings.get("FT_CMDSADMIN") or "").strip()
        or (settings.get("FT_CMDS") or "").strip()
        or (LOGO.get("FT_CMDSADMIN") or "").strip()
        or (LOGO.get("FT_CMDS") or "").strip()
        or (CMDS.get("FT_CMDSADMIN") or "").strip()
        or ""
    )
    role = _get_role(user.id)
    if (user.id not in ADMIN_IDS) and (role not in _ALLOWED_VIEW):
        await msg.reply_text(
            "❌ <b>Acceso denegado</b>\nSolo para FUNDADOR / CO-FUNDADOR / SELLER o ADMIN_ID.",
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
        )
        return

    text = _build_admin_menu()
    if ft_cmdsadmin:
        try:
            await msg.reply_photo(
                photo=ft_cmdsadmin,
                caption=text[:1000],
                parse_mode="HTML",
                reply_to_message_id=msg.message_id,
            )
            if len(text) > 1000:
                await msg.reply_text(
                    text[1000:],
                    parse_mode="HTML",
                    disable_web_page_preview=True,
                    reply_to_message_id=msg.message_id,
                )
            return
        except Exception:
            pass

    await msg.reply_text(
        text,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_to_message_id=msg.message_id,
    )

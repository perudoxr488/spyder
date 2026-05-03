import os
import json
import html
import sqlite3
import json as jsonlib
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional, Tuple
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import Update
from telegram.ext import ContextTypes
from storage import db_path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")
DB_PATH = db_path("multiplataforma.db")

BOT_NAME = ""
API_BASE = ""
INTERNAL_API_KEY = ""
cfg = {}
_SETTINGS_CACHE = {"ts": 0.0, "data": None}

if os.path.exists(CONFIG_FILE_PATH):
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        BOT_NAME = (cfg.get("BOT_NAME") or cfg.get("NAME") or "SpiderSyn").strip()
    except Exception:
        BOT_NAME = ""
        cfg = {}

API_BASE = (
    os.environ.get("SPIDERSYN_API_BASE")
    or os.environ.get("API_BASE")
    or os.environ.get("API_DB_BASE")
    or cfg.get("API_DB_BASE")
    or cfg.get("API_BASE")
    or ""
).rstrip("/")
INTERNAL_API_KEY = (
    os.environ.get("SPIDERSYN_INTERNAL_API_KEY")
    or os.environ.get("INTERNAL_API_KEY")
    or cfg.get("INTERNAL_API_KEY")
    or cfg.get("TOKEN_BOT")
    or ""
).strip()


def _to_lima_iso_hm(iso_str: Optional[str]) -> str:
    if not iso_str:
        return "—"
    s = iso_str.strip()
    if s.endswith("Z"):
        s = s[:-1]
    try:
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except Exception:
        return iso_str
    try:
        lima = dt.astimezone(ZoneInfo("America/Lima"))
    except Exception:
        lima = dt
    return lima.strftime("%Y-%m-%d %H:%M:%S")


def _days_left(exp_iso: Optional[str]) -> Tuple[str, bool, Optional[int]]:
    if not exp_iso:
        return ("Sin plan", False, None)
    s = exp_iso.strip()
    if s.endswith("Z"):
        s = s[:-1]
    try:
        exp = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except Exception:
        return (exp_iso, False, None)

    now = datetime.now(timezone.utc)
    delta = exp - now
    days = int(delta.total_seconds() // 86400)

    if delta.total_seconds() <= 0:
        return (f"Vencido hace {abs(days)} día(s)", False, max(days, 0))

    return (f"{days} día(s)", True, days)


def _fetch_json(url: str, timeout: int = 15):
    headers = {"User-Agent": "tussybot/1.0"}
    if INTERNAL_API_KEY:
        headers["X-Internal-Api-Key"] = INTERNAL_API_KEY
    req = _urlreq.Request(url, headers=headers)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode() or 200
            data = resp.read().decode("utf-8", errors="replace")
            try:
                return status, jsonlib.loads(data)
            except Exception:
                return status, {"status": "error", "message": data}
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            data = jsonlib.loads(body)
        except Exception:
            data = {"status": "error", "message": str(e)}
        return e.code, data
    except URLError as e:
        return 599, {"status": "error", "message": str(e)}
    except Exception as e:
        return 500, {"status": "error", "message": str(e)}


def _get_remote_settings() -> dict:
    now = time.monotonic()
    if _SETTINGS_CACHE["data"] is not None and now - float(_SETTINGS_CACHE["ts"]) < 30:
        return _SETTINGS_CACHE["data"]
    if not API_BASE:
        return {}
    st, js = _fetch_json(f"{API_BASE}/bot_catalog", timeout=12)
    if st == 200 and js.get("status") == "ok":
        data = ((js.get("data") or {}).get("settings") or {})
        _SETTINGS_CACHE["ts"] = now
        _SETTINGS_CACHE["data"] = data
        return data
    return {}


def _bot_brand() -> str:
    settings = _get_remote_settings()
    raw = (
        settings.get("BOT_NAME")
        or settings.get("NAME")
        or os.environ.get("SPIDERSYN_BOT_NAME")
        or BOT_NAME
        or cfg.get("BOT_NAME")
        or cfg.get("NAME")
        or "#SPIDERSYN"
    )
    raw = str(raw).strip() or "#SPIDERSYN"
    if raw.upper() == "SPIDERSYN":
        raw = "#SPIDERSYN"
    if "⇒" not in raw and "➾" not in raw:
        raw = f"{raw} ⇒"
    return raw


async def me_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    invoker = update.effective_user
    msg = update.effective_message

    target_id = str(invoker.id)
    if context.args:
        arg = (context.args[0] or "").strip()
        if arg.isdigit():
            target_id = arg
        else:
            await msg.reply_text(
                "⚠️ Formato inválido. Usa <code>/me</code> o <code>/me ID_TG</code>.",
                parse_mode="HTML",
                disable_web_page_preview=True,
                reply_to_message_id=msg.message_id,
            )
            return

    if not API_BASE:
        await msg.reply_text(
            "❌ <b>API no configurada</b>\n\n"
            "Revisa la clave <code>API_DB_BASE</code> en tu <code>config.json</code>.",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_to_message_id=msg.message_id,
        )
        return

    s1, j1 = _fetch_json(f"{API_BASE}/tg_info?ID_TG={target_id}")
    if s1 == 404:
        await msg.reply_text(
            "⚠️ Usuario no encontrado en la base. Usa /register primero.",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_to_message_id=msg.message_id,
        )
        return

    if s1 != 200:
        await msg.reply_text(
            f"⚠️ Error consultando perfil (code {s1}): "
            f"<code>{html.escape(str(j1.get('message', 'error')))}</code>",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_to_message_id=msg.message_id,
        )
        return

    data = j1.get("data", {}) or {}
    antispam = data.get("ANTISPAM", "—")
    creditos = data.get("CREDITOS", "—")
    estado = data.get("ESTADO", "—")
    fecha_reg = data.get("FECHA_REGISTER_TG")
    id_api = data.get("ID_TG", target_id)
    plan = data.get("PLAN", "—")
    rol_tg = data.get("ROL_TG", "—")
    exp = data.get("FECHA DE CADUCIDAD")

    s2, j2 = _fetch_json(f"{API_BASE}/historial_id?ID_TG={target_id}")
    total_consultas = 0
    hoy_consultas = 0

    if s2 == 200:
        rows = j2.get("data", []) or []
        total_consultas = len(rows)
        try:
            lima_today = datetime.now(ZoneInfo("America/Lima")).date()
        except Exception:
            lima_today = datetime.utcnow().date()

        for r in rows:
            f = r.get("FECHA")
            if not f:
                continue
            ff = f[:-1] if f.endswith("Z") else f
            try:
                dt = datetime.fromisoformat(ff).replace(tzinfo=timezone.utc)
                try:
                    dt = dt.astimezone(ZoneInfo("America/Lima"))
                except Exception:
                    pass
                if dt.date() == lima_today:
                    hoy_consultas += 1
            except Exception:
                pass

    target_name = None
    target_username = None
    try:
        chat = await context.bot.get_chat(int(target_id))
        target_name = getattr(chat, "first_name", None) or getattr(chat, "title", None)
        target_username = getattr(chat, "username", None)
    except Exception:
        if target_id == str(invoker.id):
            target_name = invoker.first_name
            target_username = invoker.username

    perfil_link = f"https://t.me/{target_username}" if target_username else f"tg://user?id={target_id}"
    nombre_html = html.escape(target_name or f"ID {target_id}")

    exp_str_local = _to_lima_iso_hm(exp)
    tiempo_str, activo, _ = _days_left(exp)
    creditos_str = f"{creditos}{' ♾️' if activo else ''}"

    header = f"{_bot_brand()} ME - PERFIL"

    caption = (
        f"<b>{header}</b>\n"
        f"\n<b>PERFIL DE</b> ➾ <a href=\"{perfil_link}\">{nombre_html}</a>\n"
        f"\n<b>INFORMACIÓN PERSONAL</b>\n"
        f"[🙎‍♂️] <b>ID</b> ➾ <code>{id_api}</code>\n"
        f"[👨🏻‍💻] <b>USER</b> ➾ @{target_username if target_username else '—'}\n"
        f"[👺] <b>ESTADO</b> ➾ {html.escape(str(estado))}\n"
        f"[📅] <b>F. REGISTRO</b> ➾ {_to_lima_iso_hm(fecha_reg)}\n"
        f"\n<b>🌐 ESTADO DE CUENTA</b>\n\n"
        f"[〽️] <b>ROL TG</b> ➾ <code>{html.escape(str(rol_tg))}</code>\n"
        f"[📈] <b>PLAN</b> ➾ <code>{html.escape(str(plan))}</code>\n"
        f"[⏱️] <b>ANTI-SPAM</b> ➾ <code>{html.escape(str(antispam))}</code>\n"
        f"[💰] <b>CREDITOS</b> ➾ <code>{html.escape(str(creditos_str))}</code>\n"
        f"[⏳] <b>TIEMPO</b> ➾ <code>{html.escape(str(tiempo_str))}</code>\n"
        f"[📅] <b>F. EXPIRACIÓN</b> ➾ <code>{html.escape(str(exp_str_local))}</code>\n"
        f"[📊] <b>TOTAL CONSULTAS</b> ➾ <code>{total_consultas}</code>\n"
        f"[🗓️] <b>CONSULTAS HOY</b> ➾ <code>{hoy_consultas}</code>\n"
        f"\n[🛒] <b>Verifica tus compras</b> ➾ /compras"
    )

    try:
        photos = await context.bot.get_user_profile_photos(user_id=int(target_id), limit=1)
        if photos and photos.total_count > 0:
            largest = photos.photos[0][-1]
            await msg.reply_photo(
                photo=largest.file_id,
                caption=caption,
                parse_mode="HTML",
                reply_to_message_id=msg.message_id,
            )
            return
    except Exception:
        pass

    await msg.reply_text(
        caption,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_to_message_id=msg.message_id,
    )


async def me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id

    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT creditos, fecha_caducidad FROM usuarios WHERE id_tg = ?",
            (user_id,),
        )
        result = cursor.fetchone()
        conn.close()
    except Exception as e:
        await update.message.reply_text(f"Error consultando la base local: {e}")
        return

    if result:
        credits, expiration_date = result
        days_left = None

        if expiration_date:
            try:
                expiration_date = datetime.strptime(expiration_date, "%Y-%m-%d %H:%M:%S")
                days_left = (expiration_date - datetime.now()).days
            except Exception:
                days_left = None

        response = (
            f"Tu perfil:\n"
            f"Créditos: {credits}\n"
            f"Días válidos: {days_left if days_left is not None else 'No tiene fecha de caducidad'}"
        )
        await update.message.reply_text(response)
    else:
        await update.message.reply_text("No se encontraron datos para tu perfil.")

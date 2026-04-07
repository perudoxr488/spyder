import os
import json
import html
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import Update
from telegram.ext import ContextTypes

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")

BOT_NAME = ""
API_BASE = ""
INTERNAL_API_KEY = ""
cfg = {}

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


def _fetch_json(url: str, timeout: int = 15):
    headers = {"User-Agent": "tussybot/1.0"}
    if INTERNAL_API_KEY:
        headers["X-Internal-Api-Key"] = INTERNAL_API_KEY
    req = _urlreq.Request(url, headers=headers)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode() or 200
            body = resp.read().decode("utf-8", errors="replace")
            try:
                import json as _json
                return status, _json.loads(body)
            except Exception:
                return status, {"status": "error", "message": body}
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            import json as _json
            data = _json.loads(body)
        except Exception:
            data = {"status": "error", "message": str(e)}
        return e.code, data
    except URLError as e:
        return 599, {"status": "error", "message": str(e)}
    except Exception as e:
        return 500, {"status": "error", "message": str(e)}


async def register_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    msg = update.effective_message
    id_tg = str(user.id)

    if not API_BASE:
        await msg.reply_text(
            "❌ <b>API no configurada</b>\n\n"
            "Revisa la clave <code>API_DB_BASE</code> en tu <code>config.json</code>.",
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_to_message_id=msg.message_id,
        )
        return

    status, data = _fetch_json(f"{API_BASE}/register?ID_TG={id_tg}")

    nombre = html.escape(user.first_name or "Usuario")
    perfil = f"https://t.me/{user.username}" if user.username else f"tg://user?id={user.id}"
    header = f"{BOT_NAME} REGISTRO".strip() or "REGISTRO"

    if status == 200:
        texto = (
            f"🎉 <b>{header}</b>\n\n"
            f"¡Bienvenido, <a href=\"{perfil}\">{nombre}</a>!\n"
            f"✅ <b>Registro completado</b>\n"
            f"🆔 <b>ID</b> ➾ <code>{id_tg}</code>\n\n"
            f"📌 Ya puedes usar <b>/me</b>, <b>/cmds</b> y más comandos."
        )
        await msg.reply_text(
            texto,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_to_message_id=msg.message_id,
        )
        return

    if status == 423:
        texto = (
            f"🎉 <b>{header}</b>\n\n"
            f"Hola, <a href=\"{perfil}\">{nombre}</a>.\n"
            f"⚠️ <b>Ya estabas registrado</b>\n"
            f"🆔 <b>ID</b> ➾ <code>{id_tg}</code>\n\n"
            f"Usa <b>/me</b> para ver tu perfil."
        )
        await msg.reply_text(
            texto,
            parse_mode="HTML",
            disable_web_page_preview=True,
            reply_to_message_id=msg.message_id,
        )
        return

    detalle = html.escape(str(data.get("message", "Error desconocido")))
    texto = (
        f"❌ <b>{header}</b>\n\n"
        f"⚠️ Ocurrió un problema al registrar tu cuenta.\n"
        f"Código: <code>{status}</code>\n"
        f"Detalle: <code>{detalle}</code>"
    )
    await msg.reply_text(
        texto,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_to_message_id=msg.message_id,
    )

import io
import json
import os
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import InputFile, Update
from telegram.ext import ContextTypes

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
PANEL_URL = (
    os.environ.get("SPIDERSYN_PANEL_URL")
    or CFG.get("PANEL_URL")
    or (f"{API_BASE}/admin/panel" if API_BASE else "")
).rstrip("/")
INTERNAL_API_KEY = (
    os.environ.get("SPIDERSYN_INTERNAL_API_KEY")
    or os.environ.get("INTERNAL_API_KEY")
    or CFG.get("INTERNAL_API_KEY")
    or CFG.get("TOKEN_BOT")
    or ""
).strip()

_admin_raw = os.environ.get("SPIDERSYN_ADMIN_ID") or os.environ.get("ADMIN_ID") or CFG.get("ADMIN_ID")
if isinstance(_admin_raw, list):
    _admin_values = _admin_raw
elif _admin_raw is None:
    _admin_values = []
else:
    _admin_values = str(_admin_raw).replace(",", " ").split()
ADMIN_IDS = {int(x) for x in _admin_values if str(x).strip().isdigit()}


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _request(url: str, timeout: int = 20, as_bytes: bool = False):
    headers = {"User-Agent": "SpiderSynBot/1.0"}
    if INTERNAL_API_KEY:
        headers["X-Internal-Api-Key"] = INTERNAL_API_KEY
    req = _urlreq.Request(url, headers=headers)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            status = resp.getcode() or 200
            body = resp.read()
            if as_bytes:
                return status, body
            text = body.decode("utf-8", errors="replace")
            try:
                return status, json.loads(text)
            except Exception:
                return status, {"status": "error", "message": text}
    except HTTPError as e:
        try:
            text = e.read().decode("utf-8", errors="replace")
            data = json.loads(text)
        except Exception:
            data = {"status": "error", "message": str(e)}
        return e.code, data
    except URLError as e:
        return 599, {"status": "error", "message": str(e)}
    except Exception as e:
        return 500, {"status": "error", "message": str(e)}


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await msg.reply_text("No tienes permisos para usar /status.", reply_to_message_id=msg.message_id)
        return
    if not API_BASE:
        await msg.reply_text("API_BASE no está configurado.", reply_to_message_id=msg.message_id)
        return

    st, data = _request(f"{API_BASE}/health", timeout=15)
    storage = (data or {}).get("storage") or {}
    items = storage.get("items") or []
    lines = [
        "<b>#SPIDERSYN ⇒ STATUS</b>",
        f"Web: <code>{st}</code> · {(data or {}).get('status', 'error')}",
        f"Data dir: <code>{storage.get('data_dir', '—')}</code>",
        "",
        "<b>DB</b>",
    ]
    for item in items:
        mark = "OK" if item.get("exists") and item.get("in_data_dir") else "WARN"
        lines.append(f"{mark} · {item.get('name')} · {item.get('size', 0)} bytes")
    await msg.reply_text("\n".join(lines), parse_mode="HTML", reply_to_message_id=msg.message_id)


async def panel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await msg.reply_text("No tienes permisos para usar /panel.", reply_to_message_id=msg.message_id)
        return
    if not PANEL_URL:
        await msg.reply_text("Panel URL no está configurada.", reply_to_message_id=msg.message_id)
        return
    await msg.reply_text(f"<b>Panel:</b>\n{PANEL_URL}", parse_mode="HTML", reply_to_message_id=msg.message_id)


async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await msg.reply_text("No tienes permisos para usar /backup.", reply_to_message_id=msg.message_id)
        return
    if not API_BASE:
        await msg.reply_text("API_BASE no está configurado.", reply_to_message_id=msg.message_id)
        return

    st, body = _request(f"{API_BASE}/internal/db-backup.zip", timeout=30, as_bytes=True)
    if st != 200 or not isinstance(body, (bytes, bytearray)):
        await msg.reply_text(f"No se pudo crear backup. Código: {st}", reply_to_message_id=msg.message_id)
        return
    bio = io.BytesIO(body)
    bio.name = "spidersyn-db-backup.zip"
    await msg.reply_document(
        document=InputFile(bio, filename=bio.name),
        caption="Backup de DB generado desde Railway.",
        reply_to_message_id=msg.message_id,
    )

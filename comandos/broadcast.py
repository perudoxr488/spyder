import asyncio
import html
import json
import os
from urllib import parse as _urlparse
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden, RetryAfter, TimedOut
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
BROADCAST_TTL_SECONDS = 900


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _fetch_json(url: str, timeout: int = 20):
    headers = {"User-Agent": "SpiderSynBot/1.0"}
    if INTERNAL_API_KEY:
        headers["X-Internal-Api-Key"] = INTERNAL_API_KEY
    req = _urlreq.Request(url, headers=headers)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return resp.getcode() or 200, json.loads(body)
            except Exception:
                return resp.getcode() or 200, {"status": "error", "message": body}
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            return e.code, json.loads(body)
        except Exception:
            return e.code, {"status": "error", "message": str(e)}
    except URLError as e:
        return 599, {"status": "error", "message": str(e)}
    except Exception as e:
        return 500, {"status": "error", "message": str(e)}


def _usage() -> str:
    return (
        "<b>#SPIDERSYN ⇒ MENSAJE GLOBAL</b>\n\n"
        "Uso:\n"
        "<code>/global Hola a todos</code>\n"
        "<code>/global --all Hola incluyendo baneados</code>\n\n"
        "También puedes responder a una foto, archivo o mensaje con <code>/global</code> "
        "y el bot lo copiará a todos los usuarios activos. El envío pide confirmación antes de salir."
    )


def _parse_scope_and_text(raw_text: str) -> tuple[str, str]:
    body = (raw_text or "").split(maxsplit=1)
    if len(body) < 2:
        return "active", ""
    text = body[1].strip()
    scope = "active"
    lowered = text.lower()
    if lowered.startswith("--all "):
        scope = "all"
        text = text[6:].strip()
    elif lowered == "--all":
        scope = "all"
        text = ""
    return scope, text


def _target_ids(scope: str) -> tuple[list[int], str | None]:
    if not API_BASE:
        return [], "API_BASE no está configurado."
    url = f"{API_BASE}/internal/broadcast/users?scope={_urlparse.quote(scope)}"
    status, data = _fetch_json(url, timeout=25)
    if status != 200 or (data or {}).get("status") != "ok":
        return [], f"No se pudo cargar usuarios. Código {status}: {(data or {}).get('message', 'error')}"
    users = []
    for item in (data or {}).get("users") or []:
        try:
            users.append(int(item["id_tg"]))
        except Exception:
            continue
    return users, None


async def _safe_send_text(context: ContextTypes.DEFAULT_TYPE, chat_id: int, text: str):
    try:
        await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
        return True, None
    except RetryAfter as e:
        await asyncio.sleep(float(getattr(e, "retry_after", 2)) + 0.5)
        try:
            await context.bot.send_message(chat_id=chat_id, text=text, parse_mode="HTML", disable_web_page_preview=True)
            return True, None
        except Exception as retry_error:
            return False, type(retry_error).__name__
    except (Forbidden, BadRequest, TimedOut) as e:
        return False, type(e).__name__
    except Exception as e:
        return False, type(e).__name__


async def _safe_copy_message(context: ContextTypes.DEFAULT_TYPE, chat_id: int, from_chat_id: int, message_id: int):
    try:
        await context.bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)
        return True, None
    except RetryAfter as e:
        await asyncio.sleep(float(getattr(e, "retry_after", 2)) + 0.5)
        try:
            await context.bot.copy_message(chat_id=chat_id, from_chat_id=from_chat_id, message_id=message_id)
            return True, None
        except Exception as retry_error:
            return False, type(retry_error).__name__
    except (Forbidden, BadRequest, TimedOut) as e:
        return False, type(e).__name__
    except Exception as e:
        return False, type(e).__name__


async def global_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return
    if not _is_admin(user.id):
        await msg.reply_text("No tienes permisos para usar /global.", reply_to_message_id=msg.message_id)
        return

    scope, text = _parse_scope_and_text(msg.text or "")
    source_message = msg.reply_to_message
    if not text and not source_message:
        await msg.reply_text(_usage(), parse_mode="HTML", reply_to_message_id=msg.message_id)
        return

    users, error = _target_ids(scope)
    if error:
        await msg.reply_text(error, reply_to_message_id=msg.message_id)
        return
    if not users:
        await msg.reply_text("No hay usuarios registrados para enviar el mensaje.", reply_to_message_id=msg.message_id)
        return

    token = f"{user.id}:{msg.message_id}"
    pending = context.bot_data.setdefault("broadcast_pending", {})
    pending[token] = {
        "owner_id": user.id,
        "scope": scope,
        "users": users,
        "text": text,
        "from_chat_id": msg.chat_id,
        "source_id": source_message.message_id if source_message else None,
        "created": asyncio.get_running_loop().time(),
    }
    preview_lines = [
        "<b>#SPIDERSYN ⇒ PREVIEW GLOBAL</b>",
        "",
        f"Alcance: <code>{html.escape(scope)}</code>",
        f"Usuarios destino: <code>{len(users)}</code>",
        f"Tipo: <code>{'mensaje copiado' if source_message else 'texto'}</code>",
    ]
    if text:
        preview = html.escape(text[:700])
        preview_lines.extend(["", "<b>Mensaje</b>", preview])
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Confirmar envío", callback_data=f"global_confirm:{token}"),
                InlineKeyboardButton("Cancelar", callback_data=f"global_cancel:{token}"),
            ]
        ]
    )
    await msg.reply_text(
        "\n".join(preview_lines),
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=msg.message_id,
    )


async def global_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return
    data = query.data or ""
    action, _, token = data.partition(":")
    pending = context.bot_data.setdefault("broadcast_pending", {})
    job = pending.get(token)
    if not job:
        await query.answer("Este envío ya expiró o no existe.", show_alert=True)
        return
    if int(job.get("owner_id") or 0) != query.from_user.id:
        await query.answer("Solo quien preparó el global puede confirmarlo.", show_alert=True)
        return
    age = asyncio.get_running_loop().time() - float(job.get("created") or 0)
    if age > BROADCAST_TTL_SECONDS:
        pending.pop(token, None)
        await query.answer("Este envío expiró.", show_alert=True)
        try:
            await query.edit_message_text("Mensaje global expirado. Vuelve a usar /global.")
        except Exception:
            pass
        return
    if action == "global_cancel":
        pending.pop(token, None)
        await query.answer("Cancelado.")
        try:
            await query.edit_message_text("Mensaje global cancelado.")
        except Exception:
            pass
        return
    if action != "global_confirm":
        await query.answer()
        return

    pending.pop(token, None)
    await query.answer("Enviando...")
    try:
        progress = await query.edit_message_text(f"Enviando mensaje global a {len(job['users'])} usuarios...")
    except Exception:
        progress = query.message

    ok = 0
    failed = 0
    failed_reasons: dict[str, int] = {}
    users = job.get("users") or []
    text = job.get("text") or ""
    scope = job.get("scope") or "active"
    from_chat_id = int(job.get("from_chat_id") or 0)
    source_id = job.get("source_id")
    for idx, target_id in enumerate(users, start=1):
        if source_id:
            sent, reason = await _safe_copy_message(context, target_id, from_chat_id, int(source_id))
        else:
            sent, reason = await _safe_send_text(context, target_id, text)
        if sent:
            ok += 1
        else:
            failed += 1
            failed_reasons[reason or "error"] = failed_reasons.get(reason or "error", 0) + 1
        if idx % 25 == 0:
            await asyncio.sleep(1)

    details = ", ".join(f"{html.escape(k)}: {v}" for k, v in sorted(failed_reasons.items())) or "—"
    result = (
        "<b>#SPIDERSYN ⇒ GLOBAL FINALIZADO</b>\n\n"
        f"Alcance: <code>{html.escape(scope)}</code>\n"
        f"Usuarios: <code>{len(users)}</code>\n"
        f"Enviados: <code>{ok}</code>\n"
        f"Fallidos: <code>{failed}</code>\n"
        f"Detalle fallos: {details}"
    )
    try:
        await progress.edit_text(result, parse_mode="HTML")
    except Exception:
        if query.message:
            await query.message.reply_text(result, parse_mode="HTML")

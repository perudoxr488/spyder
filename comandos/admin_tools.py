import html
import json
import os
from urllib import parse as _urlparse
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
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


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _api(path: str, timeout: int = 18, method: str = "GET", payload: dict | None = None):
    if not API_BASE:
        return 599, {"status": "error", "message": "API_BASE no está configurado"}
    headers = {"User-Agent": "SpiderSynBot/1.0"}
    data = None
    if INTERNAL_API_KEY:
        headers["X-Internal-Api-Key"] = INTERNAL_API_KEY
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = _urlreq.Request(f"{API_BASE}{path}", headers=headers, data=data, method=method)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return resp.getcode() or 200, json.loads(body)
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8", errors="replace"))
        except Exception:
            return e.code, {"status": "error", "message": str(e)}
    except URLError as e:
        return 599, {"status": "error", "message": str(e)}
    except Exception as e:
        return 500, {"status": "error", "message": str(e)}


def _need_admin(update: Update) -> bool:
    return bool(update.effective_user and _is_admin(update.effective_user.id))


def _err(st: int, data) -> str:
    return f"Error API/Railway <code>{st}</code>: {html.escape(str((data or {}).get('message') or 'sin detalle'))}"


async def dm_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not _need_admin(update):
        await msg.reply_text("No tienes permisos para usar /dm.")
        return
    args = msg.text.split(maxsplit=2) if msg.text else []
    if len(args) < 3 or not args[1].isdigit():
        await msg.reply_text("Uso: /dm ID mensaje", reply_to_message_id=msg.message_id)
        return
    target_id, text = args[1], args[2].strip()
    try:
        await context.bot.send_message(
            chat_id=int(target_id),
            text=f"<b>#SPIDERSYN ⇒ MENSAJE</b>\n\n{html.escape(text)}",
            parse_mode="HTML",
            disable_web_page_preview=True,
        )
        await msg.reply_text(f"Mensaje enviado a {target_id}.", reply_to_message_id=msg.message_id)
    except Exception as e:
        await msg.reply_text(f"No se pudo enviar DM: {type(e).__name__}", reply_to_message_id=msg.message_id)


async def ban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ban_preview(update, context, "ban")


async def unban_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await _ban_preview(update, context, "unban")


async def _ban_preview(update: Update, context: ContextTypes.DEFAULT_TYPE, action: str):
    msg = update.effective_message
    if not msg or not _need_admin(update):
        await msg.reply_text("No tienes permisos para usar este comando.")
        return
    if not context.args or not str(context.args[0]).isdigit():
        await msg.reply_text(f"Uso: /{action} ID", reply_to_message_id=msg.message_id)
        return
    target = str(context.args[0])
    keyboard = InlineKeyboardMarkup(
        [[
            InlineKeyboardButton("Confirmar", callback_data=f"admintool:{action}:{target}"),
            InlineKeyboardButton("Cancelar", callback_data=f"admintool:cancel:{target}"),
        ]]
    )
    await msg.reply_text(
        f"Confirmar acción <code>{action}</code> para usuario <code>{target}</code>.",
        parse_mode="HTML",
        reply_markup=keyboard,
        reply_to_message_id=msg.message_id,
    )


async def admin_tools_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not query.from_user:
        return
    if not _is_admin(query.from_user.id):
        await query.answer("Sin permisos.", show_alert=True)
        return
    _, action, target = (query.data or "").split(":", 2)
    if action == "cancel":
        await query.answer("Cancelado.")
        await query.edit_message_text("Acción cancelada.")
        return
    st, data = _api("/internal/admin/user-action", method="POST", payload={"ID_TG": target, "action": action})
    if st == 200 and (data or {}).get("status") == "ok":
        await query.answer("Actualizado.")
        await query.edit_message_text(f"Usuario {target} actualizado: {(data or {}).get('estado')}.")
    else:
        await query.answer("Error.", show_alert=True)
        await query.edit_message_text(_err(st, data), parse_mode="HTML")


async def user_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not _need_admin(update):
        await msg.reply_text("No tienes permisos para usar /user.")
        return
    if not context.args or not str(context.args[0]).isdigit():
        await msg.reply_text("Uso: /user ID", reply_to_message_id=msg.message_id)
        return
    target = str(context.args[0])
    st, data = _api(f"/internal/admin/user?ID_TG={_urlparse.quote(target)}")
    if st != 200 or (data or {}).get("status") != "ok":
        await msg.reply_text(_err(st, data), parse_mode="HTML", reply_to_message_id=msg.message_id)
        return
    profile = data["data"]
    user = profile.get("user") or {}
    lines = [
        "<b>#SPIDERSYN ⇒ PERFIL ADMIN</b>",
        f"ID: <code>{html.escape(str(user.get('id_tg')))}</code>",
        f"Rol: <code>{html.escape(str(user.get('rol_tg') or 'FREE'))}</code>",
        f"Plan: <code>{html.escape(str(user.get('plan') or 'FREE'))}</code>",
        f"Créditos: <code>{user.get('creditos') or 0}</code>",
        f"Estado: <code>{html.escape(str(user.get('estado') or '—'))}</code>",
        f"Vence: <code>{html.escape(str(user.get('fecha_caducidad') or 'Sin plan'))}</code>",
        "",
        f"Compras: <code>{len(profile.get('purchases') or [])}</code> · Consultas: <code>{len(profile.get('history') or [])}</code> · Keys: <code>{len(profile.get('keys') or [])}</code> · Solicitudes: <code>{len(profile.get('requests') or [])}</code>",
    ]
    await msg.reply_text("\n".join(lines), parse_mode="HTML", reply_to_message_id=msg.message_id)


async def ventas_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not _need_admin(update):
        await msg.reply_text("No tienes permisos para usar /ventas.")
        return
    st, data = _api("/internal/admin/sales-summary")
    if st != 200 or (data or {}).get("status") != "ok":
        await msg.reply_text(_err(st, data), parse_mode="HTML", reply_to_message_id=msg.message_id)
        return
    payload = data.get("data") or {}
    lines = ["<b>#SPIDERSYN ⇒ VENTAS</b>", ""]
    for item in payload.get("ventas_por_periodo") or []:
        lines.append(f"{html.escape(item.get('label'))}: <code>{item.get('total', 0)}</code> · Cred: <code>{item.get('creditos', 0)}</code> · Días: <code>{item.get('dias', 0)}</code>")
    lines.append("")
    lines.append("<b>Top vendedores</b>")
    for item in (payload.get("top_vendedores") or [])[:5]:
        lines.append(f"• <code>{html.escape(str(item.get('vendedor')))}</code> ⇒ {item.get('total', 0)}")
    await msg.reply_text("\n".join(lines), parse_mode="HTML", reply_to_message_id=msg.message_id)


async def errores_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    if not msg or not _need_admin(update):
        await msg.reply_text("No tienes permisos para usar /errores.")
        return
    st, data = _api("/internal/admin/errors?limit=10")
    if st != 200 or (data or {}).get("status") != "ok":
        await msg.reply_text(_err(st, data), parse_mode="HTML", reply_to_message_id=msg.message_id)
        return
    metrics = data.get("metrics") or {}
    lines = [
        "<b>#SPIDERSYN ⇒ ERRORES</b>",
        f"15m: <code>{metrics.get('ultimos_15m', 0)}</code> · 24h: <code>{metrics.get('ultimos_24h', 0)}</code>",
        "",
    ]
    for row in data.get("data") or []:
        lines.append(f"#{row.get('id')} <code>{html.escape(row.get('method') or '')} {html.escape(row.get('path') or '')}</code>")
        lines.append(f"{html.escape(str(row.get('message') or '')[:160])}")
    if len(lines) == 3:
        lines.append("Sin errores registrados.")
    await msg.reply_text("\n".join(lines), parse_mode="HTML", reply_to_message_id=msg.message_id)

import html
import json
import os
from urllib import parse as _urlparse
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import Update
from telegram.ext import ContextTypes

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")

CFG = {}
if os.path.exists(CONFIG_FILE_PATH):
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f) or {}
    except Exception:
        CFG = {}

_admin_raw = os.environ.get("SPIDERSYN_ADMIN_ID") or os.environ.get("ADMIN_ID") or CFG.get("ADMIN_ID")
if isinstance(_admin_raw, list):
    _admin_values = _admin_raw
elif _admin_raw is None:
    _admin_values = []
else:
    _admin_values = str(_admin_raw).replace(",", " ").split()
ADMIN_IDS = {int(x) for x in _admin_values if str(x).strip().isdigit()}

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


def _fetch_json(url: str, timeout: int = 15, method: str = "GET", payload: dict | None = None):
    headers = {"User-Agent": "SpiderSynBot/1.0"}
    data = None
    if INTERNAL_API_KEY:
        headers["X-Internal-Api-Key"] = INTERNAL_API_KEY
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    req = _urlreq.Request(url, data=data, headers=headers, method=method)
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


def _api_ready() -> bool:
    return bool(API_BASE)


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _badge(value) -> str:
    return f"<code>{html.escape(str(value))}</code>"


def _parse_positive_int(value: str, field: str) -> tuple[int | None, str | None]:
    try:
        num = int(value)
    except Exception:
        return None, f"{field} debe ser un número entero."
    if num <= 0:
        return None, f"{field} debe ser mayor a 0."
    return num, None


def _normalize_tipo(value: str) -> str | None:
    s = (value or "").strip().lower()
    aliases = {
        "dia": "dias",
        "dias": "dias",
        "d": "dias",
        "day": "dias",
        "days": "dias",
        "credito": "creditos",
        "creditos": "creditos",
        "cred": "creditos",
        "creds": "creditos",
        "c": "creditos",
    }
    return aliases.get(s)


def _usage_text() -> str:
    return (
        "Uso:\n"
        "<code>/genkey dias 12</code> ➜ 1 key de 12 días, 1 uso\n"
        "<code>/genkey creditos 100</code> ➜ 1 key de 100 créditos, 1 uso\n"
        "<code>/genkey dias 30 3</code> ➜ 1 key de 30 días, 3 usos\n"
        "<code>/genkey creditos 50 1 10</code> ➜ 10 keys de 50 créditos"
    )


async def genkey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await msg.reply_text("❌ No tienes permisos para usar este comando.")
        return
    if not _api_ready():
        await msg.reply_text("❌ API_BASE no está configurada; no puedo generar keys persistentes.")
        return

    if len(context.args) < 2:
        await msg.reply_text(
            _usage_text(),
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
        )
        return

    args = list(context.args)
    if len(args) >= 2 and args[0].isdigit() and _normalize_tipo(args[1]):
        args[0], args[1] = args[1], args[0]

    tipo = _normalize_tipo(args[0])
    if not tipo:
        await msg.reply_text("Tipo inválido. Usa: <code>dias</code> o <code>creditos</code>.\n\n" + _usage_text(), parse_mode="HTML")
        return
    cantidad, err = _parse_positive_int(args[1], "cantidad")
    if err:
        await msg.reply_text(f"❌ {html.escape(err)}", parse_mode="HTML")
        return
    usos = 1
    if len(args) >= 3:
        usos, err = _parse_positive_int(args[2], "usos")
        if err:
            await msg.reply_text(f"❌ {html.escape(err)}", parse_mode="HTML")
            return
    total = 1
    if len(args) >= 4:
        total, err = _parse_positive_int(args[3], "total")
        if err:
            await msg.reply_text(f"❌ {html.escape(err)}", parse_mode="HTML")
            return

    status, data = _fetch_json(
        f"{API_BASE}/keys/generate",
        method="POST",
        payload={
            "tipo": tipo,
            "cantidad": cantidad,
            "usos": usos,
            "total": total,
            "creador_id": user.id,
        },
    )
    if status != 200 or data.get("status") != "ok":
        await msg.reply_text(
            f"❌ No se pudo generar la key.\nCódigo: {_badge(status)}\n{html.escape(str(data.get('message', 'Error')))}",
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
        )
        return

    keys = ((data.get("data") or {}).get("keys") or [])
    key_lines = "\n".join(_badge(key) for key in keys[:30])
    extra = "" if len(keys) <= 30 else f"\n... y {len(keys) - 30} más."
    await msg.reply_text(
        (
            "✅ <b>Keys generadas</b>\n\n"
            f"Tipo: {_badge(tipo)}\n"
            f"Cantidad: {_badge(cantidad)}\n"
            f"Usos por key: {_badge(usos)}\n"
            f"Total: {_badge(len(keys))}\n\n"
            f"{key_lines}{extra}"
        ),
        parse_mode="HTML",
        reply_to_message_id=msg.message_id,
    )


async def redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not user:
        return
    if not _api_ready():
        await msg.reply_text("❌ API_BASE no está configurada; no puedo canjear keys.")
        return
    if len(context.args) < 1:
        await msg.reply_text("Uso: <code>/redeem KEY</code>", parse_mode="HTML", reply_to_message_id=msg.message_id)
        return

    key_input = context.args[0].strip().upper()
    status, data = _fetch_json(
        f"{API_BASE}/keys/redeem",
        method="POST",
        payload={"key": key_input, "ID_TG": user.id},
    )
    if status != 200 or data.get("status") != "ok":
        await msg.reply_text(
            f"❌ {html.escape(str(data.get('message', 'Key inválida')))}",
            parse_mode="HTML",
            reply_to_message_id=msg.message_id,
        )
        return

    info = data.get("data") or {}
    lines = [
        f"Key: {_badge(info.get('key', key_input))}",
        f"Tipo: {_badge(info.get('tipo', '—'))}",
        f"Cantidad: {_badge(info.get('cantidad', '—'))}",
        f"Usos restantes: {_badge(info.get('usos_restantes', '—'))}",
    ]
    if "CREDITOS" in info:
        lines.append(f"Nuevo saldo: {_badge(info.get('CREDITOS'))}")
    if "FECHA_DE_CADUCIDAD" in info:
        lines.append(f"Vence: {_badge(info.get('FECHA_DE_CADUCIDAD'))}")
    await msg.reply_text("✅ <b>Key canjeada</b>\n\n" + "\n".join(lines), parse_mode="HTML", reply_to_message_id=msg.message_id)


async def keyslog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await msg.reply_text("❌ No tienes permisos para usar este comando.")
        return
    if not _api_ready():
        await msg.reply_text("❌ API_BASE no está configurada.")
        return

    status, data = _fetch_json(f"{API_BASE}/keys/log?limit=15")
    if status != 200 or data.get("status") != "ok":
        await msg.reply_text(f"❌ Error consultando canjes: {html.escape(str(data.get('message', status)))}", parse_mode="HTML")
        return
    rows = data.get("data") or []
    if not rows:
        await msg.reply_text("📭 No hay canjes registrados aún.")
        return

    parts = ["📜 <b>Últimos canjes de keys</b>\n"]
    for row in rows:
        parts.append(
            f"🔑 {_badge(row.get('key'))}\n"
            f"👤 User: {_badge(row.get('user_id'))}\n"
            f"📅 {html.escape(str(row.get('fecha_canje') or '—'))}\n"
            f"➕ {_badge(row.get('cantidad'))} {html.escape(str(row.get('tipo') or ''))}"
        )
    await msg.reply_text("\n\n".join(parts), parse_mode="HTML", reply_to_message_id=msg.message_id)


async def keysinfo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not user or not _is_admin(user.id):
        await msg.reply_text("❌ No tienes permisos para usar este comando.")
        return
    if not _api_ready():
        await msg.reply_text("❌ API_BASE no está configurada.")
        return
    if len(context.args) < 1:
        await msg.reply_text("Uso: <code>/keysinfo KEY</code>", parse_mode="HTML", reply_to_message_id=msg.message_id)
        return

    key_input = context.args[0].strip().upper()
    status, data = _fetch_json(f"{API_BASE}/keys/info?key={_urlparse.quote(key_input)}")
    if status != 200 or data.get("status") != "ok":
        await msg.reply_text(f"❌ {html.escape(str(data.get('message', 'Key no encontrada')))}", parse_mode="HTML")
        return
    row = data.get("data") or {}
    await msg.reply_text(
        (
            "🔑 <b>Información de la key</b>\n\n"
            f"Key: {_badge(row.get('key'))}\n"
            f"Tipo: {_badge(row.get('tipo'))}\n"
            f"Cantidad: {_badge(row.get('cantidad'))}\n"
            f"Usos restantes: {_badge(row.get('usos'))}\n"
            f"Canjes: {_badge(row.get('canjes'))}\n"
            f"Creada por: {_badge(row.get('creador_id'))}\n"
            f"Fecha creación: {_badge(row.get('fecha_creacion'))}"
        ),
        parse_mode="HTML",
        reply_to_message_id=msg.message_id,
    )

import os
import io
import json
import html
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib import parse as _urlparse
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import Update, InputFile
from telegram.ext import ContextTypes

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")

CFG = {}
try:
    if os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f)
except Exception:
    CFG = {}

BOT_NAME = (os.environ.get("SPIDERSYN_BOT_NAME") or CFG.get("BOT_NAME") or CFG.get("NAME") or "").strip() or "#BOT"
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
_SETTINGS_CACHE = {"ts": 0.0, "data": None}


def _fetch_json(url: str, timeout: int = 20):
    headers = {"User-Agent": "tussybot/1.0"}
    if INTERNAL_API_KEY:
        headers["X-Internal-Api-Key"] = INTERNAL_API_KEY
    req = _urlreq.Request(url, headers=headers)
    try:
        with _urlreq.urlopen(req, timeout=timeout) as resp:
            st = resp.getcode() or 200
            body = resp.read().decode("utf-8", errors="replace")
            try:
                import json as _j
                return st, _j.loads(body)
            except Exception:
                return st, {"status": "error", "message": body}
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            import json as _j
            data = _j.loads(body)
        except Exception:
            data = {"status": "error", "message": str(e)}
        return e.code, data
    except URLError as e:
        return 599, {"status": "error", "message": str(e)}
    except Exception as e:
        return 500, {"status": "error", "message": str(e)}


def _to_lima(iso: str | None) -> str:
    if not iso:
        return "—"
    s = iso.strip()
    if s.endswith("Z"):
        s = s[:-1]
    try:
        dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
    except Exception:
        return iso
    try:
        dt = dt.astimezone(ZoneInfo("America/Lima"))
    except Exception:
        pass
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _parse_iso_utc(iso: str | None) -> datetime | None:
    if not iso:
        return None
    s = str(iso).strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except Exception:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_lima_dt(iso: str | None) -> datetime | None:
    dt = _parse_iso_utc(iso)
    if not dt:
        return None
    try:
        return dt.astimezone(ZoneInfo("America/Lima"))
    except Exception:
        return dt


def _extract_first_number(text: str | None) -> int | None:
    if not text:
        return None
    current = ""
    for ch in str(text):
        if ch.isdigit():
            current += ch
        elif current:
            break
    return int(current) if current else None


_ALLOWED_ROLES = {"FUNDADOR", "CO-FUNDADOR", "SELLER"}


def _get_user_info(id_tg: str):
    return _fetch_json(f"{API_BASE}/tg_info?ID_TG={_urlparse.quote(id_tg)}")


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
    raw = settings.get("BOT_NAME") or settings.get("NAME") or BOT_NAME or "#BOT"
    return str(raw).strip() or "#BOT"


def _is_authorized_viewer(viewer_id: int, viewer_info: dict) -> bool:
    if viewer_id in ADMIN_IDS:
        return True
    data = viewer_info.get("data", {}) or {}
    rol = (data.get("ROL_TG") or "").upper()
    return rol in _ALLOWED_ROLES


def _build_compras_txt(bot_name: str, owner_id: str, filas: list[dict]) -> bytes:
    def _sort_key(row: dict):
        dt = _parse_iso_utc(row.get("FECHA"))
        return dt or datetime.min.replace(tzinfo=timezone.utc)

    rows = sorted(filas, key=_sort_key, reverse=True)
    por_vendedor: dict[str, int] = {}
    por_producto: dict[str, int] = {}
    total_dias = 0
    compras_hoy = 0
    ultima_fecha: datetime | None = None

    try:
        lima_today = datetime.now(ZoneInfo("America/Lima")).date()
    except Exception:
        lima_today = datetime.utcnow().date()

    for row in rows:
        vendedor = str(row.get("ID_VENDEDOR") or "—").strip() or "—"
        por_vendedor[vendedor] = por_vendedor.get(vendedor, 0) + 1

        cantidad = " ".join(str(row.get("CANTIDAD") or "—").upper().split()).strip()
        por_producto[cantidad] = por_producto.get(cantidad, 0) + 1

        amount = _extract_first_number(cantidad)
        if amount is not None and "DIA" in cantidad:
            total_dias += amount

        dt_lima = _to_lima_dt(row.get("FECHA"))
        if dt_lima:
            if dt_lima.date() == lima_today:
                compras_hoy += 1
            if ultima_fecha is None or dt_lima > ultima_fecha:
                ultima_fecha = dt_lima

    header = [
        f"{bot_name} - COMPRAS REGISTRADAS",
        f"ID_TG: {owner_id}",
        "-" * 56,
        f"Total de compras: {len(rows)}",
        f"Compras de hoy: {compras_hoy}",
        f"Dias adquiridos aprox.: {total_dias}",
        f"Ultima compra: {_to_lima(ultima_fecha.isoformat()) if ultima_fecha else '—'}",
    ]
    if por_vendedor:
        header.append("Por vendedor (ID_VENDEDOR):")
        for k, v in sorted(por_vendedor.items(), key=lambda x: (-x[1], x[0])):
            header.append(f"  - {k}: {v}")
    if por_producto:
        header.append("Por compra:")
        for k, v in sorted(por_producto.items(), key=lambda x: (-x[1], x[0])):
            header.append(f"  - {k}: {v}")
    header.append("-" * 56)
    header.append("")

    lines = []
    lines.append("FECHA_LIMA           | CANTIDAD             | VENDEDOR")
    lines.append("---------------------+----------------------+---------")
    for row in rows:
        fecha = _to_lima(row.get("FECHA"))
        cantidad = " ".join(str(row.get("CANTIDAD") or "—").split())[:20]
        vendedor = str(row.get("ID_VENDEDOR") or "—")
        lines.append(f"{fecha:21} | {cantidad:20} | {vendedor}")

    content = "\n".join(header + lines) + "\n"
    return content.encode("utf-8", errors="replace")


def _build_compras_caption(bot_name: str, owner_id: str, filas: list[dict]) -> str:
    rows = sorted(
        filas,
        key=lambda row: _parse_iso_utc(row.get("FECHA")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    por_vendedor: dict[str, int] = {}
    total_dias = 0
    compras_hoy = 0
    ultima_fecha: datetime | None = None

    try:
        lima_today = datetime.now(ZoneInfo("America/Lima")).date()
    except Exception:
        lima_today = datetime.utcnow().date()

    for row in rows:
        vendedor = str(row.get("ID_VENDEDOR") or "—").strip() or "—"
        por_vendedor[vendedor] = por_vendedor.get(vendedor, 0) + 1

        cantidad = " ".join(str(row.get("CANTIDAD") or "—").upper().split()).strip()
        amount = _extract_first_number(cantidad)
        if amount is not None and "DIA" in cantidad:
            total_dias += amount

        dt_lima = _to_lima_dt(row.get("FECHA"))
        if dt_lima:
            if dt_lima.date() == lima_today:
                compras_hoy += 1
            if ultima_fecha is None or dt_lima > ultima_fecha:
                ultima_fecha = dt_lima

    top_vendedor = "—"
    if por_vendedor:
        top_vendedor = sorted(por_vendedor.items(), key=lambda item: (-item[1], item[0]))[0][0]

    return (
        f"<b>{bot_name} • Exportación de compras</b>\n"
        f"ID consultado: <code>{html.escape(owner_id)}</code>\n"
        f"Total: <b>{len(rows)}</b>\n"
        f"Hoy: <b>{compras_hoy}</b>\n"
        f"Dias aprox.: <b>{total_dias}</b>\n"
        f"Top vendedor: <b>{html.escape(top_vendedor)}</b>\n"
        f"Ultima: <code>{html.escape(_to_lima(ultima_fecha.isoformat()) if ultima_fecha else '—')}</code>"
    )


async def compras_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    user = update.effective_user
    caller_id = str(user.id)

    if not chat or str(chat.type).lower() != "private":
        await msg.reply_text(
            "⚠️ Este comando solo puede usarse por privado.",
            reply_to_message_id=msg.message_id
        )
        return

    if not API_BASE:
        await msg.reply_text(
            "❌ API no configurada. Revisa API_DB_BASE en config.json",
            reply_to_message_id=msg.message_id
        )
        return

    target_id = caller_id
    viewing_third_party = False

    if context.args:
        arg = "".join(context.args).strip()
        if arg.isdigit():
            target_id = arg
            viewing_third_party = (target_id != caller_id)
        else:
            await msg.reply_text(
                "Uso: <code>/compras</code> o <code>/compras ID</code>",
                parse_mode="HTML",
                reply_to_message_id=msg.message_id
            )
            return

    if viewing_third_party:
        st_view, js_view = _get_user_info(caller_id)
        if st_view != 200:
            await msg.reply_text(
                f"⚠️ No se pudo validar tu rol (code {st_view}).",
                reply_to_message_id=msg.message_id
            )
            return
        if not _is_authorized_viewer(int(caller_id), js_view):
            await msg.reply_text(
                "🚫 No tienes permisos para ver las compras de otros usuarios.",
                reply_to_message_id=msg.message_id
            )
            return

    st_c, js_c = _fetch_json(f"{API_BASE}/compras_id?ID_TG={_urlparse.quote(target_id)}")
    if st_c != 200:
        detalle = html.escape(str(js_c.get("message", "Error desconocido")))
        await msg.reply_text(
            f"⚠️ No se pudieron obtener las compras (code {st_c}).\nDetalle: <code>{detalle}</code>",
            parse_mode="HTML",
            reply_to_message_id=msg.message_id
        )
        return

    filas = js_c.get("data", []) or []

    pretty_bot = _bot_brand()
    data_bytes = _build_compras_txt(pretty_bot, target_id, filas)
    filename = f"compras_{target_id}.txt"

    bio = io.BytesIO(data_bytes)
    bio.name = filename

    caption = _build_compras_caption(pretty_bot, target_id, filas)

    await msg.reply_document(
        document=InputFile(bio, filename=filename),
        caption=caption,
        parse_mode="HTML",
        reply_to_message_id=msg.message_id
    )

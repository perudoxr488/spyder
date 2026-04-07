# comandos/historial_cmd.py
import os
import io
import json
import html
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from urllib import parse as _urlparse
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import Update, InputFile
from telegram.ext import ContextTypes

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_DB_BASE = "http://127.0.0.1:4764"   # tg_info, historial_id
INTERNAL_API_KEY = ""
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")

# ================== Carga de config ==================
CFG = {}
try:
    if os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f)
except Exception:
    CFG = {}

API_DB_BASE = (
    os.environ.get("SPIDERSYN_API_BASE")
    or os.environ.get("API_BASE")
    or os.environ.get("API_DB_BASE")
    or CFG.get("API_DB_BASE")
    or CFG.get("API_BASE")
    or API_DB_BASE
).rstrip("/")
INTERNAL_API_KEY = (
    os.environ.get("SPIDERSYN_INTERNAL_API_KEY")
    or os.environ.get("INTERNAL_API_KEY")
    or CFG.get("INTERNAL_API_KEY")
    or CFG.get("TOKEN_BOT")
    or ""
).strip()

BOT_NAME = (CFG.get("BOT_NAME") or CFG.get("NAME") or "").strip() or "#BOT"
_admin_raw = CFG.get("ADMIN_ID")
if isinstance(_admin_raw, list):
    ADMIN_IDS = {int(x) for x in _admin_raw if str(x).isdigit()}
elif _admin_raw is None:
    ADMIN_IDS = set()
else:
    ADMIN_IDS = {int(_admin_raw)} if str(_admin_raw).isdigit() else set()

# ================== Utilidades HTTP ==================
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

# ================== Utilidades de tiempo ==================
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


def _to_lima(iso: str | None) -> str:
    dt = _to_lima_dt(iso)
    if not dt:
        return iso or "—"
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _clean_counter_key(value: str | None, fallback: str = "OTROS") -> str:
    cleaned = " ".join(str(value or "").upper().split()).strip(" -_/")
    return cleaned or fallback

# ================== Autorización ==================
_ALLOWED_ROLES = {"FUNDADOR", "CO-FUNDADOR", "SELLER"}

def _get_user_info(id_tg: str):
    return _fetch_json(f"{API_DB_BASE}/tg_info?ID_TG={_urlparse.quote(id_tg)}")

def _is_authorized_viewer(viewer_id: int, viewer_info: dict) -> bool:
    """
    El viewer puede ver el historial de terceros si:
    - ROL_TG ∈ {FUNDADOR, CO-FUNDADOR, SELLER}, o
    - Está en ADMIN_ID del config.json
    """
    if viewer_id in ADMIN_IDS:
        return True
    data = viewer_info.get("data", {}) or {}
    rol = (data.get("ROL_TG") or "").upper()
    return rol in _ALLOWED_ROLES

# ================== Render TXT ==================
def _build_historial_txt(bot_name: str, owner_id: str, filas: list[dict]) -> bytes:
    def _sort_key(row: dict):
        dt = _parse_iso_utc(row.get("FECHA"))
        return dt or datetime.min.replace(tzinfo=timezone.utc)

    rows = sorted(filas, key=_sort_key, reverse=True)
    por_tipo: dict[str, int] = {}
    por_plataforma: dict[str, int] = {}
    hoy = 0
    ultima_fecha: datetime | None = None

    try:
        lima_today = datetime.now(ZoneInfo("America/Lima")).date()
    except Exception:
        lima_today = datetime.utcnow().date()

    for row in rows:
        consulta = _clean_counter_key(row.get("CONSULTA"), "SIN TIPO")
        plataforma = _clean_counter_key(row.get("PLATAFORMA"), "SIN PLATAFORMA")
        por_tipo[consulta] = por_tipo.get(consulta, 0) + 1
        por_plataforma[plataforma] = por_plataforma.get(plataforma, 0) + 1

        dt_lima = _to_lima_dt(row.get("FECHA"))
        if dt_lima:
            if dt_lima.date() == lima_today:
                hoy += 1
            if ultima_fecha is None or dt_lima > ultima_fecha:
                ultima_fecha = dt_lima

    header = [
        f"{bot_name} - HISTORIAL DE CONSULTAS",
        f"ID_TG: {owner_id}",
        "-" * 56,
        f"Total de consultas: {len(rows)}",
        f"Consultas de hoy: {hoy}",
        f"Ultima consulta: {_to_lima(ultima_fecha.isoformat()) if ultima_fecha else '—'}",
    ]
    if por_plataforma:
        header.append("Por plataforma:")
        for key, value in sorted(por_plataforma.items(), key=lambda item: (-item[1], item[0])):
            header.append(f"  - {key}: {value}")
    if por_tipo:
        header.append("Por tipo:")
        for key, value in sorted(por_tipo.items(), key=lambda item: (-item[1], item[0])):
            header.append(f"  - {key}: {value}")
    header.append("-" * 56)
    header.append("")

    lines = []
    lines.append("FECHA_LIMA           | PLATAFORMA | CONSULTA     | VALOR")
    lines.append("---------------------+------------+--------------+--------------------------")
    for row in rows:
        fecha = _to_lima(row.get("FECHA"))
        plataforma = _clean_counter_key(row.get("PLATAFORMA"), "—")[:10]
        consulta = _clean_counter_key(row.get("CONSULTA"), "—")[:12]
        valor = str(row.get("VALOR") or "—")[:26]
        lines.append(f"{fecha:21} | {plataforma:10} | {consulta:12} | {valor}")

    content = "\n".join(header + lines) + "\n"
    return content.encode("utf-8", errors="replace")


def _build_historial_caption(bot_name: str, owner_id: str, filas: list[dict]) -> str:
    rows = sorted(
        filas,
        key=lambda row: _parse_iso_utc(row.get("FECHA")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    por_tipo: dict[str, int] = {}
    hoy = 0
    ultima_fecha: datetime | None = None

    try:
        lima_today = datetime.now(ZoneInfo("America/Lima")).date()
    except Exception:
        lima_today = datetime.utcnow().date()

    for row in rows:
        consulta = _clean_counter_key(row.get("CONSULTA"), "SIN TIPO")
        por_tipo[consulta] = por_tipo.get(consulta, 0) + 1
        dt_lima = _to_lima_dt(row.get("FECHA"))
        if dt_lima:
            if dt_lima.date() == lima_today:
                hoy += 1
            if ultima_fecha is None or dt_lima > ultima_fecha:
                ultima_fecha = dt_lima

    top_tipo = "—"
    if por_tipo:
        top_tipo = sorted(por_tipo.items(), key=lambda item: (-item[1], item[0]))[0][0]

    return (
        f"<b>{bot_name} • Exportación de historial</b>\n"
        f"ID consultado: <code>{html.escape(owner_id)}</code>\n"
        f"Total: <b>{len(rows)}</b>\n"
        f"Hoy: <b>{hoy}</b>\n"
        f"Top consulta: <b>{html.escape(top_tipo)}</b>\n"
        f"Ultima: <code>{html.escape(_to_lima(ultima_fecha.isoformat()) if ultima_fecha else '—')}</code>"
    )

# ================== Comando ==================
async def historial_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    msg = update.effective_message
    user = update.effective_user
    caller_id = str(user.id)

    # 1) Solo en privado
    if not chat or str(chat.type).lower() != "private":
        await msg.reply_text(
            "⚠️ Este comando solo puede usarse por privado.",
            reply_to_message_id=msg.message_id
        )
        return

    # 2) Si piden /historial sin args → historial propio
    target_id = caller_id
    viewing_third_party = False

    if context.args:
        # Piden /historial ID
        arg = "".join(context.args).strip()
        if arg.isdigit():
            target_id = arg
            viewing_third_party = (target_id != caller_id)
        else:
            await msg.reply_text(
                "Uso: <code>/historial</code> (propio) o <code>/historial ID</code>",
                parse_mode="HTML",
                reply_to_message_id=msg.message_id
            )
            return

    # 3) Si verán tercero, validar permisos del solicitante
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
                "🚫 No tienes permisos para ver el historial de otros usuarios.",
                reply_to_message_id=msg.message_id
            )
            return

    # 4) Obtener historial del target
    st_h, js_h = _fetch_json(f"{API_DB_BASE}/historial_id?ID_TG={_urlparse.quote(target_id)}")
    if st_h != 200:
        await msg.reply_text(
            f"⚠️ No se pudo obtener el historial (code {st_h}).",
            reply_to_message_id=msg.message_id
        )
        return

    filas = js_h.get("data", []) or []

    # 5) Construir TXT y enviar
    pretty_bot = (BOT_NAME or "#BOT").strip()
    data_bytes = _build_historial_txt(pretty_bot, target_id, filas)
    filename = f"historial_{target_id}.txt"

    bio = io.BytesIO(data_bytes)
    bio.name = filename

    caption = _build_historial_caption(pretty_bot, target_id, filas)

    await msg.reply_document(
        document=InputFile(bio, filename=filename),
        caption=caption,
        parse_mode="HTML",
        reply_to_message_id=msg.message_id
    )

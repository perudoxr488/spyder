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

API_DB_BASE = "http://127.0.0.1:4764"   # tg_info, historial_id
INTERNAL_API_KEY = ""
CONFIG_FILE_PATH = "config.json"

# ================== Carga de config ==================
CFG = {}
try:
    if os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f)
        API_DB_BASE = (CFG.get("API_DB_BASE") or CFG.get("API_BASE") or API_DB_BASE).rstrip("/")
        INTERNAL_API_KEY = (CFG.get("INTERNAL_API_KEY") or CFG.get("TOKEN_BOT") or "").strip()
except Exception:
    CFG = {}

BOT_NAME = (CFG.get("BOT_NAME") or "").strip() or "#BOT"
ADMIN_IDS = set(CFG.get("ADMIN_ID") or [])

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
    # Ordenar por fecha DESC
    def _key(r):
        f = r.get("FECHA")
        if not f:
            return ""
        return f
    rows = sorted(filas, key=_key, reverse=True)

    # Conteos útiles
    total = len(rows)
    por_tipo = {}
    hoy = 0
    try:
        lima_today = datetime.now(ZoneInfo("America/Lima")).date()
    except Exception:
        lima_today = datetime.utcnow().date()

    for r in rows:
        t = (r.get("CONSULTA") or "").upper()
        por_tipo[t] = por_tipo.get(t, 0) + 1
        # contar hoy
        ff = r.get("FECHA")
        if ff:
            s = ff[:-1] if ff.endswith("Z") else ff
            try:
                dt = datetime.fromisoformat(s).replace(tzinfo=timezone.utc)
                try:
                    dt = dt.astimezone(ZoneInfo("America/Lima"))
                except Exception:
                    pass
                if dt.date() == lima_today:
                    hoy += 1
            except Exception:
                pass

    header = [
        f"{bot_name} - HISTORIAL DE CONSULTAS",
        f"ID_TG: {owner_id}",
        "-"*48,
        f"Total de consultas: {total}",
        f"Consultas de hoy: {hoy}",
    ]
    if por_tipo:
        header.append("Por tipo:")
        for k, v in sorted(por_tipo.items()):
            header.append(f"  - {k}: {v}")
    header.append("-"*48)
    header.append("")

    # Cuerpo
    lines = []
    lines.append("FECHA_LIMA           | PLATAFORMA | TIPO   | VALOR")
    lines.append("---------------------+------------+--------+----------------")
    for r in rows:
        fecha = _to_lima(r.get("FECHA"))
        plat  = (r.get("PLATAFORMA") or "—")[:10]
        cons  = (r.get("CONSULTA") or "—")[:6]
        valor = r.get("VALOR") or "—"
        lines.append(f"{fecha:21} | {plat:10} | {cons:6} | {valor}")

    content = "\n".join(header + lines) + "\n"
    return content.encode("utf-8", errors="replace")

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

    caption = (
        f"<b>{pretty_bot} • Exportación de historial</b>\n"
        f"ID consultado: <code>{html.escape(target_id)}</code>\n"
        f"Registros: <b>{len(filas)}</b>"
    )

    await msg.reply_document(
        document=InputFile(bio, filename=filename),
        caption=caption,
        parse_mode="HTML",
        reply_to_message_id=msg.message_id
    )

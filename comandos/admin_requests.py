import json
import os
import re
import sqlite3
from datetime import datetime
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from storage import db_path

DB_FILE = db_path("requests.db")
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
HISTORIAL_ENDPOINT = f"{API_BASE}/historial"
REQUEST_SYNC_ENDPOINT = f"{API_BASE}/internal/request/upsert"

DEFAULT_QUICK_TEMPLATES = {
    "nodata": "《⚠️》 No se encontró información.",
    "proceso": "⏳ Tu solicitud sigue en proceso. Apenas la terminemos te la enviamos.",
    "formato": "⚠️ Revisa el formato enviado e inténtalo otra vez. Si quieres, vuelve a mandar la consulta con un ejemplo más claro.",
    "observado": "⚠️ La solicitud fue observada. Escríbenos de nuevo con los datos completos para continuar.",
    "completado": "✅ Listo, aquí tienes el resultado de tu solicitud.",
}
REQUEST_ACTION_KEY = "request_action_state"


def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def primary_admin_id() -> int | None:
    return next(iter(ADMIN_IDS), None)


def now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _fetch_json(url: str, timeout: int = 12, method: str = "GET", payload: dict | None = None):
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


def _log_historial(user_id: int, command: str, payload: str):
    if not API_BASE:
        return
    try:
        _fetch_json(
            HISTORIAL_ENDPOINT,
            method="POST",
            payload={
                "ID_TG": str(user_id),
                "CONSULTA": str(command).lower().strip(),
                "VALOR": payload or f"/{command}",
                "PLATAFORMA": "TG",
            },
        )
    except Exception:
        pass


def _request_row_to_payload(row) -> dict:
    (
        request_id,
        user_id,
        username,
        command,
        payload,
        status,
        admin_msg_id,
        cost,
        charged,
        delivery_count,
        created_at,
        resolved_at,
        resolved_by,
        resolution_note,
    ) = row
    return {
        "id": request_id,
        "user_id": user_id,
        "username": username or "",
        "command": command or "",
        "payload": payload or "",
        "status": status or "pending",
        "admin_msg_id": admin_msg_id,
        "cost": int(cost or 1),
        "charged": int(charged or 0),
        "delivery_count": int(delivery_count or 0),
        "created_at": created_at or now_iso(),
        "resolved_at": resolved_at or None,
        "resolved_by": resolved_by or None,
        "resolution_note": resolution_note or "",
    }


def _sync_request_payload(payload: dict):
    if not API_BASE:
        return
    try:
        _fetch_json(REQUEST_SYNC_ENDPOINT, timeout=8, method="POST", payload=payload)
    except Exception:
        pass


def _sync_request_by_id(request_id: int):
    if not API_BASE:
        return
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        row = _get_request_by_id(c, request_id)
        conn.close()
        if row:
            _sync_request_payload(_request_row_to_payload(row))
    except Exception:
        pass


def sync_recent_requests_to_api(limit: int = 300):
    if not API_BASE:
        return
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute(
            """
            SELECT id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count,
                   created_at, resolved_at, resolved_by, resolution_note
            FROM requests
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = c.fetchall()
        conn.close()
        for row in rows:
            _sync_request_payload(_request_row_to_payload(row))
    except Exception:
        pass


def init_db():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            command TEXT,
            payload TEXT,
            status TEXT,
            admin_msg_id INTEGER,
            cost INTEGER DEFAULT 1,
            charged INTEGER DEFAULT 0,
            delivery_count INTEGER DEFAULT 0,
            created_at TEXT,
            resolved_at TEXT,
            resolved_by INTEGER,
            resolution_note TEXT
        )
        """
    )
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS request_templates (
            key TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            billable INTEGER DEFAULT 0
        )
        """
    )

    c.execute("PRAGMA table_info(requests)")
    columns = {row[1] for row in c.fetchall()}
    if "payload" not in columns:
        c.execute("ALTER TABLE requests ADD COLUMN payload TEXT")
    if "created_at" not in columns:
        c.execute("ALTER TABLE requests ADD COLUMN created_at TEXT")
    if "charged" not in columns:
        c.execute("ALTER TABLE requests ADD COLUMN charged INTEGER DEFAULT 0")
    if "delivery_count" not in columns:
        c.execute("ALTER TABLE requests ADD COLUMN delivery_count INTEGER DEFAULT 0")
    if "resolved_at" not in columns:
        c.execute("ALTER TABLE requests ADD COLUMN resolved_at TEXT")
    if "resolved_by" not in columns:
        c.execute("ALTER TABLE requests ADD COLUMN resolved_by INTEGER")
    if "resolution_note" not in columns:
        c.execute("ALTER TABLE requests ADD COLUMN resolution_note TEXT")

    c.execute("UPDATE requests SET created_at = COALESCE(created_at, ?) WHERE created_at IS NULL OR created_at = ''", (now_iso(),))
    for key, text in DEFAULT_QUICK_TEMPLATES.items():
        billable = 0 if key in {"nodata", "proceso", "formato", "observado"} else 1
        c.execute(
            """
            INSERT INTO request_templates (key, text, billable)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, text, billable),
        )
    conn.commit()
    conn.close()
    sync_recent_requests_to_api(limit=300)


def _get_request_by_id(cursor, request_id: int):
    cursor.execute(
        """
        SELECT id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count,
               created_at, resolved_at, resolved_by, resolution_note
        FROM requests
        WHERE id=?
        """,
        (request_id,),
    )
    return cursor.fetchone()


def _get_request_by_admin_message(cursor, admin_msg_id: int):
    cursor.execute(
        """
        SELECT id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count,
               created_at, resolved_at, resolved_by, resolution_note
        FROM requests
        WHERE admin_msg_id=?
        """,
        (admin_msg_id,),
    )
    return cursor.fetchone()


def _target_label(username, user_id) -> str:
    return f"@{username}" if username else str(user_id)


def _trim(text: str | None, limit: int = 90) -> str:
    value = (text or "").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def get_quick_templates():
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    try:
        c.execute("SELECT key, text, billable FROM request_templates ORDER BY key")
        rows = c.fetchall()
    except Exception:
        rows = []
    conn.close()
    if not rows:
        return {key: {"text": text, "billable": 0 if key in {"nodata", "proceso", "formato", "observado"} else 1} for key, text in DEFAULT_QUICK_TEMPLATES.items()}
    return {key: {"text": text, "billable": int(billable or 0)} for key, text, billable in rows}


def _parse_request_target(message_text: str, reply_to_message, command_name: str):
    raw_text = (message_text or "").strip()
    parts = raw_text.split(maxsplit=2)

    request_id = None
    content = ""

    if len(parts) >= 2 and parts[1].isdigit():
        request_id = int(parts[1])
        content = parts[2].strip() if len(parts) >= 3 else ""
    elif len(parts) >= 2 and reply_to_message:
        content = raw_text[len(command_name):].strip()

    return request_id, content


def _extract_request_id_from_text(text: str | None) -> int | None:
    value = (text or "").strip()
    if not value:
        return None
    match = re.search(r"(?:solicitud\s*#|#)(\d+)", value, re.IGNORECASE)
    if match:
        try:
            return int(match.group(1))
        except Exception:
            return None
    return None


def _resolve_request_id_from_message(cursor, context: ContextTypes.DEFAULT_TYPE, explicit_request_id: int | None, reply_to_message) -> int | None:
    if explicit_request_id is not None:
        return explicit_request_id

    state = (getattr(context, "user_data", {}) or {}).get(REQUEST_ACTION_KEY) or {}
    state_request_id = state.get("request_id")
    if state_request_id:
        try:
            return int(state_request_id)
        except Exception:
            pass

    if not reply_to_message:
        return None

    row = _get_request_by_admin_message(cursor, reply_to_message.message_id)
    if row:
        return int(row[0])

    guessed = _extract_request_id_from_text(getattr(reply_to_message, "text", None) or getattr(reply_to_message, "caption", None))
    if guessed is not None:
        return guessed

    return None


def _build_delivery_caption(intro: str, caption: str | None = None, limit: int = 1024) -> str:
    text = f"{intro}\n\n{(caption or '').strip()}" if (caption or "").strip() else intro
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _resolve_template(template_key: str) -> str | None:
    entry = get_quick_templates().get((template_key or "").strip().lower())
    return entry.get("text") if entry else None


def _should_charge(text: str, template_key: str | None = None) -> bool:
    clean = (text or "").strip()
    key = (template_key or "").strip().lower()
    templates = get_quick_templates()
    if key and key in templates:
        return bool(templates[key].get("billable"))
    nodata_text = templates.get("nodata", {}).get("text", DEFAULT_QUICK_TEMPLATES["nodata"])
    return clean != nodata_text


def _update_request_status(cursor, request_id: int, status: str, admin_id: int | None, note: str = ""):
    cursor.execute(
        """
        UPDATE requests
        SET status = ?, resolved_at = ?, resolved_by = ?, resolution_note = ?
        WHERE id = ?
        """,
        (status, now_iso(), admin_id, note, request_id),
    )


def _append_note(previous: str | None, note: str) -> str:
    clean_note = (note or "").strip()
    if not clean_note:
        return (previous or "").strip()
    stamped = f"[{now_iso()}] {clean_note}"
    previous_clean = (previous or "").strip()
    if not previous_clean:
        return stamped
    return f"{previous_clean}\n{stamped}"


def _mark_request_delivery(cursor, request_id: int, admin_id: int | None, note: str, *, charged: int | None = None, resolved: bool = False):
    row = _get_request_by_id(cursor, request_id)
    if not row:
        return
    (
        _id,
        _user_id,
        _username,
        _command,
        _payload,
        _status,
        _admin_msg_id,
        _cost,
        current_charged,
        _delivery_count,
        _created_at,
        _resolved_at,
        _resolved_by,
        resolution_note,
    ) = row
    final_charged = current_charged if charged is None else charged
    final_note = _append_note(resolution_note, note)
    if resolved:
        cursor.execute(
            """
            UPDATE requests
            SET status = 'resolved',
                charged = ?,
                delivery_count = COALESCE(delivery_count, 0) + 1,
                resolved_at = ?,
                resolved_by = ?,
                resolution_note = ?
            WHERE id = ?
            """,
            (final_charged, now_iso(), admin_id, final_note, request_id),
        )
        return
    cursor.execute(
        """
        UPDATE requests
        SET status = 'pending',
            charged = ?,
            delivery_count = COALESCE(delivery_count, 0) + 1,
            resolution_note = ?
        WHERE id = ?
        """,
        (final_charged, final_note, request_id),
    )


def _maybe_charge_request(cursor, user_id: int, cost: int, already_charged: int) -> int:
    if already_charged:
        return 1
    from comandos.utils import descontar_creditos, verificar_usuario

    valido, info = verificar_usuario(str(user_id))
    if valido and not info.get("ilimitado", False):
        descontar_creditos(str(user_id), cost)
    return 1


def _build_request_keyboard(request_id: int, status: str = "pending"):
    status = (status or "pending").strip().lower()
    if status == "pending":
        rows = [
            [
                InlineKeyboardButton("Responder", callback_data=f"adminreq:reply:{request_id}"),
                InlineKeyboardButton("Resp. s/cobro", callback_data=f"adminreq:replyfree:{request_id}"),
            ],
            [
                InlineKeyboardButton("Plantillas", callback_data=f"adminreq:templates:{request_id}"),
                InlineKeyboardButton("Finalizar", callback_data=f"adminreq:done:{request_id}"),
            ],
            [
                InlineKeyboardButton("Cerrar", callback_data=f"adminreq:close:{request_id}"),
                InlineKeyboardButton("Fallida", callback_data=f"adminreq:fail:{request_id}"),
            ],
        ]
    else:
        rows = [
            [
                InlineKeyboardButton("Reabrir", callback_data=f"adminreq:reopen:{request_id}"),
                InlineKeyboardButton("Plantillas", callback_data=f"adminreq:templates:{request_id}"),
            ]
        ]
    return InlineKeyboardMarkup(rows)


def _build_template_keyboard(request_id: int):
    rows = []
    items = list(get_quick_templates().keys())
    for idx in range(0, len(items), 2):
        pair = items[idx: idx + 2]
        rows.append([InlineKeyboardButton(key, callback_data=f"adminreq:tpl:{request_id}:{key}") for key in pair])
    rows.append([InlineKeyboardButton("Volver", callback_data=f"adminreq:back:{request_id}")])
    return InlineKeyboardMarkup(rows)


def _set_action_state(context: ContextTypes.DEFAULT_TYPE, action: str, request_id: int):
    context.user_data[REQUEST_ACTION_KEY] = {"action": action, "request_id": request_id}


def _remember_request(context: ContextTypes.DEFAULT_TYPE, request_id: int):
    context.user_data[REQUEST_ACTION_KEY] = {"action": "last", "request_id": request_id}


def _clear_action_state(context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get(REQUEST_ACTION_KEY) or {}
    request_id = state.get("request_id")
    if request_id:
        context.user_data[REQUEST_ACTION_KEY] = {"action": "last", "request_id": request_id}
    else:
        context.user_data.pop(REQUEST_ACTION_KEY, None)


async def _send_request_reply(context: ContextTypes.DEFAULT_TYPE, admin_id: int, request_id: int, reply_text: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    row = _get_request_by_id(c, request_id)
    if not row:
        conn.close()
        return False, "Solicitud no encontrada."

    request_id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count, created_at, resolved_at, resolved_by, resolution_note = row
    if status != "pending":
        conn.close()
        return False, f"⚠️ La solicitud #{request_id} ya está en estado {status}."

    if _should_charge(reply_text):
        charged = _maybe_charge_request(c, user_id, cost, int(charged or 0))

    await context.bot.send_message(
        chat_id=user_id,
        text=f"📬 Respuesta a tu solicitud #{request_id}\n📌 Comando: /{command}\n\n{reply_text}",
    )
    _mark_request_delivery(c, request_id, admin_id, reply_text, charged=int(charged or 0), resolved=False)
    conn.commit()
    conn.close()
    await _update_admin_message_markup(context, request_id)
    return True, f"Respuesta enviada a {_target_label(username, user_id)} para la solicitud #{request_id} ✅ Sigue abierta; usa /done {request_id} cuando termines."


async def _send_request_reply_free(context: ContextTypes.DEFAULT_TYPE, admin_id: int, request_id: int, reply_text: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    row = _get_request_by_id(c, request_id)
    if not row:
        conn.close()
        return False, "Solicitud no encontrada."
    request_id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count, created_at, resolved_at, resolved_by, resolution_note = row
    if status != "pending":
        conn.close()
        return False, f"⚠️ La solicitud #{request_id} ya está en estado {status}."
    await context.bot.send_message(
        chat_id=user_id,
        text=f"📬 Respuesta a tu solicitud #{request_id}\n📌 Comando: /{command}\n\n{reply_text}\n\nNo se descontaron créditos.",
    )
    _mark_request_delivery(c, request_id, admin_id, f"[sin_cobro] {reply_text}", charged=int(charged or 0), resolved=False)
    conn.commit()
    conn.close()
    await _update_admin_message_markup(context, request_id)
    return True, f"Respuesta sin cobro enviada a {_target_label(username, user_id)} para la solicitud #{request_id} ✅ Sigue abierta; usa /done {request_id} cuando termines."


async def _done_request_by_id(context: ContextTypes.DEFAULT_TYPE, admin_id: int, request_id: int, note: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    row = _get_request_by_id(c, request_id)
    if not row:
        conn.close()
        return False, "Solicitud no encontrada."

    request_id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count, created_at, resolved_at, resolved_by, resolution_note = row
    if status != "pending":
        conn.close()
        return False, f"⚠️ La solicitud #{request_id} ya está en estado {status}."

    final_note = note or "✅ Tu solicitud fue finalizada por el administrador."
    await context.bot.send_message(
        chat_id=user_id,
        text=f"📌 Solicitud #{request_id} finalizada.\n📌 Comando: /{command}\n\n{final_note}",
    )
    _update_request_status(c, request_id, "resolved", admin_id, _append_note(resolution_note, final_note))
    conn.commit()
    conn.close()
    await _update_admin_message_markup(context, request_id)
    return True, f"Solicitud #{request_id} finalizada ✅"


async def _close_request_by_id(context: ContextTypes.DEFAULT_TYPE, admin_id: int, request_id: int, note: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    row = _get_request_by_id(c, request_id)
    if not row:
        conn.close()
        return False, "Solicitud no encontrada."

    request_id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count, created_at, resolved_at, resolved_by, resolution_note = row
    if status != "pending":
        conn.close()
        return False, f"⚠️ La solicitud #{request_id} ya está en estado {status}."

    final_note = note or "Tu solicitud fue cerrada por el administrador."
    await context.bot.send_message(
        chat_id=user_id,
        text=f"📌 Tu solicitud #{request_id} del comando /{command} fue cerrada.\n\n{final_note}\n\nNo se descontaron créditos.",
    )
    _update_request_status(c, request_id, "cancelled", admin_id, final_note)
    conn.commit()
    conn.close()
    await _update_admin_message_markup(context, request_id)
    return True, f"Solicitud #{request_id} cerrada sin cobro ✅"


async def _fail_request_by_id(context: ContextTypes.DEFAULT_TYPE, admin_id: int, request_id: int, note: str):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    row = _get_request_by_id(c, request_id)
    if not row:
        conn.close()
        return False, "Solicitud no encontrada."

    request_id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count, created_at, resolved_at, resolved_by, resolution_note = row
    if status != "pending":
        conn.close()
        return False, f"⚠️ La solicitud #{request_id} ya está en estado {status}."

    final_note = note or _resolve_template("nodata") or DEFAULT_QUICK_TEMPLATES["nodata"]
    await context.bot.send_message(
        chat_id=user_id,
        text=f"📬 Resultado de tu solicitud #{request_id}\n📌 Comando: /{command}\n\n{final_note}\n\nNo se descontaron créditos.",
    )
    _update_request_status(c, request_id, "failed", admin_id, final_note)
    conn.commit()
    conn.close()
    await _update_admin_message_markup(context, request_id)
    return True, f"Solicitud #{request_id} marcada como fallida sin cobro ✅"


async def _send_template_by_id(context: ContextTypes.DEFAULT_TYPE, admin_id: int, request_id: int, template_key: str):
    template_text = _resolve_template(template_key)
    if not template_text:
        return False, "❌ Plantilla no encontrada. Usa /templates para ver las disponibles."
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    row = _get_request_by_id(c, request_id)
    if not row:
        conn.close()
        return False, "Solicitud no encontrada."

    request_id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count, created_at, resolved_at, resolved_by, resolution_note = row
    if status != "pending":
        conn.close()
        return False, f"⚠️ La solicitud #{request_id} ya está en estado {status}."

    if _should_charge(template_text, template_key):
        charged = _maybe_charge_request(c, user_id, cost, int(charged or 0))

    await context.bot.send_message(
        chat_id=user_id,
        text=f"📬 Respuesta a tu solicitud #{request_id}\n📌 Comando: /{command}\n\n{template_text}",
    )
    _mark_request_delivery(c, request_id, admin_id, f"[template:{template_key}] {template_text}", charged=int(charged or 0), resolved=False)
    conn.commit()
    conn.close()
    await _update_admin_message_markup(context, request_id)
    return True, f"Plantilla {template_key} enviada para la solicitud #{request_id} ✅ Sigue abierta; usa /done {request_id} cuando termines."


async def _reopen_request_by_id(context: ContextTypes.DEFAULT_TYPE, admin_id: int, request_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    row = _get_request_by_id(c, request_id)
    if not row:
        conn.close()
        return False, "Solicitud no encontrada."
    request_id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count, created_at, resolved_at, resolved_by, resolution_note = row
    if status == "pending":
        conn.close()
        return False, f"⚠️ La solicitud #{request_id} ya está pendiente."
    c.execute(
        """
        UPDATE requests
        SET status='pending', resolved_at=NULL, resolved_by=NULL, resolution_note=''
        WHERE id=?
        """,
        (request_id,),
    )
    conn.commit()
    conn.close()
    await _update_admin_message_markup(context, request_id)
    return True, f"Solicitud #{request_id} reabierta ✅"


async def _update_admin_message_markup(context: ContextTypes.DEFAULT_TYPE, request_id: int):
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    row = _get_request_by_id(c, request_id)
    conn.close()
    if not row:
        return
    _sync_request_payload(_request_row_to_payload(row))
    _, _, _, _, _, status, admin_msg_id, _, _, _, _, _, _, _ = row
    admin_chat_id = primary_admin_id()
    if not admin_chat_id or not admin_msg_id:
        return
    try:
        await context.bot.edit_message_reply_markup(
            chat_id=admin_chat_id,
            message_id=admin_msg_id,
            reply_markup=_build_request_keyboard(request_id, status),
        )
    except Exception:
        pass


async def create_request(update: Update, context: ContextTypes.DEFAULT_TYPE, command: str, cost: int = 1):
    user = update.effective_user
    message = update.message
    from comandos.utils import get_command_runtime_config

    cfg = get_command_runtime_config(command, cost)
    cost = int(cfg.get("cost", cost))

    if message.text:
        payload = message.text
    elif message.caption:
        payload = message.caption
    else:
        payload = "📎 Archivo adjunto"

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO requests (user_id, username, command, payload, status, cost, charged, delivery_count, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user.id, user.username, command, payload, "pending", cost, 0, 0, now_iso()),
    )
    request_id = c.lastrowid
    conn.commit()
    conn.close()
    _sync_request_by_id(request_id)
    _log_historial(user.id, command, payload)

    await message.reply_text(
        f"✅ Tu solicitud *{command.upper()}* está siendo procesada por el bot.\n"
        f"ID de solicitud: {request_id}",
        parse_mode="Markdown",
    )

    admin_chat_id = primary_admin_id()
    if admin_chat_id is None:
        await message.reply_text("❌ No hay ADMIN_ID configurado en config.json.")
        return

    sent = await context.bot.send_message(
        chat_id=admin_chat_id,
        text=(
            f"📩 Nueva solicitud #{request_id}\n"
            f"👤 Usuario: {_target_label(user.username, user.id)}\n"
            f"📌 Comando: /{command}\n"
            f"💳 Costo: {cost} créditos\n"
            f"📝 Pedido: {payload}\n\n"
            f"Comandos:\n"
            f"/reply {request_id} <texto>\n"
            f"/close {request_id} [motivo]\n"
            f"/fail {request_id} [motivo]\n"
            f"/rquick {request_id} <plantilla>"
        ),
        reply_markup=_build_request_keyboard(request_id, "pending"),
    )

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute("UPDATE requests SET admin_msg_id=? WHERE id=?", (sent.message_id, request_id))
    conn.commit()
    conn.close()
    _sync_request_by_id(request_id)


async def reply_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos para responder solicitudes.")
        return

    request_id, reply_text = _parse_request_target(update.message.text, update.message.reply_to_message, "/reply")
    if not reply_text:
        await update.message.reply_text("Uso: /reply <id> <texto> o responde al mensaje del admin con /reply <texto>")
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    request_id = _resolve_request_id_from_message(c, context, request_id, update.message.reply_to_message)
    conn.close()
    if request_id is None:
        await update.message.reply_text("Solicitud no encontrada.")
        return

    ok, msg = await _send_request_reply(context, update.effective_user.id, request_id, reply_text)
    await update.message.reply_text(msg)


async def forward_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return
    if not update.effective_user or not is_admin(update.effective_user.id):
        return
    if not any([update.message.photo, update.message.document, update.message.video, update.message.audio, update.message.voice]):
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    request_id = _resolve_request_id_from_message(c, context, None, update.message.reply_to_message)
    row = _get_request_by_id(c, request_id) if request_id is not None else None

    if not row:
        await update.message.reply_text("❌ Ese mensaje no está vinculado a una solicitud pendiente.")
        conn.close()
        return

    request_id, user_id, username, command, payload, status, admin_msg_id, cost, charged, delivery_count, created_at, resolved_at, resolved_by, resolution_note = row
    if status != "pending":
        await update.message.reply_text(f"⚠️ La solicitud #{request_id} ya está en estado {status}.")
        conn.close()
        return

    caption = (update.message.caption or "").strip()
    intro = f"📬 Archivo para tu solicitud #{request_id}\n📌 Comando: /{command}"
    delivered = False

    try:
        if update.message.photo:
            await context.bot.send_photo(chat_id=user_id, photo=update.message.photo[-1].file_id, caption=_build_delivery_caption(intro, caption))
            delivered = True
        elif update.message.document:
            await context.bot.send_document(chat_id=user_id, document=update.message.document.file_id, caption=_build_delivery_caption(intro, caption))
            delivered = True
        elif update.message.video:
            await context.bot.send_video(chat_id=user_id, video=update.message.video.file_id, caption=_build_delivery_caption(intro, caption))
            delivered = True
        elif update.message.audio:
            await context.bot.send_audio(chat_id=user_id, audio=update.message.audio.file_id, caption=_build_delivery_caption(intro, caption))
            delivered = True
        elif update.message.voice:
            await context.bot.send_voice(chat_id=user_id, voice=update.message.voice.file_id, caption=_build_delivery_caption(intro, caption))
            delivered = True
    except Exception as exc:
        await update.message.reply_text(f"❌ No se pudo reenviar el archivo: {exc}")
        conn.close()
        return

    if not delivered:
        await update.message.reply_text("❌ Ese tipo de archivo todavía no se reenvía automáticamente.")
        conn.close()
        return

    charged = _maybe_charge_request(c, user_id, cost, int(charged or 0))

    note = caption or "[archivo enviado]"
    _mark_request_delivery(c, request_id, update.effective_user.id, note, charged=int(charged or 0), resolved=False)
    conn.commit()
    await update.message.reply_text(f"Archivo enviado a {_target_label(username, user_id)} para la solicitud #{request_id} ✅ Sigue abierta; usa /done {request_id} cuando termines.")
    conn.close()


async def done_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos para finalizar solicitudes.")
        return

    request_id, note = _parse_request_target(update.message.text, update.message.reply_to_message, "/done")
    note = note or "✅ Tu solicitud fue finalizada por el administrador."

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    request_id = _resolve_request_id_from_message(c, context, request_id, update.message.reply_to_message)
    conn.close()
    if request_id is None:
        await update.message.reply_text("Solicitud no encontrada.")
        return

    _clear_action_state(context)
    ok, msg = await _done_request_by_id(context, update.effective_user.id, request_id, note)
    await update.message.reply_text(msg)


async def close_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos para cerrar solicitudes.")
        return

    request_id, note = _parse_request_target(update.message.text, update.message.reply_to_message, "/close")
    note = note or "Tu solicitud fue cerrada por el administrador."

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    request_id = _resolve_request_id_from_message(c, context, request_id, update.message.reply_to_message)
    conn.close()
    if request_id is None:
        await update.message.reply_text("Solicitud no encontrada.")
        return

    ok, msg = await _close_request_by_id(context, update.effective_user.id, request_id, note)
    await update.message.reply_text(msg)


async def fail_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos para marcar solicitudes.")
        return

    request_id, note = _parse_request_target(update.message.text, update.message.reply_to_message, "/fail")
    note = note or _resolve_template("nodata") or DEFAULT_QUICK_TEMPLATES["nodata"]

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    request_id = _resolve_request_id_from_message(c, context, request_id, update.message.reply_to_message)
    conn.close()
    if request_id is None:
        await update.message.reply_text("Solicitud no encontrada.")
        return

    ok, msg = await _fail_request_by_id(context, update.effective_user.id, request_id, note)
    await update.message.reply_text(msg)


async def templates_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not is_admin(update.effective_user.id):
        return

    lines = ["🧩 Plantillas rápidas disponibles:"]
    for key, meta in get_quick_templates().items():
        tag = " con cobro" if meta.get("billable") else " sin cobro"
        lines.append(f"- {key}:{tag} {meta.get('text')}")
    lines.append("")
    lines.append("Usa /rquick <id> <plantilla> o responde al mensaje del admin con /rquick <plantilla>.")
    await update.message.reply_text("\n".join(lines))


async def quick_reply_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos para usar plantillas.")
        return

    raw_text = update.message.text.strip()
    parts = raw_text.split(maxsplit=2)
    request_id = None
    template_key = ""

    if len(parts) >= 3 and parts[1].isdigit():
        request_id = int(parts[1])
        template_key = parts[2].strip().lower()
    elif len(parts) >= 2 and update.message.reply_to_message:
        template_key = parts[1].strip().lower()
    else:
        await update.message.reply_text("Uso: /rquick <id> <plantilla> o responde al mensaje del admin con /rquick <plantilla>")
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    request_id = _resolve_request_id_from_message(c, context, request_id, update.message.reply_to_message)
    conn.close()
    if request_id is None:
        await update.message.reply_text("Solicitud no encontrada.")
        return

    ok, msg = await _send_template_by_id(context, update.effective_user.id, request_id, template_key)
    if ok:
        _remember_request(context, request_id)
    await update.message.reply_text(msg)


async def pending_requests_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not is_admin(update.effective_user.id):
        return

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        SELECT id, username, user_id, command, cost, created_at
        FROM requests
        WHERE status = 'pending'
        ORDER BY id DESC
        LIMIT 12
        """
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No hay solicitudes pendientes.")
        return

    lines = ["📋 Pendientes recientes:"]
    for request_id, username, user_id, command, cost, created_at in rows:
        lines.append(f"#{request_id} | /{command} | {_target_label(username, user_id)} | {cost}cr | {created_at or '—'}")
    lines.append("")
    lines.append("Usa /reply, /rquick, /done, /close o /fail.")
    await update.message.reply_text("\n".join(lines))


async def request_log_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.effective_user or not is_admin(update.effective_user.id):
        return

    limit = 12
    if context.args:
        try:
            limit = max(1, min(int(context.args[0]), 30))
        except Exception:
            limit = 12

    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    c.execute(
        """
        SELECT id, username, user_id, command, status, cost, created_at, resolved_at, resolution_note
        FROM requests
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,),
    )
    rows = c.fetchall()
    conn.close()

    if not rows:
        await update.message.reply_text("No hay historial de solicitudes.")
        return

    lines = ["🧾 Historial reciente de solicitudes:"]
    for request_id, username, user_id, command, status, cost, created_at, resolved_at, resolution_note in rows:
        lines.append(
            f"#{request_id} | /{command} | {_target_label(username, user_id)} | {status} | {cost}cr"
        )
        lines.append(f"Creada: {created_at or '—'} | Cerrada: {resolved_at or '—'}")
        if resolution_note:
            lines.append(f"Nota: {_trim(resolution_note)}")
    await update.message.reply_text("\n".join(lines))


async def reopen_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    if not update.effective_user or not is_admin(update.effective_user.id):
        await update.message.reply_text("❌ No tienes permisos para reabrir solicitudes.")
        return
    parts = update.message.text.split(maxsplit=1)
    if len(parts) < 2 or not parts[1].strip().isdigit():
        await update.message.reply_text("Uso: /reopen <id>")
        return
    request_id = int(parts[1].strip())
    ok, msg = await _reopen_request_by_id(context, update.effective_user.id, request_id)
    await update.message.reply_text(msg)


async def request_buttons_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query or not update.effective_user or not is_admin(update.effective_user.id):
        return

    await query.answer()
    data = (query.data or "").strip()
    parts = data.split(":")
    if len(parts) < 3 or parts[0] != "adminreq":
        return

    action = parts[1]
    try:
        request_id = int(parts[2])
    except Exception:
        await query.edit_message_reply_markup(reply_markup=_build_request_keyboard(0, "pending"))
        return

    if action == "reply":
        _set_action_state(context, "reply", request_id)
        await query.message.reply_text(f"Escribe la respuesta para la solicitud #{request_id}. Se enviará al usuario cuando mandes el siguiente mensaje.")
        return

    if action == "replyfree":
        _set_action_state(context, "replyfree", request_id)
        await query.message.reply_text(f"Escribe la respuesta sin cobro para la solicitud #{request_id}.")
        return

    if action == "templates":
        await query.edit_message_reply_markup(reply_markup=_build_template_keyboard(request_id))
        return

    if action == "back":
        await query.edit_message_reply_markup(reply_markup=_build_request_keyboard(request_id, "pending"))
        return

    if action == "close":
        _set_action_state(context, "close", request_id)
        await query.message.reply_text(f"Escribe el motivo para cerrar la solicitud #{request_id} o manda solo un punto `.` para usar el texto por defecto.")
        return

    if action == "done":
        _set_action_state(context, "done", request_id)
        await query.message.reply_text(f"Escribe un cierre final para la solicitud #{request_id} o manda solo un punto `.` para usar el texto por defecto.")
        return

    if action == "fail":
        _set_action_state(context, "fail", request_id)
        await query.message.reply_text(f"Escribe el motivo de la falla para la solicitud #{request_id} o manda solo un punto `.` para usar el texto por defecto.")
        return

    if action == "reopen":
        ok, msg = await _reopen_request_by_id(context, update.effective_user.id, request_id)
        await query.message.reply_text(msg)
        return

    if action == "tpl" and len(parts) >= 4:
        template_key = parts[3].strip().lower()
        ok, msg = await _send_template_by_id(context, update.effective_user.id, request_id, template_key)
        if ok:
            _remember_request(context, request_id)
        await query.message.reply_text(msg)
        return


async def admin_followup_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text or not update.effective_user or not is_admin(update.effective_user.id):
        return
    if update.message.text.startswith("/"):
        return

    state = context.user_data.get(REQUEST_ACTION_KEY)
    if not state:
        return

    request_id = state.get("request_id")
    action = (state.get("action") or "").strip().lower()
    if action == "last":
        return
    text = (update.message.text or "").strip()
    if text == ".":
        text = ""

    if action == "reply":
        if not text:
            await update.message.reply_text("❌ La respuesta no puede estar vacía.")
            return
        ok, msg = await _send_request_reply(context, update.effective_user.id, request_id, text)
        await update.message.reply_text(msg)
        return

    if action == "replyfree":
        if not text:
            await update.message.reply_text("❌ La respuesta no puede estar vacía.")
            return
        ok, msg = await _send_request_reply_free(context, update.effective_user.id, request_id, text)
        await update.message.reply_text(msg)
        return

    _clear_action_state(context)

    if action == "done":
        ok, msg = await _done_request_by_id(context, update.effective_user.id, request_id, text or "✅ Tu solicitud fue finalizada por el administrador.")
        await update.message.reply_text(msg)
        return

    if action == "close":
        ok, msg = await _close_request_by_id(context, update.effective_user.id, request_id, text)
        await update.message.reply_text(msg)
        return

    if action == "fail":
        ok, msg = await _fail_request_by_id(context, update.effective_user.id, request_id, text)
        await update.message.reply_text(msg)
        return

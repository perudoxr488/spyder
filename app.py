from flask import Flask, jsonify, request, redirect, render_template, session, url_for, Response, send_file
import sqlite3
from datetime import datetime, timedelta
import secrets
from collections import Counter
import math
import hashlib
import secrets
import time
import os
import json
import csv
import io
import zipfile
import traceback
import shutil
from flask_cors import CORS, cross_origin
from werkzeug.security import check_password_hash, generate_password_hash
from storage import db_path, get_data_dir

DB_PATH = db_path("multiplataforma.db")
HIST_DB_PATH = db_path("historial.db")
COMPRAS_DB_PATH = db_path("compras.db")
KEYS_DB_PATH = db_path("keys.db")
REQUESTS_DB_PATH = db_path("requests.db")
CONFIG_FILE_PATH = "config.json"

app = Flask(__name__)

CFG = {}
if os.path.exists(CONFIG_FILE_PATH):
    try:
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f) or {}
    except Exception:
        CFG = {}

INTERNAL_API_KEY = (
    os.environ.get("SPIDERSYN_INTERNAL_API_KEY")
    or CFG.get("INTERNAL_API_KEY")
    or CFG.get("TOKEN_BOT")
    or ""
)
PANEL_PUBLIC = (
    str(os.environ.get("SPIDERSYN_PANEL_PUBLIC") or CFG.get("PANEL_PUBLIC") or "0").strip().lower()
    in {"1", "true", "yes", "on"}
)
app.secret_key = (
    os.environ.get("SPIDERSYN_PANEL_SECRET")
    or CFG.get("PANEL_SECRET")
    or CFG.get("TOKEN_BOT")
    or "spidersyn-panel-secret"
)
PANEL_USER = (os.environ.get("SPIDERSYN_PANEL_USER") or CFG.get("PANEL_USER") or "admin").strip()
PANEL_PASSWORD = (
    os.environ.get("SPIDERSYN_PANEL_PASSWORD")
    or CFG.get("PANEL_PASSWORD")
    or str(CFG.get("ADMIN_ID") or "admin123")
)
PANEL_LOGIN_ATTEMPTS = {}
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = PANEL_PUBLIC
_BACKUP_CHECK_TS = 0.0


def _is_loopback_request() -> bool:
    remote = (request.remote_addr or "").strip()
    return remote in {"127.0.0.1", "::1", "localhost"}


def _panel_request_allowed() -> bool:
    if PANEL_PUBLIC:
        return True
    return _is_loopback_request()


def require_internal_access():
    # Permite llamadas locales del bot/API o, si se despliega separado,
    # un header explícito compartido entre servicios.
    if _is_loopback_request():
        return None

    supplied = (request.headers.get("X-Internal-Api-Key") or "").strip()
    if INTERNAL_API_KEY and secrets.compare_digest(supplied, INTERNAL_API_KEY):
        return None

    return jsonify({"status": "error", "message": "Acceso no autorizado"}), 403


@app.before_request
def maybe_create_daily_backup():
    global _BACKUP_CHECK_TS
    now_ts = time.time()
    if now_ts - _BACKUP_CHECK_TS < 3600:
        return None
    _BACKUP_CHECK_TS = now_ts
    try:
        ensure_daily_backup(force=False)
    except Exception:
        pass
    return None


def request_value(name: str, default=None):
    if request.is_json:
        payload = request.get_json(silent=True) or {}
        if name in payload:
            return payload.get(name)
    return request.values.get(name, default)


def configured_admin_ids() -> set[str]:
    raw = (
        os.environ.get("SPIDERSYN_ADMIN_ID")
        or os.environ.get("ADMIN_ID")
        or CFG.get("ADMIN_ID")
    )
    if isinstance(raw, list):
        values = raw
    elif raw is None:
        values = []
    else:
        values = str(raw).replace(",", " ").split()
    return {str(value).strip() for value in values if str(value).strip()}

# -------------------------
# Utils
# -------------------------
def generate_unique_token() -> str:
    # 64 chars hex (SHA-256). Mezcla tiempo (ns) + entropía criptográfica
    seed = f"{time.time_ns()}:{secrets.token_hex(32)}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()

def now_utc() -> datetime:
    return datetime.utcnow().replace(microsecond=0)

def now_iso() -> str:
    return now_utc().isoformat() + "Z"

def parse_iso(dt_str: str) -> datetime:
    # Acepta "YYYY-mm-ddTHH:MM:SSZ" o sin 'Z'
    s = dt_str.strip()
    if s.endswith("Z"):
        s = s[:-1]
    return datetime.fromisoformat(s)

def get_conn(db_path=DB_PATH):
    return sqlite3.connect(db_path, check_same_thread=False)

def init_main_db():
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS usuarios (
            id_tg TEXT PRIMARY KEY,
            rol_tg TEXT DEFAULT 'FREE',
            fecha_register_tg TEXT,

            creditos INTEGER DEFAULT 5,
            plan TEXT DEFAULT 'FREE',
            estado TEXT DEFAULT 'ACTIVO',
            fecha_caducidad TEXT,

            register_web INTEGER DEFAULT 0,   -- FALSE por defecto
            register_wsp INTEGER DEFAULT 0,   -- FALSE por defecto

            token_api_web TEXT UNIQUE,
            user_web TEXT,
            pass_web TEXT,
            rol_web TEXT DEFAULT 'FREE',
            fecha_register_web TEXT,

            token_api_wsp TEXT UNIQUE,
            number_wsp TEXT,
            rol_wsp TEXT DEFAULT 'FREE',
            fecha_register_wsp TEXT,

            antispam INTEGER DEFAULT 60
        );
        """
    )
    conn.commit()
    conn.close()

def init_keys_db():
    conn = get_conn(KEYS_DB_PATH)
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS keys (
        key TEXT PRIMARY KEY,
        tipo TEXT NOT NULL,
        cantidad INTEGER NOT NULL,
        usos INTEGER NOT NULL,
        creador_id INTEGER NOT NULL,
        fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS redemptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        fecha_canje TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (key) REFERENCES keys(key)
    )
    """)

    conn.commit()
    conn.close()    


DEFAULT_CATEGORIES = [
    ("reniec", "RENIEC", "Consultas RENIEC", 1, 1),
    ("vehiculos", "VEHICULOS", "Consultas vehiculares", 2, 1),
    ("delitos", "DELITOS", "Antecedentes, requisitorias y denuncias", 3, 1),
    ("familia", "FAMILIA", "Hogar, arbol y vínculos", 4, 1),
    ("telefonia", "TELEFONIA", "Operadoras y telefonía", 5, 1),
    ("sunarp", "SUNARP", "Propiedades y registros", 6, 1),
    ("laboral", "LABORAL", "Trabajo y planillas", 7, 1),
    ("actas", "ACTAS", "Actas y documentos relacionados", 8, 1),
    ("migraciones", "MIGRACIONES", "Consultas migratorias", 9, 1),
    ("extras", "EXTRAS", "Consultas adicionales", 10, 1),
]

DEFAULT_COMMANDS = [
    ("nm", "NM", "reniec", 2),
    ("dni", "DNI", "reniec", 1),
    ("dnif", "DNIF", "reniec", 3),
    ("dnim", "DNIM", "reniec", 2),
    ("c4", "C4", "reniec", 5),
    ("c4blanco", "C4 BLANCO", "reniec", 5),
    ("c4azul", "C4 AZUL", "reniec", 5),
    ("dnivel", "DNIVEL", "reniec", 5),
    ("dnivam", "DNIVAM", "reniec", 5),
    ("dnivaz", "DNIVAZ", "reniec", 5),
    ("revitec", "REVITEC", "vehiculos", 10),
    ("tiveqr", "TIVE QR", "vehiculos", 15),
    ("soat", "SOAT", "vehiculos", 7),
    ("tive", "TIVE", "vehiculos", 8),
    ("tiveor", "TIVE OR", "vehiculos", 10),
    ("tarjetafisica", "TARJETA FISICA", "vehiculos", 10),
    ("placasiento", "PLACA SIENTO", "vehiculos", 10),
    ("pla", "PLA", "vehiculos", 3),
    ("papeletas", "PAPELETAS", "vehiculos", 8),
    ("bolinv", "BOLINV", "vehiculos", 8),
    ("insve", "INSVE", "vehiculos", 6),
    ("licencia", "LICENCIA", "vehiculos", 5),
    ("licenciapdf", "LICENCIA PDF", "vehiculos", 8),
    ("rqv", "RQV", "delitos", 10),
    ("denunciasv", "DENUNCIAS V", "delitos", 10),
    ("det", "DET", "delitos", 5),
    ("ant", "ANT", "delitos", 8),
    ("antpe", "ANTPE", "delitos", 7),
    ("antpo", "ANTPO", "delitos", 7),
    ("antju", "ANTJU", "delitos", 7),
    ("denuncias", "DENUNCIAS", "delitos", 10),
    ("rq", "RQ", "delitos", 8),
    ("fis", "FIS", "delitos", 10),
    ("fispdf", "FIS PDF", "delitos", 25),
    ("hogar", "HOGAR", "familia", 5),
    ("ag", "AG", "familia", 10),
    ("agv", "AGV", "familia", 20),
    ("her", "HER", "familia", 5),
    ("numclaro", "NUMCLARO", "telefonia", 7),
    ("correo", "CORREO", "telefonia", 3),
    ("enteldb", "ENTELDB", "telefonia", 3),
    ("movistar", "MOVISTAR", "telefonia", 7),
    ("bitel", "BITEL", "telefonia", 7),
    ("claro", "CLARO", "telefonia", 7),
    ("vlop", "VLOP", "telefonia", 1),
    ("vlnum", "VLNUM", "telefonia", 1),
    ("cel", "CEL", "telefonia", 7),
    ("tels", "TELS", "telefonia", 5),
    ("telp", "TELP", "telefonia", 7),
    ("tel", "TEL", "telefonia", 3),
    ("sunarp", "SUNARP", "sunarp", 10),
    ("sunarpdf", "SUNARP PDF", "sunarp", 20),
    ("sueldos", "SUELDOS", "laboral", 5),
    ("trabajos", "TRABAJOS", "laboral", 5),
    ("actamdb", "ACTAMDB", "actas", 5),
    ("actaddb", "ACTADDB", "actas", 5),
    ("migrapdf", "MIGRAPDF", "migraciones", 6),
    ("afp", "AFP", "extras", 3),
    ("dir", "DIR", "extras", 3),
    ("trabajadores", "TRABAJADORES", "extras", 8),
    ("sbs", "SBS", "extras", 5),
    ("notas", "NOTAS", "extras", 25),
    ("essalud", "ESSALUD", "extras", 3),
    ("doc", "DOC", "extras", 3),
    ("ruc", "RUC", "extras", 5),
    ("sunat", "SUNAT", "extras", 8),
    ("seeker", "SEEKER", "extras", 10),
    ("facial", "FACIAL", "extras", 30),
]

DEFAULT_BUY_PACKAGES = [
    ("credits", "basico", "🔰", "BASICO", "45's", "50 + 20 Creditos ➩ 10 Soles", 1, 1),
    ("credits", "basico", "🔰", "BASICO", "45's", "100 + 30 Creditos ➩ 15 Soles", 2, 1),
    ("credits", "basico", "🔰", "BASICO", "45's", "200 + 50 Creditos ➩ 23 Soles", 3, 1),
    ("credits", "basico", "🔰", "BASICO", "45's", "350 + 80 Creditos ➩ 30 Soles", 4, 1),
    ("credits", "standard", "⭐", "STANDARD", "15's", "500 + 100 Creditos ➩ 50 Soles", 5, 1),
    ("credits", "standard", "⭐", "STANDARD", "15's", "800 + 150 Creditos ➩ 70 Soles", 6, 1),
    ("credits", "standard", "⭐", "STANDARD", "15's", "1000 + 200 Creditos ➩ 90 Soles", 7, 1),
    ("credits", "premium", "💎", "PREMIUM", "5's", "1500 + 200 Creditos ➩ 100 Soles", 8, 1),
    ("credits", "premium", "💎", "PREMIUM", "5's", "2000 + 300 Creditos ➩ 130 Soles", 9, 1),
    ("credits", "premium", "💎", "PREMIUM", "5's", "2800 + 400 Creditos ➩ 170 Soles", 10, 1),
    ("days", "basico-dias", "🔰", "BASICO - NV1", "25's", "3 Dias ➩ 12 Soles", 11, 1),
    ("days", "basico-dias", "🔰", "BASICO - NV1", "25's", "7 Dias ➩ 17 Soles", 12, 1),
    ("days", "standard-dias", "⭐", "STANDARD - NV2", "15's", "15 Dias ➩ 30 Soles", 13, 1),
    ("days", "standard-dias", "⭐", "STANDARD - NV2", "15's", "30 Dias ➩ 50 Soles", 14, 1),
    ("days", "premium-dias", "💎", "PREMIUM - NV3", "5's", "60 Dias ➩ 75 Soles", 15, 1),
    ("days", "premium-dias", "💎", "PREMIUM - NV3", "5's", "90 Dias ➩ 110 Soles", 16, 1),
]

DEFAULT_PANEL_SETTINGS = [
    ("BOT_NAME", CFG.get("BOT_NAME") or CFG.get("NAME") or "#SPIDERSYN ⇒"),
    ("BT_OWNER", CFG.get("BT_OWNER") or "OWNER"),
    ("OWNER_LINK", CFG.get("OWNER_LINK") or ""),
    ("BT_CANAL", CFG.get("BT_CANAL") or "CANAL"),
    ("CANAL_LINK", CFG.get("CANAL_LINK") or ""),
    ("BT_GRUPO", CFG.get("BT_GRUPO") or "GRUPO"),
    ("GRUPO_LINK", CFG.get("GRUPO_LINK") or ""),
    ("BT_SELLER", CFG.get("BT_SELLER") or ""),
    ("SELLER_LINK", CFG.get("SELLER_LINK") or ""),
    ("BT_SELLER1", CFG.get("BT_SELLER1") or ""),
    ("SELLER_LINK1", CFG.get("SELLER_LINK1") or ""),
    ("BT_SELLER2", CFG.get("BT_SELLER2") or ""),
    ("SELLER_LINK2", CFG.get("SELLER_LINK2") or ""),
    ("BT_SELLER3", CFG.get("BT_SELLER3") or ""),
    ("SELLER_LINK3", CFG.get("SELLER_LINK3") or ""),
    ("FT_BUY", ((CFG.get("LOGO") or {}).get("FT_BUY") or "")),
    ("FT_CMDS", ((CFG.get("LOGO") or {}).get("FT_CMDS") or "")),
    ("FT_CMDSADMIN", ((CFG.get("LOGO") or {}).get("FT_CMDSADMIN") or "")),
    ("FT_START", ((CFG.get("LOGO") or {}).get("FT_START") or "")),
]


def init_catalog_db():
    conn = get_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS command_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            slug TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS command_catalog (
            slug TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            category_id INTEGER,
            cost INTEGER NOT NULL DEFAULT 1,
            is_active INTEGER DEFAULT 1,
            sort_order INTEGER DEFAULT 0,
            usage_hint TEXT DEFAULT '',
            FOREIGN KEY (category_id) REFERENCES command_categories(id)
        )
        """
    )
    for slug, name, description, sort_order, is_active in DEFAULT_CATEGORIES:
        cur.execute(
            """
            INSERT INTO command_categories (slug, name, description, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = COALESCE(command_categories.name, excluded.name)
            """,
            (slug, name, description, sort_order, is_active),
        )
    conn.commit()

    cur.execute("SELECT id, slug FROM command_categories")
    category_ids = {row["slug"]: row["id"] for row in cur.fetchall()}
    for idx, (slug, name, category_slug, cost) in enumerate(DEFAULT_COMMANDS, start=1):
        cur.execute(
            """
            INSERT INTO command_catalog (slug, name, category_id, cost, is_active, sort_order)
            VALUES (?, ?, ?, ?, 1, ?)
            ON CONFLICT(slug) DO NOTHING
            """,
            (slug, name, category_ids.get(category_slug), cost, idx),
        )
    conn.commit()
    conn.close()


def init_buy_db():
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS buy_packages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            kind TEXT NOT NULL CHECK(kind IN ('credits', 'days')),
            group_slug TEXT NOT NULL,
            badge TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            subtitle TEXT DEFAULT '',
            line_text TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            is_active INTEGER DEFAULT 1
        )
        """
    )
    for kind, group_slug, badge, title, subtitle, line_text, sort_order, is_active in DEFAULT_BUY_PACKAGES:
        cur.execute(
            """
            INSERT INTO buy_packages (kind, group_slug, badge, title, subtitle, line_text, sort_order, is_active)
            SELECT ?, ?, ?, ?, ?, ?, ?, ?
            WHERE NOT EXISTS (
                SELECT 1 FROM buy_packages
                WHERE kind = ? AND group_slug = ? AND line_text = ?
            )
            """,
            (kind, group_slug, badge, title, subtitle, line_text, sort_order, is_active, kind, group_slug, line_text),
        )
    conn.commit()
    conn.close()


def init_panel_settings_db():
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS panel_settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
        """
    )
    for key, value in DEFAULT_PANEL_SETTINGS:
        cur.execute(
            """
            INSERT INTO panel_settings (key, value)
            VALUES (?, ?)
            ON CONFLICT(key) DO NOTHING
            """,
            (key, value),
        )
    conn.commit()
    conn.close()


def sync_owner_users():
    admin_ids = configured_admin_ids()
    if not admin_ids:
        return
    owner_exp = "2099-12-31T23:59:59Z"
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    for admin_id in admin_ids:
        cur.execute(
            """
            INSERT INTO usuarios (
                id_tg, rol_tg, fecha_register_tg, creditos, plan, estado,
                fecha_caducidad, rol_web, rol_wsp, antispam
            )
            VALUES (?, 'FUNDADOR', ?, 999999, 'PREMIUM', 'ACTIVO', ?, 'FUNDADOR', 'FUNDADOR', 0)
            ON CONFLICT(id_tg) DO UPDATE SET
                rol_tg = 'FUNDADOR',
                rol_web = 'FUNDADOR',
                rol_wsp = 'FUNDADOR',
                plan = 'PREMIUM',
                estado = 'ACTIVO',
                antispam = 0,
                creditos = CASE WHEN COALESCE(creditos, 0) < 999999 THEN 999999 ELSE creditos END,
                fecha_caducidad = CASE
                    WHEN fecha_caducidad IS NULL OR fecha_caducidad = '' OR fecha_caducidad < ?
                    THEN ?
                    ELSE fecha_caducidad
                END
            """,
            (admin_id, now_iso(), owner_exp, owner_exp, owner_exp),
        )
    conn.commit()
    conn.close()


def init_requests_db():
    conn = get_conn(REQUESTS_DB_PATH)
    cur = conn.cursor()
    cur.execute(
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
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS request_templates (
            key TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            billable INTEGER DEFAULT 0
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS error_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT,
            method TEXT,
            message TEXT,
            traceback TEXT,
            created_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            actor TEXT,
            ip TEXT,
            action TEXT,
            target TEXT,
            details TEXT,
            created_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def log_audit_event(action: str, target: str = "", details: str = "", actor: str = ""):
    try:
        conn = get_conn(REQUESTS_DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO audit_logs (actor, ip, action, target, details, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                actor or session.get("panel_user") or PANEL_USER,
                request.remote_addr or "",
                action,
                target,
                str(details or "")[:2000],
                now_iso(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def log_error_event(exc: Exception):
    try:
        conn = get_conn(REQUESTS_DB_PATH)
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO error_logs (path, method, message, traceback, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                request.path,
                request.method,
                str(exc),
                traceback.format_exc()[-6000:],
                now_iso(),
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


@app.errorhandler(Exception)
def handle_unexpected_error(exc):
    if getattr(exc, "code", None) and int(getattr(exc, "code")) < 500:
        return exc
    log_error_event(exc)
    return (
        "<h1>Internal Server Error</h1>"
        "<p>The server encountered an internal error and was unable to complete your request.</p>",
        500,
    )


def get_catalog_categories():
    conn = get_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, slug, name, description, sort_order, is_active
        FROM command_categories
        ORDER BY sort_order ASC, name ASC
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_catalog_commands():
    conn = get_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.slug, c.name, c.description, c.cost, c.is_active, c.sort_order, c.usage_hint,
               cat.id AS category_id, cat.slug AS category_slug, cat.name AS category_name
        FROM command_catalog c
        LEFT JOIN command_categories cat ON cat.id = c.category_id
        ORDER BY COALESCE(cat.sort_order, 9999), COALESCE(cat.name, 'ZZZ'), c.sort_order ASC, c.name ASC
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_command_config_value(slug: str, default_cost: int = 1):
    conn = get_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.slug, c.name, c.cost, c.is_active, cat.slug AS category_slug, cat.name AS category_name
        FROM command_catalog c
        LEFT JOIN command_categories cat ON cat.id = c.category_id
        WHERE c.slug = ?
        """,
        (slug,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return {
            "slug": slug,
            "name": slug.upper(),
            "cost": int(default_cost),
            "is_active": True,
            "category_slug": None,
            "category_name": None,
        }
    return {
        "slug": row["slug"],
        "name": row["name"],
        "cost": int(row["cost"] or default_cost),
        "is_active": bool(row["is_active"]),
        "category_slug": row["category_slug"],
        "category_name": row["category_name"],
    }


def get_buy_packages():
    conn = get_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, kind, group_slug, badge, title, subtitle, line_text, sort_order, is_active
        FROM buy_packages
        ORDER BY kind ASC, sort_order ASC, id ASC
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def get_buy_packages_grouped(active_only: bool = True):
    rows = get_buy_packages()
    grouped = {"credits": [], "days": []}
    seen = {}
    for row in rows:
        if active_only and not row["is_active"]:
            continue
        key = (row["kind"], row["group_slug"])
        if key not in seen:
            entry = {
                "group_slug": row["group_slug"],
                "badge": row["badge"],
                "title": row["title"],
                "subtitle": row["subtitle"],
                "items": [],
            }
            seen[key] = entry
            grouped[row["kind"]].append(entry)
        seen[key]["items"].append(row["line_text"])
    return grouped


def get_panel_settings():
    conn = get_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS panel_settings (
            key TEXT PRIMARY KEY,
            value TEXT DEFAULT ''
        )
        """
    )
    cur.execute("SELECT key, value FROM panel_settings ORDER BY key ASC")
    rows = {row["key"]: row["value"] for row in cur.fetchall()}
    conn.close()
    return rows


def get_panel_setting(key: str, default: str = "") -> str:
    try:
        return str(get_panel_settings().get(key, default) or default)
    except Exception:
        return default


def save_panel_setting_value(key: str, value: str):
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO panel_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()


def verify_panel_password(password: str) -> bool:
    stored_hash = get_panel_setting("PANEL_PASSWORD_HASH", "")
    if stored_hash:
        try:
            return check_password_hash(stored_hash, password)
        except Exception:
            return False
    return secrets.compare_digest(password, PANEL_PASSWORD)


def filter_catalog_commands(commands: list[dict], q: str = "", category: str = "", status: str = ""):
    q = (q or "").strip().lower()
    category = (category or "").strip().lower()
    status = (status or "").strip().lower()
    result = []
    for cmd in commands:
        if q:
            hay = " ".join([
                str(cmd.get("slug") or ""),
                str(cmd.get("name") or ""),
                str(cmd.get("description") or ""),
                str(cmd.get("usage_hint") or ""),
            ]).lower()
            if q not in hay:
                continue
        if category and (cmd.get("category_slug") or "").lower() != category:
            continue
        if status == "active" and not cmd.get("is_active"):
            continue
        if status == "inactive" and cmd.get("is_active"):
            continue
        result.append(cmd)
    return result


def parse_bulk_command_rows(raw_text: str):
    rows = []
    errors = []
    for idx, raw_line in enumerate((raw_text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [part.strip() for part in line.split(";;")]
        if len(parts) < 5:
            errors.append(
                f"Línea {idx}: formato inválido. Usa slug;;nombre;;costo;;usage_hint;;info"
            )
            continue
        slug, name, cost_raw, usage_hint, description = parts[:5]
        status_raw = parts[5].strip().lower() if len(parts) >= 6 else "1"
        order_raw = parts[6].strip() if len(parts) >= 7 else "0"
        if not slug or not name:
            errors.append(f"Línea {idx}: slug y nombre son obligatorios")
            continue
        try:
            cost = max(0, int(cost_raw))
        except Exception:
            errors.append(f"Línea {idx}: costo inválido '{cost_raw}'")
            continue
        is_active = 0 if status_raw in {"0", "off", "inactive", "inactivo"} else 1
        try:
            sort_order = int(order_raw or 0)
        except Exception:
            errors.append(f"Línea {idx}: orden inválido '{order_raw}'")
            continue
        rows.append(
            {
                "slug": slug.lower(),
                "name": name,
                "cost": cost,
                "usage_hint": usage_hint,
                "description": description,
                "is_active": is_active,
                "sort_order": sort_order,
            }
        )
    return rows, errors


def build_panel_previews(settings: dict, buy_packages: list[dict], commands: list[dict]):
    owner = settings.get("BT_OWNER") or "OWNER"
    canal = settings.get("BT_CANAL") or "CANAL"
    grupo = settings.get("BT_GRUPO") or "GRUPO"
    owner_link = settings.get("OWNER_LINK") or "https://t.me/owner"
    grupo_link = settings.get("GRUPO_LINK") or "https://t.me/grupo"
    canal_link = settings.get("CANAL_LINK") or "https://t.me/canal"
    preview_start = (
        "👋 Hola, Usuario\n\n"
        "Comandos principales:\n/register\n/cmds\n/me\n/buy\n\n"
        f"Botones:\n[{grupo}] {grupo_link}\n[{canal}] {canal_link}\n[{owner}] {owner_link}"
    )

    grouped = get_buy_packages_grouped(active_only=True)
    buy_lines = []
    for kind in ("credits", "days"):
        for group in grouped[kind][:2]:
            buy_lines.append(f"{group['badge']} {group['title']} ({group['subtitle']})")
            buy_lines.extend(group["items"][:2])
    preview_buy = "✨ PLANES Y TARIFAS ✨\n\n" + ("\n".join(buy_lines[:8]) or "Sin paquetes activos.")

    active_commands = [c for c in commands if c.get("is_active")]
    sample = []
    for cmd in active_commands[:6]:
        sample.append(f"/{cmd['slug']} · {cmd['cost']} cr · {cmd.get('category_name') or 'Sin categoría'}")
    preview_cmds = "Menu principal de comandos\n\n" + ("\n".join(sample) or "Sin comandos activos.")
    return {
        "start": preview_start,
        "buy": preview_buy,
        "cmds": preview_cmds,
    }


def paginate_items(items: list[dict], page: int, per_page: int = 12):
    total = len(items)
    total_pages = max(1, math.ceil(total / per_page)) if total else 1
    page = max(1, min(page, total_pages))
    start = (page - 1) * per_page
    end = start + per_page
    return items[start:end], page, total_pages, total


def get_dashboard_snapshot():
    now = now_utc()
    cutoffs = {
        "today": now.replace(hour=0, minute=0, second=0, microsecond=0),
        "last_7": now - timedelta(days=7),
        "last_30": now - timedelta(days=30),
    }
    cutoff_iso = {key: value.isoformat() + "Z" for key, value in cutoffs.items()}
    data = {
        "usuarios": 0,
        "consultas": 0,
        "pendientes": 0,
        "ventas": 0,
        "periods": {
            "today": {"label": "Hoy", "consultas": 0, "ventas": 0, "solicitudes": 0},
            "last_7": {"label": "7 dias", "consultas": 0, "ventas": 0, "solicitudes": 0},
            "last_30": {"label": "30 dias", "consultas": 0, "ventas": 0, "solicitudes": 0},
        },
        "top_comandos": [],
        "top_usuarios": [],
        "top_vendedores": [],
        "consultas_por_dia": [],
        "ventas_por_dia": [],
        "usuarios_por_plan": [],
        "usuarios_por_estado": [],
        "solicitudes_por_estado": [],
    }
    try:
        conn = get_conn(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM usuarios")
        data["usuarios"] = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(plan), ''), 'SIN PLAN') plan, COUNT(*) total
            FROM usuarios
            GROUP BY COALESCE(NULLIF(TRIM(plan), ''), 'SIN PLAN')
            ORDER BY total DESC
            LIMIT 10
            """
        )
        data["usuarios_por_plan"] = [{"plan": r[0], "total": r[1]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(estado), ''), 'SIN ESTADO') estado, COUNT(*) total
            FROM usuarios
            GROUP BY COALESCE(NULLIF(TRIM(estado), ''), 'SIN ESTADO')
            ORDER BY total DESC
            """
        )
        data["usuarios_por_estado"] = [{"estado": r[0], "total": r[1]} for r in cur.fetchall()]
        conn.close()
    except Exception:
        pass
    try:
        conn = get_conn(HIST_DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM historial")
        data["consultas"] = cur.fetchone()[0]
        for key, start in cutoff_iso.items():
            cur.execute("SELECT COUNT(*) FROM historial WHERE fecha >= ?", (start,))
            data["periods"][key]["consultas"] = cur.fetchone()[0]
        cur.execute("SELECT consulta, COUNT(*) total FROM historial GROUP BY consulta ORDER BY total DESC LIMIT 10")
        data["top_comandos"] = [{"consulta": r[0], "total": r[1]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT ID_TG, COUNT(*) total
            FROM historial
            GROUP BY ID_TG
            ORDER BY total DESC
            LIMIT 10
            """
        )
        data["top_usuarios"] = [{"id_tg": r[0], "total": r[1]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT substr(fecha, 1, 10) dia, COUNT(*) total
            FROM historial
            WHERE fecha >= ?
            GROUP BY substr(fecha, 1, 10)
            ORDER BY dia DESC
            LIMIT 14
            """,
            (cutoff_iso["last_30"],),
        )
        data["consultas_por_dia"] = [{"dia": r[0], "total": r[1]} for r in cur.fetchall()]
        conn.close()
    except Exception:
        pass
    try:
        conn = get_conn(REQUESTS_DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM requests WHERE status = 'pending'")
        data["pendientes"] = cur.fetchone()[0]
        for key, start in cutoff_iso.items():
            cur.execute("SELECT COUNT(*) FROM requests WHERE created_at >= ?", (start,))
            data["periods"][key]["solicitudes"] = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(status), ''), 'sin estado') status, COUNT(*) total
            FROM requests
            GROUP BY COALESCE(NULLIF(TRIM(status), ''), 'sin estado')
            ORDER BY total DESC
            """
        )
        data["solicitudes_por_estado"] = [{"status": r[0], "total": r[1]} for r in cur.fetchall()]
        conn.close()
    except Exception:
        pass
    try:
        conn = get_conn(COMPRAS_DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM compras")
        data["ventas"] = cur.fetchone()[0]
        for key, start in cutoff_iso.items():
            cur.execute("SELECT COUNT(*) FROM compras WHERE FECHA >= ?", (start,))
            data["periods"][key]["ventas"] = cur.fetchone()[0]
        cur.execute(
            """
            SELECT COALESCE(NULLIF(TRIM(VENDEDOR), ''), 'SIN VENDEDOR') vendedor, COUNT(*) total
            FROM compras
            GROUP BY COALESCE(NULLIF(TRIM(VENDEDOR), ''), 'SIN VENDEDOR')
            ORDER BY total DESC
            LIMIT 10
            """
        )
        data["top_vendedores"] = [{"vendedor": r[0], "total": r[1]} for r in cur.fetchall()]
        cur.execute(
            """
            SELECT substr(FECHA, 1, 10) dia, COUNT(*) total
            FROM compras
            WHERE FECHA >= ?
            GROUP BY substr(FECHA, 1, 10)
            ORDER BY dia DESC
            LIMIT 14
            """,
            (cutoff_iso["last_30"],),
        )
        data["ventas_por_dia"] = [{"dia": r[0], "total": r[1]} for r in cur.fetchall()]
        conn.close()
    except Exception:
        pass
    return data


def get_request_items(status: str | None = None, limit: int = 50):
    items = []
    try:
        conn = get_conn(REQUESTS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        if status:
            cur.execute(
                """
                SELECT id, user_id, username, command, payload, status, admin_msg_id, cost,
                       created_at, resolved_at, resolved_by, resolution_note
                FROM requests
                WHERE status = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (status, limit),
            )
        else:
            cur.execute(
                """
                SELECT id, user_id, username, command, payload, status, admin_msg_id, cost,
                       created_at, resolved_at, resolved_by, resolution_note
                FROM requests
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
        items = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        items = []
    return items


def get_request_templates():
    items = []
    try:
        conn = get_conn(REQUESTS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT key, text, billable FROM request_templates ORDER BY key")
        items = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        items = []
    return items


def filter_request_items(items: list[dict], q: str = "", status: str = "", command: str = ""):
    q = (q or "").strip().lower()
    status = (status or "").strip().lower()
    command = (command or "").strip().lower()
    out = []
    for item in items:
        if status and (item.get("status") or "").lower() != status:
            continue
        if command and (item.get("command") or "").lower() != command:
            continue
        if q:
            hay = " ".join(
                [
                    str(item.get("id") or ""),
                    str(item.get("user_id") or ""),
                    str(item.get("username") or ""),
                    str(item.get("command") or ""),
                    str(item.get("payload") or ""),
                    str(item.get("resolution_note") or ""),
                ]
            ).lower()
            if q not in hay:
                continue
        out.append(item)
    return out


def get_admin_users(q: str = "", status: str = "", plan: str = "", limit: int = 200):
    q = (q or "").strip().lower()
    status = (status or "").strip().upper()
    plan = (plan or "").strip().upper()
    items = []
    try:
        conn = get_conn(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id_tg, rol_tg, creditos, plan, estado, fecha_caducidad, antispam,
                   register_web, register_wsp, user_web, number_wsp
            FROM usuarios
            ORDER BY id_tg DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        rows = []
    for row in rows:
        if q:
            hay = " ".join(
                [
                    str(row.get("id_tg") or ""),
                    str(row.get("rol_tg") or ""),
                    str(row.get("user_web") or ""),
                    str(row.get("number_wsp") or ""),
                    str(row.get("plan") or ""),
                    str(row.get("estado") or ""),
                ]
            ).lower()
            if q not in hay:
                continue
        if status and (row.get("estado") or "").upper() != status:
            continue
        if plan and (row.get("plan") or "").upper() != plan:
            continue
        items.append(row)
    return items


def get_vendor_sales_summary(q: str = "", limit: int = 200):
    q = (q or "").strip().lower()
    items = []
    try:
        conn = get_conn(COMPRAS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT VENDEDOR, COUNT(*) AS total_ventas, MAX(FECHA) AS ultima_venta
            FROM compras
            WHERE VENDEDOR IS NOT NULL AND TRIM(VENDEDOR) != ''
            GROUP BY VENDEDOR
            ORDER BY total_ventas DESC, ultima_venta DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        rows = []
    for row in rows:
        vendedor = str(row.get("VENDEDOR") or "").strip()
        if q and q not in vendedor.lower():
            continue
        items.append(
            {
                "vendedor": vendedor,
                "total_ventas": int(row.get("total_ventas") or 0),
                "ultima_venta": row.get("ultima_venta") or "",
            }
        )
    return items


def get_vendor_sales_detail(vendedor_id: str, limit: int = 100):
    vendedor_id = (vendedor_id or "").strip()
    if not vendedor_id:
        return []
    try:
        conn = get_conn(COMPRAS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ID, ID_TG, VENDEDOR, FECHA, COMPRO
            FROM compras
            WHERE VENDEDOR = ?
            ORDER BY FECHA DESC, ID DESC
            LIMIT ?
            """,
            (vendedor_id, limit),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def _date_bounds(date_from: str = "", date_to: str = ""):
    start = (date_from or "").strip()
    end = (date_to or "").strip()
    start_iso = f"{start}T00:00:00" if start else ""
    end_iso = f"{end}T23:59:59" if end else ""
    return start_iso, end_iso


PURCHASE_STATUSES = {"PENDIENTE", "PAGADA", "ENTREGADA", "CANCELADA"}
PANEL_ROLES = {"FUNDADOR", "CO-FUNDADOR", "SELLER", "SOPORTE"}
PANEL_SECTION_ACCESS = {
    "resumen": PANEL_ROLES,
    "buscar": PANEL_ROLES,
    "compras": {"FUNDADOR", "CO-FUNDADOR", "SELLER"},
    "vendedores": {"FUNDADOR", "CO-FUNDADOR", "SELLER"},
    "estadisticas": {"FUNDADOR", "CO-FUNDADOR", "SELLER"},
    "usuarios": {"FUNDADOR", "CO-FUNDADOR", "SOPORTE"},
    "usuario": {"FUNDADOR", "CO-FUNDADOR", "SELLER", "SOPORTE"},
    "historial": {"FUNDADOR", "CO-FUNDADOR", "SOPORTE"},
    "solicitudes": {"FUNDADOR", "CO-FUNDADOR", "SOPORTE"},
    "categorias": {"FUNDADOR", "CO-FUNDADOR"},
    "comandos": {"FUNDADOR", "CO-FUNDADOR"},
    "buy": {"FUNDADOR", "CO-FUNDADOR"},
    "ajustes": {"FUNDADOR", "CO-FUNDADOR"},
    "herramientas": {"FUNDADOR", "CO-FUNDADOR"},
    "sistema": {"FUNDADOR"},
}
PANEL_NAV_ITEMS = [
    ("resumen", "Resumen"),
    ("buscar", "Buscar"),
    ("categorias", "Categorías"),
    ("comandos", "Comandos"),
    ("buy", "Paquetes /buy"),
    ("usuarios", "Usuarios"),
    ("compras", "Compras"),
    ("historial", "Historial"),
    ("vendedores", "Vendedores"),
    ("ajustes", "Ajustes Visuales"),
    ("solicitudes", "Solicitudes"),
    ("herramientas", "Herramientas"),
    ("sistema", "Sistema"),
    ("estadisticas", "Estadísticas"),
]


def get_admin_purchases(user_id: str = "", vendor_id: str = "", date_from: str = "", date_to: str = "", kind: str = "", status: str = "", limit: int = 300):
    clauses = []
    params = []
    user_id = (user_id or "").strip()
    vendor_id = (vendor_id or "").strip()
    kind = (kind or "").strip().lower()
    status = (status or "").strip().upper()
    start_iso, end_iso = _date_bounds(date_from, date_to)
    if user_id:
        clauses.append("ID_TG LIKE ?")
        params.append(f"%{user_id}%")
    if vendor_id:
        clauses.append("VENDEDOR LIKE ?")
        params.append(f"%{vendor_id}%")
    if start_iso:
        clauses.append("FECHA >= ?")
        params.append(start_iso)
    if end_iso:
        clauses.append("FECHA <= ?")
        params.append(end_iso)
    if kind == "credits":
        clauses.append("UPPER(COMPRO) LIKE '%CREDIT%'")
    elif kind == "days":
        clauses.append("(UPPER(COMPRO) LIKE '%DIA%' OR UPPER(COMPRO) LIKE '%DAY%')")
    if status in PURCHASE_STATUSES:
        clauses.append("UPPER(COALESCE(ESTADO, 'ENTREGADA')) = ?")
        params.append(status)
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    try:
        conn = get_conn(COMPRAS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT ID, ID_TG, VENDEDOR, FECHA, COMPRO,
                   COALESCE(ESTADO, 'ENTREGADA') AS ESTADO,
                   COALESCE(NOTAS, '') AS NOTAS,
                   COALESCE(COMPROBANTE, '') AS COMPROBANTE
            FROM compras
            {where}
            ORDER BY FECHA DESC, ID DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        rows = []
    return rows


def get_admin_history(user_id: str = "", command: str = "", platform: str = "", date_from: str = "", date_to: str = "", q: str = "", limit: int = 300):
    clauses = []
    params = []
    user_id = (user_id or "").strip()
    command = (command or "").strip().lower()
    platform = (platform or "").strip().upper()
    q = (q or "").strip().lower()
    start_iso, end_iso = _date_bounds(date_from, date_to)
    if user_id:
        clauses.append("ID_TG LIKE ?")
        params.append(f"%{user_id}%")
    if command:
        clauses.append("LOWER(consulta) = ?")
        params.append(command)
    if platform:
        clauses.append("plataforma = ?")
        params.append(platform)
    if start_iso:
        clauses.append("fecha >= ?")
        params.append(start_iso)
    if end_iso:
        clauses.append("fecha <= ?")
        params.append(end_iso)
    if q:
        clauses.append("(LOWER(valor) LIKE ? OR LOWER(consulta) LIKE ? OR LOWER(ID_TG) LIKE ?)")
        params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
    where = "WHERE " + " AND ".join(clauses) if clauses else ""
    try:
        conn = get_conn(HIST_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT ID, ID_TG, consulta, valor, fecha, plataforma
            FROM historial
            {where}
            ORDER BY fecha DESC, ID DESC
            LIMIT ?
            """,
            (*params, limit),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        rows = []
    return rows


def get_user_request_items(user_id: str, limit: int = 80):
    user_id = (user_id or "").strip()
    if not user_id:
        return []
    try:
        conn = get_conn(REQUESTS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, user_id, username, command, payload, status, cost, charged,
                   delivery_count, created_at, resolved_at, resolved_by, resolution_note
            FROM requests
            WHERE CAST(user_id AS TEXT) = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_user_profile_snapshot(user_id: str):
    user_id = (user_id or "").strip()
    if not user_id:
        return {"user": None, "purchases": [], "history": [], "requests": []}
    row = get_user_by_id(user_id)
    return {
        "user": dict(row) if row else None,
        "purchases": get_admin_purchases(user_id=user_id, limit=80),
        "history": get_admin_history(user_id=user_id, limit=80),
        "requests": get_user_request_items(user_id, limit=80),
    }


def get_global_search_results(q: str, limit: int = 25):
    q = (q or "").strip()
    results = {"q": q, "users": [], "purchases": [], "history": [], "requests": []}
    if not q:
        return results
    like = f"%{q.lower()}%"
    try:
        conn = get_conn(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id_tg, rol_tg, creditos, plan, estado, fecha_caducidad, antispam,
                   register_web, register_wsp, user_web, number_wsp
            FROM usuarios
            WHERE LOWER(id_tg) LIKE ?
               OR LOWER(COALESCE(rol_tg, '')) LIKE ?
               OR LOWER(COALESCE(plan, '')) LIKE ?
               OR LOWER(COALESCE(estado, '')) LIKE ?
               OR LOWER(COALESCE(user_web, '')) LIKE ?
               OR LOWER(COALESCE(number_wsp, '')) LIKE ?
            ORDER BY id_tg DESC
            LIMIT ?
            """,
            (like, like, like, like, like, like, limit),
        )
        results["users"] = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        pass
    try:
        conn = get_conn(COMPRAS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ID, ID_TG, VENDEDOR, FECHA, COMPRO,
                   COALESCE(ESTADO, 'ENTREGADA') AS ESTADO,
                   COALESCE(NOTAS, '') AS NOTAS,
                   COALESCE(COMPROBANTE, '') AS COMPROBANTE
            FROM compras
            WHERE LOWER(COALESCE(ID_TG, '')) LIKE ?
               OR LOWER(COALESCE(VENDEDOR, '')) LIKE ?
               OR LOWER(COALESCE(COMPRO, '')) LIKE ?
               OR LOWER(COALESCE(ESTADO, '')) LIKE ?
               OR LOWER(COALESCE(NOTAS, '')) LIKE ?
            ORDER BY FECHA DESC, ID DESC
            LIMIT ?
            """,
            (like, like, like, like, like, limit),
        )
        results["purchases"] = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        pass
    try:
        conn = get_conn(HIST_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT ID, ID_TG, consulta, valor, fecha, plataforma
            FROM historial
            WHERE LOWER(COALESCE(ID_TG, '')) LIKE ?
               OR LOWER(COALESCE(consulta, '')) LIKE ?
               OR LOWER(COALESCE(valor, '')) LIKE ?
               OR LOWER(COALESCE(plataforma, '')) LIKE ?
            ORDER BY fecha DESC, ID DESC
            LIMIT ?
            """,
            (like, like, like, like, limit),
        )
        results["history"] = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        pass
    try:
        conn = get_conn(REQUESTS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, user_id, username, command, payload, status, cost,
                   created_at, resolved_at, resolved_by, resolution_note
            FROM requests
            WHERE LOWER(CAST(user_id AS TEXT)) LIKE ?
               OR LOWER(COALESCE(username, '')) LIKE ?
               OR LOWER(COALESCE(command, '')) LIKE ?
               OR LOWER(COALESCE(payload, '')) LIKE ?
               OR LOWER(COALESCE(status, '')) LIKE ?
               OR LOWER(COALESCE(resolution_note, '')) LIKE ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (like, like, like, like, like, like, limit),
        )
        results["requests"] = [dict(row) for row in cur.fetchall()]
        conn.close()
    except Exception:
        pass
    return results


def get_storage_snapshot():
    dbs = [
        ("usuarios", DB_PATH),
        ("historial", HIST_DB_PATH),
        ("compras", COMPRAS_DB_PATH),
        ("keys", KEYS_DB_PATH),
        ("requests", REQUESTS_DB_PATH),
    ]
    data_dir = get_data_dir()
    items = []
    for name, path in dbs:
        exists = os.path.exists(path)
        items.append(
            {
                "name": name,
                "path": path,
                "exists": exists,
                "size": os.path.getsize(path) if exists else 0,
                "in_data_dir": os.path.abspath(path).startswith(os.path.abspath(data_dir)),
            }
        )
    return {
        "data_dir": data_dir,
        "env_data_dir": os.environ.get("SPIDERSYN_DATA_DIR") or "",
        "railway_mount": os.environ.get("RAILWAY_VOLUME_MOUNT_PATH") or "",
        "items": items,
    }


def backups_dir() -> str:
    path = os.path.join(get_data_dir(), "backups")
    os.makedirs(path, exist_ok=True)
    return path


def get_daily_backups(limit: int = 20):
    try:
        folder = backups_dir()
        items = []
        for name in os.listdir(folder):
            if not (name.startswith("spidersyn-auto-") and name.endswith(".zip")):
                continue
            path = os.path.join(folder, name)
            if not os.path.isfile(path):
                continue
            items.append(
                {
                    "name": name,
                    "path": path,
                    "size": os.path.getsize(path),
                    "created_at": datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="seconds"),
                }
            )
        items.sort(key=lambda row: row["name"], reverse=True)
        return items[:limit]
    except Exception:
        return []


def create_db_backup_file(path: str):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for item in get_storage_snapshot()["items"]:
            if item["exists"]:
                zf.write(item["path"], arcname=os.path.basename(item["path"]))


def ensure_daily_backup(force: bool = False):
    folder = backups_dir()
    today = now_utc().strftime("%Y%m%d")
    backup_name = f"spidersyn-auto-{today}.zip"
    backup_path = os.path.join(folder, backup_name)
    if force or not os.path.exists(backup_path):
        tmp_path = backup_path + ".tmp"
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            create_db_backup_file(tmp_path)
            if force and os.path.exists(backup_path):
                os.remove(backup_path)
            os.replace(tmp_path, backup_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
        log_audit_event("backup.auto", backup_name, f"size={os.path.getsize(backup_path)}")

    backups = get_daily_backups(limit=100)
    for old in backups[7:]:
        try:
            os.remove(old["path"])
        except Exception:
            pass
    return backup_path


def get_history_cleanup_preview():
    preview = []
    now = now_utc()
    for days in (30, 60, 90, 180):
        cutoff = (now - timedelta(days=days)).replace(microsecond=0).isoformat() + "Z"
        total = 0
        try:
            conn = get_conn(HIST_DB_PATH)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM historial WHERE fecha < ?", (cutoff,))
            total = int(cur.fetchone()[0] or 0)
            conn.close()
        except Exception:
            total = 0
        preview.append({"days": days, "cutoff": cutoff, "total": total})
    return preview


def get_error_logs(limit: int = 50):
    try:
        conn = get_conn(REQUESTS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS error_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT,
                method TEXT,
                message TEXT,
                traceback TEXT,
                created_at TEXT
            )
            """
        )
        cur.execute(
            """
            SELECT id, path, method, message, traceback, created_at
            FROM error_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def get_audit_logs(limit: int = 80):
    try:
        conn = get_conn(REQUESTS_DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                actor TEXT,
                ip TEXT,
                action TEXT,
                target TEXT,
                details TEXT,
                created_at TEXT
            )
            """
        )
        cur.execute(
            """
            SELECT id, actor, ip, action, target, details, created_at
            FROM audit_logs
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def init_panel_accounts_db():
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS panel_accounts (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            role TEXT NOT NULL DEFAULT 'SOPORTE',
            is_active INTEGER DEFAULT 1,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()
    conn.close()


def get_panel_account(username: str):
    username = (username or "").strip()
    if not username:
        return None
    try:
        init_panel_accounts_db()
        conn = get_conn(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            "SELECT username, password_hash, role, is_active, created_at, updated_at FROM panel_accounts WHERE username = ?",
            (username,),
        )
        row = cur.fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


def get_panel_accounts():
    try:
        init_panel_accounts_db()
        conn = get_conn(DB_PATH)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT username, role, is_active, created_at, updated_at
            FROM panel_accounts
            ORDER BY role ASC, username ASC
            """
        )
        rows = [dict(row) for row in cur.fetchall()]
        conn.close()
        return rows
    except Exception:
        return []


def _csv_response(filename: str, rows: list[dict], fieldnames: list[str]):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    body = out.getvalue()
    return Response(
        body,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _json_download_response(filename: str, payload):
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        body,
        mimetype="application/json; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _is_panel_logged_in() -> bool:
    return bool(session.get("panel_auth"))


def require_panel_login():
    if not _panel_request_allowed():
        return jsonify({"status": "error", "message": "Panel solo disponible localmente"}), 403
    if not _is_panel_logged_in():
        return redirect(url_for("panel_login", next=request.full_path if request.query_string else request.path))
    return None


def panel_current_role() -> str:
    return (session.get("panel_role") or "FUNDADOR").strip().upper()


def panel_can_access_section(section: str, role: str | None = None) -> bool:
    role = (role or panel_current_role()).strip().upper()
    return role in PANEL_SECTION_ACCESS.get(section, {"FUNDADOR"})


def panel_nav_items_for_role(role: str | None = None):
    role = (role or panel_current_role()).strip().upper()
    return [{"section": section, "label": label} for section, label in PANEL_NAV_ITEMS if panel_can_access_section(section, role)]


def require_panel_roles(*roles: str):
    gate = require_panel_login()
    if gate:
        return gate
    allowed = {role.strip().upper() for role in roles}
    if panel_current_role() not in allowed:
        return redirect(url_for("admin_panel", section="resumen", flash="No tienes permiso para esa acción."))
    return None


def require_panel_owner():
    gate = require_panel_login()
    if gate:
        return gate
    if panel_current_role() != "FUNDADOR":
        return redirect(url_for("admin_panel", section="sistema", flash="Solo el FUNDADOR puede hacer esa acción."))
    return None

def init_hist_db():
    conn = get_conn(HIST_DB_PATH)
    cur = conn.cursor()
    # ¿Existe la tabla?
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='historial';")
    exists = cur.fetchone() is not None

    if not exists:
        # Crear con el esquema nuevo (ID autoincremental y CHECK de plataforma)
        cur.execute(
            """
            CREATE TABLE historial (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                ID_TG TEXT,
                consulta TEXT,
                valor TEXT,
                fecha TEXT,
                plataforma TEXT NOT NULL CHECK (plataforma IN ('TG','WEB','WSP'))
            );
            """
        )
        conn.commit()
        conn.close()
        return

    # Si existe, revisamos columnas; si estaba con ID_TG como PK, migramos.
    cur.execute("PRAGMA table_info(historial);")
    cols = [(r[1], r[5]) for r in cur.fetchall()]  # (name, pk)
    col_names = [c[0] for c in cols]
    # Esquema deseado:
    desired = ["ID", "ID_TG", "consulta", "valor", "fecha", "plataforma"]

    def needs_migration() -> bool:
        # Si no coincide EXACTO o si ID_TG es PK, migramos
        if col_names == desired and any(pk == 1 for (name, pk) in cols if name == "ID"):
            return False
        # Caso típico viejo: PK en ID_TG
        if "ID_TG" in col_names and any(pk == 1 for (name, pk) in cols if name == "ID_TG"):
            return True
        # Cualquier otra diferencia de esquema -> migrar por seguridad
        return True

    if needs_migration():
        # Crear tabla nueva, copiar datos, renombrar
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS historial_new (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                ID_TG TEXT,
                consulta TEXT,
                valor TEXT,
                fecha TEXT,
                plataforma TEXT NOT NULL CHECK (plataforma IN ('TG','WEB','WSP'))
            );
            """
        )
        # Copiar lo que exista, normalizando plataforma a 'TG' si no cumple
        if "plataforma" in col_names:
            cur.execute(
                """
                INSERT INTO historial_new (ID_TG, consulta, valor, fecha, plataforma)
                SELECT 
                    COALESCE(ID_TG, ''), 
                    COALESCE(consulta, ''), 
                    COALESCE(valor, ''), 
                    COALESCE(fecha, ''), 
                    CASE WHEN plataforma IN ('TG','WEB','WSP') THEN plataforma ELSE 'TG' END
                FROM historial;
                """
            )
        else:
            # Tabla antigua sin 'plataforma'
            cur.execute(
                """
                INSERT INTO historial_new (ID_TG, consulta, valor, fecha, plataforma)
                SELECT 
                    COALESCE(ID_TG, ''), 
                    COALESCE(consulta, ''), 
                    COALESCE(valor, ''), 
                    COALESCE(fecha, ''), 
                    'TG'
                FROM historial;
                """
            )
        cur.execute("DROP TABLE historial;")
        cur.execute("ALTER TABLE historial_new RENAME TO historial;")
        conn.commit()

    conn.close()

def init_compras_db():
    conn = get_conn(COMPRAS_DB_PATH)
    cur = conn.cursor()

    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='compras';")
    exists = cur.fetchone() is not None

    recreate = False
    cols = []
    if exists:
        cur.execute("PRAGMA table_info(compras);")
        cols = [r[1] for r in cur.fetchall()]
        desired = ["ID", "ID_TG", "VENDEDOR", "FECHA", "COMPRO", "ESTADO", "NOTAS", "COMPROBANTE"]
        if cols != desired:
            recreate = True
    else:
        recreate = True

    if recreate:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS compras_new (
                ID INTEGER PRIMARY KEY AUTOINCREMENT,
                ID_TG TEXT,
                VENDEDOR TEXT,
                FECHA TEXT,
                COMPRO TEXT,
                ESTADO TEXT DEFAULT 'ENTREGADA',
                NOTAS TEXT DEFAULT '',
                COMPROBANTE TEXT DEFAULT ''
            );
            """
        )
        if exists:
            old_cols = set(cols)
            select_id = "ID_TG" if "ID_TG" in old_cols else "''"
            select_vendedor = "VENDEDOR" if "VENDEDOR" in old_cols else "''"
            select_fecha = "FECHA" if "FECHA" in old_cols else "''"
            select_compro = "COMPRO" if "COMPRO" in old_cols else "''"
            select_estado = "ESTADO" if "ESTADO" in old_cols else "'ENTREGADA'"
            select_notas = "NOTAS" if "NOTAS" in old_cols else "''"
            select_comprobante = "COMPROBANTE" if "COMPROBANTE" in old_cols else "''"
            cur.execute(
                f"""
                INSERT INTO compras_new (ID_TG, VENDEDOR, FECHA, COMPRO, ESTADO, NOTAS, COMPROBANTE)
                SELECT {select_id}, {select_vendedor}, {select_fecha}, {select_compro},
                       COALESCE(NULLIF(TRIM({select_estado}), ''), 'ENTREGADA'),
                       COALESCE({select_notas}, ''),
                       COALESCE({select_comprobante}, '')
                FROM compras
                """
            )
            cur.execute("DROP TABLE compras;")
            cur.execute("ALTER TABLE compras_new RENAME TO compras;")
        else:
            cur.execute("ALTER TABLE compras_new RENAME TO compras;")
        conn.commit()

    conn.close()

# -------------------------
# DB helpers
# -------------------------
def get_user_by_id(id_tg):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE id_tg = ?", (id_tg,))
    row = cur.fetchone()
    conn.close()
    return row

def get_user_by_web_token(token):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE token_api_web = ?", (token,))
    row = cur.fetchone()
    conn.close()
    return row

def update_user_profile(user_id, credits, days_valid):
    """Actualiza los créditos y días válidos del usuario en su perfil en multplatatforma.db."""
    conn = sqlite3.connect(DB_PATH)  # Conectar a la base de datos de clientes
    cursor = conn.cursor()

    # Actualizar los créditos y días válidos del usuario
    cursor.execute("""
        UPDATE usuarios
        SET creditos = creditos + ?, fecha_caducidad = ?
        WHERE id_tg = ?
    """, (credits, days_valid, user_id))

    conn.commit()
    conn.close()

def get_user_by_wsp_token(token):
    conn = get_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM usuarios WHERE token_api_wsp = ?", (token,))
    row = cur.fetchone()
    conn.close()
    return row

def create_user(id_tg):
    ts = now_iso()
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO usuarios (
            id_tg, rol_tg, fecha_register_tg,
            creditos, plan, estado, fecha_caducidad,
            register_web, register_wsp,
            token_api_web, user_web, pass_web, rol_web, fecha_register_web,
            token_api_wsp, number_wsp, rol_wsp, fecha_register_wsp,
            antispam
        ) VALUES (
            ?, 'FREE', ?,
            5, 'FREE', 'ACTIVO', NULL,
            0, 0,
            NULL, NULL, NULL, 'FREE', NULL,
            NULL, NULL, 'FREE', NULL,
            60
        )
        """,
        (id_tg, ts),
    )
    conn.commit()
    conn.close()

def row_info_payload(row: sqlite3.Row):
    return {
        "ID_TG": row["id_tg"],
        "ROL_TG": row["rol_tg"],
        "FECHA_REGISTER_TG": row["fecha_register_tg"],
        "CREDITOS": row["creditos"],
        "PLAN": row["plan"],
        "ESTADO": row["estado"],
        "FECHA DE CADUCIDAD": row["fecha_caducidad"],
        "REGISTER_WEB": bool(row["register_web"]),
        "REGISTER_WSP": bool(row["register_wsp"]),
        "ROL_WEB": row["rol_web"],
        "ROL_WSP": row["rol_wsp"],
        "ANTISPAM": row["antispam"],
    }

# -------------------------
# Endpoints existentes resumidos (con mensajes)
# -------------------------

@app.route("/register", methods=["GET"])
def register():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request.args.get("ID_TG")
    if not id_tg:
        return jsonify({"status": "error", "exists": False, "message": "Falta el parámetro ID_TG"}), 400
    row = get_user_by_id(id_tg)
    if row:
        return jsonify({"status": "error", "exists": True, "message": "El usuario ya está registrado"}), 423
    create_user(id_tg)
    return jsonify({"status": "ok", "exists": False, "message": "Usuario registrado correctamente"}), 200

@app.route("/tg_info", methods=["GET"])
def tg_info():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    if not id_tg:
        return jsonify({"status": "error", "message": "Falta el parámetro ID_TG"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    data = row_info_payload(row)
    return jsonify({"status": "ok", "message": "Información obtenida correctamente", "data": data}), 200

@app.route("/create_token_web", methods=["POST"])
def create_token_web():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    if not id_tg:
        return jsonify({"status": "error", "message": "Falta el parámetro ID_TG"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    if row["token_api_web"] is not None:
        return jsonify({"status": "error", "message": "Ya existe un token WEB para este usuario"}), 423
    token = generate_unique_token()
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET token_api_web = ? WHERE id_tg = ?", (token, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": "Token WEB creado correctamente"}), 200

@app.route("/create_token_wsp", methods=["POST"])
def create_token_wsp():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    if not id_tg:
        return jsonify({"status": "error", "message": "Falta el parámetro ID_TG"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    if row["token_api_wsp"] is not None:
        return jsonify({"status": "error", "message": "Ya existe un token WSP para este usuario"}), 423
    token = generate_unique_token()
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET token_api_wsp = ? WHERE id_tg = ?", (token, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": "Token WSP creado correctamente"}), 200

@app.route("/info_token_web", methods=["POST"])
def info_token_web():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    if not id_tg:
        return jsonify({"status": "error", "message": "Falta el parámetro ID_TG"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    token = row["token_api_web"]
    if not token:
        return jsonify({"status": "error", "message": "Token WEB no encontrado para este usuario"}), 404
    return jsonify({"status": "ok", "message": "Token WEB obtenido correctamente", "TOKEN_API_WEB": token}), 200

@app.route("/info_token_wsp", methods=["POST"])
def info_token_wsp():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    if not id_tg:
        return jsonify({"status": "error", "message": "Falta el parámetro ID_TG"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    token = row["token_api_wsp"]
    if not token:
        return jsonify({"status": "error", "message": "Token WSP no encontrado para este usuario"}), 404
    return jsonify({"status": "ok", "message": "Token WSP obtenido correctamente", "TOKEN_API_WSP": token}), 200

@app.route("/info_web", methods=["GET"])
def info_web():
    token = request.args.get("token")
    if not token:
        return jsonify({"status": "error", "message": "Falta el parámetro token"}), 400
    row = get_user_by_web_token(token)
    if not row:
        return jsonify({"status": "error", "message": "Token WEB no válido o usuario no encontrado"}), 404
    data = {
        "TOKEN_API_WEB": token,
        "ID_TG": row["id_tg"],
        "CREDITOS": row["creditos"],
        "PLAN": row["plan"],
        "ESTADO": row["estado"],
        "FECHA DE CADUCIDAD": row["fecha_caducidad"],
        "REGISTER_WEB": bool(row["register_web"]),
        "REGISTER_WSP": bool(row["register_wsp"]),
        "ROL_WEB": row["rol_web"],
        "FECHA_REGISTER_WEB": row["fecha_register_web"],
        "ANTISPAM": row["antispam"],
    }
    return jsonify({"status": "ok", "message": "Información WEB obtenida correctamente", "data": data}), 200

@app.route("/info_wsp", methods=["GET"])
def info_wsp():
    token = request.args.get("token")
    if not token:
        return jsonify({"status": "error", "message": "Falta el parámetro token"}), 400
    row = get_user_by_wsp_token(token)
    if not row:
        return jsonify({"status": "error", "message": "Token WSP no válido o usuario no encontrado"}), 404
    data = {
        "TOKEN_API_WSP": token,
        "ID_TG": row["id_tg"],
        "CREDITOS": row["creditos"],
        "PLAN": row["plan"],
        "ESTADO": row["estado"],
        "FECHA DE CADUCIDAD": row["fecha_caducidad"],
        "REGISTER_WEB": bool(row["register_web"]),
        "REGISTER_WSP": bool(row["register_wsp"]),
        "NUMBER_WSP": row["number_wsp"],
        "ROL_WSP": row["rol_wsp"],
        "FECHA_REGISTER_WSP": row["fecha_register_wsp"],
        "ANTISPAM": row["antispam"],
    }
    return jsonify({"status": "ok", "message": "Información WSP obtenida correctamente", "data": data}), 200

# -------------------------
# Activación WEB/WSP
# -------------------------
@app.route("/activate_wsp", methods=["POST"])
def activate_wsp():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    token = request_value("token")
    number_wsp = request_value("number_wsp")
    if not token or not number_wsp:
        return jsonify({"status": "error", "message": "Faltan parámetros: token y number_wsp son requeridos"}), 400
    row = get_user_by_wsp_token(token)
    if not row:
        return jsonify({"status": "error", "message": "Token WSP no válido o usuario no encontrado"}), 404
    if bool(row["register_wsp"]):
        return jsonify({"status": "error", "message": "WSP ya se encuentra activado para este usuario"}), 423
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET register_wsp = 1, number_wsp = ?, fecha_register_wsp = ? WHERE token_api_wsp = ?",
                (number_wsp, now_iso(), token))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": "WSP activado correctamente"}), 200

@app.route("/activate_web", methods=["POST"])
def activate_web():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    token = request_value("token")
    user = request_value("user")
    password = request_value("pass")
    if not token or not user or not password:
        return jsonify({"status": "error", "message": "Faltan parámetros: token, user y pass son requeridos"}), 400
    row = get_user_by_web_token(token)
    if not row:
        return jsonify({"status": "error", "message": "Token WEB no válido o usuario no encontrado"}), 404
    if bool(row["register_web"]):
        return jsonify({"status": "error", "message": "WEB ya se encuentra activado para este usuario"}), 423
    conn = get_conn(); cur = conn.cursor()
    password_hash = generate_password_hash(password)
    cur.execute("UPDATE usuarios SET register_web = 1, user_web = ?, pass_web = ?, fecha_register_web = ? WHERE token_api_web = ?",
                (user, password_hash, now_iso(), token))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": "WEB activado correctamente"}), 200

# -------------------------
# Créditos (/cred) y Suscripción (/sub)
# -------------------------
@app.route("/cred", methods=["POST"])
def cred():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    oper = (request_value("operacion") or "").strip().lower()
    cantidad_raw = request_value("cantidad")
    if not id_tg or not oper or cantidad_raw is None:
        return jsonify({"status": "error", "message": "Parámetros requeridos: ID_TG, operacion, cantidad"}), 400
    try:
        cantidad = int(cantidad_raw)
        if cantidad < 0:
            raise ValueError()
    except ValueError:
        return jsonify({"status": "error", "message": "cantidad debe ser un entero no negativo"}), 400

    if oper not in ("igualar", "sumar", "restar"):
        return jsonify({"status": "error", "message": "operacion debe ser igualar, sumar o restar"}), 400

    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404

    current = int(row["creditos"] or 0)
    if oper == "igualar":
        new_val = cantidad
    elif oper == "sumar":
        new_val = current + cantidad
    else:  # restar
        new_val = max(0, current - cantidad)

    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET creditos = ? WHERE id_tg = ?", (new_val, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": f"Créditos {oper} => {new_val}", "CREDITOS": new_val}), 200

@app.route("/sub", methods=["POST"])
def sub():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    oper = (request_value("operacion") or "").strip().lower()
    cantidad_raw = request_value("cantidad")
    if not id_tg or not oper or cantidad_raw is None:
        return jsonify({"status": "error", "message": "Parámetros requeridos: ID_TG, operacion, cantidad"}), 400
    try:
        dias = int(cantidad_raw)
        if dias < 0:
            raise ValueError()
    except ValueError:
        return jsonify({"status": "error", "message": "cantidad debe ser un entero no negativo (días)"}), 400

    if oper not in ("igualar", "sumar", "restar"):
        return jsonify({"status": "error", "message": "operacion debe ser igualar, sumar o restar"}), 400

    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404

    now = now_utc()
    fcad = row["fecha_caducidad"]
    # Reglas especiales:
    if fcad is None or str(fcad).strip() == "":
        if oper in ("sumar", "igualar"):
            new_dt = now + timedelta(days=dias)
        else:  # restar desde NULL no tiene sentido
            return jsonify({"status": "error", "message": "No se puede restar días: la fecha de caducidad está vacía"}), 400
    else:
        try:
            current_dt = parse_iso(fcad)
        except Exception:
            current_dt = now  # si hay formato inesperado, normalizamos
        if current_dt < now:
            # Si ya venció: igualar a ahora + dias (sin importar la operación)
            new_dt = now + timedelta(days=dias)
        else:
            if oper == "igualar":
                new_dt = now + timedelta(days=dias)
            elif oper == "sumar":
                new_dt = current_dt + timedelta(days=dias)
            else:  # restar
                new_dt = current_dt - timedelta(days=dias)

    new_iso = new_dt.replace(microsecond=0).isoformat() + "Z"
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET fecha_caducidad = ? WHERE id_tg = ?", (new_iso, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": f"Fecha de caducidad {oper}", "FECHA_DE_CADUCIDAD": new_iso}), 200

# -------------------------
# Plan y Roles
# -------------------------
PLANES_VALIDOS = {"PREMIUM", "STANDARD", "BASICO", "FREE"}
ROLES_VALIDOS = {"FREE", "CLIENTE", "SELLER", "CO-FUNDADOR", "FUNDADOR"}

@app.route("/plan", methods=["POST"])
def set_plan():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    plan = (request_value("plan") or "").upper()
    if not id_tg or not plan:
        return jsonify({"status": "error", "message": "Parámetros requeridos: ID_TG, plan"}), 400
    if plan not in PLANES_VALIDOS:
        return jsonify({"status": "error", "message": f"plan inválido. Opciones: {', '.join(PLANES_VALIDOS)}"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET plan = ? WHERE id_tg = ?", (plan, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": f"Plan actualizado a {plan}"}), 200

@app.route("/rol_wsp", methods=["POST"])
def set_rol_wsp():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    rol = (request_value("rol") or "").upper()
    if not id_tg or not rol:
        return jsonify({"status": "error", "message": "Parámetros requeridos: ID_TG, rol"}), 400
    if rol not in ROLES_VALIDOS:
        return jsonify({"status": "error", "message": f"rol inválido. Opciones: {', '.join(ROLES_VALIDOS)}"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET rol_wsp = ? WHERE id_tg = ?", (rol, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": f"ROL_WSP actualizado a {rol}"}), 200

@app.route("/rol_web", methods=["POST"])
def set_rol_web():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    rol = (request_value("rol") or "").upper()
    if not id_tg or not rol:
        return jsonify({"status": "error", "message": "Parámetros requeridos: ID_TG, rol"}), 400
    if rol not in ROLES_VALIDOS:
        return jsonify({"status": "error", "message": f"rol inválido. Opciones: {', '.join(ROLES_VALIDOS)}"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET rol_web = ? WHERE id_tg = ?", (rol, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": f"ROL_WEB actualizado a {rol}"}), 200

@app.route("/rol_tg", methods=["POST"])
def set_rol_tg():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    rol = (request_value("rol") or "").upper()
    if not id_tg or not rol:
        return jsonify({"status": "error", "message": "Parámetros requeridos: ID_TG, rol"}), 400
    if rol not in ROLES_VALIDOS:
        return jsonify({"status": "error", "message": f"rol inválido. Opciones: {', '.join(ROLES_VALIDOS)}"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET rol_tg = ? WHERE id_tg = ?", (rol, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": f"ROL_TG actualizado a {rol}"}), 200

# -------------------------
# Antispam
# -------------------------
@app.route("/antispam", methods=["POST"])
def set_antispam():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    val_raw = request_value("valor")
    if not id_tg or val_raw is None:
        return jsonify({"status": "error", "message": "Parámetros requeridos: ID_TG, valor"}), 400
    try:
        val = int(val_raw)
        if val < 0:
            raise ValueError()
    except ValueError:
        return jsonify({"status": "error", "message": "valor debe ser un entero no negativo"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET antispam = ? WHERE id_tg = ?", (val, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": f"ANTISPAM actualizado a {val}", "ANTISPAM": val}), 200

# -------------------------
# Compras e Historial
# -------------------------
@app.route("/compras", methods=["POST"])
def compras():
    # Ahora ID_TG es el identificador del cliente
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    id_vendedor = request_value("ID_VENDEDOR")
    cantidad = request_value("CANTIDAD")  # p.ej. "DIAS:30" o "CREDITOS:100" o un número

    if not id_tg or not id_vendedor or not cantidad:
        return jsonify({
            "status": "error",
            "message": "Parámetros requeridos: ID_TG, ID_VENDEDOR, CANTIDAD"
        }), 400

    # Validar que el cliente exista en usuarios
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario (ID_TG) no encontrado"}), 404

    fecha = now_iso()  # fecha automática

    # Guardar cada compra como evento independiente.
    conn = get_conn(COMPRAS_DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO compras (ID_TG, VENDEDOR, FECHA, COMPRO)
        VALUES (?, ?, ?, ?)
        """,
        (id_tg, id_vendedor, fecha, cantidad)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "message": "Compra registrada",
        "FECHA": fecha
    }), 200

@app.route("/historial", methods=["POST"])
def historial():
    # Requeridos
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    consulta = request_value("CONSULTA")
    valor = request_value("VALOR")
    plataforma = (request_value("PLATAFORMA") or "").upper().strip()

    if not id_tg or not consulta or not valor or not plataforma:
        return jsonify({
            "status": "error",
            "message": "Parámetros requeridos: ID_TG, CONSULTA, VALOR, PLATAFORMA"
        }), 400

    if plataforma not in {"TG", "WEB", "WSP"}:
        return jsonify({
            "status": "error",
            "message": "PLATAFORMA inválida. Valores permitidos: TG, WEB, WSP"
        }), 400

    # Validar que el usuario exista
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario (ID_TG) no encontrado"}), 404

    fecha = now_iso()  # fecha automática en servidor

    # INSERT simple (NO REPLACE) para no sobrescribir registros anteriores
    conn = get_conn(HIST_DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO historial (ID_TG, consulta, valor, fecha, plataforma) VALUES (?, ?, ?, ?, ?)",
        (id_tg, consulta, valor, fecha, plataforma)
    )
    conn.commit()
    conn.close()

    return jsonify({
        "status": "ok",
        "message": "Historial registrado",
        "FECHA": fecha
    }), 200


# -------------------------
# Reset y Estado
# -------------------------
@app.route("/reset", methods=["GET"])
def reset_user():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request.args.get("ID_TG")
    if not id_tg:
        return jsonify({"status": "error", "message": "Falta el parámetro ID_TG"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404

    conn = get_conn(); cur = conn.cursor()
    cur.execute(
        """
        UPDATE usuarios
        SET plan='FREE',
            rol_tg='FREE',
            rol_web='FREE',
            rol_wsp='FREE',
            creditos=5,
            fecha_caducidad=NULL,
            antispam=60,
            estado='ACTIVO'
        WHERE id_tg = ?
        """,
        (id_tg,)
    )
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": "Usuario reseteado a valores por defecto"}), 200

@app.route("/estado", methods=["GET"])
def estado():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request.args.get("ID_TG")
    valor = (request.args.get("valor") or "").upper()
    if not id_tg or not valor:
        return jsonify({"status": "error", "message": "Parámetros requeridos: ID_TG, valor"}), 400
    if valor not in {"ACTIVO", "BANEADO"}:
        return jsonify({"status": "error", "message": "valor inválido. Opciones: ACTIVO, BANEADO"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    conn = get_conn(); cur = conn.cursor()
    cur.execute("UPDATE usuarios SET estado = ? WHERE id_tg = ?", (valor, id_tg))
    conn.commit(); conn.close()
    return jsonify({"status": "ok", "message": f"Estado actualizado a {valor}"}), 200

def _safe_parse_date(s: str):
    if not s:
        return None
    try:
        ds = s.strip()
        if ds.endswith("Z"):
            ds = ds[:-1]
        return datetime.fromisoformat(ds)
    except Exception:
        return None

@app.route("/estadisticas", methods=["GET"])
def estadisticas():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    try:
        # --------- HISTORIAL: conteos hoy / globales y tops ----------
        today = now_utc().date()

        # Leer historial
        h_conn = get_conn(HIST_DB_PATH)
        h_conn.row_factory = sqlite3.Row
        h_cur = h_conn.cursor()
        h_cur.execute("SELECT ID_TG, consulta, fecha FROM historial;")
        h_rows = h_cur.fetchall()
        h_conn.close()

        consultas_globales = 0
        consultas_hoy = 0
        top_cmd_global = Counter()
        top_cmd_hoy = Counter()
        top_user_global = Counter()
        top_user_hoy = Counter()

        for r in h_rows:
            consultas_globales += 1
            consulta = (r["consulta"] or "").strip()
            uid = (r["ID_TG"] or "").strip()
            top_cmd_global[consulta] += 1
            top_user_global[uid] += 1

            d = _safe_parse_date(r["fecha"])
            if d and d.date() == today:
                consultas_hoy += 1
                top_cmd_hoy[consulta] += 1
                top_user_hoy[uid] += 1

        # Top lists
        top20_cmd_hoy = [{"consulta": k, "total": v} for k, v in top_cmd_hoy.most_common(20)]
        top30_user_hoy = [{"ID_TG": k, "total": v} for k, v in top_user_hoy.most_common(30)]
        top30_cmd_global = [{"consulta": k, "total": v} for k, v in top_cmd_global.most_common(30)]
        top30_user_global = [{"ID_TG": k, "total": v} for k, v in top_user_global.most_common(30)]

        # --------- USUARIOS: créditos, planes y días ----------
        u_conn = get_conn(DB_PATH)
        u_conn.row_factory = sqlite3.Row
        u_cur = u_conn.cursor()
        u_cur.execute("SELECT id_tg, creditos, plan, fecha_caducidad FROM usuarios;")
        users = u_cur.fetchall()
        u_conn.close()

        total_users = len(users)
        creditos_totales = 0
        inactivos_5 = 0              # creditos == 5
        creditos_cero = 0            # creditos == 0
        cinco_o_1k = 0               # creditos == 5 OR creditos == 1000 (interpretación literal del ejemplo)
        mas_1k = 0                   # creditos > 1000
        mas_5 = 0                    # creditos > 5

        planes_count = Counter()

        # Días (suscripción)
        now_dt = now_utc()
        con_plan_activo = 0          # fecha_caducidad > now
        sin_plan_activado = 0        # fecha_caducidad IS NULL
        con_plan_vencido = 0         # fecha_caducidad <= now
        rangos_dias = {
            "0-7": 0,
            "8-15": 0,
            "16-30": 0,
            "31-59": 0,
            "60+": 0
        }

        # Listas para tops
        top_creditos = []
        top_dias = []

        for u in users:
            uid = u["id_tg"]
            cred = int(u["creditos"] or 0)
            plan = (u["plan"] or "FREE").upper()
            fcad = _safe_parse_date(u["fecha_caducidad"])  # puede ser None

            creditos_totales += cred
            if cred == 5: inactivos_5 += 1
            if cred == 0: creditos_cero += 1
            if cred == 5 or cred == 1000: cinco_o_1k += 1
            if cred > 1000: mas_1k += 1
            if cred > 5: mas_5 += 1

            planes_count[plan] += 1
            top_creditos.append({"ID_TG": uid, "CREDITOS": cred})

            # días restantes
            if fcad is None:
                sin_plan_activado += 1
            else:
                # normalizar a "estado"
                if fcad <= now_dt:
                    con_plan_vencido += 1
                else:
                    con_plan_activo += 1
                    # días restantes (redondeo hacia arriba para que 0.1d cuente como 1)
                    days_left = math.ceil((fcad - now_dt).total_seconds() / 86400.0)
                    # rangos
                    if 1 <= days_left <= 7:
                        rangos_dias["0-7"] += 1
                    elif 8 <= days_left <= 15:
                        rangos_dias["8-15"] += 1
                    elif 16 <= days_left <= 30:
                        rangos_dias["16-30"] += 1
                    elif 31 <= days_left <= 59:
                        rangos_dias["31-59"] += 1
                    elif days_left >= 60:
                        rangos_dias["60+"] += 1
                    top_dias.append({"ID_TG": uid, "DIAS": days_left})

        # ordenamientos
        top20_usuarios_mas_creditos = sorted(top_creditos, key=lambda x: x["CREDITOS"], reverse=True)[:20]
        top30_usuarios_mas_dias = sorted(top_dias, key=lambda x: x["DIAS"], reverse=True)[:30]

        # Bloques agregados
        creditos_globales = {
            "Usuarios_totales": total_users,
            "Inactivos_5_credits": inactivos_5,
            "Con_0_credits": creditos_cero,
            "Con_5_o_1k_credits": cinco_o_1k,
            "Con_mas_1k_credits": mas_1k,
            "Con_credits_mas_5": mas_5,
            "Creditos_totales": creditos_totales,
            "Por_plan": {
                "BASICO": planes_count.get("BASICO", 0),
                "FREE": planes_count.get("FREE", 0),
                "PREMIUM": planes_count.get("PREMIUM", 0),
                "STANDARD": planes_count.get("STANDARD", 0),
            }
        }

        dias_globales = {
            "Usuarios_totales": total_users,
            "Con_plan_activo": con_plan_activo,
            "Sin_plan_activado": sin_plan_activado,
            "Con_plan_vencido": con_plan_vencido,
            "Rangos": {
                "-_7_dias": rangos_dias["0-7"],
                "8_15_dias": rangos_dias["8-15"],
                "16_30_dias": rangos_dias["16-30"],
                "31_59_dias": rangos_dias["31-59"],
                "+_60_dias": rangos_dias["60+"]
            }
        }

        # ---------- Render estilo texto para bots ----------
        def fmt_num(n):  # separador de miles
            return f"{n:,}".replace(",", ".")

        lines = []
        lines.append(f"CONSULTAS_HOY ➾ {fmt_num(consultas_hoy)}")
        lines.append(f"CONSULTAS_GLOBALES ➾ {fmt_num(consultas_globales)}")
        lines.append("")
        lines.append("TOP 20 COMANDOS HOY:")
        for item in top20_cmd_hoy:
            c = item['consulta'] or "(vacío)"
            lines.append(f"• {c} ➾ {fmt_num(item['total'])}")
        lines.append("")
        lines.append("TOP 30 USUARIOS DE HOY:")
        for item in top30_user_hoy:
            uid = item['ID_TG'] or "(desconocido)"
            lines.append(f"• {uid} ➾ {fmt_num(item['total'])}")
        lines.append("")
        lines.append("TOP 30 COMANDOS GLOBALES:")
        for item in top30_cmd_global:
            c = item['consulta'] or "(vacío)"
            lines.append(f"• {c} ➾ {fmt_num(item['total'])}")
        lines.append("")
        lines.append("TOP 30 USUARIOS GLOBALES:")
        for item in top30_user_global:
            uid = item['ID_TG'] or "(desconocido)"
            lines.append(f"• {uid} ➾ {fmt_num(item['total'])}")
        lines.append("")
        lines.append("CREDITOS GLOBALES")
        lines.append(f"• Usuarios totales ➾ {fmt_num(total_users)}")
        lines.append(f"• Inactivos (5 créditos) ➾ {fmt_num(inactivos_5)}")
        lines.append(f"• Con 0 créditos ➾ {fmt_num(creditos_cero)}")
        lines.append(f"• Con 5 o 1k créditos ➾ {fmt_num(cinco_o_1k)}")
        lines.append(f"• Con +1k créditos ➾ {fmt_num(mas_1k)}")
        lines.append(f"• Con créditos (+5) ➾ {fmt_num(mas_5)}")
        lines.append(f"• Créditos totales ➾ {fmt_num(creditos_totales)}")
        lines.append(f"• BASICO ➾ {fmt_num(planes_count.get('BASICO', 0))} Usuarios")
        lines.append(f"• FREE ➾ {fmt_num(planes_count.get('FREE', 0))} Usuarios")
        lines.append(f"• PREMIUM ➾ {fmt_num(planes_count.get('PREMIUM', 0))} Usuarios")
        lines.append(f"• STANDARD ➾ {fmt_num(planes_count.get('STANDARD', 0))} Usuarios")
        lines.append("")
        lines.append("TOP 20 USUARIOS CON MÁS CRÉDITOS")
        for item in top20_usuarios_mas_creditos:
            lines.append(f"• {item['ID_TG']} ➾ {fmt_num(item['CREDITOS'])}")
        lines.append("")
        lines.append("DIAS GLOBALES")
        lines.append(f"• Usuarios totales ➾ {fmt_num(total_users)}")
        lines.append(f"• Con plan activo ➾ {fmt_num(con_plan_activo)}")
        lines.append(f"• Sin plan activado ➾ {fmt_num(sin_plan_activado)}")
        lines.append(f"• Con plan vencido ➾ {fmt_num(con_plan_vencido)}")
        lines.append(f"• Con - 7 días ➾ {fmt_num(rangos_dias['0-7'])}")
        lines.append(f"• Con 8-15 días ➾ {fmt_num(rangos_dias['8-15'])}")
        lines.append(f"• Con 16-30 días ➾ {fmt_num(rangos_dias['16-30'])}")
        lines.append(f"• Con 31-59 días ➾ {fmt_num(rangos_dias['31-59'])}")
        lines.append(f"• Con + 60 días ➾ {fmt_num(rangos_dias['60+'])}")
        lines.append("")
        lines.append("TOP 30 USUARIOS CON MÁS DÍAS")
        for item in top30_usuarios_mas_dias:
            lines.append(f"• {item['ID_TG']} ➾ {fmt_num(item['DIAS'])}")

        render_text = "\n".join(lines)

        # ---------- RESpuesta JSON estructurada ----------
        data = {
            "CONSULTAS_HOY": consultas_hoy,
            "CONSULTAS_GLOBALES": consultas_globales,
            "TOP_20_COMANDOS_HOY": top20_cmd_hoy,
            "TOP_30_USUARIOS_HOY": top30_user_hoy,
            "TOP_30_COMANDOS_GLOBALES": top30_cmd_global,
            "TOP_30_USUARIOS_GLOBALES": top30_user_global,
            "CREDITOS_GLOBALES": creditos_globales,
            "TOP_20_USUARIOS_MAS_CREDITOS": top20_usuarios_mas_creditos,
            "DIAS_GLOBALES": dias_globales,
            "TOP_30_USUARIOS_MAS_DIAS": top30_usuarios_mas_dias,
        }

        return jsonify({
            "status": "ok",
            "message": "Estadísticas generadas",
            "data": data,
            "render": render_text
        }), 200

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Error generando estadísticas: {e}"
        }), 500

@app.route("/compras_id", methods=["GET"])
def compras_id():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    if not id_tg:
        return jsonify({"status": "error", "message": "Falta el parámetro ID_TG"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    conn = get_conn(COMPRAS_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT ID, ID_TG, VENDEDOR, FECHA, COMPRO FROM compras WHERE ID_TG = ? ORDER BY FECHA DESC, ID DESC", (id_tg,))
    rows = cur.fetchall()
    conn.close()
    data = [{"ID": r["ID"], "ID_TG": r["ID_TG"], "ID_VENDEDOR": r["VENDEDOR"], "FECHA": r["FECHA"], "CANTIDAD": r["COMPRO"]} for r in rows]
    msg = "Compras listadas" if data else "Sin compras para este ID_TG"
    return jsonify({"status": "ok", "message": msg, "data": data}), 200

@app.route("/hist_venta_id", methods=["GET"])
def hist_venta_id():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_vendedor = request_value("ID_VENDEDOR")
    if not id_vendedor:
        return jsonify({"status": "error", "message": "Falta el parámetro ID_VENDEDOR"}), 400
    conn = get_conn(COMPRAS_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT ID, ID_TG, VENDEDOR, FECHA, COMPRO FROM compras WHERE VENDEDOR = ? ORDER BY FECHA DESC, ID DESC", (id_vendedor,))
    rows = cur.fetchall()
    conn.close()
    data = [{"ID": r["ID"], "ID_TG": r["ID_TG"], "ID_VENDEDOR": r["VENDEDOR"], "FECHA": r["FECHA"], "CANTIDAD": r["COMPRO"]} for r in rows]
    msg = "Ventas listadas" if data else "Sin ventas para este vendedor"
    return jsonify({"status": "ok", "message": msg, "data": data}), 200

@app.route("/")
def index():
    return {"status": "ok", "message": "SpiderSyn API online"}


@app.route("/health", methods=["GET"])
def health():
    storage = get_storage_snapshot()
    ok = all(item["exists"] for item in storage["items"])
    return jsonify(
        {
            "status": "ok" if ok else "warn",
            "message": "SpiderSyn healthcheck",
            "storage": storage,
            "time": now_iso(),
        }
    ), 200


@app.route("/debug/storage", methods=["GET"])
def debug_storage():
    gate = require_panel_login()
    if gate:
        return gate
    return jsonify({"status": "ok", "data": get_storage_snapshot()}), 200


@app.route("/command_config", methods=["GET"])
def command_config():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    slug = (request_value("slug") or "").strip().lower()
    default_cost = request_value("default_cost", 1)
    try:
        default_cost = int(default_cost)
    except Exception:
        default_cost = 1
    if not slug:
        return jsonify({"status": "error", "message": "Falta el parámetro slug"}), 400
    return jsonify({"status": "ok", "data": get_command_config_value(slug, default_cost)}), 200


@app.route("/bot_catalog", methods=["GET"])
def bot_catalog():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    return jsonify(
        {
            "status": "ok",
            "data": {
                "categories": get_catalog_categories(),
                "commands": get_catalog_commands(),
                "buy_packages": get_buy_packages(),
                "settings": get_panel_settings(),
            },
        }
    ), 200


# Templates del panel movidos a templates/admin_panel.html y templates/admin_login.html

@app.route("/admin/panel", methods=["GET"])
def admin_panel():
    gate = require_panel_login()
    if gate:
        return gate
    flash = request.args.get("flash", "")
    active_section = (request.args.get("section") or "resumen").strip().lower()
    if active_section not in {"resumen", "buscar", "categorias", "comandos", "buy", "usuarios", "usuario", "compras", "historial", "vendedores", "ajustes", "solicitudes", "herramientas", "sistema", "estadisticas"}:
        active_section = "resumen"
    panel_role = panel_current_role()
    if not panel_can_access_section(active_section, panel_role):
        return redirect(url_for("admin_panel", section="resumen", flash="No tienes permiso para esa sección."))
    categories = get_catalog_categories()
    commands = get_catalog_commands()
    settings = get_panel_settings()
    buy_packages = get_buy_packages()
    global_q = request.args.get("gq", "")
    global_results = get_global_search_results(global_q)
    user_q = request.args.get("uq", "")
    user_status = (request.args.get("ustatus") or "").upper()
    user_plan = (request.args.get("uplan") or "").upper()
    admin_users = get_admin_users(q=user_q, status=user_status, plan=user_plan, limit=250)
    profile_user_id = (request.args.get("uid") or request.args.get("user_id") or "").strip()
    user_profile = get_user_profile_snapshot(profile_user_id) if profile_user_id else {"user": None, "purchases": [], "history": [], "requests": []}
    purchase_user = request.args.get("purchase_user", "")
    purchase_vendor = request.args.get("purchase_vendor", "")
    purchase_from = request.args.get("purchase_from", "")
    purchase_to = request.args.get("purchase_to", "")
    purchase_kind = request.args.get("purchase_kind", "")
    purchase_status = (request.args.get("purchase_status") or "").upper()
    purchases = get_admin_purchases(
        user_id=purchase_user,
        vendor_id=purchase_vendor,
        date_from=purchase_from,
        date_to=purchase_to,
        kind=purchase_kind,
        status=purchase_status,
        limit=300,
    )
    history_user = request.args.get("history_user", "")
    history_command = request.args.get("history_command", "")
    history_platform = request.args.get("history_platform", "")
    history_from = request.args.get("history_from", "")
    history_to = request.args.get("history_to", "")
    history_q = request.args.get("history_q", "")
    history_rows = get_admin_history(
        user_id=history_user,
        command=history_command,
        platform=history_platform,
        date_from=history_from,
        date_to=history_to,
        q=history_q,
        limit=300,
    )
    history_commands = sorted({(row.get("consulta") or "").strip().lower() for row in get_admin_history(limit=1000) if row.get("consulta")})
    vendor_q = request.args.get("vq", "")
    selected_vendor = (request.args.get("vendor") or "").strip()
    vendor_summary = get_vendor_sales_summary(q=vendor_q, limit=250)
    if not selected_vendor and vendor_summary:
        selected_vendor = vendor_summary[0]["vendedor"]
    vendor_detail = get_vendor_sales_detail(selected_vendor, limit=120) if selected_vendor else []
    vendor_total_sales = sum(int(item.get("total_ventas") or 0) for item in vendor_summary)
    all_requests = get_request_items(limit=300)
    request_q = request.args.get("rq", "")
    request_status = request.args.get("rstatus", "")
    request_command = request.args.get("rcommand", "")
    filtered_requests = filter_request_items(all_requests, q=request_q, status=request_status, command=request_command)
    pending_requests = [r for r in all_requests if (r.get("status") or "") == "pending"]
    recent_requests = [r for r in all_requests if (r.get("status") or "") != "pending"]
    filtered_pending_requests = [r for r in filtered_requests if (r.get("status") or "") == "pending"]
    filtered_recent_requests = [r for r in filtered_requests if (r.get("status") or "") != "pending"]
    request_counts = {
        "pending": len([r for r in all_requests if (r.get("status") or "") == "pending"]),
        "resolved": len([r for r in all_requests if (r.get("status") or "") == "resolved"]),
        "cancelled": len([r for r in all_requests if (r.get("status") or "") == "cancelled"]),
        "failed": len([r for r in all_requests if (r.get("status") or "") == "failed"]),
    }
    request_command_options = sorted({(r.get("command") or "").strip().lower() for r in all_requests if r.get("command")})
    q = request.args.get("q", "")
    category_filter = request.args.get("category", "")
    status_filter = request.args.get("status", "")
    filtered_commands = filter_catalog_commands(commands, q=q, category=category_filter, status=status_filter)
    try:
        cmd_page = int(request.args.get("page") or 1)
    except Exception:
        cmd_page = 1
    paged_commands, cmd_page, cmd_total_pages, cmd_total = paginate_items(filtered_commands, cmd_page, per_page=10)
    return render_template(
        "admin_panel.html",
        categories=categories,
        commands=commands,
        filtered_commands=paged_commands,
        buy_packages=buy_packages,
        admin_users=admin_users,
        profile_user_id=profile_user_id,
        user_profile=user_profile,
        vendor_summary=vendor_summary,
        vendor_detail=vendor_detail,
        vendor_total_sales=vendor_total_sales,
        vendor_q=vendor_q,
        selected_vendor=selected_vendor,
        settings=settings,
        previews=build_panel_previews(settings, buy_packages, commands),
        dashboard=get_dashboard_snapshot(),
        global_q=global_q,
        global_results=global_results,
        storage=get_storage_snapshot(),
        daily_backups=get_daily_backups(limit=10),
        panel_role=panel_role,
        panel_nav_items=panel_nav_items_for_role(panel_role),
        panel_accounts=get_panel_accounts(),
        panel_roles=sorted(PANEL_ROLES),
        history_cleanup_preview=get_history_cleanup_preview(),
        error_logs=get_error_logs(limit=50),
        audit_logs=get_audit_logs(limit=80),
        purchases=purchases,
        purchase_user=purchase_user,
        purchase_vendor=purchase_vendor,
        purchase_from=purchase_from,
        purchase_to=purchase_to,
        purchase_kind=purchase_kind,
        purchase_status=purchase_status,
        purchase_statuses=sorted(PURCHASE_STATUSES),
        history_rows=history_rows,
        history_user=history_user,
        history_command=history_command,
        history_platform=history_platform,
        history_from=history_from,
        history_to=history_to,
        history_q=history_q,
        history_commands=history_commands,
        pending_requests=pending_requests,
        recent_requests=recent_requests,
        filtered_pending_requests=filtered_pending_requests,
        filtered_recent_requests=filtered_recent_requests,
        request_counts=request_counts,
        request_command_options=request_command_options,
        request_q=request_q,
        request_status=request_status,
        request_command=request_command,
        request_templates=get_request_templates(),
        user_q=user_q,
        user_status=user_status,
        user_plan=user_plan,
        q=q,
        category_filter=category_filter,
        status_filter=status_filter,
        cmd_page=cmd_page,
        cmd_total_pages=cmd_total_pages,
        cmd_total=cmd_total,
        active_section=active_section,
        flash=flash,
    )


@app.route("/admin/category/save", methods=["POST"])
def admin_save_category():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR")
    if gate:
        return gate
    slug = (request.form.get("slug") or "").strip().lower()
    original_slug = (request.form.get("original_slug") or slug).strip().lower()
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    try:
        sort_order = int(request.form.get("sort_order") or 0)
    except Exception:
        sort_order = 0
    is_active = 1 if (request.form.get("is_active") or "1") == "1" else 0
    if not slug or not name:
        return redirect(url_for("admin_panel", section="categorias", flash="Categoría inválida."))

    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM command_categories WHERE slug = ?",
        (original_slug,),
    )
    exists = cur.fetchone()
    if exists:
        cur.execute(
            """
            UPDATE command_categories
            SET slug = ?, name = ?, description = ?, sort_order = ?, is_active = ?
            WHERE slug = ?
            """,
            (slug, name, description, sort_order, is_active, original_slug),
        )
    else:
        cur.execute(
            """
            INSERT INTO command_categories (slug, name, description, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?)
            """,
            (slug, name, description, sort_order, is_active),
        )
    conn.commit()
    conn.close()
    log_audit_event("category.save", slug, f"name={name}; active={is_active}; order={sort_order}")
    return redirect(url_for("admin_panel", section="categorias", flash=f"Categoría {name} guardada."))


@app.route("/admin/command/save", methods=["POST"])
def admin_save_command():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR")
    if gate:
        return gate
    slug = (request.form.get("slug") or "").strip().lower()
    name = (request.form.get("name") or "").strip()
    description = (request.form.get("description") or "").strip()
    usage_hint = (request.form.get("usage_hint") or "").strip()
    category_id = request.form.get("category_id") or None
    try:
        category_id = int(category_id) if category_id else None
    except Exception:
        category_id = None
    try:
        cost = int(request.form.get("cost") or 0)
    except Exception:
        cost = 0
    try:
        sort_order = int(request.form.get("sort_order") or 0)
    except Exception:
        sort_order = 0
    is_active = 1 if (request.form.get("is_active") or "1") == "1" else 0
    if not slug or not name:
        return redirect(url_for("admin_panel", section="comandos", flash="Comando inválido."))

    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO command_catalog (slug, name, description, category_id, cost, is_active, sort_order, usage_hint)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(slug) DO UPDATE SET
            name = excluded.name,
            description = excluded.description,
            category_id = excluded.category_id,
            cost = excluded.cost,
            is_active = excluded.is_active,
            sort_order = excluded.sort_order,
            usage_hint = excluded.usage_hint
        """,
        (slug, name, description, category_id, max(0, cost), is_active, sort_order, usage_hint),
    )
    conn.commit()
    conn.close()
    log_audit_event("command.save", slug, f"name={name}; cost={max(0, cost)}; active={is_active}; category_id={category_id}")
    return redirect(url_for("admin_panel", section="comandos", flash=f"Comando /{slug} guardado."))


@app.route("/admin/command/import", methods=["POST"])
def admin_import_commands():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR")
    if gate:
        return gate

    bulk_text = (request.form.get("bulk_commands") or "").strip()
    category_id = request.form.get("bulk_category_id") or None
    try:
        category_id = int(category_id) if category_id else None
    except Exception:
        category_id = None

    if not bulk_text:
        return redirect(url_for("admin_panel", section="comandos", flash="Pega al menos una línea para importar."))

    rows, errors = parse_bulk_command_rows(bulk_text)
    if errors:
        return redirect(url_for("admin_panel", section="comandos", flash="Importación cancelada: " + " | ".join(errors[:4])))
    if not rows:
        return redirect(url_for("admin_panel", section="comandos", flash="No se encontraron líneas válidas para importar."))

    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    created = 0
    updated = 0
    for item in rows:
        cur.execute("SELECT 1 FROM command_catalog WHERE slug = ?", (item["slug"],))
        exists = cur.fetchone() is not None
        cur.execute(
            """
            INSERT INTO command_catalog (slug, name, description, category_id, cost, is_active, sort_order, usage_hint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                category_id = excluded.category_id,
                cost = excluded.cost,
                is_active = excluded.is_active,
                sort_order = excluded.sort_order,
                usage_hint = excluded.usage_hint
            """,
            (
                item["slug"],
                item["name"],
                item["description"],
                category_id,
                item["cost"],
                item["is_active"],
                item["sort_order"],
                item["usage_hint"],
            ),
        )
        if exists:
            updated += 1
        else:
            created += 1
    conn.commit()
    conn.close()
    log_audit_event("command.import", "bulk", f"created={created}; updated={updated}; category_id={category_id}")
    return redirect(
        url_for(
            "admin_panel",
            section="comandos",
            flash=f"Importación lista: {created} creados, {updated} actualizados.",
        )
    )


@app.route("/admin/buy/save", methods=["POST"])
def admin_save_buy_package():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR")
    if gate:
        return gate
    pkg_id = request.form.get("id")
    kind = (request.form.get("kind") or "credits").strip()
    group_slug = (request.form.get("group_slug") or "").strip().lower()
    badge = (request.form.get("badge") or "").strip()
    title = (request.form.get("title") or "").strip()
    subtitle = (request.form.get("subtitle") or "").strip()
    line_text = (request.form.get("line_text") or "").strip()
    try:
        sort_order = int(request.form.get("sort_order") or 0)
    except Exception:
        sort_order = 0
    is_active = 1 if (request.form.get("is_active") or "1") == "1" else 0
    if kind not in {"credits", "days"} or not group_slug or not title or not line_text:
        return redirect(url_for("admin_panel", section="buy", flash="Paquete inválido."))
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    if pkg_id:
        cur.execute(
            """
            UPDATE buy_packages
            SET kind = ?, group_slug = ?, badge = ?, title = ?, subtitle = ?, line_text = ?, sort_order = ?, is_active = ?
            WHERE id = ?
            """,
            (kind, group_slug, badge, title, subtitle, line_text, sort_order, is_active, pkg_id),
        )
    else:
        cur.execute(
            """
            INSERT INTO buy_packages (kind, group_slug, badge, title, subtitle, line_text, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (kind, group_slug, badge, title, subtitle, line_text, sort_order, is_active),
        )
    conn.commit()
    conn.close()
    log_audit_event("buy.save", str(pkg_id or "new"), f"kind={kind}; group={group_slug}; title={title}; active={is_active}")
    return redirect(url_for("admin_panel", section="buy", flash="Paquete de /buy guardado."))


@app.route("/admin/setting/save", methods=["POST"])
def admin_save_setting():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR")
    if gate:
        return gate
    key = (request.form.get("key") or "").strip()
    value = (request.form.get("value") or "").strip()
    if not key:
        return redirect(url_for("admin_panel", section="ajustes", flash="Ajuste inválido."))
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO panel_settings (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()
    conn.close()
    log_audit_event("setting.save", key, "value updated")
    return redirect(url_for("admin_panel", section="ajustes", flash=f"Ajuste {key} guardado."))


@app.route("/admin/request-template/save", methods=["POST"])
def admin_save_request_template():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR", "SOPORTE")
    if gate:
        return gate
    key = (request.form.get("key") or "").strip().lower()
    text = (request.form.get("text") or "").strip()
    billable = 1 if (request.form.get("billable") or "0") == "1" else 0
    if not key or not text:
        return redirect(url_for("admin_panel", section="solicitudes", flash="Plantilla inválida."))
    conn = get_conn(REQUESTS_DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO request_templates (key, text, billable)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET text = excluded.text, billable = excluded.billable
        """,
        (key, text, billable),
    )
    conn.commit()
    conn.close()
    log_audit_event("request_template.save", key, f"billable={billable}")
    return redirect(url_for("admin_panel", section="solicitudes", flash=f"Plantilla {key} guardada."))


@app.route("/admin/user/save", methods=["POST"])
def admin_save_user():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR", "SOPORTE")
    if gate:
        return gate
    id_tg = (request.form.get("id_tg") or "").strip()
    plan = (request.form.get("plan") or "FREE").strip().upper()
    rol_tg = (request.form.get("rol_tg") or "FREE").strip().upper()
    estado = (request.form.get("estado") or "ACTIVO").strip().upper()
    try:
        creditos = max(0, int(request.form.get("creditos") or 0))
    except Exception:
        creditos = 0
    try:
        antispam = max(0, int(request.form.get("antispam") or 0))
    except Exception:
        antispam = 0
    if not id_tg:
        return redirect(url_for("admin_panel", section="usuarios", flash="Usuario inválido."))
    if plan not in PLANES_VALIDOS:
        plan = "FREE"
    if rol_tg not in ROLES_VALIDOS:
        rol_tg = "FREE"
    if estado not in {"ACTIVO", "BANEADO"}:
        estado = "ACTIVO"
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE usuarios
        SET creditos = ?, plan = ?, rol_tg = ?, estado = ?, antispam = ?
        WHERE id_tg = ?
        """,
        (creditos, plan, rol_tg, estado, antispam, id_tg),
    )
    conn.commit()
    conn.close()
    log_audit_event("user.save", id_tg, f"plan={plan}; rol={rol_tg}; estado={estado}; creditos={creditos}; antispam={antispam}")
    return redirect(url_for("admin_panel", section="usuarios", flash=f"Usuario {id_tg} actualizado."))


@app.route("/admin/user/action", methods=["POST"])
def admin_user_action():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR", "SOPORTE")
    if gate:
        return gate
    id_tg = (request.form.get("id_tg") or "").strip()
    action = (request.form.get("action") or "").strip().lower()
    if action == "owner" and panel_current_role() != "FUNDADOR":
        return redirect(url_for("admin_panel", section="usuarios", flash="Solo FUNDADOR puede hacer dueño a un usuario."))
    if not id_tg:
        return redirect(url_for("admin_panel", section="usuarios", flash="Usuario inválido."))
    row = get_user_by_id(id_tg)
    if not row:
        return redirect(url_for("admin_panel", section="usuarios", flash=f"Usuario {id_tg} no existe."))
    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    flash = f"Acción aplicada a {id_tg}."
    if action == "owner":
        cur.execute(
            """
            UPDATE usuarios
            SET rol_tg='FUNDADOR', rol_web='FUNDADOR', rol_wsp='FUNDADOR',
                plan='PREMIUM', estado='ACTIVO', antispam=0,
                creditos=CASE WHEN COALESCE(creditos, 0) < 999999 THEN 999999 ELSE creditos END,
                fecha_caducidad='2099-12-31T23:59:59Z'
            WHERE id_tg=?
            """,
            (id_tg,),
        )
        flash = f"Usuario {id_tg} ahora es FUNDADOR."
    elif action == "ban":
        cur.execute("UPDATE usuarios SET estado='BANEADO' WHERE id_tg=?", (id_tg,))
        flash = f"Usuario {id_tg} baneado."
    elif action == "unban":
        cur.execute("UPDATE usuarios SET estado='ACTIVO' WHERE id_tg=?", (id_tg,))
        flash = f"Usuario {id_tg} activo."
    elif action.startswith("credits_"):
        try:
            amount = int(action.split("_", 1)[1])
        except Exception:
            amount = 0
        cur.execute("UPDATE usuarios SET creditos=COALESCE(creditos, 0) + ? WHERE id_tg=?", (amount, id_tg))
        flash = f"Se agregaron {amount} créditos a {id_tg}."
    elif action.startswith("plan_"):
        try:
            days = int(action.split("_", 1)[1])
        except Exception:
            days = 0
        now = now_utc()
        current = row["fecha_caducidad"]
        try:
            base = parse_iso(current) if current else now
        except Exception:
            base = now
        if base < now:
            base = now
        new_iso = (base + timedelta(days=days)).replace(microsecond=0).isoformat() + "Z"
        cur.execute(
            "UPDATE usuarios SET plan='PREMIUM', estado='ACTIVO', fecha_caducidad=?, antispam=5 WHERE id_tg=?",
            (new_iso, id_tg),
        )
        flash = f"Se agregaron {days} días premium a {id_tg}."
    else:
        flash = "Acción no reconocida."
    conn.commit()
    conn.close()
    log_audit_event("user.action", id_tg, action)
    return redirect(url_for("admin_panel", section="usuarios", uq=id_tg, flash=flash))


@app.route("/admin/export/compras.csv", methods=["GET"])
def admin_export_purchases_csv():
    gate = require_panel_login()
    if gate:
        return gate
    rows = get_admin_purchases(
        user_id=request.args.get("purchase_user", ""),
        vendor_id=request.args.get("purchase_vendor", ""),
        date_from=request.args.get("purchase_from", ""),
        date_to=request.args.get("purchase_to", ""),
        kind=request.args.get("purchase_kind", ""),
        status=request.args.get("purchase_status", ""),
        limit=10000,
    )
    return _csv_response("spidersyn-compras.csv", rows, ["ID", "ID_TG", "VENDEDOR", "FECHA", "COMPRO", "ESTADO", "NOTAS", "COMPROBANTE"])


@app.route("/admin/export/compras.json", methods=["GET"])
def admin_export_purchases_json():
    gate = require_panel_login()
    if gate:
        return gate
    filters = {
        "purchase_user": request.args.get("purchase_user", ""),
        "purchase_vendor": request.args.get("purchase_vendor", ""),
        "purchase_from": request.args.get("purchase_from", ""),
        "purchase_to": request.args.get("purchase_to", ""),
        "purchase_kind": request.args.get("purchase_kind", ""),
        "purchase_status": request.args.get("purchase_status", ""),
    }
    rows = get_admin_purchases(
        user_id=filters["purchase_user"],
        vendor_id=filters["purchase_vendor"],
        date_from=filters["purchase_from"],
        date_to=filters["purchase_to"],
        kind=filters["purchase_kind"],
        status=filters["purchase_status"],
        limit=10000,
    )
    return _json_download_response(
        "spidersyn-compras.json",
        {"exported_at": now_iso(), "filters": filters, "total": len(rows), "data": rows},
    )


@app.route("/admin/purchase/update", methods=["POST"])
def admin_update_purchase():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR", "SELLER")
    if gate:
        return gate
    purchase_id = (request.form.get("purchase_id") or "").strip()
    estado = (request.form.get("estado") or "ENTREGADA").strip().upper()
    notas = (request.form.get("notas") or "").strip()
    comprobante = (request.form.get("comprobante") or "").strip()
    if estado not in PURCHASE_STATUSES:
        estado = "ENTREGADA"
    try:
        pid = int(purchase_id)
    except Exception:
        return redirect(url_for("admin_panel", section="compras", flash="Compra inválida."))
    conn = get_conn(COMPRAS_DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE compras
        SET ESTADO = ?, NOTAS = ?, COMPROBANTE = ?
        WHERE ID = ?
        """,
        (estado, notas, comprobante, pid),
    )
    changed = cur.rowcount
    conn.commit()
    conn.close()
    if changed:
        log_audit_event("purchase.update", str(pid), f"estado={estado}; notas={notas[:80]}; comprobante={comprobante[:80]}")
        flash = f"Compra #{pid} actualizada."
    else:
        flash = f"Compra #{pid} no encontrada."
    return redirect(
        url_for(
            "admin_panel",
            section="compras",
            purchase_user=request.form.get("purchase_user", ""),
            purchase_vendor=request.form.get("purchase_vendor", ""),
            purchase_from=request.form.get("purchase_from", ""),
            purchase_to=request.form.get("purchase_to", ""),
            purchase_kind=request.form.get("purchase_kind", ""),
            purchase_status=request.form.get("purchase_status", ""),
            flash=flash,
        )
    )


@app.route("/admin/export/historial.csv", methods=["GET"])
def admin_export_history_csv():
    gate = require_panel_login()
    if gate:
        return gate
    rows = get_admin_history(
        user_id=request.args.get("history_user", ""),
        command=request.args.get("history_command", ""),
        platform=request.args.get("history_platform", ""),
        date_from=request.args.get("history_from", ""),
        date_to=request.args.get("history_to", ""),
        q=request.args.get("history_q", ""),
        limit=10000,
    )
    return _csv_response("spidersyn-historial.csv", rows, ["ID", "ID_TG", "consulta", "valor", "fecha", "plataforma"])


@app.route("/admin/export/historial.json", methods=["GET"])
def admin_export_history_json():
    gate = require_panel_login()
    if gate:
        return gate
    filters = {
        "history_user": request.args.get("history_user", ""),
        "history_command": request.args.get("history_command", ""),
        "history_platform": request.args.get("history_platform", ""),
        "history_from": request.args.get("history_from", ""),
        "history_to": request.args.get("history_to", ""),
        "history_q": request.args.get("history_q", ""),
    }
    rows = get_admin_history(
        user_id=filters["history_user"],
        command=filters["history_command"],
        platform=filters["history_platform"],
        date_from=filters["history_from"],
        date_to=filters["history_to"],
        q=filters["history_q"],
        limit=10000,
    )
    return _json_download_response(
        "spidersyn-historial.json",
        {"exported_at": now_iso(), "filters": filters, "total": len(rows), "data": rows},
    )


@app.route("/admin/db-backup.zip", methods=["GET"])
def admin_db_backup_zip():
    gate = require_panel_login()
    if gate:
        return gate
    return build_db_backup_response()


@app.route("/admin/backup/daily/create", methods=["POST"])
def admin_create_daily_backup():
    gate = require_panel_owner()
    if gate:
        return gate
    try:
        path = ensure_daily_backup(force=True)
        flash = f"Backup diario creado: {os.path.basename(path)}"
    except Exception as exc:
        flash = f"No se pudo crear backup diario: {exc}"
    return redirect(url_for("admin_panel", section="sistema", flash=flash))


@app.route("/admin/backup/daily/<path:filename>", methods=["GET"])
def admin_download_daily_backup(filename: str):
    gate = require_panel_login()
    if gate:
        return gate
    safe_name = os.path.basename(filename)
    if safe_name != filename or not (safe_name.startswith("spidersyn-auto-") and safe_name.endswith(".zip")):
        return jsonify({"status": "error", "message": "Archivo inválido"}), 400
    path = os.path.join(backups_dir(), safe_name)
    if not os.path.exists(path):
        return jsonify({"status": "error", "message": "Backup no encontrado"}), 404
    return send_file(path, mimetype="application/zip", as_attachment=True, download_name=safe_name)


@app.route("/admin/maintenance/cleanup-history", methods=["POST"])
def admin_cleanup_history():
    gate = require_panel_login()
    if gate:
        return gate
    try:
        days = int(request.form.get("days") or 90)
    except Exception:
        days = 90
    if days < 30:
        return redirect(url_for("admin_panel", section="sistema", flash="Usa mínimo 30 días para limpiar historial."))
    if (request.form.get("confirm") or "").strip().upper() != "LIMPIAR":
        return redirect(url_for("admin_panel", section="sistema", flash="Escribe LIMPIAR para confirmar."))

    cutoff = (now_utc() - timedelta(days=days)).replace(microsecond=0).isoformat() + "Z"
    backup_name = f"historial-before-cleanup-{now_utc().strftime('%Y%m%d%H%M%S')}.db.bak"
    backup_path = os.path.join(get_data_dir(), backup_name)
    try:
        if os.path.exists(HIST_DB_PATH):
            shutil.copy2(HIST_DB_PATH, backup_path)
        conn = get_conn(HIST_DB_PATH)
        cur = conn.cursor()
        cur.execute("DELETE FROM historial WHERE fecha < ?", (cutoff,))
        deleted = int(cur.rowcount or 0)
        conn.commit()
        cur.execute("VACUUM")
        conn.close()
    except Exception as exc:
        return redirect(url_for("admin_panel", section="sistema", flash=f"No se pudo limpiar historial: {exc}"))

    log_audit_event("history.cleanup", f"{days}d", f"deleted={deleted}; cutoff={cutoff}; backup={backup_path}")
    return redirect(
        url_for(
            "admin_panel",
            section="sistema",
            flash=f"Historial limpiado: {deleted} registros. Backup previo: {backup_name}",
        )
    )


@app.route("/admin/password/update", methods=["POST"])
def admin_update_panel_password():
    gate = require_panel_owner()
    if gate:
        return gate
    current = request.form.get("current_password") or ""
    new_password = request.form.get("new_password") or ""
    confirm = request.form.get("confirm_password") or ""
    if not verify_panel_password(current):
        return redirect(url_for("admin_panel", section="sistema", flash="Clave actual incorrecta."))
    if len(new_password) < 8:
        return redirect(url_for("admin_panel", section="sistema", flash="La nueva clave debe tener mínimo 8 caracteres."))
    if new_password != confirm:
        return redirect(url_for("admin_panel", section="sistema", flash="La confirmación no coincide."))
    save_panel_setting_value("PANEL_PASSWORD_HASH", generate_password_hash(new_password))
    log_audit_event("panel.password_update", session.get("panel_user") or PANEL_USER, "password changed")
    return redirect(url_for("admin_panel", section="sistema", flash="Clave del panel actualizada."))


@app.route("/admin/panel-account/save", methods=["POST"])
def admin_save_panel_account():
    gate = require_panel_owner()
    if gate:
        return gate
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    role = (request.form.get("role") or "SOPORTE").strip().upper()
    is_active = 1 if (request.form.get("is_active") or "1") == "1" else 0
    if not username:
        return redirect(url_for("admin_panel", section="sistema", flash="Usuario de panel inválido."))
    if username == PANEL_USER:
        return redirect(url_for("admin_panel", section="sistema", flash="La cuenta principal se maneja desde Railway/Sistema."))
    if role not in PANEL_ROLES:
        role = "SOPORTE"
    existing = get_panel_account(username)
    if not existing and len(password) < 8:
        return redirect(url_for("admin_panel", section="sistema", flash="La clave inicial debe tener mínimo 8 caracteres."))

    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    now = now_iso()
    if existing:
        if password:
            if len(password) < 8:
                conn.close()
                return redirect(url_for("admin_panel", section="sistema", flash="La nueva clave debe tener mínimo 8 caracteres."))
            cur.execute(
                """
                UPDATE panel_accounts
                SET password_hash = ?, role = ?, is_active = ?, updated_at = ?
                WHERE username = ?
                """,
                (generate_password_hash(password), role, is_active, now, username),
            )
        else:
            cur.execute(
                """
                UPDATE panel_accounts
                SET role = ?, is_active = ?, updated_at = ?
                WHERE username = ?
                """,
                (role, is_active, now, username),
            )
    else:
        cur.execute(
            """
            INSERT INTO panel_accounts (username, password_hash, role, is_active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (username, generate_password_hash(password), role, is_active, now, now),
        )
    conn.commit()
    conn.close()
    log_audit_event("panel.account.save", username, f"role={role}; active={is_active}")
    return redirect(url_for("admin_panel", section="sistema", flash=f"Cuenta de panel {username} guardada."))


def build_db_backup_response():
    buffer = io.BytesIO()
    temp_path = os.path.join(get_data_dir(), f"spidersyn-manual-{now_utc().strftime('%Y%m%d%H%M%S')}.zip.tmp")
    try:
        create_db_backup_file(temp_path)
        with open(temp_path, "rb") as f:
            buffer.write(f.read())
    finally:
        try:
            os.remove(temp_path)
        except Exception:
            pass
    buffer.seek(0)
    return Response(
        buffer.getvalue(),
        mimetype="application/zip",
        headers={"Content-Disposition": "attachment; filename=spidersyn-db-backup.zip"},
    )


@app.route("/internal/db-backup.zip", methods=["GET"])
def internal_db_backup_zip():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    return build_db_backup_response()


@app.route("/admin/export", methods=["GET"])
def admin_export_panel():
    gate = require_panel_login()
    if gate:
        return gate
    payload = {
        "categories": get_catalog_categories(),
        "commands": get_catalog_commands(),
        "buy_packages": get_buy_packages(),
        "settings": get_panel_settings(),
        "request_templates": get_request_templates(),
    }
    body = json.dumps(payload, ensure_ascii=False, indent=2)
    return Response(
        body,
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=spidersyn-panel-backup.json"},
    )


@app.route("/admin/import", methods=["POST"])
def admin_import_panel():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR")
    if gate:
        return gate
    uploaded = request.files.get("backup_file")
    if not uploaded:
        return redirect(url_for("admin_panel", section="herramientas", flash="Falta el archivo de respaldo."))
    try:
        payload = json.load(uploaded.stream)
    except Exception:
        return redirect(url_for("admin_panel", section="herramientas", flash="Archivo JSON inválido."))

    conn = get_conn(DB_PATH)
    cur = conn.cursor()
    for item in payload.get("settings", {}).items():
        key, value = item
        cur.execute(
            "INSERT INTO panel_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value or "")),
        )
    for cat in payload.get("categories", []):
        cur.execute(
            """
            INSERT INTO command_categories (slug, name, description, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                sort_order = excluded.sort_order,
                is_active = excluded.is_active
            """,
            (cat.get("slug"), cat.get("name"), cat.get("description", ""), int(cat.get("sort_order", 0)), int(bool(cat.get("is_active", 1)))),
        )
    conn.commit()
    cur.execute("SELECT id, slug FROM command_categories")
    category_ids = {row[1]: row[0] for row in cur.fetchall()}
    for cmd in payload.get("commands", []):
        cur.execute(
            """
            INSERT INTO command_catalog (slug, name, description, category_id, cost, is_active, sort_order, usage_hint)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(slug) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                category_id = excluded.category_id,
                cost = excluded.cost,
                is_active = excluded.is_active,
                sort_order = excluded.sort_order,
                usage_hint = excluded.usage_hint
            """,
            (
                cmd.get("slug"),
                cmd.get("name"),
                cmd.get("description", ""),
                category_ids.get(cmd.get("category_slug")),
                int(cmd.get("cost", 1)),
                int(bool(cmd.get("is_active", 1))),
                int(cmd.get("sort_order", 0)),
                cmd.get("usage_hint", ""),
            ),
        )
    for pkg in payload.get("buy_packages", []):
        cur.execute(
            """
            INSERT INTO buy_packages (id, kind, group_slug, badge, title, subtitle, line_text, sort_order, is_active)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                kind = excluded.kind,
                group_slug = excluded.group_slug,
                badge = excluded.badge,
                title = excluded.title,
                subtitle = excluded.subtitle,
                line_text = excluded.line_text,
                sort_order = excluded.sort_order,
                is_active = excluded.is_active
            """,
            (
                int(pkg.get("id", 0)) or None,
                pkg.get("kind", "credits"),
                pkg.get("group_slug", ""),
                pkg.get("badge", ""),
                pkg.get("title", ""),
                pkg.get("subtitle", ""),
                pkg.get("line_text", ""),
                int(pkg.get("sort_order", 0)),
                int(bool(pkg.get("is_active", 1))),
            ),
        )
    conn.commit()
    conn.close()
    req_conn = get_conn(REQUESTS_DB_PATH)
    req_cur = req_conn.cursor()
    for tpl in payload.get("request_templates", []):
        req_cur.execute(
            """
            INSERT INTO request_templates (key, text, billable)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET text = excluded.text, billable = excluded.billable
            """,
            (
                str(tpl.get("key") or "").strip().lower(),
                str(tpl.get("text") or ""),
                int(tpl.get("billable") or 0),
            ),
        )
    req_conn.commit()
    req_conn.close()
    log_audit_event(
        "panel.import",
        "backup",
        f"categories={len(payload.get('categories', []))}; commands={len(payload.get('commands', []))}; packages={len(payload.get('buy_packages', []))}; templates={len(payload.get('request_templates', []))}",
    )
    return redirect(url_for("admin_panel", section="herramientas", flash="Respaldo importado correctamente."))


@app.route("/admin/bulk/commands", methods=["POST"])
def admin_bulk_commands():
    gate = require_panel_roles("FUNDADOR", "CO-FUNDADOR")
    if gate:
        return gate
    category_slug = (request.form.get("category_slug") or "").strip().lower()
    current_status = (request.form.get("current_status") or "").strip().lower()
    status_action = (request.form.get("status_action") or "").strip().lower()
    cost_action = (request.form.get("cost_action") or "").strip().lower()
    try:
        cost_value = int(request.form.get("cost_value") or 0)
    except Exception:
        cost_value = 0

    conn = get_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.slug, c.cost, c.is_active
        FROM command_catalog c
        LEFT JOIN command_categories cat ON cat.id = c.category_id
        """
    )
    rows = cur.fetchall()
    selected = []
    for row in rows:
        if category_slug:
            cur2 = get_conn(DB_PATH)
            cur2.row_factory = sqlite3.Row
            c2 = cur2.cursor()
            c2.execute("SELECT cat.slug FROM command_catalog c LEFT JOIN command_categories cat ON cat.id = c.category_id WHERE c.slug = ?", (row["slug"],))
            rr = c2.fetchone()
            cur2.close()
            if not rr or (rr["slug"] or "").lower() != category_slug:
                continue
        if current_status == "active" and not row["is_active"]:
            continue
        if current_status == "inactive" and row["is_active"]:
            continue
        selected.append(row)

    count = 0
    for row in selected:
        if status_action == "activate":
            cur.execute("UPDATE command_catalog SET is_active = 1 WHERE slug = ?", (row["slug"],))
        elif status_action == "deactivate":
            cur.execute("UPDATE command_catalog SET is_active = 0 WHERE slug = ?", (row["slug"],))
        if cost_action == "sum":
            cur.execute("UPDATE command_catalog SET cost = MAX(0, cost + ?) WHERE slug = ?", (cost_value, row["slug"]))
        elif cost_action == "set":
            cur.execute("UPDATE command_catalog SET cost = ? WHERE slug = ?", (max(0, cost_value), row["slug"]))
        count += 1
    conn.commit()
    conn.close()
    log_audit_event(
        "command.bulk",
        category_slug or "all",
        f"count={count}; status_action={status_action}; cost_action={cost_action}; cost_value={cost_value}",
    )
    return redirect(url_for("admin_panel", section="herramientas", flash=f"Acción masiva aplicada a {count} comandos."))


@app.route("/admin/login", methods=["GET", "POST"])
def panel_login():
    if not _panel_request_allowed():
        return jsonify({"status": "error", "message": "Panel solo disponible localmente"}), 403
    error = ""
    next_url = request.args.get("next") or url_for("admin_panel")
    ip = request.remote_addr or "unknown"
    attempts = PANEL_LOGIN_ATTEMPTS.get(ip, [])
    now_ts = time.time()
    attempts = [ts for ts in attempts if now_ts - ts < 900]
    PANEL_LOGIN_ATTEMPTS[ip] = attempts
    if len(attempts) >= 5:
        return render_template("admin_login.html", error="Demasiados intentos. Espera 15 minutos."), 429
    if request.method == "POST":
        username = (request.form.get("username") or "").strip()
        password = request.form.get("password") or ""
        if username == PANEL_USER and verify_panel_password(password):
            session["panel_auth"] = True
            session["panel_user"] = username
            session["panel_role"] = "FUNDADOR"
            PANEL_LOGIN_ATTEMPTS.pop(ip, None)
            log_audit_event("panel.login", username, "success", actor=username)
            return redirect(next_url)
        account = get_panel_account(username)
        if account and int(account.get("is_active") or 0) == 1 and check_password_hash(account["password_hash"], password):
            session["panel_auth"] = True
            session["panel_user"] = username
            session["panel_role"] = (account.get("role") or "SOPORTE").upper()
            PANEL_LOGIN_ATTEMPTS.pop(ip, None)
            log_audit_event("panel.login", username, f"success role={session['panel_role']}", actor=username)
            return redirect(next_url)
        attempts.append(now_ts)
        PANEL_LOGIN_ATTEMPTS[ip] = attempts
        log_audit_event("panel.login_failed", username or "unknown", f"attempts={len(attempts)}", actor=username or "unknown")
        error = "Usuario o clave inválidos."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout", methods=["GET"])
def panel_logout():
    log_audit_event("panel.logout", session.get("panel_user") or PANEL_USER, "logout")
    session.pop("panel_auth", None)
    session.pop("panel_user", None)
    session.pop("panel_role", None)
    return redirect(url_for("panel_login"))

@app.route("/historial_id", methods=["GET"])
def historial_id():
    auth_error = require_internal_access()
    if auth_error:
        return auth_error
    id_tg = request_value("ID_TG")
    if not id_tg:
        return jsonify({"status": "error", "message": "Falta el parámetro ID_TG"}), 400
    row = get_user_by_id(id_tg)
    if not row:
        return jsonify({"status": "error", "message": "Usuario no encontrado"}), 404
    conn = get_conn(HIST_DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT ID_TG, consulta, valor, fecha, plataforma FROM historial WHERE ID_TG = ? ORDER BY fecha DESC, ID DESC", (id_tg,))
    rows = cur.fetchall()
    conn.close()
    data = [{"ID_TG": r["ID_TG"], "CONSULTA": r["consulta"], "VALOR": r["valor"], "FECHA": r["fecha"], "PLATAFORMA": r["plataforma"]} for r in rows]
    msg = "Historial listado" if data else "Sin historial para este ID_TG"
    return jsonify({"status": "ok", "message": msg, "data": data}), 200

@app.route("/login_web", methods=["POST"])
@cross_origin(
    origins=["http://127.0.0.1:5500"],
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization"],
    methods=["GET", "POST", "OPTIONS"]
)
def login_web():
    """
    Login WEB:
      - Parâmetros: user, pass  (en querystring GET o en form-data/x-www-form-urlencoded POST)
      - Requisitos: el usuario debe existir con register_web=1
      - Resultado: TOKEN_API_WEB (si no existe, se genera y se retorna)
    """
    # Obtener credenciales desde args o form
    user = (request.values.get("user") or "").strip()
    password = (request.values.get("pass") or "").strip()

    if not user or not password:
        return jsonify({
            "status": "error",
            "message": "Parámetros requeridos: user y pass"
        }), 400

    # Buscar usuario por user_web (case-insensitive)
    conn = get_conn(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM usuarios WHERE LOWER(user_web) = LOWER(?)",
        (user,)
    )
    row = cur.fetchone()

    if not row:
        conn.close()
        return jsonify({
            "status": "error",
            "message": "Usuario WEB no encontrado"
        }), 404

    # Verificar que tenga WEB activado
    if not bool(row["register_web"]):
        conn.close()
        return jsonify({
            "status": "error",
            "message": "WEB no está activado para este usuario"
        }), 423

    stored_password = row["pass_web"] or ""
    password_ok = False
    if stored_password.startswith("pbkdf2:") or stored_password.startswith("scrypt:"):
        password_ok = check_password_hash(stored_password, password)
    else:
        password_ok = stored_password == password

    if not password_ok:
        conn.close()
        return jsonify({
            "status": "error",
            "message": "Credenciales inválidas"
        }), 401

    # Asegurar token_api_web (si no existe, generarlo)
    token = row["token_api_web"]
    created = False
    if not token:
        token = generate_unique_token()
        cur.execute(
            "UPDATE usuarios SET token_api_web = ? WHERE id_tg = ?",
            (token, row["id_tg"])
        )
        conn.commit()
        created = True

    # Respuesta OK con datos útiles
    payload = {
        "TOKEN_API_WEB": token,
        "ID_TG": row["id_tg"],
        "PLAN": row["plan"],
        "ESTADO": row["estado"],
        "CREDITOS": row["creditos"],
        "FECHA_DE_CADUCIDAD": row["fecha_caducidad"],
        "ANTISPAM": row["antispam"],
        "TOKEN_CREATED": created
    }
    conn.close()
    return jsonify({
        "status": "ok",
        "message": "Login correcto",
        "data": payload
    }), 200


# -------------------------
# Main
# -------------------------
def init_app_databases():
    init_main_db()
    sync_owner_users()
    init_hist_db()
    init_compras_db()
    init_keys_db()
    init_catalog_db()
    init_buy_db()
    init_panel_settings_db()
    init_panel_accounts_db()
    init_requests_db()


init_app_databases()


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

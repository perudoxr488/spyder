import json
import os
import sqlite3
from urllib import request as _urlreq
from urllib import parse as _urlparse
from urllib.error import HTTPError, URLError
from storage import db_path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")
DB_PATH = db_path("multiplataforma.db")

CFG = {}
try:
    if os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f)
except Exception:
    CFG = {}

API_BASE = (CFG.get("API_BASE") or "").rstrip("/")
INTERNAL_API_KEY = (CFG.get("INTERNAL_API_KEY") or CFG.get("TOKEN_BOT") or "").strip()
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


def _fetch_json(url: str, timeout: int = 20, method: str = "GET", payload: dict | None = None):
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
            st = resp.getcode() or 200
            body = resp.read().decode("utf-8", errors="replace")
            try:
                return st, json.loads(body)
            except Exception:
                return st, {"status": "error", "message": body}
    except HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
            data = json.loads(body)
        except Exception:
            data = {"status": "error", "message": str(e)}
        return e.code, data
    except URLError as e:
        return 599, {"status": "error", "message": str(e)}
    except Exception as e:
        return 500, {"status": "error", "message": str(e)}


def verificar_usuario(id_tg: str):
    """
    Devuelve (True, info_usuario) si el usuario existe y está ACTIVO.
    Devuelve (False, data) si no existe o está inactivo.
    """
    if not API_BASE:
        return False, {}

    st, js = _fetch_json(f"{API_BASE}/tg_info?ID_TG={_urlparse.quote(id_tg)}")
    if st != 200:
        return False, {}

    data = js.get("data", {}) or {}
    estado = (data.get("ESTADO") or "").upper().strip()

    if estado != "ACTIVO":
        return False, data

    from datetime import datetime, timezone

    exp = data.get("FECHA DE CADUCIDAD")
    ilimitado = False
    if exp:
        try:
            exp_dt = datetime.fromisoformat(exp.replace("Z", "")).replace(tzinfo=timezone.utc)
            ilimitado = exp_dt > datetime.now(timezone.utc)
        except Exception:
            ilimitado = False

    data["ilimitado"] = ilimitado
    return True, data


def _catalog_conn():
    return sqlite3.connect(DB_PATH)


def ensure_command_tables():
    conn = _catalog_conn()
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
    conn.commit()
    conn.close()


def get_command_runtime_config(command_slug: str, default_cost: int = 1):
    if API_BASE:
        st, js = _fetch_json(
            f"{API_BASE}/command_config?slug={_urlparse.quote(command_slug)}&default_cost={int(default_cost)}",
            timeout=12,
        )
        if st == 200:
            data = js.get("data") or {}
            if data:
                return {
                    "exists": bool(data.get("exists", True)),
                    "slug": data.get("slug") or command_slug,
                    "name": data.get("name") or command_slug.upper(),
                    "cost": int(data.get("cost") or default_cost),
                    "is_active": bool(data.get("is_active", True)),
                    "category_slug": data.get("category_slug"),
                    "category_name": data.get("category_name"),
                    "description": data.get("description") or "",
                    "usage_hint": data.get("usage_hint") or "",
                    "validation": data.get("validation") if isinstance(data.get("validation"), dict) else {},
                }

    ensure_command_tables()
    conn = _catalog_conn()
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.slug, c.name, c.cost, c.is_active, c.description, c.usage_hint,
               cat.slug AS category_slug, cat.name AS category_name
        FROM command_catalog c
        LEFT JOIN command_categories cat ON cat.id = c.category_id
        WHERE c.slug = ?
        """,
        (command_slug,),
    )
    row = cur.fetchone()
    conn.close()
    if not row:
        return {
            "exists": False,
            "slug": command_slug,
            "name": command_slug.upper(),
            "cost": int(default_cost),
            "is_active": True,
            "category_slug": None,
            "category_name": None,
            "description": "",
            "usage_hint": "",
            "validation": {},
        }
    description = row["description"] or ""
    validation = {}
    if description.strip().startswith("{"):
        try:
            payload = json.loads(description)
            if isinstance(payload, dict):
                description = str(payload.get("info") or "").strip()
                validation = payload.get("validation") if isinstance(payload.get("validation"), dict) else {}
        except Exception:
            pass
    return {
        "exists": True,
        "slug": row["slug"],
        "name": row["name"],
        "cost": int(row["cost"] or default_cost),
        "is_active": bool(row["is_active"]),
        "category_slug": row["category_slug"],
        "category_name": row["category_name"],
        "description": description,
        "usage_hint": row["usage_hint"] or "",
        "validation": validation,
    }


def descontar_creditos(id_tg: str, cantidad: int = 1):
    if not API_BASE:
        return False, {}

    st, js = _fetch_json(
        f"{API_BASE}/cred",
        method="POST",
        payload={"ID_TG": id_tg, "operacion": "restar", "cantidad": cantidad},
    )
    if st != 200:
        return False, {}
    return True, js.get("data", {}) or {}

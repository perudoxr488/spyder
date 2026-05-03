import os
import json
import html
import math
import sqlite3
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import ContextTypes
from storage import db_path

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")
DB_PATH = db_path("multiplataforma.db")
PAGE_SIZE = 5
DEFAULT_DETAILS = {
    "nm": {"usage_hint": "/nm nombre|paterno|materno", "description": "Busqueda por nombres con DNI y edad."},
    "dni": {"usage_hint": "/dni 12345678", "description": "Imagen del rostro y datos principales."},
    "dnif": {"usage_hint": "/dnif 12345678", "description": "Rostro, huella, firma y datos ampliados."},
    "dnim": {"usage_hint": "/dnim 12345678", "description": "Grupo de votacion, correo y telefono."},
    "c4": {"usage_hint": "/c4 12345678", "description": "Certificado de inscripcion en PDF."},
    "c4blanco": {"usage_hint": "/c4blanco 12345678", "description": "Ficha RENIEC blanca en PDF."},
    "c4azul": {"usage_hint": "/c4azul 12345678", "description": "Ficha RENIEC azul en PDF."},
    "dnivel": {"usage_hint": "/dnivel 12345678", "description": "DNI virtual electronico anverso y reverso."},
    "dnivam": {"usage_hint": "/dnivam 12345678", "description": "DNI virtual amarillo anverso y reverso."},
    "dnivaz": {"usage_hint": "/dnivaz 12345678", "description": "DNI virtual azul anverso y reverso."},
    "revitec": {"usage_hint": "/revitec AAA000", "description": "Revisiones tecnicas, estado y observaciones."},
    "tiveqr": {"usage_hint": "/tiveqr AAA000", "description": "Tarjeta TIVE generada con QR en PDF."},
    "soat": {"usage_hint": "/soat AAA000", "description": "Consulta de SOAT y datos asociados."},
    "tive": {"usage_hint": "/tive AAA000", "description": "Tarjeta TIVE generada sin QR."},
    "tiveor": {"usage_hint": "/tiveor AAA000", "description": "Tarjeta TIVE original."},
    "tarjetafisica": {"usage_hint": "/tarjetafisica AAA000", "description": "Tarjeta de propiedad fisica por ambos lados."},
    "placasiento": {"usage_hint": "/placasiento AAA000", "description": "Asientos, cambios de dueno y caracteristicas."},
    "pla": {"usage_hint": "/pla AAA000", "description": "Datos de placa e imagenes del vehiculo."},
    "papeletas": {"usage_hint": "/papeletas AAA000", "description": "Papeletas, montos y evidencias."},
    "bolinv": {"usage_hint": "/bolinv AAA000", "description": "Boleta informativa vehicular en PDF."},
    "insve": {"usage_hint": "/insve AAA000", "description": "Inscripcion vehicular y datos relacionados."},
    "licencia": {"usage_hint": "/licencia 12345678", "description": "Consulta de licencia de conducir."},
    "licenciapdf": {"usage_hint": "/licenciapdf 12345678", "description": "Licencia en formato PDF."},
    "rqv": {"usage_hint": "/rqv 12345678", "description": "Requisitorias y alertas vehiculares."},
    "denunciasv": {"usage_hint": "/denunciasv 12345678", "description": "Denuncias vinculadas al vehiculo o persona."},
    "det": {"usage_hint": "/det 12345678", "description": "Detalle de consulta en sistema policial."},
    "ant": {"usage_hint": "/ant 12345678", "description": "Antecedentes generales."},
    "antpe": {"usage_hint": "/antpe 12345678", "description": "Antecedentes penales."},
    "antpo": {"usage_hint": "/antpo 12345678", "description": "Antecedentes policiales."},
    "antju": {"usage_hint": "/antju 12345678", "description": "Antecedentes judiciales."},
    "denuncias": {"usage_hint": "/denuncias 12345678", "description": "Denuncias registradas."},
    "rq": {"usage_hint": "/rq 12345678", "description": "Requisitorias personales."},
    "fis": {"usage_hint": "/fis 12345678", "description": "Consulta fiscal basica."},
    "fispdf": {"usage_hint": "/fispdf 12345678", "description": "Reporte fiscal en PDF."},
    "hogar": {"usage_hint": "/hogar 12345678", "description": "Datos de hogar y sisfoh."},
    "ag": {"usage_hint": "/ag 12345678", "description": "Arbol genealogico basico."},
    "agv": {"usage_hint": "/agv 12345678", "description": "Arbol genealogico extendido."},
    "her": {"usage_hint": "/her 12345678", "description": "Hermanos y vinculos familiares."},
    "numclaro": {"usage_hint": "/numclaro 999999999", "description": "Datos de linea Claro."},
    "correo": {"usage_hint": "/correo correo@dominio.com", "description": "Consulta por correo relacionado."},
    "enteldb": {"usage_hint": "/enteldb 999999999", "description": "Datos de linea Entel."},
    "movistar": {"usage_hint": "/movistar 999999999", "description": "Datos de linea Movistar."},
    "bitel": {"usage_hint": "/bitel 999999999", "description": "Datos de linea Bitel."},
    "claro": {"usage_hint": "/claro 999999999", "description": "Datos de linea Claro."},
    "vlop": {"usage_hint": "/vlop 999999999", "description": "Validacion basica de operador."},
    "vlnum": {"usage_hint": "/vlnum 999999999", "description": "Validacion numerica de linea."},
    "cel": {"usage_hint": "/cel 999999999", "description": "Consulta celular general."},
    "tels": {"usage_hint": "/tels 999999999", "description": "Telefonos asociados."},
    "telp": {"usage_hint": "/telp 999999999", "description": "Telefonia premium."},
    "tel": {"usage_hint": "/tel 999999999", "description": "Consulta telefonica basica."},
    "sunarp": {"usage_hint": "/sunarp 12345678", "description": "Propiedades y partidas registrales."},
    "sunarpdf": {"usage_hint": "/sunarpdf 12345678", "description": "Reporte SUNARP en PDF."},
    "sueldos": {"usage_hint": "/sueldos 12345678", "description": "Historial de sueldos."},
    "trabajos": {"usage_hint": "/trabajos 12345678", "description": "Historial laboral."},
    "actamdb": {"usage_hint": "/actamdb 12345678", "description": "Acta de matrimonio."},
    "actaddb": {"usage_hint": "/actaddb 12345678", "description": "Acta de defuncion."},
    "migrapdf": {"usage_hint": "/migrapdf 12345678", "description": "Reporte migratorio en PDF."},
    "afp": {"usage_hint": "/afp 12345678", "description": "Consulta AFP."},
    "dir": {"usage_hint": "/dir 12345678", "description": "Direcciones relacionadas."},
    "trabajadores": {"usage_hint": "/trabajadores 12345678", "description": "Lista de trabajadores asociados."},
    "sbs": {"usage_hint": "/sbs 12345678", "description": "Reporte SBS."},
    "notas": {"usage_hint": "/notas 12345678", "description": "Notas y registros academicos."},
    "essalud": {"usage_hint": "/essalud 12345678", "description": "Consulta Essalud."},
    "doc": {"usage_hint": "/doc 12345678", "description": "Documentos asociados."},
    "ruc": {"usage_hint": "/ruc 20123456789", "description": "Consulta RUC."},
    "sunat": {"usage_hint": "/sunat 20123456789", "description": "Consulta SUNAT."},
    "seeker": {"usage_hint": "/seeker 12345678", "description": "Busqueda avanzada de datos."},
    "facial": {"usage_hint": "/facial 12345678", "description": "Resultado facial o biometrico."},
}


def _load_cfg():
    cfg = {}
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
        except Exception:
            pass
    return cfg or {}


def _get_menu_image(cfg: dict) -> str | None:
    settings = _get_panel_settings()
    img = settings.get("FT_CMDS") or (cfg.get("LOGO") or {}).get("FT_CMDS")
    if not img:
        img = settings.get("FT_START") or (cfg.get("LOGO") or {}).get("FT_START")
    return img


def _user_link(u) -> str:
    if u.username:
        return f"https://t.me/{u.username}"
    return f"tg://user?id={u.id}"


def _icon_for_category(slug: str) -> str:
    icon_map = {
        "reniec": "🪪",
        "vehiculos": "🚗",
        "delitos": "👮",
        "familia": "👨‍👩‍👦",
        "telefonia": "📞",
        "sunarp": "🏠",
        "laboral": "💼",
        "actas": "📋",
        "migraciones": "⚖️",
        "extras": "📚",
    }
    return icon_map.get((slug or "").lower(), "🧩")


def _ensure_catalog_tables():
    conn = sqlite3.connect(DB_PATH)
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


def _get_panel_settings():
    conn = sqlite3.connect(DB_PATH)
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
    cur.execute("SELECT key, value FROM panel_settings")
    rows = {row["key"]: row["value"] for row in cur.fetchall()}
    conn.close()
    return rows


def _get_categories():
    _ensure_catalog_tables()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, slug, name, description, sort_order
        FROM command_categories
        WHERE is_active = 1
        ORDER BY sort_order ASC, name ASC
        """
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def _get_commands_by_category(category_slug: str):
    _ensure_catalog_tables()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        """
        SELECT c.slug, c.name, c.description, c.cost, c.usage_hint, c.is_active,
               cat.slug AS category_slug, cat.name AS category_name
        FROM command_catalog c
        JOIN command_categories cat ON cat.id = c.category_id
        WHERE cat.slug = ? AND cat.is_active = 1
        ORDER BY c.sort_order ASC, c.name ASC
        """,
        (category_slug,),
    )
    rows = [dict(row) for row in cur.fetchall()]
    conn.close()
    return rows


def _kb_home(categories: list[dict]):
    buttons = []
    row = []
    for cat in categories:
        row.append(
            InlineKeyboardButton(
                text=f"[{_icon_for_category(cat['slug'])}] {cat['name']}",
                callback_data=f"cmds_cat_{cat['slug']}_1",
            )
        )
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    return InlineKeyboardMarkup(buttons or [[InlineKeyboardButton("Sin categorías", callback_data="cmds_nav_home")]])


def _kb_category_nav(category_slug: str, page: int, total_pages: int):
    prev_page = total_pages if page <= 1 else page - 1
    next_page = 1 if page >= total_pages else page + 1
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("⬅️", callback_data=f"cmds_cat_{category_slug}_{prev_page}"),
            InlineKeyboardButton("🏠", callback_data="cmds_nav_home"),
            InlineKeyboardButton("➡️", callback_data=f"cmds_cat_{category_slug}_{next_page}"),
        ]
    ])


def _home_caption(cfg: dict, user) -> str:
    bot_name = (cfg.get("BOT_NAME") or "[#BOT] ➾").strip()
    nombre = html.escape(user.first_name or "Usuario")
    link = _user_link(user)
    return (
        f"<b>{bot_name} SISTEMA DE COMANDOS</b>\n\n"
        f"➣ Hola, <a href=\"{link}\">{nombre}</a>\n\n"
        "Bienvenido al menu principal de comandos.\n\n"
        "⚙️ Selecciona una categoría para ver los comandos activos."
    )


def _category_caption(cfg: dict, category: dict, commands: list[dict], page: int) -> str:
    bot_name = (cfg.get("BOT_NAME") or "[#BOT] ➾").strip()
    total_commands = len(commands)
    total_pages = max(1, math.ceil(total_commands / PAGE_SIZE))
    start = (page - 1) * PAGE_SIZE
    end = start + PAGE_SIZE
    items = commands[start:end]

    lines = [
        f"<b>{bot_name}</b> <i>SISTEMA DE COMANDOS</i>",
        f"🏷️ <b>CATEGORÍA</b> ➾ <code>{html.escape(category['name'])} [{_icon_for_category(category['slug'])}]</code>",
        f"🧩 <b>COMANDOS</b> ➾ <code>{total_commands}</code> disponibles",
        f"📖 <b>PÁGINA</b> ➾ <code>{page}/{total_pages}</code>",
        "",
    ]

    if not items:
        lines.append("⚠️ No hay comandos activos en esta categoría.")
        return "\n".join(lines)

    for cmd in items:
        fallback = DEFAULT_DETAILS.get(cmd["slug"], {})
        usage = cmd.get("usage_hint") or fallback.get("usage_hint") or f"/{cmd['slug']}"
        desc = cmd.get("description") or fallback.get("description") or "Sin descripción."
        is_active = bool(cmd.get("is_active"))
        lines.extend([
            f"📍 <b>{html.escape(cmd['name'])}</b>",
            "┈┈┈┈┈┈┈┈┈┈",
            f"{'🟢' if is_active else '🔴'} <b>ESTADO</b> ➾ <b>{'ACTIVO' if is_active else 'INACTIVO'}</b> {'✅' if is_active else '⛔'}",
            f"⌨️ <b>COMANDO</b> ➾ <code>{html.escape(usage)}</code>",
            f"💳 <b>PRECIO</b> ➾ <code>{int(cmd['cost'])} créditos</code>",
            f"📦 <b>INFO</b> ➾ <i>{html.escape(desc)}</i>",
            "",
        ])

    return "\n".join(lines).rstrip()


async def _send_or_edit_menu(message_or_query, text: str, markup, image_url: str | None, edit: bool):
    query = message_or_query if edit else None
    message = query.message if edit else message_or_query
    if edit:
        try:
            await query.edit_message_caption(caption=text, parse_mode="HTML", reply_markup=markup)
        except Exception:
            await query.edit_message_text(text=text, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
        return

    if image_url:
        await message.reply_photo(
            photo=image_url,
            caption=text,
            parse_mode="HTML",
            reply_markup=markup,
            reply_to_message_id=message.message_id,
        )
    else:
        await message.reply_text(
            text=text,
            parse_mode="HTML",
            reply_markup=markup,
            disable_web_page_preview=True,
            reply_to_message_id=message.message_id,
        )


async def cmds_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    cfg = _load_cfg()
    categories = _get_categories()
    await _send_or_edit_menu(
        update.effective_message,
        _home_caption(cfg, update.effective_user),
        _kb_home(categories),
        _get_menu_image(cfg),
        edit=False,
    )


async def cmds_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data or ""
    cfg = _load_cfg()
    categories = _get_categories()

    if data == "cmds_nav_home":
        await _send_or_edit_menu(
            query,
            _home_caption(cfg, update.effective_user),
            _kb_home(categories),
            _get_menu_image(cfg),
            edit=True,
        )
        await query.answer()
        return

    if data.startswith("cmds_cat_"):
        payload = data.removeprefix("cmds_cat_")
        category_slug, _, page_raw = payload.rpartition("_")
        if not category_slug:
            category_slug = payload
        try:
            page = max(1, int(page_raw or "1"))
        except Exception:
            page = 1

        category = next((c for c in categories if c["slug"] == category_slug), None)
        if not category:
            await query.answer("Categoría no disponible.", show_alert=True)
            return

        commands = _get_commands_by_category(category_slug)
        total_pages = max(1, math.ceil(max(1, len(commands)) / PAGE_SIZE))
        page = min(page, total_pages)

        await _send_or_edit_menu(
            query,
            _category_caption(cfg, category, commands, page),
            _kb_category_nav(category_slug, page, total_pages),
            _get_menu_image(cfg),
            edit=True,
        )
        await query.answer()
        return

    await query.answer()

import json
import os
import re

from telegram import Update
from telegram.ext import ContextTypes

from comandos.admin_requests import create_request
from comandos.utils import get_command_runtime_config, verificar_usuario

CONFIG_FILE_PATH = "config.json"

CFG = {}
try:
    if os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f) or {}
except Exception:
    CFG = {}

CMDS = CFG.get("CMDS", {}) or {}
ERRS = CFG.get("ERRORCONSULTA", {}) or {}

NOCRED_TXT = ERRS.get("NOCREDITSTXT") or "[❗] No tienes créditos suficientes."
NOCRED_FT = (ERRS.get("NOCREDITSFT") or "").strip() or None

PLATE_RE = re.compile(r"^[A-Za-z0-9]{1,3}[-]?[A-Za-z0-9]{1,4}[-]?[A-Za-z0-9]{0,3}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

VALIDATION_MESSAGES = {
    "missing": "Por favor, proporciona los datos después de /{command}.",
    "dni": "Por favor, introduce un número de DNI válido (8 dígitos).",
    "ruc": "Por favor, introduce un RUC válido (11 dígitos).",
    "phone": "Por favor, introduce un número válido.",
    "digits": "Por favor, introduce solo números.",
    "email": "Por favor, introduce un correo válido.",
    "plate": "Por favor, introduce una placa válida. Ejemplo: ABC123 o ABC-123.",
    "name": "Por favor, usa el formato correcto: /{command} nombre|paterno|materno",
}

LOADER_ALIASES = {
    "vehiculos": "SUNARP",
    "telefonia": "OSIPTEL",
    "familia": "RENIEC",
    "actas": "RENIEC",
    "extras": "EXTRAS",
    "delitos": "DELITOS",
    "laboral": "LABORAL",
    "migraciones": "MIGRACIONES",
    "reniec": "RENIEC",
    "sunarp": "SUNARP",
}

REQUEST_COMMANDS = [
    ("nm", 2, "reniec", "name"),
    ("dni", 1, "reniec", "dni"),
    ("dnif", 3, "reniec", "dni"),
    ("dnim", 2, "reniec", "dni"),
    ("c4", 5, "reniec", "dni"),
    ("c4blanco", 5, "reniec", "dni"),
    ("c4azul", 5, "reniec", "dni"),
    ("dnivel", 5, "reniec", "dni"),
    ("dnivam", 5, "reniec", "dni"),
    ("dnivaz", 5, "reniec", "dni"),
    ("revitec", 10, "vehiculos", "plate"),
    ("tiveqr", 15, "vehiculos", "plate"),
    ("soat", 7, "vehiculos", "plate"),
    ("tive", 8, "vehiculos", "plate"),
    ("tiveor", 10, "vehiculos", "plate"),
    ("tarjetafisica", 10, "vehiculos", "plate"),
    ("placasiento", 10, "vehiculos", "plate"),
    ("pla", 3, "vehiculos", "plate"),
    ("papeletas", 8, "vehiculos", "plate"),
    ("bolinv", 8, "vehiculos", "plate"),
    ("insve", 6, "vehiculos", "plate"),
    ("licencia", 5, "vehiculos", "dni"),
    ("licenciapdf", 8, "vehiculos", "dni"),
    ("rqv", 10, "delitos", "plate"),
    ("denunciasv", 10, "delitos", "plate"),
    ("det", 5, "delitos", "dni"),
    ("ant", 8, "delitos", "dni"),
    ("antpe", 7, "delitos", "dni"),
    ("antpo", 7, "delitos", "dni"),
    ("antju", 7, "delitos", "dni"),
    ("denuncias", 10, "delitos", "dni"),
    ("rq", 8, "delitos", "dni"),
    ("fis", 10, "delitos", "dni"),
    ("fispdf", 25, "delitos", "dni"),
    ("hogar", 5, "familia", "dni"),
    ("ag", 10, "familia", "dni"),
    ("agv", 20, "familia", "dni"),
    ("her", 5, "familia", "dni"),
    ("numclaro", 7, "telefonia", "phone"),
    ("correo", 3, "telefonia", "email"),
    ("enteldb", 3, "telefonia", "phone"),
    ("movistar", 7, "telefonia", "phone"),
    ("bitel", 7, "telefonia", "phone"),
    ("claro", 7, "telefonia", "phone"),
    ("vlop", 1, "telefonia", "phone"),
    ("vlnum", 1, "telefonia", "phone"),
    ("cel", 7, "telefonia", "phone"),
    ("tels", 5, "telefonia", "phone"),
    ("telp", 7, "telefonia", "phone"),
    ("tel", 3, "telefonia", "phone"),
    ("sunarp", 10, "sunarp", "dni"),
    ("sunarpdf", 20, "sunarp", "dni"),
    ("sueldos", 5, "laboral", "dni"),
    ("trabajos", 5, "laboral", "dni"),
    ("actamdb", 5, "actas", "dni"),
    ("actaddb", 5, "actas", "dni"),
    ("migrapdf", 6, "migraciones", "dni"),
    ("afp", 3, "extras", "dni"),
    ("dir", 3, "extras", "dni"),
    ("trabajadores", 8, "extras", "digits"),
    ("sbs", 5, "extras", "dni"),
    ("notas", 25, "extras", "dni"),
    ("essalud", 3, "extras", "dni"),
    ("doc", 3, "extras", "dni"),
    ("ruc", 5, "extras", "ruc"),
    ("sunat", 8, "extras", "ruc"),
    ("seeker", 10, "extras", "dni"),
    ("facial", 30, "reniec", "dni"),
]


def _first_arg(context: ContextTypes.DEFAULT_TYPE) -> str:
    return str((getattr(context, "args", None) or [""])[0]).strip()


def _validation_message(key: str, command: str) -> str:
    return (VALIDATION_MESSAGES.get(key) or VALIDATION_MESSAGES["missing"]).format(command=command)


def _validate_input(command: str, context: ContextTypes.DEFAULT_TYPE, validation: str) -> str | None:
    value = _first_arg(context)
    if not value:
        return _validation_message("missing", command)
    if validation == "dni" and not (value.isdigit() and len(value) == 8):
        return _validation_message("dni", command)
    if validation == "ruc" and not (value.isdigit() and len(value) == 11):
        return _validation_message("ruc", command)
    if validation == "phone" and not (value.isdigit() and 6 <= len(value) <= 15):
        return _validation_message("phone", command)
    if validation == "digits" and not value.isdigit():
        return _validation_message("digits", command)
    if validation == "email" and not EMAIL_RE.fullmatch(value):
        return _validation_message("email", command)
    if validation == "plate" and not PLATE_RE.fullmatch(value):
        return _validation_message("plate", command)
    if validation == "name" and len(" ".join(getattr(context, "args", []) or []).strip()) < 3:
        return _validation_message("name", command)
    return None


def _loader_assets(category_slug: str | None):
    alias = LOADER_ALIASES.get((category_slug or "").strip().lower(), (category_slug or "").strip().upper())
    loading_ft = (CMDS.get(f"FT_{alias}") or "").strip() or None
    loading_txt = (CMDS.get(f"TXT_{alias}") or "Consultando…").strip()
    return loading_ft, loading_txt


async def handle_request_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    command: str,
    default_cost: int,
    category_slug: str,
    validation: str,
):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return

    validation_error = _validate_input(command, context, validation)
    if validation_error:
        await msg.reply_text(validation_error, reply_to_message_id=msg.message_id)
        return

    valido, info_usuario = verificar_usuario(str(user.id))
    if not valido:
        await msg.reply_text("🚫 Tu cuenta no está activa o no existe.")
        return

    command_cfg = get_command_runtime_config(command, default_cost)
    if not command_cfg.get("is_active", True):
        await msg.reply_text("⚠️ Este comando está desactivado temporalmente.")
        return

    required_credits = int(command_cfg.get("cost") or default_cost)
    creditos = int(info_usuario.get("CREDITOS", 0))
    ilimitado = info_usuario.get("ilimitado", False)
    if not ilimitado and creditos < required_credits:
        if NOCRED_FT:
            await msg.reply_photo(photo=NOCRED_FT, caption=NOCRED_TXT, parse_mode="HTML")
        else:
            await msg.reply_text(NOCRED_TXT, parse_mode="HTML")
        return

    loader_category = command_cfg.get("category_slug") or category_slug
    loading_ft, loading_txt = _loader_assets(loader_category)
    try:
        if loading_ft:
            await msg.reply_photo(photo=loading_ft, caption=loading_txt, parse_mode="HTML")
        else:
            await msg.reply_text(loading_txt, parse_mode="HTML")
    except Exception:
        pass

    await create_request(update, context, command, cost=required_credits)


def make_request_command(command: str, default_cost: int, category_slug: str, validation: str):
    async def _command(update: Update, context: ContextTypes.DEFAULT_TYPE):
        await handle_request_command(update, context, command, default_cost, category_slug, validation)

    return _command

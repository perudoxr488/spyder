import os
import sys
import json
import time
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError
from urllib import parse as _urlparse
from telegram.ext import CommandHandler, Application, CallbackQueryHandler, MessageHandler, filters

from comandos.start import start_command
from comandos.buy import buy_command, buy_callback
from comandos.me import me_command
from comandos.register import register_command
from comandos.terminos import terminos_command
from comandos.cmds import cmds_command, cmds_callback
from comandos.historial import historial_command
from comandos.compras import compras_command
from comandos.admin_ops import (
    setcred_command, cred_command, uncred_command,
    setsub_command, sub_command, unsub_command,
    setrol_command, setantispam_command
)
from comandos.cmdsadmin import cmdsadmin_command
from comandos.precios import precios_command
from comandos.genkey import genkey, redeem, keyslog, keysinfo
from comandos import admin_requests
from comandos.manual_catalog import manual_catalog_command
from comandos.request_catalog import REQUEST_COMMANDS, make_request_command
from comandos.system_ops import status_command, panel_command, backup_command
from comandos.broadcast import global_callback, global_command
from comandos.helpadmin import helpadmin_command
from comandos.admin_tools import (
    admin_tools_callback,
    ban_command,
    dm_command,
    errores_command,
    unban_command,
    user_command,
    ventas_command,
)

# ---------- Config ----------
CONFIG_FILE_PATH = 'config.json'
API_DB_BASE = ""
TELEGRAM_TOKEN = None
ADMIN_ID = None
INTERNAL_API_KEY = ""

config_data = {}
if os.path.exists(CONFIG_FILE_PATH):
    try:
        with open(CONFIG_FILE_PATH, 'r', encoding='utf-8') as f:
            config_data = json.load(f) or {}
    except json.JSONDecodeError as e:
        print(f"Advertencia: JSON inválido en '{CONFIG_FILE_PATH}': {e}")
    except Exception as e:
        print(f"Advertencia: no se pudo cargar '{CONFIG_FILE_PATH}': {e}")

TELEGRAM_TOKEN = (
    os.environ.get("SPIDERSYN_TOKEN_BOT")
    or os.environ.get("TOKEN_BOT")
    or config_data.get("TOKEN_BOT")
)
admin_raw = (
    os.environ.get("SPIDERSYN_ADMIN_ID")
    or os.environ.get("ADMIN_ID")
    or config_data.get("ADMIN_ID")
)
try:
    ADMIN_ID = int(admin_raw) if admin_raw is not None else None
except Exception:
    ADMIN_ID = None

API_DB_BASE = (
    os.environ.get("SPIDERSYN_API_BASE")
    or os.environ.get("API_BASE")
    or os.environ.get("API_DB_BASE")
    or config_data.get('API_DB_BASE')
    or config_data.get('API_BASE')
    or ""
).rstrip("/")

INTERNAL_API_KEY = (
    os.environ.get("SPIDERSYN_INTERNAL_API_KEY")
    or os.environ.get("INTERNAL_API_KEY")
    or config_data.get("INTERNAL_API_KEY")
    or config_data.get("TOKEN_BOT")
    or ""
).strip()

if not TELEGRAM_TOKEN or ADMIN_ID is None or not API_DB_BASE:
    print("Error: faltan variables requeridas para iniciar el bot.")
    print("Necesitas definir TOKEN_BOT, ADMIN_ID y API_BASE/API_DB_BASE en variables de entorno o config.json.")
    sys.exit(1)

print(f"ID admin cargado: {ADMIN_ID}")
print(f"API base cargada: {API_DB_BASE}")
    
# ---------- Anti-spam helpers ----------
# Memoria del último uso por usuario y comando
_last_call_ts: dict[tuple[int, str], float] = {}

def _fetch_json(url: str, timeout: int = 12):
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

def _get_antispam_seconds(user_id: int) -> int:
    """
    Lee ANTISPAM desde /tg_info. Fallback: 15s si falla o no viene.
    """
    st, js = _fetch_json(f"{API_DB_BASE}/tg_info?ID_TG={_urlparse.quote(str(user_id))}")
    if st == 200:
        data = (js.get("data") or {})
        try:
            val = int(data.get("ANTISPAM", 15))
            return max(0, val)
        except Exception:
            return 15
    # si no está registrado o falla, aplica 15s por defecto
    return 15

def anti_spam_guard(handler_coro, cmd_name: str, skip_empty_args: bool = False):
    """
    Devuelve un wrapper async que respeta el anti-spam por usuario/command.
    """
    async def _wrapped(update, context):
        # Si no hay usuario/mensaje, delega
        if not getattr(update, "effective_user", None) or not getattr(update, "effective_message", None):
            return await handler_coro(update, context)

        user_id = update.effective_user.id
        if skip_empty_args and not getattr(context, "args", None):
            return await handler_coro(update, context)
        key = (user_id, cmd_name)
        now = time.monotonic()
        antispam = _get_antispam_seconds(user_id)

        last = _last_call_ts.get(key)
        if last is not None and (now - last) < antispam:
            wait = int(antispam - (now - last)) + 1
            # Mensaje consistente con lo que reconoce tu parser:
            # "UPS, POR FAVOR ESPERA EL ANTI-SPAM DE X SEGUNDOS."
            await update.effective_message.reply_text(
                f"UPS, por favor espera el anti-spam de {wait} segundos.",
                reply_to_message_id=update.effective_message.message_id
            )
            return

        # marca desde YA para evitar race al ejecutar
        _last_call_ts[key] = now
        await handler_coro(update, context)

    return _wrapped


def add_command_handler(application, command_name: str, handler_coro, use_antispam: bool = False, skip_empty_args_antispam: bool = False):
    wrapped = anti_spam_guard(handler_coro, command_name, skip_empty_args=skip_empty_args_antispam) if use_antispam else handler_coro
    application.add_handler(CommandHandler(command_name, wrapped))


def _fetch_dynamic_command_slugs() -> list[str]:
    st, js = _fetch_json(f"{API_DB_BASE}/bot_catalog", timeout=15)
    if st != 200 or (js or {}).get("status") != "ok":
        return []
    commands = ((js or {}).get("data") or {}).get("commands") or []
    reserved = {
        "start", "buy", "me", "register", "terminos", "historial", "compras", "status", "panel", "backup",
        "global", "helpadmin", "dm", "ban", "unban", "user", "ventas", "errores", "setcred", "cred",
        "uncred", "setsub", "sub", "unsub", "setrol", "setantispam", "cmds", "cmdsadmin", "genkey",
        "redeem", "keyslog", "keysinfo", "reply", "pending", "solicitudes", "close", "done", "fail",
        "templates", "rquick", "requestlog", "reopen", "precios",
    }
    reserved.update(command_name for command_name, *_ in REQUEST_COMMANDS)
    slugs = []
    for cmd in commands:
        slug = str(cmd.get("slug") or "").strip().lower()
        if not slug or slug in reserved or not slug.replace("_", "").replace("-", "").isalnum():
            continue
        if not bool(cmd.get("is_active", True)):
            continue
        slugs.append(slug)
    return sorted(set(slugs))

# ---------- Main ----------
def main():
    admin_requests.init_db()
    application = Application.builder().token(TELEGRAM_TOKEN).build()

    # Públicos / generales
    add_command_handler(application, "start", start_command)
    add_command_handler(application, "buy", buy_command)
    add_command_handler(application, "me", me_command)
    add_command_handler(application, "register", register_command)
    add_command_handler(application, "terminos", terminos_command)
    add_command_handler(application, "historial", historial_command, use_antispam=True)
    add_command_handler(application, "compras", compras_command, use_antispam=True)
    add_command_handler(application, "status", status_command)
    add_command_handler(application, "panel", panel_command)
    add_command_handler(application, "backup", backup_command)
    add_command_handler(application, "global", global_command)
    add_command_handler(application, "helpadmin", helpadmin_command)
    add_command_handler(application, "dm", dm_command)
    add_command_handler(application, "ban", ban_command)
    add_command_handler(application, "unban", unban_command)
    add_command_handler(application, "user", user_command)
    add_command_handler(application, "ventas", ventas_command)
    add_command_handler(application, "errores", errores_command)

    # Admin ops
    add_command_handler(application, "setcred", setcred_command)
    add_command_handler(application, "cred", cred_command)
    add_command_handler(application, "uncred", uncred_command)

    add_command_handler(application, "setsub", setsub_command)
    add_command_handler(application, "sub", sub_command)
    add_command_handler(application, "unsub", unsub_command)

    add_command_handler(application, "setrol", setrol_command)
    add_command_handler(application, "setantispam", setantispam_command)

    # -------------------- CMDS Y MENU ADMIN --------------------
    add_command_handler(application, "cmds", cmds_command)
    application.add_handler(CallbackQueryHandler(cmds_callback, pattern="^cmds_"))
    application.add_handler(CallbackQueryHandler(buy_callback, pattern="^buy:"))
    application.add_handler(CallbackQueryHandler(global_callback, pattern="^global_"))
    application.add_handler(CallbackQueryHandler(admin_tools_callback, pattern="^admintool:"))
    application.add_handler(CallbackQueryHandler(admin_requests.request_buttons_callback, pattern="^adminreq:"))
    add_command_handler(application, "cmdsadmin", cmdsadmin_command)
    
    # Consultas manuales del catálogo. Todas comparten validación, créditos,
    # loader y creación de solicitud al admin.
    for command_name, default_cost, category_slug, validation in REQUEST_COMMANDS:
        add_command_handler(
            application,
            command_name,
            make_request_command(command_name, default_cost, category_slug, validation),
            use_antispam=True,
        )
    
    # -------------------- GENERAR Y CANJEAR KEYS --------------------
    add_command_handler(application, "genkey", genkey)
    add_command_handler(application, "redeem", redeem, use_antispam=True)
    add_command_handler(application, "keyslog", keyslog)
    add_command_handler(application, "keysinfo", keysinfo)

    # --- Handlers del admin ---
    add_command_handler(application, "reply", admin_requests.reply_request)
    add_command_handler(application, "pending", admin_requests.pending_requests_command)
    add_command_handler(application, "solicitudes", admin_requests.pending_requests_command)
    add_command_handler(application, "close", admin_requests.close_request)
    add_command_handler(application, "done", admin_requests.done_request)
    add_command_handler(application, "fail", admin_requests.fail_request)
    add_command_handler(application, "templates", admin_requests.templates_command)
    add_command_handler(application, "rquick", admin_requests.quick_reply_command)
    add_command_handler(application, "requestlog", admin_requests.request_log_command)
    add_command_handler(application, "reopen", admin_requests.reopen_request)
    add_command_handler(application, "precios", precios_command)
    for dynamic_slug in _fetch_dynamic_command_slugs():
        add_command_handler(application, dynamic_slug, manual_catalog_command, use_antispam=True, skip_empty_args_antispam=True)
    application.add_handler(MessageHandler(filters.COMMAND, manual_catalog_command))
    application.add_handler(MessageHandler(filters.CaptionRegex(r"^/"), manual_catalog_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_requests.admin_followup_message))
    application.add_handler(MessageHandler(filters.ALL, admin_requests.forward_file))

    print("Bot started and polling for updates...")
    application.run_polling()

if __name__ == '__main__':
    main()

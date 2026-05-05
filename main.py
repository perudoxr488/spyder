import os
import sys
import json
import time
import sqlite3
from urllib import request as _urlreq
from urllib.error import HTTPError, URLError
from urllib import parse as _urlparse
from datetime import datetime
from telegram import Update
from telegram.ext import CommandHandler, Application, CallbackQueryHandler, ContextTypes, CallbackContext, MessageHandler, filters

from comandos.dnim import dnim_command
from comandos.c4blanco import c4blanco_command
from comandos.c4 import c4_command
from comandos.dnivel import dnivel_command
from comandos.dnivam import dnivam_command
from comandos.dnivaz import dnivaz_command
from comandos.c4azul import c4azul_command
from comandos.dni import dni_command
from comandos.dnif import dnif_command
from comandos.nm import nm_command
from comandos.revitec import revitec_command
from comandos.tiveqr import tiveqr_command
from comandos.soat import soat_command
from comandos.tive import tive_command
from comandos.tiveor import tiveor_command
from comandos.tarjetafisica import tarjetafisica_command
from comandos.placasiento import placasiento_command
from comandos.pla import pla_command
from comandos.papeletas import papeletas_command
from comandos.insve import insve_command
from comandos.licencia import licencia_command
from comandos.licenciapdf import licenciapdf_command
from comandos.bolinv import bolinv_command
from comandos.rqv import rqv_command
from comandos.denunciasv import denunciasv_command
from comandos.det import det_command
from comandos.ant import ant_command
from comandos.antpe import antpe_command
from comandos.antpo import antpo_command
from comandos.antju import antju_command
from comandos.denuncias import denuncias_command
from comandos.rq import rq_command
from comandos.fis import fis_command
from comandos.fispdf import fispdf_command
from comandos.hogar import hogar_command
from comandos.ag import ag_command
from comandos.agv import agv_command
from comandos.her import her_command
from comandos.numclaro import numclaro_command
from comandos.correo import correo_command
from comandos.enteldb import enteldb_command
from comandos.movistar import movistar_command
from comandos.bitel import bitel_command
from comandos.claro import claro_command
from comandos.vlop import vlop_command
from comandos.vlnum import vlnum_command
from comandos.cel import cel_command
from comandos.tels import tels_command
from comandos.telp import telp_command
from comandos.tel import tel_command
from comandos.sunarp import sunarp_command
from comandos.sunarpdf import sunarpdf_command
from comandos.sueldos import sueldos_command
from comandos.trabajos import trabajos_command
from comandos.actamdb import actamdb_command
from comandos.actaddb import actaddb_command
from comandos.migrapdf import migrapdf_command
from comandos.afp import afp_command
from comandos.dir import dir_command
from comandos.trabajadores import trabajadores_command
from comandos.sbs import sbs_command
from comandos.notas import notas_command
from comandos.essalud import essalud_command
from comandos.doc import doc_command
from comandos.ruc import ruc_command
from comandos.sunat import sunat_command
from comandos.seeker import seeker_command
from comandos.facial import facial_command
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
from comandos.system_ops import status_command, panel_command, backup_command
from comandos.broadcast import global_command

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

def anti_spam_guard(handler_coro, cmd_name: str):
    """
    Devuelve un wrapper async que respeta el anti-spam por usuario/command.
    """
    async def _wrapped(update, context):
        # Si no hay usuario/mensaje, delega
        if not getattr(update, "effective_user", None) or not getattr(update, "effective_message", None):
            return await handler_coro(update, context)

        user_id = update.effective_user.id
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


def add_command_handler(application, command_name: str, handler_coro, use_antispam: bool = False):
    wrapped = anti_spam_guard(handler_coro, command_name) if use_antispam else handler_coro
    application.add_handler(CommandHandler(command_name, wrapped))

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
    application.add_handler(CallbackQueryHandler(admin_requests.request_buttons_callback, pattern="^adminreq:"))
    add_command_handler(application, "cmdsadmin", cmdsadmin_command)
    
    # -------------------- COMANDOS RENIEC --------------------
    add_command_handler(application, "nm", nm_command, use_antispam=True)
    add_command_handler(application, "dni", dni_command, use_antispam=True)
    add_command_handler(application, "dnif", dnif_command, use_antispam=True)
    add_command_handler(application, "dnim", dnim_command, use_antispam=True)
    add_command_handler(application, "c4", c4_command, use_antispam=True)
    add_command_handler(application, "c4blanco", c4blanco_command, use_antispam=True)
    add_command_handler(application, "c4azul", c4azul_command, use_antispam=True)
    add_command_handler(application, "dnivel", dnivel_command, use_antispam=True)
    add_command_handler(application, "dnivam", dnivam_command, use_antispam=True)
    add_command_handler(application, "dnivaz", dnivaz_command, use_antispam=True)

    # -------------------- COMANDOS VEHICULO --------------------
    add_command_handler(application, "revitec", revitec_command, use_antispam=True)
    add_command_handler(application, "tiveqr", tiveqr_command, use_antispam=True)
    add_command_handler(application, "soat", soat_command, use_antispam=True)
    add_command_handler(application, "tive", tive_command, use_antispam=True)
    add_command_handler(application, "tiveor", tiveor_command, use_antispam=True)
    add_command_handler(application, "tarjetafisica", tarjetafisica_command, use_antispam=True)
    add_command_handler(application, "placasiento", placasiento_command, use_antispam=True)
    add_command_handler(application, "pla", pla_command, use_antispam=True)
    add_command_handler(application, "papeletas", papeletas_command, use_antispam=True)
    add_command_handler(application, "bolinv", bolinv_command, use_antispam=True)
    add_command_handler(application, "insve", insve_command, use_antispam=True)
    add_command_handler(application, "licencia", licencia_command, use_antispam=True)
    add_command_handler(application, "licenciapdf", licenciapdf_command, use_antispam=True)

    # -------------------- COMANDOS DELITOS --------------------
    add_command_handler(application, "rqv", rqv_command, use_antispam=True)
    add_command_handler(application, "denunciasv", denunciasv_command, use_antispam=True)
    add_command_handler(application, "det", det_command, use_antispam=True)
    add_command_handler(application, "ant", ant_command, use_antispam=True)
    add_command_handler(application, "antpe", antpe_command, use_antispam=True)
    add_command_handler(application, "antpo", antpo_command, use_antispam=True)
    add_command_handler(application, "antju", antju_command, use_antispam=True)
    add_command_handler(application, "denuncias", denuncias_command, use_antispam=True)
    add_command_handler(application, "rq", rq_command, use_antispam=True)
    add_command_handler(application, "fis", fis_command, use_antispam=True)
    add_command_handler(application, "fispdf", fispdf_command, use_antispam=True)

    # -------------------- COMANDOS FAMILIA --------------------
    add_command_handler(application, "hogar", hogar_command, use_antispam=True)
    add_command_handler(application, "ag", ag_command, use_antispam=True)
    add_command_handler(application, "agv", agv_command, use_antispam=True)
    add_command_handler(application, "her", her_command, use_antispam=True)

    # -------------------- COMANDOS TELEFONIA --------------------
    add_command_handler(application, "numclaro", numclaro_command, use_antispam=True)
    add_command_handler(application, "correo", correo_command, use_antispam=True)
    add_command_handler(application, "enteldb", enteldb_command, use_antispam=True)
    add_command_handler(application, "movistar", movistar_command, use_antispam=True)
    add_command_handler(application, "bitel", bitel_command, use_antispam=True)
    add_command_handler(application, "claro", claro_command, use_antispam=True)
    add_command_handler(application, "vlop", vlop_command, use_antispam=True)
    add_command_handler(application, "vlnum", vlnum_command, use_antispam=True)
    add_command_handler(application, "cel", cel_command, use_antispam=True)
    add_command_handler(application, "tels", tels_command, use_antispam=True)
    add_command_handler(application, "telp", telp_command, use_antispam=True)
    add_command_handler(application, "tel", tel_command, use_antispam=True)

    # -------------------- COMANDOS SUNARP --------------------
    add_command_handler(application, "sunarp", sunarp_command, use_antispam=True)
    add_command_handler(application, "sunarpdf", sunarpdf_command, use_antispam=True)

    # -------------------- COMANDOS LABORAL --------------------
    add_command_handler(application, "sueldos", sueldos_command, use_antispam=True)
    add_command_handler(application, "trabajos", trabajos_command, use_antispam=True)

    # -------------------- COMANDOS ACTAS --------------------
    add_command_handler(application, "actamdb", actamdb_command, use_antispam=True)
    add_command_handler(application, "actaddb", actaddb_command, use_antispam=True)

    # -------------------- COMANDOS MIGRACIONES --------------------
    add_command_handler(application, "migrapdf", migrapdf_command, use_antispam=True)

    # -------------------- COMANDOS VARIOS --------------------
    add_command_handler(application, "afp", afp_command, use_antispam=True)
    add_command_handler(application, "dir", dir_command, use_antispam=True)
    add_command_handler(application, "trabajadores", trabajadores_command, use_antispam=True)
    add_command_handler(application, "sbs", sbs_command, use_antispam=True)
    add_command_handler(application, "notas", notas_command, use_antispam=True)
    add_command_handler(application, "essalud", essalud_command, use_antispam=True)
    add_command_handler(application, "doc", doc_command, use_antispam=True)
    add_command_handler(application, "ruc", ruc_command, use_antispam=True)
    add_command_handler(application, "sunat", sunat_command, use_antispam=True)
    add_command_handler(application, "seeker", seeker_command, use_antispam=True)
    add_command_handler(application, "facial", facial_command, use_antispam=True)
    
    # -------------------- GENERAR Y CANJEAR KEYS --------------------
    add_command_handler(application, "genkey", genkey)
    add_command_handler(application, "redeem", redeem, use_antispam=True)
    add_command_handler(application, "keyslog", keyslog)
    add_command_handler(application, "keysinfo", keysinfo)

    # --- Handlers del admin ---
    add_command_handler(application, "reply", admin_requests.reply_request)
    add_command_handler(application, "pending", admin_requests.pending_requests_command)
    add_command_handler(application, "close", admin_requests.close_request)
    add_command_handler(application, "done", admin_requests.done_request)
    add_command_handler(application, "fail", admin_requests.fail_request)
    add_command_handler(application, "templates", admin_requests.templates_command)
    add_command_handler(application, "rquick", admin_requests.quick_reply_command)
    add_command_handler(application, "requestlog", admin_requests.request_log_command)
    add_command_handler(application, "reopen", admin_requests.reopen_request)
    add_command_handler(application, "precios", precios_command)
    application.add_handler(MessageHandler(filters.COMMAND, manual_catalog_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, admin_requests.admin_followup_message))
    application.add_handler(MessageHandler(filters.ALL, admin_requests.forward_file))

    print("Bot started and polling for updates...")
    application.run_polling()

if __name__ == '__main__':
    main()

from telegram import Update
from telegram.ext import ContextTypes
from comandos.admin_requests import create_request

# Importamos helpers que ya tienes en nm.py (kv, divider, etc.)
import html
from datetime import datetime, timezone
from urllib import parse as _urlparse
from urllib import request as _urlreq
import os, json
import re

CONFIG_FILE_PATH = "config.json"
CFG = {}
try:
    if os.path.exists(CONFIG_FILE_PATH):
        with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
            CFG = json.load(f)
except Exception:
    CFG = {}

BOT_NAME = (CFG.get("BOT_NAME") or "").strip() or "BOT"
CMDS = CFG.get("CMDS", {}) or {}
ERRS = CFG.get("ERRORCONSULTA", {}) or {}

NOCRED_TXT = ERRS.get("NOCREDITSTXT") or "[❗] No tienes créditos suficientes."
NOCRED_FT  = (ERRS.get("NOCREDITSFT") or "").strip() or None

# =============== Comando principal ===============
async def placa_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    id_tg = str(user.id)

    if not context.args:
        await update.message.reply_text(
            "Por favor, proporciona el número de placa después de /placa.",
            reply_to_message_id=update.message.message_id
        )
        return

    placa = context.args[0]

    # Expresión regular para validar los formatos de placas antiguos y modernos, con o sin guion
    if not re.match(r'^[A-Za-z0-9]{1,3}[-]?[A-Za-z0-9]{1,3}[-]?[A-Za-z0-9]{1,3}$', placa):
        await update.message.reply_text(
        "Por favor, introduce una placa válida. Formatos válidos: \n"
        "- Antiguo: ABC-1234 o 1234-ABC\n"
        "- Moderno: ABC123 o 123ABC\n"
        "- El guion puede estar en cualquier lugar o no estar presente.",
        reply_to_message_id=update.message.message_id
        )
        return

    # 1) Validar créditos igual que en el antiguo nm.py
    from comandos.utils import verificar_usuario, descontar_creditos, get_command_runtime_config
    valido, info_usuario = verificar_usuario(id_tg)
    if not valido:
        await msg.reply_text("🚫 Tu cuenta no está activa o no existe.")
        return

    ilimitado = info_usuario.get("ilimitado", False)
    creditos = int(info_usuario.get("CREDITOS", 0))

    command_cfg = get_command_runtime_config("placa", 5)
    required_credits = int(command_cfg.get("cost", 5))
    if not command_cfg.get("is_active", True):
        await msg.reply_text("⚠️ Este comando está desactivado temporalmente.")
        return

    if not ilimitado:
        if creditos < required_credits:
            if NOCRED_FT:
                await msg.reply_photo(photo=NOCRED_FT, caption=NOCRED_TXT, parse_mode="HTML")
            else:
                await msg.reply_text(NOCRED_TXT, parse_mode="HTML")
            return

    # 2) Mostrar mensaje de loader
    loading_ft = (CMDS.get("FT_SUNARP") or "").strip() or None
    loading_txt = (CMDS.get("TXT_SUNARP") or "Consultando…").strip()
    try:
        if loading_ft:
            await msg.reply_photo(photo=loading_ft, caption=loading_txt, parse_mode="HTML")
        else:
            await msg.reply_text(loading_txt, parse_mode="HTML")
    except:
        pass

    # 3) Crear solicitud al admin en vez de llamar API externa
    await create_request(update, context, "placa", cost=required_credits)
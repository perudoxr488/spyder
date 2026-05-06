import html
import json
import os

from telegram import Update
from telegram.ext import ContextTypes

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_FILE_PATH = os.path.join(BASE_DIR, "config.json")

CFG = {}
try:
    if os.path.exists(CONFIG_FILE_PATH):
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


def _is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS


def _brand() -> str:
    raw = (CFG.get("BOT_NAME") or CFG.get("NAME") or "#NEXORA").strip() or "#NEXORA"
    return "#NEXORA" if raw.upper() in {"SPIDERSYN", "#SPIDERSYN"} else raw


async def helpadmin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message
    user = update.effective_user
    if not msg or not user:
        return
    if not _is_admin(user.id):
        await msg.reply_text("No tienes permisos para usar /helpadmin.", reply_to_message_id=msg.message_id)
        return

    lines = [
        f"<b>{html.escape(_brand())} ⇒ HELP ADMIN</b>",
        "<i>Guía rápida de operación desde Telegram.</i>",
        "",
        "<b>Diagnóstico</b>",
        "<code>/panel</code> - Link del panel",
        "<code>/status</code> - Web, worker, DB, catálogo, keys, solicitudes y errores",
        "<code>/errores</code> - Últimos errores 500/API",
        "<code>/backup</code> - Descargar backup ZIP de DB",
        "",
        "<b>Usuarios y saldo</b>",
        "<code>/setcred ID|PLAN|CANTIDAD</code> - Igualar créditos. Ej: <code>/setcred 7454664711|PREMIUM|300</code>",
        "<code>/cred ID|PLAN|CANTIDAD</code> - Sumar créditos. Ej: <code>/cred 7454664711|PREMIUM|50</code>",
        "<code>/uncred ID|PLAN|CANTIDAD</code> - Restar créditos. Ej: <code>/uncred 7454664711|PREMIUM|10</code>",
        "<code>/setsub ID|PLAN|DIAS</code> - Igualar días. Ej: <code>/setsub 7454664711|PREMIUM|30</code>",
        "<code>/sub ID|PLAN|DIAS</code> - Sumar días. Ej: <code>/sub 7454664711|PREMIUM|7</code>",
        "<code>/unsub ID|PLAN|DIAS</code> - Restar días. Ej: <code>/unsub 7454664711|PREMIUM|7</code>",
        "<code>/setrol ID|ROL</code> - Cambiar rol. Ej: <code>/setrol 7454664711|SELLER</code>",
        "<code>/setantispam ID|SEGUNDOS</code> - Cambiar anti-spam. Ej: <code>/setantispam 7454664711|5</code>",
        "<code>/user ID</code> - Perfil admin rápido. Ej: <code>/user 7454664711</code>",
        "<code>/dm ID mensaje</code> - Mensaje directo. Ej: <code>/dm 7454664711 Hola</code>",
        "<code>/ban ID</code> y <code>/unban ID</code> - Ban/desban con confirmación",
        "",
        "<b>Keys</b>",
        "<code>/genkey dias 30</code> - 1 key de 30 días",
        "<code>/genkey creditos 100</code> - 1 key de 100 créditos",
        "<code>/genkey dias 30 3 10</code> - 10 keys, 3 usos cada una",
        "<code>/keysinfo KEY</code> - Ver estado de una key",
        "<code>/keyslog</code> - Últimos canjes",
        "",
        "<b>Solicitudes</b>",
        "<code>/pending</code> - Ver pendientes",
        "<code>/solicitudes</code> - Alias bonito de pendientes",
        "<code>/reply ID texto</code> - Responder y cobrar",
        "<code>/rquick ID plantilla</code> - Responder con plantilla",
        "<code>/done ID</code> - Finalizar solicitud",
        "<code>/close ID motivo</code> - Cerrar sin cobrar",
        "<code>/fail ID motivo</code> - Marcar fallida",
        "<code>/reopen ID</code> - Reabrir",
        "<code>/requestlog 20</code> - Historial rápido",
        "",
        "<b>Mensajes</b>",
        "<code>/global mensaje</code> - Preparar mensaje global con preview",
        "<code>/global --all mensaje</code> - Incluir baneados",
        "También puedes responder una foto/archivo con <code>/global</code>.",
        "",
        "<b>Catálogo</b>",
        "<code>/cmds</code> - Menú público de comandos",
        "<code>/cmdsadmin</code> - Comandos activos y precios",
        "<code>/buy</code> - Menú público de compra",
        "<code>/precios</code> - Vista rápida de precios",
        "<code>/ventas</code> - Resumen de ventas",
        "",
        "<b>Flujos rápidos</b>",
        "Atender solicitud: <code>/pending</code> → <code>/rquick ID completado</code> → <code>/done ID</code>",
        "Dar plan: <code>/setsub ID|PREMIUM|30</code>",
        "Dar créditos: <code>/cred ID|PREMIUM|100</code>",
        "Revisar sistema: <code>/status</code> y luego <code>/errores</code> si algo sale mal",
    ]
    await msg.reply_text(
        "\n".join(lines),
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_to_message_id=msg.message_id,
    )

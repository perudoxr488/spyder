# comandos/terminos.py
import os
import json
from telegram import Update
from telegram.ext import ContextTypes

CONFIG_FILE_PATH = "config.json"

def _get_bot_name() -> str:
    bot_name = "#NEXORA ⇒"
    if os.path.exists(CONFIG_FILE_PATH):
        try:
            with open(CONFIG_FILE_PATH, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            # En tu config sueles tener algo como "<code>[</code>#TUSSYBOT<code>]</code> ➾"
            # Para evitar etiquetas HTML aquí, limpiamos si es necesario
            raw = (cfg.get("BOT_NAME") or "").strip()
            if raw and raw.upper() not in {"SPIDERSYN", "#SPIDERSYN", "#SPIDERSYN ⇒"}:
                # Si viene con etiquetas HTML, quítalas para este texto plano
                # (dejamos solo el texto visible aproximado)
                bot_name = raw.replace("<code>", "").replace("</code>", "")
        except Exception:
            pass
    return bot_name.strip()

async def terminos_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    bot_name = _get_bot_name()
    header = f"{bot_name} TERMINOS Y CONDICIONES"

    texto = (
    f"<b>{header}</b>\n\n"
    "[💰] <b>REEMBOLSOS</b>\n"
    "No ofrecemos devoluciones. Si compraste créditos o planes a través de un vendedor, reclama directamente con él. No podemos gestionar devoluciones.\n\n"
    "[🛠] <b>GARANTÍA</b>\n"
    "Si el bot falla o algún comando no funciona, ten paciencia. No garantizamos funcionamiento perfecto y no contactes soporte por inconvenientes menores.\n\n"
    "[🚫] <b>USO PROHIBIDO</b>\n"
    "No revendas, compartas accesos ni pases info a otros bots. Infracciones resultarán en suspensión permanente.\n\n"
    "[👀] <b>USO INADECUADO</b>\n"
    "No uses el bot para actividades ilegales. Problemas legales no son nuestra responsabilidad.\n\n"
    "[📵] <b>ABUSO Y SPAM</b>\n"
    "Uso excesivo o irresponsable de comandos puede causar cooldown o suspensión. Usa el bot con responsabilidad.\n\n"
    "[⚠️] <b>SOLICITUDES INAPROPIADAS</b>\n"
    "Si solo quieres preguntar sin intención de comprar, abstente de solicitar recursos innecesarios.\n\n"
    "[📌] <b>MODIFICACIONES</b>\n"
    "Podemos cambiar estos términos en cualquier momento sin previo aviso. Revisa regularmente para estar al día.\n\n"
    "[⚠️] <b>IMPORTANTE</b> ➩ Una vez leído, usa <b>/buy</b> para comprar."
)

    msg = update.effective_message
    await msg.reply_text(
        texto,
        parse_mode="HTML",
        disable_web_page_preview=True,
        reply_to_message_id=msg.message_id
    )

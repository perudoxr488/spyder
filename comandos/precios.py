import html
from telegram import Update
from telegram.ext import ContextTypes

from comandos.precios_config import PRECIOS_COMANDOS


async def precios_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.effective_message

    if not PRECIOS_COMANDOS:
        await msg.reply_text(
            "⚠️ No hay precios configurados.",
            reply_to_message_id=msg.message_id
        )
        return

    texto = []
    texto.append("💳 <b>PRECIOS DEL BOT</b>\n")

    for comando, precio in sorted(PRECIOS_COMANDOS.items()):
        texto.append(f"• <b>{html.escape(comando.upper())}</b> → <code>{precio}</code> créditos")

    await msg.reply_text(
        "\n".join(texto),
        parse_mode="HTML",
        reply_to_message_id=msg.message_id
    )
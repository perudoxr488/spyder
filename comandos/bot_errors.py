import html


def api_error_text(action: str, status: int, data=None) -> str:
    payload = data if isinstance(data, dict) else {}
    raw = str(payload.get("message") or payload.get("error") or "").strip()
    if status == 599:
        title = "No se pudo conectar con Railway/API."
        hint = "Revisa que el servicio web esté Online y que API_BASE apunte al dominio correcto."
    elif status in {401, 403}:
        title = "La API rechazó la solicitud."
        hint = "Revisa que SPIDERSYN_INTERNAL_API_KEY sea igual en web y worker."
    elif status == 404:
        title = "La ruta no existe en la API."
        hint = "Puede faltar deploy o el worker está llamando un endpoint viejo."
    elif status >= 500:
        title = f"Railway devolvió error {status}."
        hint = "Mira Deploy Logs y la sección Sistema del panel para ver el traceback."
    elif status >= 400:
        title = f"La API respondió {status}."
        hint = raw or "Revisa los datos enviados al comando."
    else:
        title = "La API no respondió como se esperaba."
        hint = raw or "Intenta de nuevo y revisa /status."
    detail = raw if raw and raw != hint else hint
    return (
        f"<b>#NEXORA ⇒ ERROR API</b>\n"
        f"Acción: <code>{html.escape(action)}</code>\n"
        f"Código: <code>{status}</code>\n"
        f"Estado: {html.escape(title)}\n"
        f"Detalle: {html.escape(detail[:700])}\n\n"
        f"Sugerencia: {html.escape(hint)}"
    )

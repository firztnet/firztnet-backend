"""Envío del comprobante por email (real, vía SMTP) y generación del
enlace de WhatsApp (wa.me) con el mensaje ya redactado."""
import os
import smtplib
import urllib.parse
from email.message import EmailMessage

# Configura estas variables de entorno antes de arrancar el servidor
# (o ponlas en un archivo .env). Con Gmail, EMAIL_PASSWORD debe ser una
# "contraseña de aplicación", no tu contraseña normal:
# https://myaccount.google.com/apppasswords
EMAIL_REMITENTE = os.environ.get("EMAIL_REMITENTE")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
EMAIL_SMTP_HOST = os.environ.get("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.environ.get("EMAIL_SMTP_PORT", "465"))

MENSAJES = {
    "recepcion": (
        "Hola {nombre}, hemos recibido tu equipo ({equipo}) en Firztnet. "
        "Nº de orden: {numero_orden}. Te avisaremos en cuanto tengamos novedades."
    ),
    "entrega": (
        "Hola {nombre}, tu equipo ({equipo}) ya está reparado y listo. "
        "Garantía válida hasta el {garantia}. ¡Gracias por confiar en Firztnet!"
    ),
    "no_reparable": (
        "Hola {nombre}, hemos revisado tu equipo ({equipo}) y lamentablemente no es reparable. "
        "Motivo: {motivo}. Puedes pasar a recogerlo cuando quieras."
    ),
}


def _texto_mensaje(reparacion, tipo):
    return MENSAJES.get(tipo, "Hola {nombre}, tenemos novedades sobre tu equipo.").format(
        nombre=reparacion.cliente.nombre.split(" ")[0] if reparacion.cliente else "",
        equipo=reparacion.equipo,
        numero_orden=reparacion.numero_orden,
        garantia=reparacion.fecha_fin_garantia.strftime("%d/%m/%Y") if reparacion.fecha_fin_garantia else "",
        motivo=reparacion.motivo_no_reparable or "",
    )


def enviar_email_comprobante(reparacion, tipo, pdf_buffer, nombre_archivo):
    """Envía el PDF adjunto al email del cliente. Requiere que el cliente
    tenga email guardado y que EMAIL_REMITENTE/EMAIL_PASSWORD estén
    configurados como variables de entorno."""
    if not reparacion.cliente or not reparacion.cliente.email:
        return {"enviado": False, "motivo": "El cliente no tiene email registrado"}
    if not EMAIL_REMITENTE or not EMAIL_PASSWORD:
        return {"enviado": False, "motivo": "Falta configurar EMAIL_REMITENTE / EMAIL_PASSWORD"}

    msg = EmailMessage()
    msg["Subject"] = f"Firztnet — {tipo.replace('_', ' ')} · orden {reparacion.numero_orden}"
    msg["From"] = EMAIL_REMITENTE
    msg["To"] = reparacion.cliente.email
    msg.set_content(_texto_mensaje(reparacion, tipo))

    msg.add_attachment(pdf_buffer.getvalue(), maintype="application", subtype="pdf", filename=nombre_archivo)

    with smtplib.SMTP_SSL(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=12) as server:
        server.login(EMAIL_REMITENTE, EMAIL_PASSWORD)
        server.send_message(msg)

    return {"enviado": True}


def generar_enlace_whatsapp(reparacion, tipo):
    """Genera un enlace wa.me con el mensaje pre-escrito. No requiere
    ninguna cuenta ni API — solo hace falta el teléfono del cliente."""
    if not reparacion.cliente or not reparacion.cliente.telefono:
        return None
    telefono = "".join(ch for ch in reparacion.cliente.telefono if ch.isdigit())
    if not telefono.startswith("34") and len(telefono) == 9:
        telefono = "34" + telefono  # prefijo España si no lo trae
    texto = urllib.parse.quote(_texto_mensaje(reparacion, tipo))
    return f"https://wa.me/{telefono}?text={texto}"

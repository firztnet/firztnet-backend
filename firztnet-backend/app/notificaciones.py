"""Envío del comprobante por email (vía la API de Resend, por HTTPS —
no por SMTP, porque Railway bloquea las conexiones salientes directas
a los puertos de correo) y generación del enlace de WhatsApp (wa.me)
con el mensaje ya redactado."""
import os
import base64
import urllib.parse
import urllib.request
import json

# Configura estas dos variables de entorno antes de arrancar el servidor:
# RESEND_API_KEY  -> la API key que te da resend.com (gratis, sin tarjeta)
# EMAIL_REMITENTE -> el email que aparece como remitente. Mientras no
#   verifiques tu propio dominio en Resend, usa "onboarding@resend.dev"
#   (funciona igual, solo cambia lo que ve el cliente en el "De:").
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")
EMAIL_REMITENTE = os.environ.get("EMAIL_REMITENTE", "onboarding@resend.dev")

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
    """Envía el PDF adjunto al email del cliente vía la API de Resend.
    Requiere que el cliente tenga email guardado y que RESEND_API_KEY
    esté configurada como variable de entorno."""
    if not reparacion.cliente or not reparacion.cliente.email:
        return {"enviado": False, "motivo": "El cliente no tiene email registrado"}
    if not RESEND_API_KEY:
        return {"enviado": False, "motivo": "Falta configurar RESEND_API_KEY"}

    pdf_base64 = base64.b64encode(pdf_buffer.getvalue()).decode("ascii")

    payload = json.dumps({
        "from": f"Firztnet <{EMAIL_REMITENTE}>",
        "to": [reparacion.cliente.email],
        "subject": f"Firztnet — {tipo.replace('_', ' ')} · orden {reparacion.numero_orden}",
        "text": _texto_mensaje(reparacion, tipo),
        "attachments": [{"filename": nombre_archivo, "content": pdf_base64}],
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
        return {"enviado": True}
    except urllib.error.HTTPError as e:
        detalle = e.read().decode("utf-8", errors="ignore")
        return {"enviado": False, "motivo": f"Resend respondió {e.code}: {detalle[:200]}"}
    except Exception as e:
        return {"enviado": False, "motivo": str(e)}


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

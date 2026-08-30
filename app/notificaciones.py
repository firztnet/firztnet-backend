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
            # Sin esto, algunas peticiones automáticas (como las de
            # Python) quedan bloqueadas por la protección anti-bots de
            # Cloudflare delante de la API de Resend (error 1010).
            "User-Agent": "Firztnet/1.0 (+https://firztnet.es)",
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


def _telefono_whatsapp(telefono):
    if not telefono:
        return None
    digitos = "".join(ch for ch in telefono if ch.isdigit())
    if not digitos.startswith("34") and len(digitos) == 9:
        digitos = "34" + digitos
    return digitos


FRONTEND_URL = os.environ.get("FRONTEND_URL", "https://firztnet-preview.vercel.app")


def renderizar_plantilla(texto_plantilla, reparacion):
    """Rellena los huecos {cliente}, {equipo}, {numero_orden}, {estado},
    {fecha_estimada}, {garantia}, {enlace_seguimiento} de una plantilla
    con los datos reales de la reparación. {enlace_seguimiento} lleva al
    cliente a la página donde ve el presupuesto y puede firmarlo. Si
    algún hueco no aplica, lo deja vacío en vez de romper."""
    ETIQUETAS_ESTADO = {
        "recibido": "Recibido", "diagnostico": "En diagnóstico", "reparacion": "En reparación",
        "listo": "Listo para recoger", "entregado": "Entregado", "no_reparable": "No reparable",
    }
    valores = {
        "cliente": reparacion.cliente.nombre.split(" ")[0] if reparacion.cliente else "",
        "equipo": reparacion.equipo or "",
        "numero_orden": reparacion.numero_orden or "",
        "estado": ETIQUETAS_ESTADO.get(reparacion.estado_actual, reparacion.estado_actual or ""),
        "fecha_estimada": reparacion.fecha_estimada.strftime("%d/%m/%Y") if reparacion.fecha_estimada else "",
        "garantia": reparacion.fecha_fin_garantia.strftime("%d/%m/%Y") if reparacion.fecha_fin_garantia else "",
        "enlace_seguimiento": f"{FRONTEND_URL}/seguimiento?token={reparacion.token_seguimiento}",
    }
    try:
        return texto_plantilla.format(**valores)
    except (KeyError, IndexError):
        return texto_plantilla  # si la plantilla tiene un hueco mal escrito, mejor mandar el texto tal cual


def generar_enlace_whatsapp_texto(reparacion, texto):
    """Igual que generar_enlace_whatsapp, pero a partir de un texto ya
    redactado (de una plantilla), no de uno de los tipos fijos."""
    telefono = _telefono_whatsapp(reparacion.cliente.telefono if reparacion.cliente else None)
    if not telefono:
        return None
    return f"https://wa.me/{telefono}?text={urllib.parse.quote(texto)}"

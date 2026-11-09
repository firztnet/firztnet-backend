"""Firztnet Central — informes mensuales de visitas para tus clientes.

El día 1 de cada mes se PREPARA el informe del mes anterior de cada cliente
(en prueba o activo, con correo y con visitas). No se envía nada solo: te llega
un aviso, los revisas en «Informes mensuales» y los aceptas para enviarlos.
Se mandan con Resend (el mismo servicio que los comprobantes).
"""
import html
import json
import urllib.error
import urllib.request
from datetime import date, datetime

from app import db
from app.models import ConfiguracionNegocio, InformeMensual, LocalCliente

MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
DATO_PROPIO = {
    "peluquerias": ("📅", "citas reservadas por internet"),
    "hosteleria": ("🍽️", "reservas de mesa por internet"),
    "reformas": ("📝", "solicitudes de presupuesto desde tu web"),
    "logistica": ("📨", "solicitudes desde tu web"),
}


def nombre_mes(mes):
    return f"{MESES[int(mes[5:7]) - 1]} de {mes[:4]}"


def mes_anterior(hoy=None):
    hoy = hoy or date.today()
    return f"{hoy.year - 1}-12" if hoy.month == 1 else f"{hoy.year}-{hoy.month - 1:02d}"


def _e(texto):
    return html.escape(str(texto or ""))


def _cuerpo(l, inf):
    """Correo en HTML con estilos en línea (lo que mejor se ve en Gmail, Outlook y el móvil)."""
    from app.routes.central import NOMBRE_ORIGEN  # noqa: F401  (los nombres ya vienen en inf["origenes"])
    azul, oro, gris = "#1D4ED8", "#F59E0B", "#64748B"
    # Solo el nombre de pila, sin comas ni coletillas («Rosa, la dueña» → «Rosa»)
    import re
    nombre = (re.split(r"[\s,;(]+", (l.contacto_nombre or "").strip()) or [""])[0]
    cambio = ""
    if inf["cambio_pct"] is not None:
        flecha = "▲" if inf["cambio_pct"] > 0 else "▼" if inf["cambio_pct"] < 0 else "="
        cambio = f' <span style="color:{"#15803D" if inf["cambio_pct"] >= 0 else "#B91C1C"};font-weight:700">({flecha} {inf["cambio_pct"]:+d} % que el mes anterior)</span>'
    filas = [
        f'👁 <b>{inf["visitas"]} visitas</b>{cambio}',
        f'📱 <b>{inf["movil_pct"]} %</b> desde el móvil' if inf["movil_pct"] is not None else "",
        f'📆 Unas <b>{str(inf["media_diaria"]).replace(".", ",")}</b> visitas al día de media',
    ]
    if l.sistema in DATO_PROPIO and inf.get("reservas_tipo"):
        ico, texto = DATO_PROPIO[l.sistema]
        filas.append(f'{ico} <b>{inf["reservas_web"]}</b> {texto}')
    kpis = "".join(f'<tr><td style="padding:4px 0;font-size:16px">{f}</td></tr>' for f in filas if f)

    origenes = "".join(
        f'<tr><td style="padding:3px 8px 3px 0;font-size:14px;white-space:nowrap">{_e(o["nombre"])}</td>'
        f'<td style="width:100%;padding:3px 0"><div style="background:#E2E8F0;border-radius:6px;height:10px">'
        f'<div style="background:{azul};width:{max(3, o["pct"])}%;height:10px;border-radius:6px"></div></div></td>'
        f'<td style="padding:3px 0 3px 8px;font-size:14px;font-weight:700;text-align:right;white-space:nowrap">{o["pct"]} %</td></tr>'
        for o in inf["origenes"]
    )
    maximo = max([d["visitas"] for d in inf["por_dia"]] + [1])
    barras = "".join(
        f'<td valign="bottom" style="padding:0 1px"><div title="{d["visitas"]}" style="background:{oro if d["visitas"] == maximo else azul};'
        f'height:{max(2, round(d["visitas"] * 70 / maximo))}px;border-radius:2px 2px 0 0"></div></td>'
        for d in inf["por_dia"]
    )
    consejo = (f'<p style="background:#EFF6FF;border-radius:10px;padding:12px 14px;font-size:14px;color:#1E3A8A">💡 El día que más gente entra '
               f'en tu web es el <b>{_e(inf["mejor_dia_semana"])}</b>: buen día para publicar en tus redes o lanzar una oferta.</p>') if inf["mejor_dia_semana"] else ""
    return f"""<!doctype html><html lang="es"><body style="margin:0;background:#F1F5F9;font-family:Arial,Helvetica,sans-serif;color:#0F172A">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#F1F5F9;padding:20px 0"><tr><td align="center">
<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;background:#FFFFFF;border-radius:16px;overflow:hidden">
<tr><td style="background:linear-gradient(135deg,{azul},#0F1B3D);background-color:{azul};padding:22px 26px;color:#FFFFFF">
<div style="font-size:22px;font-weight:800;letter-spacing:1px">FIRZT<span style="color:{oro}">NET</span></div>
<div style="font-size:15px;opacity:.9;margin-top:4px">Las visitas de tu web en {nombre_mes(inf["mes"])}</div></td></tr>
<tr><td style="padding:24px 26px">
<p style="font-size:16px;margin:0 0 12px">{f"Hola {_e(nombre)}:" if nombre else "Hola:"}</p>
<p style="font-size:15px;line-height:1.5;margin:0 0 16px">Te mandamos el resumen de cómo ha ido la web de <b>{_e(l.nombre)}</b> en <b>{nombre_mes(inf["mes"])}</b>:</p>
<table role="presentation" cellpadding="0" cellspacing="0" style="margin:0 0 18px">{kpis}</table>
<p style="font-size:15px;font-weight:700;margin:18px 0 8px">Cómo llega la gente a tu web</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{origenes}</table>
<p style="font-size:15px;font-weight:700;margin:20px 0 8px">Visitas de cada día</p>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="height:74px"><tr>{barras}</tr></table>
<div style="font-size:11px;color:{gris};display:flex;justify-content:space-between">día 1 · · · día {len(inf["por_dia"])}</div>
{consejo}
<p style="font-size:15px;line-height:1.5">Si quieres más visitas o cambiar algo de tu web, responde a este correo o escríbenos por WhatsApp.</p>
<p style="font-size:15px;margin:18px 0 0">Un saludo,<br><b>Firztnet</b></p>
</td></tr>
<tr><td style="padding:14px 26px;background:#F8FAFC;font-size:12px;color:{gris}">Las visitas se cuentan sin cookies ni datos personales de tus clientes. · {_e(l.direccion_web or "")}</td></tr>
</table></td></tr></table></body></html>"""


def preparar(mes=None):
    """Prepara (o rehace, si aún no se han enviado) los informes de ese mes. Devuelve cuántos hay listos."""
    from app.routes.central import _informe
    mes = mes or mes_anterior()
    preparados = 0
    for l in LocalCliente.query.filter(LocalCliente.estado.in_(["prueba", "activo"])).all():
        if not l.contacto_email or not l.direccion_web:
            continue
        inf = _informe(l, mes)
        if inf["visitas"] <= 0:
            continue
        existente = InformeMensual.query.filter_by(local_id=l.id, mes=mes).first()
        if existente and existente.estado == "enviado":
            continue
        i = existente or InformeMensual(local_id=l.id, mes=mes)
        i.email = i.email if existente and existente.email else l.contacto_email
        i.asunto = f"📈 Las visitas de tu web en {MESES[int(mes[5:7]) - 1]} · {l.nombre}"
        i.html = _cuerpo(l, inf)
        i.visitas = inf["visitas"]
        i.cambio_pct = inf["cambio_pct"]
        i.estado = "preparado" if not existente or existente.estado in ("preparado", "error") else existente.estado
        i.error = None
        i.creado = datetime.utcnow()
        db.session.add(i)
        preparados += 1
    db.session.commit()
    return preparados


def enviar(informe):
    """Manda un informe ya aceptado. Devuelve (ok, detalle)."""
    import os
    clave = os.environ.get("RESEND_API_KEY")
    remitente = os.environ.get("EMAIL_REMITENTE", "onboarding@resend.dev")
    if not clave:
        return False, "Falta configurar RESEND_API_KEY en Railway"
    responder = (ConfiguracionNegocio.query.first().email if ConfiguracionNegocio.query.first() else None) or "contacto@firztnet.es"
    cuerpo = {
        "from": f"Firztnet <{remitente}>",
        "to": [informe.email],
        "reply_to": responder,
        "subject": informe.asunto,
        "html": informe.html,
    }
    peticion = urllib.request.Request(
        "https://api.resend.com/emails", data=json.dumps(cuerpo).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {clave}", "Content-Type": "application/json", "User-Agent": "Firztnet/1.0 (+https://firztnet.es)"},
    )
    try:
        with urllib.request.urlopen(peticion, timeout=20) as r:
            r.read()
        return True, None
    except urllib.error.HTTPError as e:
        return False, f"Resend respondió {e.code}: {e.read().decode('utf-8', errors='ignore')[:200]}"
    except Exception as e:  # noqa: BLE001
        return False, str(e)[:200]


def tarea_dia_1(app):
    """El día 1 a las 8:00 (hora de Madrid): prepara los informes del mes anterior y te avisa. No envía nada."""
    with app.app_context():
        from app.notificaciones import enviar_telegram
        mes = mes_anterior()
        n = preparar(mes)
        if n:
            try:
                enviar_telegram(f"📈 Ya están preparados {n} informe(s) de visitas de {nombre_mes(mes)} para tus clientes.\n"
                                "Revísalos en Reparaciones → «Informes mensuales» y pulsa «Aceptar y enviar». No sale ninguno sin tu permiso.")
            except Exception:  # noqa: BLE001
                pass

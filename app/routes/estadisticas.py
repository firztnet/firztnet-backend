from datetime import datetime, timedelta
from flask import Blueprint, jsonify, request
from app import db, limiter
from app.models import VisitaWeb, EventoWeb, ConfiguracionNegocio

estadisticas_bp = Blueprint("estadisticas", __name__)

SITIOS_VALIDOS = {"firztnet", "firztweb", "afiliados"}
TIPOS_EVENTO_VALIDOS = {"clic", "seccion_vista"}
DIAS_SEMANA = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]


@estadisticas_bp.post("/visita")
@limiter.limit("60 per minute")  # pública, sin login — límite generoso para tráfico normal, pero evita abuso
def registrar_visita():
    """Lo llama el propio JavaScript de tus webs públicas en cada carga
    de página. No hace falta ninguna cookie ni dato personal — solo
    contamos, no identificamos a nadie."""
    data = request.get_json() or {}
    sitio = (data.get("sitio") or "").strip().lower()
    if sitio not in SITIOS_VALIDOS:
        return jsonify({"error": "Sitio no reconocido"}), 400

    dispositivo = (data.get("dispositivo") or "desconocido").strip().lower()
    if dispositivo not in {"movil", "escritorio"}:
        dispositivo = "desconocido"

    visita = VisitaWeb(
        sitio=sitio,
        ruta=(data.get("ruta") or "/")[:200],
        referido=(data.get("referido") or "directo")[:300],
        dispositivo=dispositivo,
    )
    db.session.add(visita)
    db.session.commit()
    return jsonify({"ok": True}), 201


@estadisticas_bp.post("/evento")
@limiter.limit("120 per minute")  # más generoso que /visita: una sola visita puede generar varios clics o secciones vistas
def registrar_evento():
    """Un clic en un botón concreto, o una sección que el visitante ha
    visto al hacer scroll. También pública, sin login."""
    data = request.get_json() or {}
    sitio = (data.get("sitio") or "").strip().lower()
    tipo = (data.get("tipo") or "").strip().lower()
    etiqueta = (data.get("etiqueta") or "").strip()

    if sitio not in SITIOS_VALIDOS:
        return jsonify({"error": "Sitio no reconocido"}), 400
    if tipo not in TIPOS_EVENTO_VALIDOS:
        return jsonify({"error": "Tipo de evento no reconocido"}), 400
    if not etiqueta:
        return jsonify({"error": "Falta la etiqueta del evento"}), 400

    evento = EventoWeb(sitio=sitio, tipo=tipo, etiqueta=etiqueta[:80])
    db.session.add(evento)
    db.session.commit()
    return jsonify({"ok": True}), 201


@estadisticas_bp.get("/resumen")
def resumen_visitas():
    """Para el panel: visitas por periodo, de dónde viene la gente,
    desde qué dispositivo, qué botones tocan más, y en qué horas/días
    hay más tráfico (últimos 30 días para estos dos últimos, para que
    reflejen el patrón actual y no se diluyan con el histórico completo)."""
    hoy = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    hace_7_dias = hoy - timedelta(days=7)
    hace_30_dias = hoy - timedelta(days=30)
    inicio_mes = hoy.replace(day=1)

    resultado = {}
    for sitio in SITIOS_VALIDOS:
        base = VisitaWeb.query.filter_by(sitio=sitio)
        hoy_count = base.filter(VisitaWeb.fecha >= hoy).count()
        semana_count = base.filter(VisitaWeb.fecha >= hace_7_dias).count()
        mes_count = base.filter(VisitaWeb.fecha >= inicio_mes).count()
        total_count = base.count()

        top_referidos = (
            db.session.query(VisitaWeb.referido, db.func.count(VisitaWeb.id).label("total"))
            .filter(VisitaWeb.sitio == sitio, VisitaWeb.fecha >= hace_7_dias)
            .group_by(VisitaWeb.referido)
            .order_by(db.desc("total"))
            .limit(5)
            .all()
        )

        dispositivos = (
            db.session.query(VisitaWeb.dispositivo, db.func.count(VisitaWeb.id).label("total"))
            .filter(VisitaWeb.sitio == sitio, VisitaWeb.fecha >= hace_30_dias)
            .group_by(VisitaWeb.dispositivo)
            .all()
        )

        top_eventos = (
            db.session.query(EventoWeb.etiqueta, db.func.count(EventoWeb.id).label("total"))
            .filter(EventoWeb.sitio == sitio, EventoWeb.fecha >= hace_30_dias)
            .group_by(EventoWeb.etiqueta)
            .order_by(db.desc("total"))
            .limit(8)
            .all()
        )

        por_hora = (
            db.session.query(
                db.func.strftime("%H", VisitaWeb.fecha).label("hora"),
                db.func.count(VisitaWeb.id).label("total"),
            )
            .filter(VisitaWeb.sitio == sitio, VisitaWeb.fecha >= hace_30_dias)
            .group_by("hora")
            .all()
        )
        por_dia_semana = (
            db.session.query(
                db.func.strftime("%w", VisitaWeb.fecha).label("dia"),
                db.func.count(VisitaWeb.id).label("total"),
            )
            .filter(VisitaWeb.sitio == sitio, VisitaWeb.fecha >= hace_30_dias)
            .group_by("dia")
            .all()
        )

        top_paginas = (
            db.session.query(VisitaWeb.ruta, db.func.count(VisitaWeb.id).label("total"))
            .filter(VisitaWeb.sitio == sitio, VisitaWeb.fecha >= hace_30_dias)
            .group_by(VisitaWeb.ruta)
            .order_by(db.desc("total"))
            .limit(8)
            .all()
        )
        ultima = base.order_by(VisitaWeb.fecha.desc()).first()

        resultado[sitio] = {
            "ultima_visita": _iso(ultima.fecha) if ultima else None,
            "top_paginas": [{"ruta": r or "/", "visitas": t} for r, t in top_paginas],
            "hoy": hoy_count,
            "semana": semana_count,
            "mes": mes_count,
            "total": total_count,
            "top_referidos": [{"referido": r, "visitas": t} for r, t in top_referidos],
            "dispositivos": [{"dispositivo": d or "desconocido", "visitas": t} for d, t in dispositivos],
            "top_eventos": [{"etiqueta": e, "veces": t} for e, t in top_eventos],
            "por_hora": {h: t for h, t in por_hora},
            "por_dia_semana": [{"dia": DIAS_SEMANA[int(d)], "visitas": t} for d, t in por_dia_semana],
        }

    return jsonify(resultado)



# ---------------------------------------------------------------------------
# Aviso de visitas nuevas (campana) y detalle de la actividad (pantalla Visitas web)
# ---------------------------------------------------------------------------

def _iso(fecha):
    """Las fechas se guardan en UTC sin zona; se devuelven con 'Z' para que el navegador las pase bien a la hora local."""
    return (fecha.isoformat() + "Z") if fecha else None


def _leer_fecha(texto):
    if not texto:
        return None
    try:
        return datetime.fromisoformat(texto.strip().rstrip("Zz"))
    except ValueError:
        return None


@estadisticas_bp.get("/novedades")
def novedades():
    """Cuánta actividad ha entrado en tus webs desde la última vez que miraste la pantalla Visitas web.
    Es lo que alimenta el aviso de la campana."""
    config = ConfiguracionNegocio.obtener()
    if config.visitas_vistas_hasta is None:
        config.visitas_vistas_hasta = datetime.utcnow()  # primera vez: se parte de ahora, sin avisar del pasado
        db.session.commit()
    desde = config.visitas_vistas_hasta

    sitios = {}
    for sitio in sorted(SITIOS_VALIDOS):
        eventos = EventoWeb.query.filter(EventoWeb.sitio == sitio, EventoWeb.fecha > desde)
        sitios[sitio] = {
            "visitas": VisitaWeb.query.filter(VisitaWeb.sitio == sitio, VisitaWeb.fecha > desde).count(),
            "clics": eventos.filter(EventoWeb.tipo == "clic").count(),
            "secciones": eventos.filter(EventoWeb.tipo == "seccion_vista").count(),
        }
    return jsonify({
        "desde": _iso(desde),
        "total_visitas": sum(s["visitas"] for s in sitios.values()),
        "total_clics": sum(s["clics"] for s in sitios.values()),
        "total_secciones": sum(s["secciones"] for s in sitios.values()),
        "sitios": sitios,
    })


@estadisticas_bp.post("/marcar-vistas")
def marcar_vistas():
    """Se llama al entrar en Visitas web: lo que haya hasta ahora pasa a contar como visto."""
    config = ConfiguracionNegocio.obtener()
    anterior = config.visitas_vistas_hasta
    config.visitas_vistas_hasta = datetime.utcnow()
    db.session.commit()
    return jsonify({"ok": True, "desde": _iso(anterior)})


@estadisticas_bp.get("/recientes")
def actividad_reciente():
    """Línea de tiempo con el detalle de cada visita, clic y sección vista, de más nueva a más antigua.

    Parámetros opcionales: sitio (firztnet|firztweb|afiliados), tipo (visita|clic|seccion_vista),
    limite (por defecto 60, máximo 200) y antes (fecha ISO, para pedir la página siguiente)."""
    sitio = request.args.get("sitio")
    tipo = request.args.get("tipo")
    try:
        limite = min(max(int(request.args.get("limite", 60)), 1), 200)
    except ValueError:
        limite = 60
    antes = _leer_fecha(request.args.get("antes"))

    items = []  # tuplas (fecha real, id, datos): se ordena por la fecha de verdad, no por su texto
    if tipo in (None, "", "visita"):
        consulta = VisitaWeb.query
        if sitio in SITIOS_VALIDOS:
            consulta = consulta.filter(VisitaWeb.sitio == sitio)
        if antes:
            consulta = consulta.filter(VisitaWeb.fecha < antes)
        for v in consulta.order_by(VisitaWeb.fecha.desc(), VisitaWeb.id.desc()).limit(limite + 1).all():
            items.append((v.fecha, v.id, {"clase": "visita", "id": v.id, "sitio": v.sitio, "fecha": _iso(v.fecha),
                          "ruta": v.ruta or "/", "referido": v.referido or "directo", "dispositivo": v.dispositivo or "desconocido"}))

    if tipo in (None, "", "clic", "seccion_vista"):
        consulta = EventoWeb.query
        if tipo in TIPOS_EVENTO_VALIDOS:
            consulta = consulta.filter(EventoWeb.tipo == tipo)
        if sitio in SITIOS_VALIDOS:
            consulta = consulta.filter(EventoWeb.sitio == sitio)
        if antes:
            consulta = consulta.filter(EventoWeb.fecha < antes)
        for e in consulta.order_by(EventoWeb.fecha.desc(), EventoWeb.id.desc()).limit(limite + 1).all():
            items.append((e.fecha, e.id, {"clase": e.tipo, "id": e.id, "sitio": e.sitio, "fecha": _iso(e.fecha), "etiqueta": e.etiqueta}))

    items.sort(key=lambda t: (t[0] or datetime.min, t[1]), reverse=True)
    return jsonify({"items": [t[2] for t in items[:limite]], "hay_mas": len(items) > limite})

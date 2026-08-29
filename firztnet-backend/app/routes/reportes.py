from datetime import datetime, timedelta
from sqlalchemy import func
from flask import Blueprint, jsonify
from app import db
from app.models import MovimientoFinanciero, Reparacion

reportes_bp = Blueprint("reportes", __name__)


def _balance(query):
    ingresos = query.filter(MovimientoFinanciero.tipo == "ingreso").with_entities(
        func.coalesce(func.sum(MovimientoFinanciero.monto), 0)
    ).scalar()
    gastos = query.filter(MovimientoFinanciero.tipo == "gasto").with_entities(
        func.coalesce(func.sum(MovimientoFinanciero.monto), 0)
    ).scalar()
    return float(ingresos), float(gastos)


@reportes_bp.get("/diario")
def reporte_diario():
    hoy = datetime.utcnow().date()
    inicio = datetime.combine(hoy, datetime.min.time())
    fin = inicio + timedelta(days=1)

    query = MovimientoFinanciero.query.filter(
        MovimientoFinanciero.fecha >= inicio, MovimientoFinanciero.fecha < fin
    )
    ingresos, gastos = _balance(query)

    recibidos_hoy = Reparacion.query.filter(
        Reparacion.fecha_recepcion >= inicio, Reparacion.fecha_recepcion < fin
    ).count()
    entregados_hoy = Reparacion.query.filter(
        Reparacion.fecha_entrega >= inicio, Reparacion.fecha_entrega < fin
    ).count()

    return jsonify(
        {
            "fecha": hoy.isoformat(),
            "ingresos": ingresos,
            "gastos": gastos,
            "balance_neto": ingresos - gastos,
            "equipos_recibidos": recibidos_hoy,
            "equipos_entregados": entregados_hoy,
        }
    )


@reportes_bp.get("/mensual")
def reporte_mensual():
    hoy = datetime.utcnow()
    inicio_mes = hoy.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    query = MovimientoFinanciero.query.filter(MovimientoFinanciero.fecha >= inicio_mes)
    ingresos, gastos = _balance(query)

    entregadas = Reparacion.query.filter(
        Reparacion.fecha_entrega >= inicio_mes, Reparacion.estado_actual == "entregado"
    ).count()
    no_reparables = Reparacion.query.filter(
        Reparacion.fecha_recepcion >= inicio_mes, Reparacion.estado_actual == "no_reparable"
    ).count()

    ticket_medio = (ingresos / entregadas) if entregadas else 0

    return jsonify(
        {
            "mes": inicio_mes.strftime("%Y-%m"),
            "ingresos": ingresos,
            "gastos": gastos,
            "balance_neto": ingresos - gastos,
            "reparaciones_entregadas": entregadas,
            "reparaciones_no_reparables": no_reparables,
            "ticket_medio": round(ticket_medio, 2),
        }
    )


@reportes_bp.get("/contador")
def contador_reparaciones():
    """El contador de reparaciones que pidió Carlos, con desglose por estado."""
    total = Reparacion.query.count()
    en_curso = Reparacion.query.filter(
        ~Reparacion.estado_actual.in_(["entregado", "no_reparable"])
    ).count()
    entregadas = Reparacion.query.filter_by(estado_actual="entregado").count()
    no_reparables = Reparacion.query.filter_by(estado_actual="no_reparable").count()

    return jsonify(
        {
            "total": total,
            "en_curso": en_curso,
            "entregadas": entregadas,
            "no_reparables": no_reparables,
        }
    )


@reportes_bp.get("/tendencia")
def tendencia_semanal():
    """Ingresos, gastos y nº de reparaciones recibidas de cada uno de
    los últimos 7 días (incluyendo hoy) — para la gráfica del panel."""
    hoy = datetime.utcnow().date()
    dias = []
    for i in range(6, -1, -1):
        dia = hoy - timedelta(days=i)
        inicio = datetime.combine(dia, datetime.min.time())
        fin = inicio + timedelta(days=1)

        query = MovimientoFinanciero.query.filter(
            MovimientoFinanciero.fecha >= inicio, MovimientoFinanciero.fecha < fin
        )
        ingresos, gastos = _balance(query)

        recibidas = Reparacion.query.filter(
            Reparacion.fecha_recepcion >= inicio, Reparacion.fecha_recepcion < fin
        ).count()

        dias.append({
            "fecha": dia.isoformat(),
            "dia_semana": ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"][dia.weekday()],
            "ingresos": ingresos,
            "gastos": gastos,
            "reparaciones_recibidas": recibidas,
        })

    return jsonify(dias)

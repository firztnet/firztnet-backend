import calendar
import csv
import io
from datetime import datetime, timedelta
from sqlalchemy import func
from flask import Blueprint, jsonify, request, Response
from app import db
from app.models import MovimientoFinanciero, Reparacion, Cliente, Factura

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
    nuevos_clientes_hoy = Cliente.query.filter(
        Cliente.creado_en >= inicio, Cliente.creado_en < fin
    ).count()

    return jsonify(
        {
            "fecha": hoy.isoformat(),
            "ingresos": ingresos,
            "gastos": gastos,
            "balance_neto": ingresos - gastos,
            "equipos_recibidos": recibidos_hoy,
            "equipos_entregados": entregados_hoy,
            "nuevos_clientes": nuevos_clientes_hoy,
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


@reportes_bp.get("/exportar")
def exportar_mes():
    """CSV listo para Excel/tu gestoría: movimientos y facturas del mes
    indicado (por defecto, el mes actual). Usa ?mes=2026-08."""
    mes_str = request.args.get("mes")
    if mes_str:
        anio, mes = map(int, mes_str.split("-"))
    else:
        hoy = datetime.utcnow()
        anio, mes = hoy.year, hoy.month

    inicio = datetime(anio, mes, 1)
    ultimo_dia = calendar.monthrange(anio, mes)[1]
    fin = datetime(anio, mes, ultimo_dia, 23, 59, 59)

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")  # ; para que Excel en español lo abra bien

    writer.writerow([f"Resumen contable — {mes:02d}/{anio}"])
    writer.writerow([])

    writer.writerow(["MOVIMIENTOS"])
    writer.writerow(["Fecha", "Tipo", "Concepto", "Método de pago", "Importe (€)", "Nº orden asociado"])
    movimientos = (
        MovimientoFinanciero.query.filter(MovimientoFinanciero.fecha >= inicio, MovimientoFinanciero.fecha <= fin)
        .order_by(MovimientoFinanciero.fecha)
        .all()
    )
    total_ingresos = total_gastos = 0
    for m in movimientos:
        writer.writerow([
            m.fecha.strftime("%d/%m/%Y %H:%M"),
            "Ingreso" if m.tipo == "ingreso" else "Gasto",
            m.concepto or "",
            m.metodo_pago or "",
            f"{float(m.monto):.2f}".replace(".", ","),
            m.reparacion.numero_orden if m.reparacion else "",
        ])
        if m.tipo == "ingreso":
            total_ingresos += float(m.monto)
        else:
            total_gastos += float(m.monto)

    writer.writerow([])
    writer.writerow(["Total ingresos", f"{total_ingresos:.2f}".replace(".", ",")])
    writer.writerow(["Total gastos", f"{total_gastos:.2f}".replace(".", ",")])
    writer.writerow(["Balance neto", f"{(total_ingresos - total_gastos):.2f}".replace(".", ",")])
    writer.writerow([])

    writer.writerow(["FACTURAS EMITIDAS"])
    writer.writerow(["Nº factura", "Fecha", "Cliente", "NIF cliente", "Base imponible (€)", "IVA (%)", "IVA (€)", "Total (€)"])
    facturas = Factura.query.filter(Factura.fecha_emision >= inicio, Factura.fecha_emision <= fin).order_by(Factura.fecha_emision).all()
    for f in facturas:
        writer.writerow([
            f.numero,
            f.fecha_emision.strftime("%d/%m/%Y"),
            f.cliente.nombre if f.cliente else "",
            f.cliente.nif if f.cliente else "",
            f"{float(f.base_imponible):.2f}".replace(".", ","),
            f"{float(f.iva_pct):.0f}",
            f"{float(f.iva_importe):.2f}".replace(".", ","),
            f"{float(f.total):.2f}".replace(".", ","),
        ])

    contenido = "\ufeff" + buffer.getvalue()  # BOM para que Excel detecte bien los acentos
    return Response(
        contenido,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename=resumen_{anio}-{mes:02d}.csv"},
    )


@reportes_bp.get("/rendimiento")
def rendimiento_tecnicos():
    """Por técnico: cuántos trabajos completó (entregado/completado) y
    el tiempo medio desde que se recibió hasta que se entregó. Solo
    cuenta trabajos que tengan técnico asignado."""
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")

    query = Reparacion.query.filter(
        Reparacion.tecnico.isnot(None),
        Reparacion.tecnico != "",
        Reparacion.estado_actual.in_(["entregado", "completado"]),
        Reparacion.fecha_entrega.isnot(None),
    )
    if desde:
        query = query.filter(Reparacion.fecha_entrega >= datetime.fromisoformat(desde))
    if hasta:
        query = query.filter(Reparacion.fecha_entrega <= datetime.fromisoformat(hasta))

    por_tecnico = {}
    for rep in query.all():
        stats = por_tecnico.setdefault(rep.tecnico, {"tecnico": rep.tecnico, "completados": 0, "suma_horas": 0.0})
        stats["completados"] += 1
        if rep.fecha_recepcion:
            stats["suma_horas"] += (rep.fecha_entrega - rep.fecha_recepcion).total_seconds() / 3600

    resultado = []
    for stats in por_tecnico.values():
        promedio_horas = stats["suma_horas"] / stats["completados"] if stats["completados"] else 0
        resultado.append({
            "tecnico": stats["tecnico"],
            "completados": stats["completados"],
            "tiempo_promedio_horas": round(promedio_horas, 1),
        })

    resultado.sort(key=lambda r: r["completados"], reverse=True)
    return jsonify(resultado)


@reportes_bp.get("/abandonados")
def equipos_abandonados():
    """Equipos 'listo para entrega' que llevan muchos días sin recoger.
    Usa ?dias=30 (por defecto) o ?dias=60 para el umbral. IMPORTANTE:
    el texto legal del aviso es orientativo — antes de enviarlo de
    verdad, conviene que confirmes con un profesional el plazo y la
    base legal exacta que aplican en tu caso."""
    from app.models import ConfiguracionNegocio
    from app.notificaciones import generar_enlace_whatsapp_texto

    umbral_dias = int(request.args.get("dias", 30))
    limite = datetime.utcnow() - timedelta(days=umbral_dias)
    negocio = ConfiguracionNegocio.obtener()
    coste_dia = float(negocio.coste_almacenamiento_diario or 1)

    reparaciones = Reparacion.query.filter(
        Reparacion.estado_actual == "listo",
        Reparacion.fecha_listo.isnot(None),
        Reparacion.fecha_listo <= limite,
    ).order_by(Reparacion.fecha_listo).all()

    resultado = []
    for rep in reparaciones:
        dias = (datetime.utcnow() - rep.fecha_listo).days
        coste_acumulado = round(dias * coste_dia, 2)
        nombre = rep.cliente.nombre.split(" ")[0] if rep.cliente else ""
        texto = (
            f"Hola {nombre}, te escribimos de Firztnet sobre tu equipo ({rep.equipo}, orden {rep.numero_orden}), "
            f"que lleva {dias} días listo para recoger sin que hayamos tenido noticias tuyas. "
            f"Aplicamos un coste de custodia de {coste_dia:.2f} €/día (acumulado: {coste_acumulado:.2f} €). "
            f"Por favor, ponte en contacto con nosotros para coordinar la recogida."
        )
        resultado.append({
            "id": rep.id,
            "numero_orden": rep.numero_orden,
            "equipo": rep.equipo,
            "cliente": rep.cliente.to_dict() if rep.cliente else None,
            "fecha_listo": rep.fecha_listo.isoformat(),
            "dias_abandonado": dias,
            "coste_acumulado": coste_acumulado,
            "mensaje_sugerido": texto,
            "enlace_whatsapp": generar_enlace_whatsapp_texto(rep, texto),
        })

    return jsonify(resultado)


@reportes_bp.get("/rentabilidad")
def rentabilidad_por_linea():
    """Ingresos, coste de piezas (a precio de compra) y margen, agrupado
    por categoría de servicio (redes, cámaras, impresoras, mantenimiento
    empresas) o 'reparación general' si no tiene categoría."""
    from app.models import ReparacionRepuesto, MovimientoFinanciero

    reparaciones = Reparacion.query.filter(Reparacion.estado_actual.in_(["entregado", "completado"])).all()

    grupos = {}
    for rep in reparaciones:
        clave = rep.categoria or "reparacion_general"
        g = grupos.setdefault(clave, {"categoria": clave, "trabajos": 0, "ingresos": 0.0, "coste_piezas": 0.0})
        g["trabajos"] += 1
        g["ingresos"] += float(sum((m.monto for m in rep.movimientos if m.tipo == "ingreso"), 0))
        g["coste_piezas"] += sum(float(rr.repuesto.precio_compra or 0) * rr.cantidad for rr in rep.repuestos_usados if rr.repuesto)

    resultado = []
    for g in grupos.values():
        margen = g["ingresos"] - g["coste_piezas"]
        g["margen"] = round(margen, 2)
        g["margen_pct"] = round((margen / g["ingresos"] * 100), 1) if g["ingresos"] > 0 else 0
        g["ingresos"] = round(g["ingresos"], 2)
        g["coste_piezas"] = round(g["coste_piezas"], 2)
        resultado.append(g)

    resultado.sort(key=lambda g: g["margen"], reverse=True)
    return jsonify(resultado)

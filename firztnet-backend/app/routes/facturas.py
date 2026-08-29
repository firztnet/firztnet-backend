from datetime import datetime
from decimal import Decimal
from flask import Blueprint, request, jsonify, send_file
from app import db
from app.models import Factura, Reparacion, MovimientoFinanciero, ConfiguracionNegocio
from app.pdf_generator import generar_pdf_factura

facturas_bp = Blueprint("facturas", __name__)


def generar_numero_factura():
    """Nº correlativo por año, ej: 2026-F0001. Por ley debe ser
    correlativo y sin huecos — nunca borres una factura ya emitida."""
    anio = datetime.utcnow().year
    ultima = (
        Factura.query.filter(Factura.numero.like(f"{anio}-F%"))
        .order_by(Factura.id.desc())
        .first()
    )
    siguiente = 1
    if ultima:
        siguiente = int(ultima.numero.split("F")[1]) + 1
    return f"{anio}-F{siguiente:04d}"


@facturas_bp.post("")
def emitir_factura():
    """Emite la factura de una reparación, calculada sobre el total ya
    cobrado (los importes registrados en Caja/Cobro para esa
    reparación). Si el cliente no tiene NIF guardado, se puede emitir
    igualmente, pero se recomienda pedírselo primero."""
    data = request.get_json() or {}
    reparacion = Reparacion.query.get_or_404(data.get("reparacion_id"))
    if not reparacion.cliente:
        return jsonify({"error": "Esta reparación no tiene cliente asociado"}), 400

    ingresos = MovimientoFinanciero.query.filter_by(reparacion_id=reparacion.id, tipo="ingreso").all()
    total_cobrado = sum((m.monto for m in ingresos), Decimal("0"))
    if total_cobrado <= 0:
        return jsonify({"error": "No hay ningún cobro registrado en esta reparación todavía"}), 400

    negocio = ConfiguracionNegocio.obtener()
    iva_pct = negocio.iva_pct if negocio.iva_pct is not None else Decimal("21")

    # Se asume que el total cobrado ya incluye el IVA (precio final al
    # cliente), como es habitual de cara al consumidor. Se calcula la
    # base imponible hacia atrás.
    base_imponible = (total_cobrado / (1 + iva_pct / 100)).quantize(Decimal("0.01"))
    iva_importe = (total_cobrado - base_imponible).quantize(Decimal("0.01"))

    factura = Factura(
        numero=generar_numero_factura(),
        reparacion_id=reparacion.id,
        cliente_id=reparacion.cliente.id,
        concepto=data.get("concepto") or f"Reparación de {reparacion.equipo}",
        base_imponible=base_imponible,
        iva_pct=iva_pct,
        iva_importe=iva_importe,
        total=total_cobrado,
    )
    db.session.add(factura)
    db.session.commit()
    return jsonify(factura.to_dict()), 201


@facturas_bp.get("/<int:factura_id>/pdf")
def descargar_factura(factura_id):
    factura = Factura.query.get_or_404(factura_id)
    negocio = ConfiguracionNegocio.obtener()
    buffer = generar_pdf_factura(factura, factura.reparacion, factura.cliente, negocio)
    return send_file(buffer, mimetype="application/pdf", download_name=f"factura_{factura.numero}.pdf")


@facturas_bp.get("/reparacion/<int:rep_id>")
def facturas_de_reparacion(rep_id):
    """Para no duplicar: mira si esta reparación ya tiene factura emitida."""
    facturas = Factura.query.filter_by(reparacion_id=rep_id).order_by(Factura.id.desc()).all()
    return jsonify([f.to_dict() for f in facturas])

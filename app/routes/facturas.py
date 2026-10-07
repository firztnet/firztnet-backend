from datetime import datetime
from decimal import Decimal
from flask import Blueprint, request, jsonify, send_file
from app import db
from app.models import Factura, Reparacion, MovimientoFinanciero, ConfiguracionNegocio
from app.pdf_generator import generar_pdf_factura

facturas_bp = Blueprint("facturas", __name__)


def datos_emisor_incompletos(negocio):
    """Una factura tiene que llevar el nombre, el NIF y la dirección de quien la emite.
    Devuelve el mensaje de error si falta algo, o None si está todo."""
    faltan = [que for que, valor in (("el NIF", negocio.nif), ("la dirección", negocio.direccion), ("el nombre del negocio", negocio.nombre_negocio)) if not (valor or "").strip()]
    if faltan:
        return "Para emitir facturas tienes que rellenar en Ajustes " + " y ".join(faltan) + ". Una factura sin esos datos no es válida."
    return None


def congelar_emisor(factura, negocio):
    """Copia TUS datos de negocio en la factura en el momento de emitirla."""
    factura.emisor_nombre = negocio.nombre_negocio
    factura.emisor_nif = negocio.nif
    factura.emisor_direccion = negocio.direccion
    factura.emisor_telefono = negocio.telefono
    factura.emisor_email = negocio.email


def _anio_madrid():
    # Año en hora de Madrid: la primera factura del 1 de enero a las 00:30 ya es del año nuevo.
    from app.horario import hoy_madrid
    return hoy_madrid().year


def generar_numero_factura():
    """Nº correlativo por año, ej: 2026-F0001. Por ley debe ser
    correlativo y sin huecos — nunca borres una factura ya emitida."""
    anio = _anio_madrid()
    ultima = (
        Factura.query.filter(Factura.numero.like(f"{anio}-F%"))
        .order_by(Factura.id.desc())
        .first()
    )
    siguiente = 1
    if ultima:
        siguiente = int(ultima.numero.split("F")[1]) + 1
    return f"{anio}-F{siguiente:04d}"


def generar_numero_rectificativa():
    """Serie separada para las rectificativas, ej: 2026-R0001 — así se
    ve a simple vista cuáles son correcciones, sin mezclarse con la
    numeración normal (que debe quedar intacta, sin huecos)."""
    anio = _anio_madrid()
    ultima = (
        Factura.query.filter(Factura.numero.like(f"{anio}-R%"))
        .order_by(Factura.id.desc())
        .first()
    )
    siguiente = 1
    if ultima:
        siguiente = int(ultima.numero.split("R")[1]) + 1
    return f"{anio}-R{siguiente:04d}"


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
    error_emisor = datos_emisor_incompletos(negocio)
    if error_emisor:
        return jsonify({"error": error_emisor}), 400
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
        cliente_nombre_congelado=reparacion.cliente.nombre,
        cliente_nif_congelado=reparacion.cliente.nif,
    )
    congelar_emisor(factura, negocio)
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


@facturas_bp.post("/<int:factura_id>/rectificar")
def rectificar_factura(factura_id):
    """Emite una factura RECTIFICATIVA que sustituye a la original (con
    los importes correctos), sin tocar ni borrar la factura con el
    error — así lo exige la ley. Ambas quedan visibles para siempre,
    con la rectificativa referenciando a la original y el motivo."""
    original = Factura.query.get_or_404(factura_id)
    if original.es_rectificativa:
        return jsonify({"error": "Esta factura ya es una rectificativa — no se puede rectificar una rectificativa. Crea una nueva a mano si hace falta corregir de nuevo."}), 400

    data = request.get_json() or {}
    if not data.get("motivo"):
        return jsonify({"error": "Indica el motivo de la rectificación (obligatorio para el registro)"}), 400

    negocio = ConfiguracionNegocio.obtener()
    error_emisor = datos_emisor_incompletos(negocio)
    if error_emisor:
        return jsonify({"error": error_emisor}), 400

    # Datos del cliente para la rectificativa: los ACTUALES de su ficha (si la rectificas
    # porque su NIF estaba mal, aquí ya sale el NIF corregido). Si el cliente fue borrado
    # por RGPD, se mantienen los de la factura original.
    cliente = original.cliente
    if cliente and not (cliente.nombre or "").startswith("Cliente eliminado (RGPD"):
        nombre_cliente, nif_cliente = cliente.nombre, cliente.nif
    else:
        nombre_cliente, nif_cliente = original.cliente_nombre_congelado, original.cliente_nif_congelado

    if data.get("nuevo_total") is not None:
        nuevo_total = Decimal(str(data["nuevo_total"]))
        iva_pct = original.iva_pct
        base_imponible = (nuevo_total / (1 + iva_pct / 100)).quantize(Decimal("0.01"))
        iva_importe = (nuevo_total - base_imponible).quantize(Decimal("0.01"))
    else:
        # Sin importe nuevo indicado: se asume que el error no era de
        # dinero (ej. NIF mal escrito), y se repiten los mismos importes.
        base_imponible, iva_pct, iva_importe, nuevo_total = (
            original.base_imponible, original.iva_pct, original.iva_importe, original.total,
        )

    rectificativa = Factura(
        numero=generar_numero_rectificativa(),
        reparacion_id=original.reparacion_id,
        cliente_id=original.cliente_id,
        concepto=data.get("concepto") or original.concepto,
        base_imponible=base_imponible,
        iva_pct=iva_pct,
        iva_importe=iva_importe,
        total=nuevo_total,
        es_rectificativa=True,
        factura_original_id=original.id,
        motivo_rectificacion=data["motivo"],
        cliente_nombre_congelado=nombre_cliente,
        cliente_nif_congelado=nif_cliente,
    )
    congelar_emisor(rectificativa, negocio)
    db.session.add(rectificativa)
    db.session.commit()
    return jsonify(rectificativa.to_dict()), 201

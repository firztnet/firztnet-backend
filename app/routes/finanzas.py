from datetime import datetime
from decimal import Decimal, InvalidOperation
from flask import Blueprint, request, jsonify
from app import db
from app.models import MovimientoFinanciero

finanzas_bp = Blueprint("finanzas", __name__)

IMPORTE_MAXIMO = Decimal("100000")


def leer_importe(valor):
    """Devuelve (importe, error). Solo acepta números mayores que 0 (con coma o punto),
    con 2 decimales como mucho. Antes se aceptaban importes negativos, y con letras
    el servidor daba un error interno."""
    try:
        importe = Decimal(str(valor).strip().replace(",", "."))
    except (InvalidOperation, AttributeError, ValueError):
        return None, "El importe no es un número válido"
    if not importe.is_finite() or importe <= 0:
        return None, "El importe tiene que ser mayor que 0"
    if importe > IMPORTE_MAXIMO:
        return None, "El importe es demasiado alto: revisa que esté bien escrito"
    return importe.quantize(Decimal("0.01")), None


@finanzas_bp.get("")
def listar_movimientos():
    """Soporta ?desde=2026-08-01&hasta=2026-08-31 para filtrar por rango."""
    query = MovimientoFinanciero.query
    desde = request.args.get("desde")
    hasta = request.args.get("hasta")
    if desde:
        query = query.filter(MovimientoFinanciero.fecha >= datetime.fromisoformat(desde))
    if hasta:
        query = query.filter(MovimientoFinanciero.fecha <= datetime.fromisoformat(hasta))
    movimientos = query.order_by(MovimientoFinanciero.fecha.desc()).all()
    return jsonify([m.to_dict() for m in movimientos])


@finanzas_bp.post("")
def crear_movimiento():
    data = request.get_json() or {}
    if data.get("tipo") not in ("ingreso", "gasto"):
        return jsonify({"error": "El tipo debe ser 'ingreso' o 'gasto'"}), 400
    if data.get("monto") in (None, ""):
        return jsonify({"error": "El monto es obligatorio"}), 400
    importe, error = leer_importe(data["monto"])
    if error:
        return jsonify({"error": error}), 400

    movimiento = MovimientoFinanciero(
        reparacion_id=data.get("reparacion_id"),
        tipo=data["tipo"],
        concepto=(data.get("concepto") or "")[:120] or None,
        monto=importe,
        metodo_pago=data.get("metodo_pago"),
    )
    db.session.add(movimiento)
    db.session.commit()
    return jsonify(movimiento.to_dict()), 201


@finanzas_bp.post("/<int:movimiento_id>/anular")
def anular_movimiento(movimiento_id):
    """Anula un cobro o gasto mal apuntado. No se borra: se marca como anulado y se crea
    un apunte de corrección con el mismo importe en negativo, que lo compensa.
    Si la orden de ese movimiento ya tiene factura, avisa primero (habrá que emitir
    también una factura rectificativa) y solo sigue si se confirma."""
    from app.models import Factura

    movimiento = MovimientoFinanciero.query.get_or_404(movimiento_id)
    data = request.get_json() or {}
    motivo = (data.get("motivo") or "").strip()[:200]

    if movimiento.anula_a_id:
        return jsonify({"error": "Este apunte ya es una anulación: no se puede anular"}), 400
    if movimiento.anulado:
        return jsonify({"error": "Este movimiento ya estaba anulado"}), 400
    if not motivo:
        return jsonify({"error": "Indica el motivo de la anulación"}), 400

    if movimiento.reparacion_id and not data.get("confirmar"):
        factura = Factura.query.filter_by(reparacion_id=movimiento.reparacion_id).order_by(Factura.id.desc()).first()
        if factura:
            return jsonify({
                "error": "tiene_factura",
                "requiere_confirmacion": True,
                "mensaje": f"La orden de este cobro ya tiene la factura {factura.numero} ({float(factura.total):.2f} €). "
                           "Si anulas el cobro, emite después una factura rectificativa con el importe correcto. ¿Anular de todos modos?",
            }), 409

    movimiento.anulado = True
    movimiento.motivo_anulacion = motivo
    correccion = MovimientoFinanciero(
        reparacion_id=movimiento.reparacion_id,
        tipo=movimiento.tipo,
        concepto=f"ANULACIÓN: {movimiento.concepto or movimiento.tipo}"[:120],
        monto=-movimiento.monto,
        metodo_pago=movimiento.metodo_pago,
        anula_a_id=movimiento.id,
        motivo_anulacion=motivo,
    )
    db.session.add(correccion)
    db.session.commit()
    return jsonify({"anulado": movimiento.to_dict(), "correccion": correccion.to_dict()}), 201

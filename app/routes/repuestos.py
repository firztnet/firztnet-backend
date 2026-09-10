from flask import Blueprint, request, jsonify
from app import db
from app.models import Repuesto, MovimientoFinanciero

repuestos_bp = Blueprint("repuestos", __name__)


@repuestos_bp.get("")
def listar_repuestos():
    solo_stock_bajo = request.args.get("stock_bajo") == "true"
    repuestos = Repuesto.query.order_by(Repuesto.nombre).all()
    resultado = [r.to_dict() for r in repuestos]
    if solo_stock_bajo:
        resultado = [r for r in resultado if r["stock_bajo"]]
    return jsonify(resultado)


@repuestos_bp.post("")
def crear_repuesto():
    data = request.get_json() or {}
    if not data.get("nombre"):
        return jsonify({"error": "El nombre es obligatorio"}), 400

    repuesto = Repuesto(
        nombre=data["nombre"],
        categoria=data.get("categoria"),
        proveedor_id=data.get("proveedor_id"),
        stock_actual=data.get("stock_actual", 0),
        stock_minimo=data.get("stock_minimo", 1),
        precio_compra=data.get("precio_compra", 0),
        precio_venta=data.get("precio_venta", 0),
    )
    db.session.add(repuesto)
    db.session.commit()
    return jsonify(repuesto.to_dict()), 201


@repuestos_bp.patch("/<int:repuesto_id>/stock")
def actualizar_stock(repuesto_id):
    """Para registrar una compra de reposición de stock."""
    repuesto = Repuesto.query.get_or_404(repuesto_id)
    data = request.get_json() or {}
    cantidad = int(data.get("cantidad", 0))
    repuesto.stock_actual += cantidad
    db.session.commit()
    return jsonify(repuesto.to_dict())


@repuestos_bp.post("/<int:repuesto_id>/vender")
def vender_directo(repuesto_id):
    """Vender un repuesto/accesorio suelto (SSD, RAM, cable...) sin
    necesitar ninguna reparación de por medio — descuenta el stock y
    registra el ingreso en Caja en un solo paso."""
    repuesto = Repuesto.query.get_or_404(repuesto_id)
    data = request.get_json() or {}

    try:
        cantidad = int(data.get("cantidad", 1))
    except (TypeError, ValueError):
        return jsonify({"error": "La cantidad no es válida"}), 400
    if cantidad <= 0:
        return jsonify({"error": "La cantidad debe ser mayor que 0"}), 400
    if cantidad > repuesto.stock_actual:
        return jsonify({"error": f"Solo quedan {repuesto.stock_actual} unidades en stock"}), 400

    precio_unitario = data.get("precio_unitario")
    if precio_unitario is None:
        precio_unitario = float(repuesto.precio_venta or 0)
    else:
        try:
            precio_unitario = float(precio_unitario)
        except (TypeError, ValueError):
            return jsonify({"error": "El precio no es válido"}), 400
    if precio_unitario < 0:
        return jsonify({"error": "El precio no puede ser negativo"}), 400

    repuesto.stock_actual -= cantidad

    monto_total = round(precio_unitario * cantidad, 2)
    movimiento = MovimientoFinanciero(
        reparacion_id=None,  # venta suelta, sin reparación asociada
        tipo="ingreso",
        concepto=f"Venta directa: {repuesto.nombre} x{cantidad}",
        monto=monto_total,
        metodo_pago=data.get("metodo_pago", "efectivo"),
    )
    db.session.add(movimiento)
    db.session.commit()

    return jsonify({
        "repuesto": repuesto.to_dict(),
        "movimiento": movimiento.to_dict(),
    }), 201

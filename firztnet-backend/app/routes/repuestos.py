from flask import Blueprint, request, jsonify
from app import db
from app.models import Repuesto

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

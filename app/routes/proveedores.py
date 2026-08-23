from flask import Blueprint, request, jsonify
from app import db
from app.models import Proveedor

proveedores_bp = Blueprint("proveedores", __name__)


@proveedores_bp.get("")
def listar_proveedores():
    proveedores = Proveedor.query.order_by(Proveedor.nombre).all()
    return jsonify([p.to_dict() for p in proveedores])


@proveedores_bp.post("")
def crear_proveedor():
    data = request.get_json() or {}
    if not data.get("nombre"):
        return jsonify({"error": "El nombre es obligatorio"}), 400

    proveedor = Proveedor(nombre=data["nombre"], telefono=data.get("telefono"), email=data.get("email"))
    db.session.add(proveedor)
    db.session.commit()
    return jsonify(proveedor.to_dict()), 201


@proveedores_bp.get("/<int:proveedor_id>")
def obtener_proveedor(proveedor_id):
    proveedor = Proveedor.query.get_or_404(proveedor_id)
    data = proveedor.to_dict()
    data["repuestos"] = [r.to_dict() for r in proveedor.repuestos]
    return jsonify(data)

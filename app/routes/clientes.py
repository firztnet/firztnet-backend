from flask import Blueprint, request, jsonify
from app import db
from app.models import Cliente

clientes_bp = Blueprint("clientes", __name__)


def generar_codigo_cliente():
    """Nº correlativo simple para identificar al cliente, ej: CLI-0001."""
    ultimo = Cliente.query.order_by(Cliente.id.desc()).first()
    siguiente = (ultimo.id + 1) if ultimo else 1
    return f"CLI-{siguiente:04d}"


@clientes_bp.get("")
def listar_clientes():
    q = request.args.get("q", "").strip()
    query = Cliente.query
    if q:
        query = query.filter(Cliente.nombre.ilike(f"%{q}%"))
    clientes = query.order_by(Cliente.nombre).all()
    return jsonify([c.to_dict() for c in clientes])


@clientes_bp.post("")
def crear_cliente():
    data = request.get_json() or {}
    if not data.get("nombre"):
        return jsonify({"error": "El nombre es obligatorio"}), 400

    cliente = Cliente(
        codigo=generar_codigo_cliente(),
        nombre=data["nombre"],
        telefono=data.get("telefono"),
        email=data.get("email"),
    )
    db.session.add(cliente)
    db.session.commit()
    return jsonify(cliente.to_dict()), 201


@clientes_bp.get("/<int:cliente_id>")
def obtener_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    data = cliente.to_dict()
    data["reparaciones"] = [r.to_dict() for r in cliente.reparaciones]
    return jsonify(data)


@clientes_bp.put("/<int:cliente_id>")
def actualizar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    data = request.get_json() or {}
    cliente.nombre = data.get("nombre", cliente.nombre)
    cliente.telefono = data.get("telefono", cliente.telefono)
    cliente.email = data.get("email", cliente.email)
    db.session.commit()
    return jsonify(cliente.to_dict())

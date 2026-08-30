from datetime import datetime
from decimal import Decimal
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
        nif=data.get("nif"),
    )
    db.session.add(cliente)
    db.session.commit()
    return jsonify(cliente.to_dict()), 201


def _resumen_alertas(cliente):
    """Calcula, para un cliente: cuántas reparaciones entregadas no
    tienen ningún cobro registrado, y qué reparaciones siguen dentro
    del plazo de garantía."""
    hoy = datetime.utcnow()
    sin_cobrar = []
    en_garantia = []

    for rep in cliente.reparaciones:
        if rep.estado_actual in ("entregado", "completado"):
            total_cobrado = sum((m.monto for m in rep.movimientos if m.tipo == "ingreso"), Decimal("0"))
            if total_cobrado <= 0:
                sin_cobrar.append({"id": rep.id, "numero_orden": rep.numero_orden, "equipo": rep.equipo})

        if rep.fecha_fin_garantia and rep.fecha_fin_garantia >= hoy:
            en_garantia.append({
                "id": rep.id,
                "numero_orden": rep.numero_orden,
                "equipo": rep.equipo,
                "fecha_fin_garantia": rep.fecha_fin_garantia.isoformat(),
            })

    return {"sin_cobrar": sin_cobrar, "en_garantia": en_garantia}


@clientes_bp.get("/<int:cliente_id>")
def obtener_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    data = cliente.to_dict()
    data["reparaciones"] = [r.to_dict() for r in cliente.reparaciones]
    data["resumen"] = _resumen_alertas(cliente)
    return jsonify(data)


@clientes_bp.put("/<int:cliente_id>")
def actualizar_cliente(cliente_id):
    cliente = Cliente.query.get_or_404(cliente_id)
    data = request.get_json() or {}
    cliente.nombre = data.get("nombre", cliente.nombre)
    cliente.telefono = data.get("telefono", cliente.telefono)
    cliente.email = data.get("email", cliente.email)
    cliente.nif = data.get("nif", cliente.nif)
    db.session.commit()
    return jsonify(cliente.to_dict())

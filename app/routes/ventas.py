from datetime import datetime
from flask import Blueprint, jsonify, request
from app import db
from app.models import Venta

ventas_bp = Blueprint("ventas", __name__)

NEGOCIOS_VALIDOS = {"firztnet", "firztweb", "afiliados"}
TIPOS_VALIDOS = {"web", "app", "sistema", "afiliado", "otro"}


@ventas_bp.get("")
def listar_ventas():
    """Todas las ventas, más recientes primero. Filtrable por negocio
    con ?negocio=firztweb, y por cobradas/pendientes con ?cobrado=si|no."""
    query = Venta.query
    negocio = request.args.get("negocio")
    if negocio:
        query = query.filter_by(negocio=negocio)
    cobrado = request.args.get("cobrado")
    if cobrado == "si":
        query = query.filter_by(cobrado=True)
    elif cobrado == "no":
        query = query.filter_by(cobrado=False)

    ventas = query.order_by(Venta.fecha.desc(), Venta.id.desc()).all()
    return jsonify([v.to_dict() for v in ventas])


@ventas_bp.post("")
def crear_venta():
    data = request.get_json() or {}

    negocio = (data.get("negocio") or "firztweb").strip().lower()
    if negocio not in NEGOCIOS_VALIDOS:
        return jsonify({"error": "Negocio no reconocido"}), 400

    tipo = (data.get("tipo") or "").strip().lower()
    if tipo not in TIPOS_VALIDOS:
        return jsonify({"error": "Tipo de venta no reconocido"}), 400

    cliente_nombre = (data.get("cliente_nombre") or "").strip()
    if not cliente_nombre:
        return jsonify({"error": "El nombre del cliente es obligatorio"}), 400

    try:
        importe = float(data.get("importe") or 0)
    except (TypeError, ValueError):
        return jsonify({"error": "El importe no es un número válido"}), 400
    if importe < 0:
        return jsonify({"error": "El importe no puede ser negativo"}), 400

    fecha = datetime.utcnow().date()
    if data.get("fecha"):
        try:
            fecha = datetime.strptime(data["fecha"], "%Y-%m-%d").date()
        except ValueError:
            return jsonify({"error": "Fecha en formato incorrecto (usa AAAA-MM-DD)"}), 400

    venta = Venta(
        negocio=negocio,
        tipo=tipo,
        cliente_nombre=cliente_nombre,
        descripcion=data.get("descripcion"),
        importe=importe,
        cobrado=bool(data.get("cobrado")),
        enlace_nota=data.get("enlace_nota"),
        fecha=fecha,
    )
    db.session.add(venta)
    db.session.commit()
    return jsonify(venta.to_dict()), 201


@ventas_bp.patch("/<int:venta_id>")
def actualizar_venta(venta_id):
    """Para marcar como cobrada (o al revés), o corregir cualquier dato."""
    venta = Venta.query.get(venta_id)
    if not venta:
        return jsonify({"error": "Venta no encontrada"}), 404

    data = request.get_json() or {}
    if "cobrado" in data:
        venta.cobrado = bool(data["cobrado"])
    if "cliente_nombre" in data and data["cliente_nombre"].strip():
        venta.cliente_nombre = data["cliente_nombre"].strip()
    if "descripcion" in data:
        venta.descripcion = data["descripcion"]
    if "enlace_nota" in data:
        venta.enlace_nota = data["enlace_nota"]
    if "importe" in data:
        try:
            nuevo_importe = float(data["importe"])
            if nuevo_importe < 0:
                return jsonify({"error": "El importe no puede ser negativo"}), 400
            venta.importe = nuevo_importe
        except (TypeError, ValueError):
            return jsonify({"error": "El importe no es un número válido"}), 400
    if "tipo" in data:
        if data["tipo"] not in TIPOS_VALIDOS:
            return jsonify({"error": "Tipo de venta no reconocido"}), 400
        venta.tipo = data["tipo"]
    if "negocio" in data:
        if data["negocio"] not in NEGOCIOS_VALIDOS:
            return jsonify({"error": "Negocio no reconocido"}), 400
        venta.negocio = data["negocio"]

    db.session.commit()
    return jsonify(venta.to_dict())


@ventas_bp.delete("/<int:venta_id>")
def borrar_venta(venta_id):
    venta = Venta.query.get(venta_id)
    if not venta:
        return jsonify({"error": "Venta no encontrada"}), 404
    db.session.delete(venta)
    db.session.commit()
    return jsonify({"ok": True})


@ventas_bp.get("/resumen")
def resumen_ventas():
    """Totales por negocio: cuánto se ha vendido, cuánto está cobrado
    y cuánto sigue pendiente."""
    resultado = {}
    for negocio in NEGOCIOS_VALIDOS:
        ventas = Venta.query.filter_by(negocio=negocio).all()
        total = sum(v.importe for v in ventas)
        cobrado = sum(v.importe for v in ventas if v.cobrado)
        pendiente = total - cobrado
        resultado[negocio] = {
            "num_ventas": len(ventas),
            "total": round(total, 2),
            "cobrado": round(cobrado, 2),
            "pendiente": round(pendiente, 2),
        }
    return jsonify(resultado)

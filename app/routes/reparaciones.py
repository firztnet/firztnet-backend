from datetime import datetime
from flask import Blueprint, request, jsonify
from app import db
from app.models import Reparacion, Cliente, ReparacionRepuesto, Repuesto

reparaciones_bp = Blueprint("reparaciones", __name__)


def generar_numero_orden():
    """Nº correlativo por año, ej: 2026-0001, 2026-0002..."""
    anio = datetime.utcnow().year
    ultima = (
        Reparacion.query.filter(Reparacion.numero_orden.like(f"{anio}-%"))
        .order_by(Reparacion.id.desc())
        .first()
    )
    siguiente = 1
    if ultima:
        siguiente = int(ultima.numero_orden.split("-")[1]) + 1
    return f"{anio}-{siguiente:04d}"


@reparaciones_bp.get("")
def listar_reparaciones():
    """Soporta ?estado=diagnostico y ?q=busqueda para el kanban y el buscador."""
    estado = request.args.get("estado")
    q = request.args.get("q", "").strip()

    query = Reparacion.query
    if estado:
        query = query.filter_by(estado_actual=estado)
    if q:
        query = query.join(Cliente).filter(
            db.or_(
                Reparacion.numero_orden.ilike(f"%{q}%"),
                Reparacion.equipo.ilike(f"%{q}%"),
                Cliente.nombre.ilike(f"%{q}%"),
            )
        )
    reparaciones = query.order_by(Reparacion.fecha_recepcion.desc()).all()
    return jsonify([r.to_dict() for r in reparaciones])


@reparaciones_bp.post("")
def crear_reparacion():
    """Da de alta la reparación (recepción del equipo)."""
    data = request.get_json() or {}
    for campo in ("cliente_id", "equipo"):
        if not data.get(campo):
            return jsonify({"error": f"El campo '{campo}' es obligatorio"}), 400

    reparacion = Reparacion(
        numero_orden=generar_numero_orden(),
        cliente_id=data["cliente_id"],
        equipo=data["equipo"],
        accesorios_entregados=data.get("accesorios_entregados"),
        problema_reportado=data.get("problema_reportado"),
        estado_entrada=data.get("estado_entrada"),
        estado_actual="recibido",
    )
    if data.get("fecha_estimada"):
        reparacion.fecha_estimada = datetime.fromisoformat(data["fecha_estimada"])
    db.session.add(reparacion)
    db.session.commit()
    return jsonify(reparacion.to_dict()), 201


@reparaciones_bp.get("/<int:rep_id>")
def obtener_reparacion(rep_id):
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = reparacion.to_dict()
    data["repuestos_usados"] = [rr.to_dict() for rr in reparacion.repuestos_usados]
    data["movimientos"] = [m.to_dict() for m in reparacion.movimientos]
    return jsonify(data)


@reparaciones_bp.patch("/<int:rep_id>")
def editar_reparacion(rep_id):
    """Para editar campos sueltos después de crearla, como la fecha
    estimada de entrega (si al principio no la sabías)."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = request.get_json() or {}
    if "fecha_estimada" in data:
        reparacion.fecha_estimada = datetime.fromisoformat(data["fecha_estimada"]) if data["fecha_estimada"] else None
    db.session.commit()
    return jsonify(reparacion.to_dict())


@reparaciones_bp.patch("/<int:rep_id>/estado")
def cambiar_estado(rep_id):
    """Mueve la reparación en el kanban. Estados especiales (entregado,
    no_reparable) disparan la lógica adicional (garantía, motivo)."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = request.get_json() or {}
    nuevo_estado = data.get("estado")
    if not nuevo_estado:
        return jsonify({"error": "Falta el campo 'estado'"}), 400

    if nuevo_estado == "entregado":
        reparacion.marcar_entregada()
    elif nuevo_estado == "no_reparable":
        if not data.get("motivo"):
            return jsonify({"error": "Indica el motivo de no reparable"}), 400
        reparacion.marcar_no_reparable(data["motivo"])
    else:
        reparacion.estado_actual = nuevo_estado

    db.session.commit()
    return jsonify(reparacion.to_dict())


@reparaciones_bp.post("/<int:rep_id>/repuestos")
def añadir_repuesto(rep_id):
    """Asocia un repuesto usado a la reparación y descuenta stock."""
    reparacion = Reparacion.query.get_or_404(rep_id)
    data = request.get_json() or {}
    repuesto = Repuesto.query.get_or_404(data.get("repuesto_id"))
    cantidad = int(data.get("cantidad", 1))

    if repuesto.stock_actual < cantidad:
        return jsonify({"error": "Stock insuficiente de ese repuesto"}), 400

    uso = ReparacionRepuesto(
        reparacion_id=reparacion.id,
        repuesto_id=repuesto.id,
        cantidad=cantidad,
        precio_aplicado=data.get("precio_aplicado", repuesto.precio_venta),
    )
    repuesto.stock_actual -= cantidad
    db.session.add(uso)
    db.session.commit()
    return jsonify(uso.to_dict()), 201

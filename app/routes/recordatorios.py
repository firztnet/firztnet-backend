from datetime import date, datetime, timedelta
from flask import Blueprint, request, jsonify
from app import db
from app.models import Recordatorio, Cliente, Reparacion
from app.notificaciones import generar_enlace_whatsapp_texto

recordatorios_bp = Blueprint("recordatorios", __name__)


def _tiempo_transcurrido(desde):
    """'hace 6 meses' / 'hace 1 año' / 'hace 2 años', a partir de una fecha."""
    if not desde:
        return None
    dias = (datetime.utcnow() - desde).days
    if dias < 45:
        return "hace poco"
    meses = round(dias / 30)
    if meses < 11:
        return f"hace {meses} meses"
    anios = round(dias / 365)
    return f"hace {anios} año" + ("" if anios == 1 else "s")


def _con_mensaje_whatsapp(recordatorio):
    data = recordatorio.to_dict()
    cliente = recordatorio.cliente
    nombre = cliente.nombre.split(" ")[0] if cliente else ""

    referencia = ""
    if recordatorio.reparacion_id:
        reparacion = Reparacion.query.get(recordatorio.reparacion_id)
        if reparacion:
            cuando = _tiempo_transcurrido(reparacion.fecha_entrega or reparacion.fecha_recepcion)
            if cuando:
                referencia = f" {cuando} hicimos: {reparacion.equipo}."

    texto = f"Hola {nombre},{referencia} Te escribimos para agendar: {recordatorio.texto.lower()}. ¿Qué día te viene bien?"
    data["mensaje_sugerido"] = texto
    data["enlace_whatsapp"] = generar_enlace_whatsapp_texto(recordatorio, texto) if cliente and cliente.telefono else None
    return data


@recordatorios_bp.get("")
def listar_recordatorios():
    """Por defecto, solo los pendientes, ordenados por fecha (los más
    próximos o ya vencidos primero). Usa ?todos=true para verlos todos."""
    query = Recordatorio.query
    if request.args.get("todos") != "true":
        query = query.filter_by(cumplido=False)
    recordatorios = query.order_by(Recordatorio.fecha_programada).all()
    return jsonify([_con_mensaje_whatsapp(r) for r in recordatorios])


@recordatorios_bp.post("")
def crear_recordatorio():
    data = request.get_json() or {}
    if not data.get("cliente_id") or not data.get("texto"):
        return jsonify({"error": "Cliente y texto son obligatorios"}), 400

    Cliente.query.get_or_404(data["cliente_id"])

    if data.get("meses"):
        fecha_programada = date.today() + timedelta(days=30 * int(data["meses"]))
    elif data.get("fecha_programada"):
        fecha_programada = date.fromisoformat(data["fecha_programada"])
    else:
        return jsonify({"error": "Indica 'meses' (6 o 12) o una fecha concreta"}), 400

    recordatorio = Recordatorio(
        reparacion_id=data.get("reparacion_id"),
        cliente_id=data["cliente_id"],
        texto=data["texto"],
        fecha_programada=fecha_programada,
    )
    db.session.add(recordatorio)
    db.session.commit()
    return jsonify(recordatorio.to_dict()), 201


@recordatorios_bp.patch("/<int:recordatorio_id>")
def marcar_recordatorio(recordatorio_id):
    recordatorio = Recordatorio.query.get_or_404(recordatorio_id)
    data = request.get_json() or {}
    if "cumplido" in data:
        recordatorio.cumplido = bool(data["cumplido"])
    db.session.commit()
    return jsonify(recordatorio.to_dict())


@recordatorios_bp.delete("/<int:recordatorio_id>")
def borrar_recordatorio(recordatorio_id):
    recordatorio = Recordatorio.query.get_or_404(recordatorio_id)
    db.session.delete(recordatorio)
    db.session.commit()
    return jsonify({"eliminado": True})

from flask import Blueprint, request, jsonify
from app import db
from app.models import ConfiguracionNegocio

configuracion_bp = Blueprint("configuracion", __name__)


@configuracion_bp.get("")
def obtener_configuracion():
    return jsonify(ConfiguracionNegocio.obtener().to_dict())


@configuracion_bp.put("")
def actualizar_configuracion():
    config = ConfiguracionNegocio.obtener()
    data = request.get_json() or {}
    config.nombre_negocio = data.get("nombre_negocio", config.nombre_negocio)
    config.eslogan = data.get("eslogan", config.eslogan)
    config.direccion = data.get("direccion", config.direccion)
    config.telefono = data.get("telefono", config.telefono)
    config.email = data.get("email", config.email)
    config.nif = data.get("nif", config.nif)
    if "iva_pct" in data:
        try:
            config.iva_pct = float(data["iva_pct"])
        except (TypeError, ValueError):
            pass
    if "suplemento_desplazamiento" in data:
        try:
            config.suplemento_desplazamiento = float(data["suplemento_desplazamiento"])
        except (TypeError, ValueError):
            pass
    if "tarifa_hora" in data:
        try:
            config.tarifa_hora = float(data["tarifa_hora"])
        except (TypeError, ValueError):
            pass
    if "enlace_resenas_google" in data:
        config.enlace_resenas_google = data["enlace_resenas_google"]
    if "tecnicos" in data:
        # Puede llegar como lista (["Carlos", "Ana"]) o como texto ya unido.
        valor = data["tecnicos"]
        config.tecnicos = ", ".join(valor) if isinstance(valor, list) else valor
    if "coste_almacenamiento_diario" in data:
        try:
            config.coste_almacenamiento_diario = float(data["coste_almacenamiento_diario"])
        except (TypeError, ValueError):
            pass
    if "telegram_chat_id" in data:
        config.telegram_chat_id = data["telegram_chat_id"]
    db.session.commit()
    return jsonify(config.to_dict())


@configuracion_bp.post("/telegram/probar")
def probar_telegram():
    """Manda un mensaje de prueba para confirmar que el bot y el
    chat_id están bien configurados."""
    from app.notificaciones import enviar_telegram

    ok, detalle = enviar_telegram("🔧 Firztnet: esto es un mensaje de prueba. Si lo ves, ¡ya tienes las notificaciones de Telegram funcionando!")
    return jsonify({"ok": ok, "detalle": detalle}), (200 if ok else 400)

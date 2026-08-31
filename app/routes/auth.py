from flask import Blueprint, request, jsonify, current_app
from app.auth import generar_token, verificar_credenciales
from app import limiter

auth_bp = Blueprint("auth", __name__)


def _ip_real():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip()


@auth_bp.post("/login")
@limiter.limit(
    "5 per minute",
    deduct_when=lambda response: response.status_code == 401,  # SOLO cuentan los fallos — un login correcto nunca te puede bloquear a ti mismo
)
@limiter.limit(
    "15 per hour",  # si alguien espera el minuto y lo vuelve a intentar, esta capa lo frena antes de llegar muy lejos
    deduct_when=lambda response: response.status_code == 401,
)
@limiter.limit(
    "30 per day",  # última barrera: un atacante paciente choca con esto y queda bloqueado el resto del día
    deduct_when=lambda response: response.status_code == 401,
)
def login():
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")

    if not verificar_credenciales(username, password, current_app.config):
        from app.notificaciones import enviar_telegram
        try:
            enviar_telegram(f"⚠️ Intento de acceso fallido a Firztnet.\nUsuario probado: {username or '(vacío)'}\nIP: {_ip_real()}")
        except Exception:
            pass  # un fallo al avisar nunca debe impedir que el login responda con normalidad
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    token = generar_token(username, current_app.config["SECRET_KEY"])
    return jsonify({"token": token})

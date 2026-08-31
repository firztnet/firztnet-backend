from flask import Blueprint, request, jsonify, current_app
from app.auth import generar_token, verificar_credenciales
from app import limiter

auth_bp = Blueprint("auth", __name__)


@auth_bp.post("/login")
@limiter.limit("5 per minute")  # frena la fuerza bruta contra el usuario/contraseña
def login():
    data = request.get_json() or {}
    username = data.get("username", "")
    password = data.get("password", "")

    if not verificar_credenciales(username, password, current_app.config):
        return jsonify({"error": "Usuario o contraseña incorrectos"}), 401

    token = generar_token(username, current_app.config["SECRET_KEY"])
    return jsonify({"token": token})

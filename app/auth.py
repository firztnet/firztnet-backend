"""Login simple de un solo usuario (el dueño del negocio) mediante token.
Protege toda la API excepto /api/auth/login y /api/salud."""
import time
import hmac
import jwt
from flask import request, jsonify

DURACION_TOKEN_SEGUNDOS = 60 * 60 * 24 * 14  # 14 días

RUTAS_PUBLICAS = ("/api/auth/login", "/api/salud")


def generar_token(username, secret_key):
    payload = {"sub": username, "exp": int(time.time()) + DURACION_TOKEN_SEGUNDOS}
    return jwt.encode(payload, secret_key, algorithm="HS256")


def verificar_credenciales(username, password, config):
    """Comparación segura (evita timing attacks) del usuario/contraseña
    configurados en las variables de entorno."""
    return hmac.compare_digest(username or "", config["ADMIN_USERNAME"]) and hmac.compare_digest(
        password or "", config["ADMIN_PASSWORD"]
    )


def registrar_proteccion(app):
    @app.before_request
    def _verificar_token():
        # El navegador manda una petición OPTIONS antes de cada POST/PUT/PATCH
        # entre dominios distintos (CORS) — hay que dejarla pasar siempre,
        # o el navegador bloquea también las peticiones reales por CORS.
        if request.method == "OPTIONS":
            return

        if request.path in RUTAS_PUBLICAS or not request.path.startswith("/api/"):
            return

        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "No autorizado"}), 401

        token = auth_header.split(" ", 1)[1]
        try:
            jwt.decode(token, app.config["SECRET_KEY"], algorithms=["HS256"])
        except jwt.PyJWTError:
            return jsonify({"error": "Sesión expirada o inválida"}), 401

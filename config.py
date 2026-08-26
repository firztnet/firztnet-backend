import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))


class Config:
    # En local usa SQLite (como el POS). En producción, pon aquí tu URL de
    # PostgreSQL en la nube (Railway, Render, Supabase...), por ejemplo:
    # postgresql://usuario:password@host:5432/firztnet
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", f"sqlite:///{os.path.join(BASE_DIR, 'firztnet.db')}"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = os.environ.get("SECRET_KEY", "cambia-esta-clave-en-produccion")

    # Credenciales de acceso al panel. Cámbialas con las variables de
    # entorno ADMIN_USERNAME / ADMIN_PASSWORD en Railway — no dejes las
    # de por defecto en producción.
    ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
    ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "cambia-esta-contraseña")

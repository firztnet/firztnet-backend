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

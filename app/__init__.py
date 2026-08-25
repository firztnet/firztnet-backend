from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    db.init_app(app)
    CORS(app)  # permite que el frontend (web/app) consuma esta API

    from app.routes.clientes import clientes_bp
    from app.routes.reparaciones import reparaciones_bp
    from app.routes.repuestos import repuestos_bp
    from app.routes.proveedores import proveedores_bp
    from app.routes.finanzas import finanzas_bp
    from app.routes.reportes import reportes_bp
    from app.routes.comprobantes import comprobantes_bp
    from app.routes.configuracion import configuracion_bp

    app.register_blueprint(clientes_bp, url_prefix="/api/clientes")
    app.register_blueprint(reparaciones_bp, url_prefix="/api/reparaciones")
    app.register_blueprint(repuestos_bp, url_prefix="/api/repuestos")
    app.register_blueprint(proveedores_bp, url_prefix="/api/proveedores")
    app.register_blueprint(finanzas_bp, url_prefix="/api/finanzas")
    app.register_blueprint(reportes_bp, url_prefix="/api/reportes")
    app.register_blueprint(comprobantes_bp, url_prefix="/api/comprobantes")
    app.register_blueprint(configuracion_bp, url_prefix="/api/configuracion")

    @app.get("/api/salud")
    def salud():
        return {"estado": "ok", "servicio": "Firztnet - gestión de reparaciones"}

    return app

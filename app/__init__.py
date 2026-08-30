from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from app.auth import registrar_proteccion

db = SQLAlchemy()


def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    db.init_app(app)
    CORS(app)  # permite que el frontend (web/app) consuma esta API
    registrar_proteccion(app)  # exige login (token) en toda la API

    from app.routes.auth import auth_bp
    from app.routes.clientes import clientes_bp
    from app.routes.reparaciones import reparaciones_bp
    from app.routes.repuestos import repuestos_bp
    from app.routes.proveedores import proveedores_bp
    from app.routes.finanzas import finanzas_bp
    from app.routes.reportes import reportes_bp
    from app.routes.comprobantes import comprobantes_bp
    from app.routes.configuracion import configuracion_bp
    from app.routes.recibos import recibos_bp
    from app.routes.facturas import facturas_bp
    from app.routes.seguimiento import seguimiento_bp
    from app.routes.fotos import fotos_bp
    from app.routes.checklist import checklist_bp
    from app.routes.presupuestos import presupuestos_bp
    from app.routes.plantillas import plantillas_bp
    from app.routes.sesiones import sesiones_bp
    from app.routes.conocimiento import conocimiento_bp
    from app.routes.recordatorios import recordatorios_bp
    from app.routes.parte_trabajo import parte_trabajo_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(clientes_bp, url_prefix="/api/clientes")
    app.register_blueprint(reparaciones_bp, url_prefix="/api/reparaciones")
    app.register_blueprint(repuestos_bp, url_prefix="/api/repuestos")
    app.register_blueprint(proveedores_bp, url_prefix="/api/proveedores")
    app.register_blueprint(finanzas_bp, url_prefix="/api/finanzas")
    app.register_blueprint(reportes_bp, url_prefix="/api/reportes")
    app.register_blueprint(comprobantes_bp, url_prefix="/api/comprobantes")
    app.register_blueprint(configuracion_bp, url_prefix="/api/configuracion")
    app.register_blueprint(recibos_bp, url_prefix="/api/recibos")
    app.register_blueprint(facturas_bp, url_prefix="/api/facturas")
    app.register_blueprint(seguimiento_bp, url_prefix="/api/seguimiento")
    app.register_blueprint(fotos_bp, url_prefix="/api")
    app.register_blueprint(checklist_bp, url_prefix="/api/checklist")
    app.register_blueprint(presupuestos_bp, url_prefix="/api")
    app.register_blueprint(plantillas_bp, url_prefix="/api/plantillas")
    app.register_blueprint(sesiones_bp, url_prefix="/api")
    app.register_blueprint(conocimiento_bp, url_prefix="/api/conocimiento")
    app.register_blueprint(recordatorios_bp, url_prefix="/api/recordatorios")
    app.register_blueprint(parte_trabajo_bp, url_prefix="/api")

    @app.get("/api/salud")
    def salud():
        return {"estado": "ok", "servicio": "Firztnet - gestión de reparaciones"}

    return app

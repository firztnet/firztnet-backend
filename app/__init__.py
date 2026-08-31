from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from app.auth import registrar_proteccion

db = SQLAlchemy()
# Aviso: el almacenamiento en memoria de Flask-Limiter asume UN SOLO
# proceso (igual que el backup automático) — el Procfile actual no usa
# --workers, así que vale. Si algún día escalas a varios workers,
# habría que pasar a un almacenamiento compartido (ej. Redis).
limiter = Limiter(get_remote_address, default_limits=[])


def create_app():
    app = Flask(__name__)
    app.config.from_object("config.Config")

    db.init_app(app)
    CORS(app)  # permite que el frontend (web/app) consuma esta API
    registrar_proteccion(app)  # exige login (token) en toda la API
    limiter.init_app(app)

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
    from app.routes.rma import rma_bp
    from app.routes.solicitudes import solicitudes_bp
    from app.routes.sugerencias import sugerencias_bp
    from app.routes.backup import backup_bp
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
    app.register_blueprint(rma_bp, url_prefix="/api/rma")
    app.register_blueprint(solicitudes_bp, url_prefix="/api/solicitudes")
    app.register_blueprint(sugerencias_bp, url_prefix="/api/sugerencias")
    app.register_blueprint(backup_bp, url_prefix="/api/backup")
    app.register_blueprint(sesiones_bp, url_prefix="/api")
    app.register_blueprint(conocimiento_bp, url_prefix="/api/conocimiento")
    app.register_blueprint(recordatorios_bp, url_prefix="/api/recordatorios")
    app.register_blueprint(parte_trabajo_bp, url_prefix="/api")

    @app.get("/api/salud")
    def salud():
        return {"estado": "ok", "servicio": "Firztnet - gestión de reparaciones"}

    @app.errorhandler(413)
    def _archivo_demasiado_grande(e):
        from flask import jsonify
        return jsonify({"error": "El archivo (o la suma de archivos) supera el límite de 30 MB por subida."}), 413

    @app.errorhandler(429)
    def _demasiadas_peticiones(e):
        from flask import jsonify
        return jsonify({"error": "Demasiados intentos seguidos. Espera un minuto y vuelve a intentarlo."}), 429

    _programar_backup_automatico(app)

    return app


def _programar_backup_automatico(app):
    """Backup diario automático (a las 4:00 UTC), enviado por Telegram
    si lo tienes configurado — si no, no hace nada (no rompe nada).

    Aviso: esto asume UN SOLO proceso de gunicorn (el Procfile actual
    no especifica --workers, así que por defecto es 1). Si algún día
    escalas a varios workers, esta tarea se dispararía una vez por
    worker — habría que moverla a un servicio de cron aparte en ese
    caso."""
    import os
    if os.environ.get("DESACTIVAR_BACKUP_AUTOMATICO") == "true":
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler
    except ImportError:
        return  # si la librería no está instalada, simplemente no se programa nada

    def _tarea_backup():
        with app.app_context():
            from app.backup import crear_backup_zip
            from app.notificaciones import enviar_documento_telegram
            try:
                nombre_archivo, buffer = crear_backup_zip()
                enviar_documento_telegram(nombre_archivo, buffer.read(), caption=f"📦 Backup automático diario — {nombre_archivo}")
            except Exception:
                pass  # un fallo en el backup automático no debe tumbar el servidor

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(_tarea_backup, "cron", hour=4, minute=0)
    scheduler.start()

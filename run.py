from app import create_app, db
from app.models import Estado, Cliente, Reparacion, PlantillaMensaje
from app.migraciones import aplicar_migraciones
import os
import secrets

app = create_app()

ESTADOS_INICIALES = [
    ("recibido", "Recibido", 1),
    ("diagnostico", "Diagnóstico", 2),
    ("reparacion", "En reparación", 3),
    ("listo", "Listo para entrega", 4),
    ("entregado", "Entregado", 5),
    ("no_reparable", "No reparable", 6),
]

PLANTILLAS_INICIALES = [
    ("Equipo listo para retirar", "Hola {cliente}, tu equipo ({equipo}) ya está listo para recoger. ¡Te esperamos!", "listo"),
    ("Esperando repuesto", "Hola {cliente}, tu equipo ({equipo}, orden {numero_orden}) está a la espera de un repuesto. Te avisaremos en cuanto llegue.", None),
    ("Diagnóstico y firma", "Hola {cliente}, ya tenemos el diagnóstico de tu {equipo}. Revisa y aprueba el presupuesto aquí: {enlace_seguimiento}", "diagnostico"),
    ("Presupuesto pendiente de aprobación", "Hola {cliente}, te hemos preparado el presupuesto de tu equipo ({equipo}). Revísalo y fírmalo aquí: {enlace_seguimiento}", None),
]

# Se ejecuta siempre al importar el módulo (tanto con `python run.py` en
# local como con gunicorn en producción), para que las tablas y los
# estados iniciales existan sin depender de cómo se arranque la app.
with app.app_context():
    db.create_all()
    aplicar_migraciones(db)  # añade columnas nuevas a tablas que ya existían

    if Estado.query.count() == 0:
        for codigo, nombre, orden in ESTADOS_INICIALES:
            db.session.add(Estado(codigo=codigo, nombre=nombre, orden=orden))
        db.session.commit()

    # Asigna código a clientes ya existentes que se crearon antes de que
    # este campo existiera (por si la base de datos ya tenía clientes).
    sin_codigo = Cliente.query.filter(Cliente.codigo.is_(None)).order_by(Cliente.id).all()
    for cliente in sin_codigo:
        cliente.codigo = f"CLI-{cliente.id:04d}"
    if sin_codigo:
        db.session.commit()

    # Igual, pero para el token de la página pública de seguimiento.
    sin_token = Reparacion.query.filter(Reparacion.token_seguimiento.is_(None)).all()
    for reparacion in sin_token:
        reparacion.token_seguimiento = secrets.token_hex(8)
    if sin_token:
        db.session.commit()

    if PlantillaMensaje.query.count() == 0:
        for nombre, texto, estado_disparador in PLANTILLAS_INICIALES:
            db.session.add(PlantillaMensaje(nombre=nombre, texto=texto, estado_disparador=estado_disparador))
        db.session.commit()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

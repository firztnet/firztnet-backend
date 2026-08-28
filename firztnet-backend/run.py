from app import create_app, db
from app.models import Estado, Cliente
from app.migraciones import aplicar_migraciones
import os

app = create_app()

ESTADOS_INICIALES = [
    ("recibido", "Recibido", 1),
    ("diagnostico", "Diagnóstico", 2),
    ("reparacion", "En reparación", 3),
    ("listo", "Listo para entrega", 4),
    ("entregado", "Entregado", 5),
    ("no_reparable", "No reparable", 6),
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

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

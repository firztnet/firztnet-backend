from app import create_app, db
from app.models import Estado
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
    if Estado.query.count() == 0:
        for codigo, nombre, orden in ESTADOS_INICIALES:
            db.session.add(Estado(codigo=codigo, nombre=nombre, orden=orden))
        db.session.commit()

if __name__ == "__main__":
    app.run(debug=False, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

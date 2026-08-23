from app import create_app, db
from app.models import Estado

app = create_app()

ESTADOS_INICIALES = [
    ("recibido", "Recibido", 1),
    ("diagnostico", "Diagnóstico", 2),
    ("reparacion", "En reparación", 3),
    ("listo", "Listo para entrega", 4),
    ("entregado", "Entregado", 5),
    ("no_reparable", "No reparable", 6),
]

if __name__ == "__main__":
    with app.app_context():
        db.create_all()
        if Estado.query.count() == 0:
            for codigo, nombre, orden in ESTADOS_INICIALES:
                db.session.add(Estado(codigo=codigo, nombre=nombre, orden=orden))
            db.session.commit()
            print("Estados iniciales creados.")

    app.run(debug=True, port=5000)

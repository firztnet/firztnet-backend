"""SQLite (y la mayoría de bases de datos) no añaden columnas nuevas
solo porque el modelo de Python cambie — `db.create_all()` únicamente
crea tablas que todavía no existen. Como la base de datos ahora es
permanente (volumen en Railway), cada vez que añadimos un campo nuevo
a un modelo hace falta esta pequeña migración para que se refleje en
la tabla real, sin perder los datos que ya había."""
from sqlalchemy import inspect, text

# columna -> definición SQL a usar si hay que crearla
COLUMNAS_NUEVAS = {
    "clientes": [
        ("nif", "VARCHAR(20)"),
    ],
    "configuracion_negocio": [
        ("nif", "VARCHAR(20)"),
        ("iva_pct", "NUMERIC(5, 2) DEFAULT 21"),
        ("suplemento_desplazamiento", "NUMERIC(10, 2) DEFAULT 20"),
        ("tarifa_hora", "NUMERIC(10, 2) DEFAULT 25"),
        ("enlace_resenas_google", "VARCHAR(300)"),
    ],
    "reparaciones": [
        ("token_seguimiento", "VARCHAR(40)"),
        ("presupuesto_importe", "NUMERIC(10, 2)"),
        ("presupuesto_descripcion", "TEXT"),
        ("presupuesto_estado", "VARCHAR(20)"),
        ("presupuesto_fecha", "DATETIME"),
        ("marca", "VARCHAR(60)"),
        ("modelo", "VARCHAR(60)"),
        ("urgente", "BOOLEAN DEFAULT 0"),
        ("tipo_trabajo", "VARCHAR(20) DEFAULT 'taller'"),
        ("direccion_servicio", "VARCHAR(200)"),
        ("categoria", "VARCHAR(40)"),
    ],
}


def aplicar_migraciones(db):
    inspector = inspect(db.engine)
    tablas_existentes = inspector.get_table_names()

    for tabla, columnas in COLUMNAS_NUEVAS.items():
        if tabla not in tablas_existentes:
            continue  # la tabla se crea entera con create_all(), no hace falta nada más
        columnas_actuales = {c["name"] for c in inspector.get_columns(tabla)}
        for nombre_columna, tipo_sql in columnas:
            if nombre_columna not in columnas_actuales:
                db.session.execute(text(f"ALTER TABLE {tabla} ADD COLUMN {nombre_columna} {tipo_sql}"))

    db.session.commit()

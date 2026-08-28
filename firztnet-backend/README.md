# Firztnet — backend de gestión de reparaciones

API en Flask que implementa el esquema que revisamos: clientes,
reparaciones (recepción → seguimiento → entrega/no reparable),
inventario de repuestos con proveedores, movimientos financieros y
comprobantes.

## Puesta en marcha (local, con SQLite)

```bash
python -m venv venv
source venv/bin/activate      # en Windows: venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Esto crea `firztnet.db` (SQLite) con las tablas y los 6 estados
iniciales, y arranca la API en `http://localhost:5000`.

## Pasar a producción (PostgreSQL en la nube)

1. Crea una base de datos en Railway, Render o Supabase.
2. Copia la URL de conexión (empieza por `postgresql://...`).
3. Define la variable de entorno `DATABASE_URL` con esa URL antes de
   arrancar la app (o en un archivo `.env`).
4. Vuelve a ejecutar `python run.py` — creará las tablas en la nube.

## Endpoints principales

| Método | Ruta | Qué hace |
|---|---|---|
| POST | `/api/clientes` | Alta de cliente |
| POST | `/api/reparaciones` | Recepción de un equipo (genera nº de orden automático) |
| GET | `/api/reparaciones?estado=diagnostico` | Listado para el kanban, filtrable por estado |
| PATCH | `/api/reparaciones/<id>/estado` | Mueve la reparación de estado (entregado dispara la garantía de 6 meses; no_reparable pide motivo) |
| POST | `/api/reparaciones/<id>/repuestos` | Asocia un repuesto usado y descuenta stock |
| POST | `/api/comprobantes` | Genera el comprobante (recepción/entrega/no reparable) con enlace de seguimiento |
| GET | `/api/reportes/diario` | Balance del día |
| GET | `/api/reportes/mensual` | Balance del mes, ticket medio |
| GET | `/api/reportes/contador` | Contador de reparaciones (total, en curso, entregadas, no reparables) |
| GET/POST | `/api/repuestos` | Inventario (usa `?stock_bajo=true` para ver qué reponer) |
| GET/POST | `/api/proveedores` | Proveedores |
| GET/POST | `/api/finanzas` | Movimientos de caja (ingresos/gastos) |

## Siguiente paso

Este backend ya expone todo lo necesario para conectar el panel
visual (el prototipo React/JSX) vía `fetch` a estas rutas. La
generación real del PDF del comprobante (con reportlab o WeasyPrint)
y el envío por WhatsApp/email quedan como el siguiente bloque a
construir.

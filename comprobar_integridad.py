"""Comprobación de que no falta nada importante antes de publicar.

El 13/11/2026 se subió la sección Flota hecha sobre una copia antigua y borró
Firztnet Central sin que nadie se diera cuenta. Esta comprobación lo impide:

· Railway la ejecuta al construir (railway.json): si falta algo, NO publica y
  sigue funcionando la versión anterior.
· GitHub la ejecuta en cada subida (.github/workflows/comprobar.yml) y, si
  falla, te llega un correo.

Solo lee el texto de los archivos: no necesita librerías ni base de datos.
Si algún día quitas algo a propósito, quítalo también de esta lista.
Uso: python comprobar_integridad.py
"""
import os
import sys

AQUI = os.path.dirname(os.path.abspath(__file__))

# archivo -> trozos de texto que tienen que estar (con una explicación de qué es)
OBLIGATORIO = {
    "app/models.py": [
        ("class PeticionAyuda", "Central: peticiones de ayuda de los sistemas"),
        ("class SistemaVigilado", "Central: sistemas y webs vigilados"),
        ("class IncidenciaSistema", "Central: caídas de los sistemas"),
        ("class LocalCliente", "Central: fichas de los clientes de tus sistemas"),
        ("class InformeMensual", "Central: informes mensuales de visitas"),
        ("class CopiaSistema", "Central: copias de seguridad vigiladas"),
        ("class Vehiculo", "Flota: vehículos"),
        ("class RegistroVehiculo", "Flota: registros de los vehículos"),
        ("class PosTienda", "Punto de venta: tiendas"),
        ("class PosEquipo", "Punto de venta: ordenadores de cada tienda"),
    ],
    "app/__init__.py": [
        ("register_blueprint(central_bp", "Central: sus rutas"),
        ("central_extra", "Central: cobros, riesgo, copias y respuestas rápidas"),
        ("_programar_vigilancia(app)", "Central: vigilancia cada 2 minutos y avisos de las 9:00"),
        ("register_blueprint(flota_bp", "Flota: sus rutas"),
        ("register_blueprint(pos_bp", "Punto de venta: sus rutas"),
        ("_programar_backup_automatico(app)", "Copia de seguridad diaria"),
    ],
    "app/auth.py": [
        ("/api/central/entrada/", "Central: los sistemas entran con su clave, sin login"),
        ("/api/seguimiento/", "Página pública de seguimiento de reparaciones"),
        ("/api/central/pos/entrada/", "Punto de venta: las tiendas entran con su credencial, sin login"),
    ],
    "app/routes/central.py": [
        ("/entrada/ayuda", "Central: recibir «Pedir ayuda»"),
        ("/entrada/locales", "Central: recibir las fichas de los clientes"),
    ],
    "app/routes/central_extra.py": [("def guardar_copia_sistema", "Central: copias de los sistemas")],
    "app/salud.py": [("def comprobar_todo", "Central: la vigilancia de los sistemas")],
    "app/routes/flota.py": [("flota_bp", "Flota")],
    "app/routes/pos.py": [("/entrada/parte", "Punto de venta: parte de cada tienda"), ("def licencia_de", "Punto de venta: licencias firmadas")],
}


def faltas():
    lista = []
    for archivo, trozos in OBLIGATORIO.items():
        ruta = os.path.join(AQUI, archivo)
        if not os.path.exists(ruta):
            lista.append(f"Falta el archivo {archivo}")
            continue
        with open(ruta, encoding="utf-8", errors="replace") as f:
            texto = f.read()
        for trozo, que_es in trozos:
            if trozo not in texto:
                lista.append(f"{archivo}: falta «{trozo}» ({que_es})")
    return lista


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    problemas = faltas()
    if problemas:
        print("NO SE PUBLICA: a esta versión le faltan partes importantes.")
        print("¿Se ha subido una copia antigua? Descarga la última versión de GitHub y vuelve a hacer el cambio.\n")
        for p in problemas:
            print(" - " + p)
        sys.exit(1)
    print("Comprobación correcta: Central, Flota y copias están en su sitio.")

import os
import re
import base64
import uuid
from app.models import Firma

# Igual que las fotos: en Railway, configura FIRMAS_DIR=/data/firmas
# (el mismo volumen persistente) para que no se pierdan al redesplegar.
FIRMAS_DIR = os.environ.get("FIRMAS_DIR", os.path.join(os.path.dirname(os.path.dirname(__file__)), "firmas"))
os.makedirs(FIRMAS_DIR, exist_ok=True)


def guardar_firma_png(data_url, reparacion_id, tipo):
    """data_url es el string que da un <canvas>.toDataURL('image/png'),
    tipo 'data:image/png;base64,AAAA...'. Devuelve la ruta del archivo
    guardado."""
    coincidencia = re.match(r"data:image/png;base64,(.+)", data_url or "")
    if not coincidencia:
        raise ValueError("Formato de firma no válido")

    bytes_png = base64.b64decode(coincidencia.group(1))
    nombre_archivo = f"{tipo}_{reparacion_id}_{uuid.uuid4().hex[:10]}.png"
    ruta = os.path.join(FIRMAS_DIR, nombre_archivo)
    with open(ruta, "wb") as f:
        f.write(bytes_png)
    return nombre_archivo, ruta


def ruta_completa(nombre_archivo):
    return os.path.join(FIRMAS_DIR, nombre_archivo)

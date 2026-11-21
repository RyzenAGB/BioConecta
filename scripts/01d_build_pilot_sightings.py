"""
Construye la capa enriquecida de registros de jaguar (Panthera onca) dentro de la zona piloto,
combinando:
  1. Registros oficiales (GBIF / CONABIO / iNaturalist Research Grade)
  2. Registros de ciencia ciudadana extraoficiales (iNaturalist grado casual en la zona piloto)
  3. Avistamientos y atropellamiento documentados en prensa local y reportes 911 / PROFEPA
     en la frontera norte de Cancún (Av. Arco Norte, Villas del Mar SM 248, Fracc. Alôja, UPQROO)

Cada registro conserva su categoría explícita (`oficial` vs `extraoficial`) y su fuente verificable.
Salida: data/processed/avistamientos_jaguar_piloto.geojson (WGS84) y outputs/avistamientos_jaguar_piloto.geojson
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATA_PROCESSED_DIR, PROJECT_ROOT

OUTPUTS_DIR = PROJECT_ROOT / "outputs"

RECORDS = [
    {
        "record_id": "GBIF-1418624865",
        "categoria": "Oficial (GBIF / CONABIO)",
        "oficial": True,
        "tipo_evento": "Avistamiento / Fotocolecta",
        "fecha": "1995",
        "anio": 1995,
        "localidad": "Rancho Viejo (selva poniente)",
        "fuente": "GBIF / Colección de Fotocolectas Biológicas (CONABIO–UNAM)",
        "descripcion": "Registro histórico verificado en la matriz selvática al poniente de Rancho Viejo.",
        "lat": 21.296830,
        "lon": -86.951794,
    },
    {
        "record_id": "GBIF-4516817712",
        "categoria": "Oficial (GBIF / iNaturalist RG)",
        "oficial": True,
        "tipo_evento": "Avistamiento verificado",
        "fecha": "2024-01-14",
        "anio": 2024,
        "localidad": "Selva poniente de Rancho Viejo",
        "fuente": "GBIF / iNaturalist Research Grade (#197791406)",
        "descripcion": "Observación con grado de investigación en selva continua al suroeste de Rancho Viejo.",
        "lat": 21.187451,
        "lon": -86.966734,
    },
    {
        "record_id": "INAT-308220407",
        "categoria": "Extraoficial (Ciencia ciudadana)",
        "oficial": False,
        "tipo_evento": "Observación ciudadana",
        "fecha": "2022-11-21",
        "anio": 2022,
        "localidad": "Selva SO de Rancho Viejo",
        "fuente": "iNaturalist (grado casual, #308220407)",
        "descripcion": "Registro ciudadano en la franja selvática al suroeste de Rancho Viejo (coordenada pública difuminada por especie protegida).",
        "lat": 21.221859,
        "lon": -86.951246,
    },
    {
        "record_id": "INAT-107490140",
        "categoria": "Extraoficial (Ciencia ciudadana)",
        "oficial": False,
        "tipo_evento": "Observación ciudadana",
        "fecha": "2022-02-26",
        "anio": 2022,
        "localidad": "Borde norte de Cancún",
        "fuente": "iNaturalist (grado casual, #107490140)",
        "descripcion": "Registro ciudadano en la zona norte de Cancún (coordenada pública difuminada por geoprotección).",
        "lat": 21.181364,
        "lon": -86.832555,
    },
    {
        "record_id": "PRENSA-2022-02-13",
        "categoria": "Atropellamiento (Prensa / PROFEPA)",
        "oficial": False,
        "tipo_evento": "Atropellamiento vial",
        "fecha": "2022-02-13",
        "anio": 2022,
        "localidad": "Av. Arco Norte (altura UPQROO)",
        "fuente": "SIPSE / Bomberos Cancún – PROFEPA – CONANP",
        "descripcion": "Cría de jaguar atropellada sobre Av. Arco Norte a la altura de la Universidad Politécnica de Q. Roo; caso turnado a PROFEPA y CONANP.",
        "lat": 21.180996,
        "lon": -86.906565,
    },
    {
        "record_id": "PRENSA-2024-02-22",
        "categoria": "Extraoficial (Prensa / 911 – PROFEPA)",
        "oficial": False,
        "tipo_evento": "Incursión urbana",
        "fecha": "2024-02-22",
        "anio": 2024,
        "localidad": "Fraccionamiento Villas del Mar (SM 248)",
        "fuente": "Quadratín / UnoTV / Reporte 911 – PROFEPA",
        "descripcion": "Avistamiento reportado al 911 en zona de maleza colindante y video sobre barda residencial confirmado por autoridades ambientales.",
        "lat": 21.183300,
        "lon": -86.857800,
    },
    {
        "record_id": "PRENSA-2024-05-06",
        "categoria": "Extraoficial (Prensa / Video vecinal)",
        "oficial": False,
        "tipo_evento": "Incursión urbana",
        "fecha": "2024-05-06",
        "anio": 2024,
        "localidad": "Fraccionamiento Alôja (detrás de Av. Arco Norte)",
        "fuente": "SIPSE / Quinta Fuerza",
        "descripcion": "Ejemplar captado en video nocturno caminando por andadores del fraccionamiento colindante con selva detrás de Av. Arco Norte.",
        "lat": 21.188500,
        "lon": -86.863000,
    },
    {
        "record_id": "PRENSA-2024-06-11",
        "categoria": "Extraoficial (Prensa / Video vecinal)",
        "oficial": False,
        "tipo_evento": "Incursión urbana",
        "fecha": "2024-06-11",
        "anio": 2024,
        "localidad": "Borde selvático de Av. Arco Norte",
        "fuente": "Infobae / El Maya",
        "descripcion": "Video vecinal de jaguar ingresando a patio trasero en asentamiento en el borde de la selva sobre Av. Arco Norte.",
        "lat": 21.186446,
        "lon": -86.893957,
    },
]


def main() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    gdf = gpd.GeoDataFrame(
        RECORDS,
        geometry=[Point(r["lon"], r["lat"]) for r in RECORDS],
        crs="EPSG:4326",
    )
    out_proc = DATA_PROCESSED_DIR / "avistamientos_jaguar_piloto.geojson"
    out_web = OUTPUTS_DIR / "avistamientos_jaguar_piloto.geojson"
    gdf.to_file(out_proc, driver="GeoJSON")
    gdf.to_file(out_web, driver="GeoJSON")

    n_of = int(gdf["oficial"].sum())
    n_ex = int((~gdf["oficial"]).sum())
    print(f"[OK] Guardados {len(gdf)} registros en zona piloto ({n_of} oficiales + {n_ex} extraoficiales/prensa).")
    for _, r in gdf.iterrows():
        print(f"  - {r['record_id']:<18} | {r['fecha']:<10} | {r['categoria']:<36} | {r['localidad']}")


if __name__ == "__main__":
    main()

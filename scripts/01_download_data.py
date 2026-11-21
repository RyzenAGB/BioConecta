"""
Paso 0 (Parte 1): Descarga de las capas geoespaciales base para BioConecta.

Capas que se descargan en data/raw/:
1. Cobertura vegetal 2020 (ESA WorldCover 10m v100, tile N21W087)
2. Cobertura vegetal 2021 (ESA WorldCover 10m v200, tile N21W087)
3. Red vial de la zona piloto (OpenStreetMap vía Overpass API)
4. Registros de presencia de jaguar - Panthera onca (GBIF API, para validación)

Nota: La capa de mancha urbana se extrae directamente de la clase 50 (Built-up)
de ESA WorldCover en el paso de normalización (02_prepare_layers.py).
"""

import json
import sys
from pathlib import Path

import requests

# Permitir importar config.py desde la raíz del proyecto
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    AOI_BBOX_WGS84,
    DATA_RAW_DIR,
    ESA_WORLDCOVER_URLS,
    REGIONAL_BBOX_WGS84,
)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def download_file(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [OK] Ya existe: {dest.name} ({dest.stat().st_size / 1e6:.2f} MB)")
        return

    print(f"  Descargando {dest.name} ...")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    print(f"  [OK] Descargado: {dest.name} ({dest.stat().st_size / 1e6:.2f} MB)")


def download_worldcover() -> None:
    print("\n[1/3] Descargando ESA WorldCover (2020 y 2021)...")
    for year, url in ESA_WORLDCOVER_URLS.items():
        dest = DATA_RAW_DIR / f"esa_worldcover_{year}_N21W087.tif"
        download_file(url, dest)


def download_osm_roads() -> None:
    print("\n[2/3] Descargando red vial de OpenStreetMap (Overpass API)...")
    dest = DATA_RAW_DIR / "osm_roads_raw.geojson"
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [OK] Ya existe: {dest.name} ({dest.stat().st_size / 1e6:.2f} MB)")
        return

    min_lon, min_lat, max_lon, max_lat = AOI_BBOX_WGS84
    # Overpass usa orden (south, west, north, east)
    query = f"""
    [out:json][timeout:90];
    (
      way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|track|path|living_street|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link)$"]({min_lat},{min_lon},{max_lat},{max_lon});
    );
    out body geom;
    """

    data = None
    last_err = None
    for endpoint in OVERPASS_ENDPOINTS:
        try:
            print(f"  Consultando {endpoint} ...")
            resp = requests.post(
                endpoint,
                data={"data": query},
                headers={"User-Agent": "BioConecta/1.0 (Proyecto educativo Quintana Roo)"},
                timeout=120,
            )
            resp.raise_for_status()
            data = resp.json()
            break
        except Exception as exc:
            last_err = exc
            print(f"  [Aviso] Falló {endpoint}: {exc}")

    if data is None:
        raise RuntimeError(f"No se pudo descargar la red vial de Overpass: {last_err}")

    features = []
    for elem in data.get("elements", []):
        if elem.get("type") != "way" or "geometry" not in elem:
            continue
        coords = [[pt["lon"], pt["lat"]] for pt in elem["geometry"]]
        if len(coords) < 2:
            continue
        tags = elem.get("tags", {})
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "osm_id": elem.get("id"),
                    "highway": tags.get("highway", ""),
                    "name": tags.get("name", ""),
                    "surface": tags.get("surface", ""),
                    "lanes": tags.get("lanes", ""),
                },
                "geometry": {
                    "type": "LineString",
                    "coordinates": coords,
                },
            }
        )

    geojson = {"type": "FeatureCollection", "features": features}
    dest.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
    print(f"  [OK] Guardados {len(features)} segmentos viales en {dest.name}")


def fetch_gbif_occurrences(bbox: tuple[float, float, float, float], dest: Path, label: str) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        existing = json.loads(dest.read_text(encoding="utf-8"))
        print(f"  [OK] Ya existe: {dest.name} ({len(existing.get('features', []))} registros)")
        return

    min_lon, min_lat, max_lon, max_lat = bbox
    all_records = []
    offset = 0
    limit = 300

    while True:
        params = {
            "scientificName": "Panthera onca",
            "hasCoordinate": "true",
            "hasGeospatialIssue": "false",
            "decimalLatitude": f"{min_lat},{max_lat}",
            "decimalLongitude": f"{min_lon},{max_lon}",
            "limit": limit,
            "offset": offset,
        }
        r = requests.get("https://api.gbif.org/v1/occurrence/search", params=params, timeout=30)
        r.raise_for_status()
        payload = r.json()
        results = payload.get("results", [])
        all_records.extend(results)
        if payload.get("endOfRecords", True) or not results:
            break
        offset += limit

    features = []
    for rec in all_records:
        lon = rec.get("decimalLongitude")
        lat = rec.get("decimalLatitude")
        if lon is None or lat is None:
            continue
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "gbif_id": rec.get("key"),
                    "species": rec.get("species", "Panthera onca"),
                    "year": rec.get("year"),
                    "event_date": rec.get("eventDate", ""),
                    "basis_of_record": rec.get("basisOfRecord", ""),
                    "dataset_name": rec.get("datasetName", ""),
                    "locality": rec.get("locality", "") or rec.get("municipality", ""),
                    "coordinate_uncertainty_m": rec.get("coordinateUncertaintyInMeters"),
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat],
                },
            }
        )

    geojson = {"type": "FeatureCollection", "features": features}
    dest.write_text(json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  [OK] {label}: {len(features)} registros guardados en {dest.name}")


def download_gbif() -> None:
    print("\n[3/3] Descargando registros de presencia de jaguar (GBIF - Panthera onca)...")
    fetch_gbif_occurrences(
        AOI_BBOX_WGS84,
        DATA_RAW_DIR / "gbif_jaguar_pilot.geojson",
        "Zona piloto",
    )
    fetch_gbif_occurrences(
        REGIONAL_BBOX_WGS84,
        DATA_RAW_DIR / "gbif_jaguar_regional.geojson",
        "Contexto regional (norte Q. Roo)",
    )


def main() -> None:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Directorio de descarga: {DATA_RAW_DIR}")
    print(f"BBOX zona piloto (WGS84): {AOI_BBOX_WGS84}")

    download_worldcover()
    download_osm_roads()
    download_gbif()

    print("\nDescarga completada exitosamente.")


if __name__ == "__main__":
    main()

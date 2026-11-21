"""
Descarga polígonos de infraestructura turística, hotelera y desarrollo urbano reciente
de OpenStreetMap (hoteles, resorts, campos de golf, marinas, uso comercial/residencial/construcción)
y los rasteriza en la grilla canónica UTM 16N (30x30 m).

Esto complementa la mancha urbana de ESA WorldCover 2021 con la franja hotelera
de Playa Mujeres / Costa Mujeres y desarrollos recientes (2022-2026).
"""

import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import requests
from rasterio.features import rasterize

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import AOI_BBOX_WGS84, DATA_PROCESSED_DIR, DATA_RAW_DIR, TARGET_CRS

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]


def main() -> None:
    raw_path = DATA_RAW_DIR / "osm_anthro_raw.geojson"
    if not (raw_path.exists() and raw_path.stat().st_size > 0):
        min_lon, min_lat, max_lon, max_lat = AOI_BBOX_WGS84
        bbox_str = f"{min_lat},{min_lon},{max_lat},{max_lon}"
        # Nota: edificios se descargan en la franja costera oriental (Costa/Playa Mujeres/Punta Sam)
        # donde ESA 2021 no refleja resorts nuevos; en el resto usamos polígonos de turismo/uso de suelo.
        query = f"""
        [out:json][timeout:90];
        (
          way["tourism"~"^(hotel|resort|motel|hostel|guest_house|camp_site|theme_park)$"]({bbox_str});
          relation["tourism"~"^(hotel|resort)$"]({bbox_str});
          way["leisure"~"^(golf_course|resort|marina|water_park)$"]({bbox_str});
          relation["leisure"~"^(golf_course|resort|marina)$"]({bbox_str});
          way["landuse"~"^(residential|commercial|retail|industrial|construction|brownfield|quarry)$"]({bbox_str});
          way["building"](21.21,-86.84,21.39,-86.78);
        );
        out body geom;
        """
        data = None
        last_err = None
        for ep in OVERPASS_ENDPOINTS:
            try:
                print(f"Consultando {ep} ...")
                r = requests.post(
                    ep,
                    data={"data": query},
                    headers={"User-Agent": "BioConecta/1.0 (Proyecto educativo Quintana Roo)"},
                    timeout=120,
                )
                r.raise_for_status()
                data = r.json()
                break
            except Exception as exc:
                last_err = exc
                print(f"  [Aviso] Falló {ep}: {exc}")
        if data is None:
            raise RuntimeError(f"No se pudo descargar capa turística/urbana OSM: {last_err}")

        features = []
        for elem in data.get("elements", []):
            et = elem.get("type")
            tags = elem.get("tags", {})
            props = {
                "osm_id": elem.get("id"),
                "name": tags.get("name", ""),
                "tourism": tags.get("tourism", ""),
                "leisure": tags.get("leisure", ""),
                "landuse": tags.get("landuse", ""),
                "building": tags.get("building", ""),
            }
            if et == "way" and "geometry" in elem:
                coords = [[pt["lon"], pt["lat"]] for pt in elem["geometry"]]
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    features.append(
                        {
                            "type": "Feature",
                            "properties": props,
                            "geometry": {"type": "Polygon", "coordinates": [coords]},
                        }
                    )
            elif et == "relation" and "members" in elem:
                for m in elem.get("members", []):
                    if m.get("role") == "outer" and "geometry" in m:
                        coords = [[pt["lon"], pt["lat"]] for pt in m["geometry"]]
                        if len(coords) >= 4 and coords[0] == coords[-1]:
                            features.append(
                                {
                                    "type": "Feature",
                                    "properties": props,
                                    "geometry": {"type": "Polygon", "coordinates": [coords]},
                                }
                            )
        raw_path.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  [OK] Guardados {len(features)} polígonos turísticos/urbanos OSM en {raw_path.name}")
    else:
        print(f"  [OK] Ya existe: {raw_path.name}")

    aoi_utm = gpd.read_file(DATA_PROCESSED_DIR / "aoi_utm16n.geojson")
    gdf = gpd.read_file(raw_path)
    gdf_utm = gpd.clip(gdf.to_crs(TARGET_CRS), aoi_utm)
    gdf_utm = gdf_utm[~gdf_utm.geometry.is_empty].copy()
    gdf_utm.to_file(DATA_PROCESSED_DIR / "osm_anthro_utm16n.geojson", driver="GeoJSON")

    with rasterio.open(DATA_PROCESSED_DIR / "landcover_2021_30m.tif") as ref:
        profile = ref.profile.copy()

    anthro_raster = rasterize(
        shapes=((g, 1) for g in gdf_utm.geometry if g is not None and not g.is_empty),
        out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"],
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )

    out_prof = profile.copy()
    out_prof.update(dtype="uint8", nodata=255, compress="lzw")
    out_tif = DATA_PROCESSED_DIR / "osm_anthro_30m.tif"
    with rasterio.open(out_tif, "w", **out_prof) as dst:
        dst.write(anthro_raster, 1)

    px_ha = 0.09
    print(
        f"  [OK] {out_tif.name} generado: {int(np.sum(anthro_raster == 1)) * px_ha:,.1f} ha "
        f"({len(gdf_utm)} polígonos de resorts, hoteles, golf y desarrollos)."
    )


if __name__ == "__main__":
    main()

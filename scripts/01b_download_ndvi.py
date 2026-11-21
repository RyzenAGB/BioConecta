"""
Fase 1b: Descarga y procesamiento de NDVI (Sentinel-2 L2A) y fuentes de agua (OSM + ESA).

Genera en data/processed/ (alineado exactamente a la grilla UTM 16N 30x30 m):
1. ndvi_2025_30m.tif  -> Compuesto de mediana temporada seca (marzo-mayo 2025), nubes enmascaradas (SCL)
2. ndvi_2026_30m.tif  -> Compuesto de mediana temporada seca (marzo-mayo 2026), nubes enmascaradas (SCL)
3. ndvi_metadata.json -> Lista exacta de escenas Sentinel-2 usadas por año
4. osm_water_utm16n.geojson -> Cenotes, lagunas, manantiales y corrientes de OpenStreetMap
5. water_sources_30m.tif    -> Máscara binaria combinada de fuentes de agua (ESA 80 + ESA 90 + OSM)
"""

import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import requests
from pystac_client import Client
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from shapely.geometry import LineString, Point, Polygon

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import AOI_BBOX_WGS84, DATA_PROCESSED_DIR, DATA_RAW_DIR, TARGET_CRS

STAC_URL = "https://earth-search.aws.element84.com/v1"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

# Clases SCL de Sentinel-2 a descartar (sin dato, saturado, sombra de nube, nubes, cirros, nieve)
SCL_INVALID_CLASSES = {0, 1, 3, 8, 9, 10, 11}
MAX_SCENES_PER_YEAR = 8
MAX_WORKERS = 6


def get_reference_profile() -> tuple[dict, rasterio.coords.BoundingBox]:
    ref_path = DATA_PROCESSED_DIR / "landcover_2021_30m.tif"
    with rasterio.open(ref_path) as src:
        return src.profile.copy(), src.bounds


def read_s2_band_on_10m_grid(
    href: str,
    dst_shape_10m: tuple[int, int],
    dst_transform_10m,
    dst_crs: str,
    resampling: Resampling,
    dtype,
) -> np.ndarray:
    """Lee solo la ventana del AOI desde un COG de Sentinel-2 y la alinea a la grilla de 10 m."""
    with rasterio.open(href) as src:
        # Leer ventana con margen de 60 m para evitar artefactos en el borde
        left, bottom, right, top = rasterio.transform.array_bounds(
            dst_shape_10m[0], dst_shape_10m[1], dst_transform_10m
        )
        win = from_bounds(left - 60, bottom - 60, right + 60, top + 60, src.transform)
        win = win.round_offsets().round_lengths()
        src_data = src.read(1, window=win, boundless=True, fill_value=0)
        src_transform = src.window_transform(win)

        dst = np.zeros(dst_shape_10m, dtype=dtype)
        reproject(
            source=src_data,
            destination=dst,
            src_transform=src_transform,
            src_crs=src.crs,
            dst_transform=dst_transform_10m,
            dst_crs=dst_crs,
            resampling=resampling,
        )
        return dst


def read_scene_ndvi_10m(it, h10: int, w10: int, transform_10m):
    """Descarga las bandas B04, B08 y SCL de una escena en el AOI y calcula NDVI a 10 m."""
    cc = float(it.properties.get("eo:cloud_cover", 0.0))
    red_dn = read_s2_band_on_10m_grid(
        it.assets["red"].href, (h10, w10), transform_10m, TARGET_CRS, Resampling.nearest, np.uint16
    )
    nir_dn = read_s2_band_on_10m_grid(
        it.assets["nir"].href, (h10, w10), transform_10m, TARGET_CRS, Resampling.nearest, np.uint16
    )
    scl = read_s2_band_on_10m_grid(
        it.assets["scl"].href, (h10, w10), transform_10m, TARGET_CRS, Resampling.nearest, np.uint8
    )

    # Los COGs de Sentinel-2 L2A en Earth Search ya vienen armonizados (DN = reflectancia * 10000, offset = 0)
    valid = (red_dn > 0) & (nir_dn > 0) & (~np.isin(scl, list(SCL_INVALID_CLASSES)))
    red = red_dn.astype(np.float32) * 0.0001
    nir = nir_dn.astype(np.float32) * 0.0001

    denom = nir + red
    ndvi = np.full((h10, w10), np.nan, dtype=np.float32)
    ok = valid & (denom > 1e-5)
    ndvi[ok] = np.clip((nir[ok] - red[ok]) / denom[ok], -1.0, 1.0)
    valid_pct = float(np.mean(ok) * 100.0)
    info = {
        "id": it.id,
        "datetime": it.datetime.isoformat() if it.datetime else "",
        "scene_cloud_cover": round(cc, 2),
        "aoi_valid_pct": round(valid_pct, 2),
    }
    return ndvi, info


def compute_ndvi_year(year: int, ref_profile: dict, ref_bounds, force: bool = False) -> dict:
    """Descarga escenas Sentinel-2 L2A (marzo-mayo), calcula compuesto de mediana y remuestrea a 30 m."""
    out_path = DATA_PROCESSED_DIR / f"ndvi_{year}_30m.tif"
    if out_path.exists() and not force:
        with rasterio.open(out_path) as src:
            arr = src.read(1)
            valid_vals = arr[(arr != src.nodata) & np.isfinite(arr)]
            nan_count = int(np.sum((arr == src.nodata) | ~np.isfinite(arr)))
        stats = {
            "year": year,
            "cached": True,
            "nan_pixels_30m": nan_count,
            "ndvi_min": round(float(np.min(valid_vals)), 4),
            "ndvi_median": round(float(np.median(valid_vals)), 4),
            "ndvi_max": round(float(np.max(valid_vals)), 4),
        }
        print(
            f"\n[NDVI {year}] Ya existe {out_path.name} "
            f"(mediana={stats['ndvi_median']:.3f}, rango=[{stats['ndvi_min']:.3f}, {stats['ndvi_max']:.3f}])"
        )
        return stats
    print(f"\n[NDVI {year}] Buscando escenas Sentinel-2 L2A (marzo–mayo {year}, nubes < 30%)...")

    cat = Client.open(STAC_URL)
    search = cat.search(
        collections=["sentinel-2-l2a"],
        bbox=list(AOI_BBOX_WGS84),
        datetime=f"{year}-03-01/{year}-05-31",
        query={"eo:cloud_cover": {"lt": 30}},
    )
    items = [it for it in search.items() if "16QEJ" in it.id]
    items.sort(key=lambda it: float(it.properties.get("eo:cloud_cover", 100.0)))
    items = items[:MAX_SCENES_PER_YEAR]

    if not items:
        raise RuntimeError(f"No se encontraron escenas Sentinel-2 (tile 16QEJ) para {year}.")

    print(
        f"  Encontradas {len(items)} escenas limpias "
        f"(nubes {items[0].properties.get('eo:cloud_cover'):.1f}% – {items[-1].properties.get('eo:cloud_cover'):.1f}%). "
        f"Descargando en paralelo ({MAX_WORKERS} hilos)..."
    )

    h10 = ref_profile["height"] * 3
    w10 = ref_profile["width"] * 3
    transform_10m = rasterio.transform.from_origin(ref_bounds.left, ref_bounds.top, 10.0, 10.0)

    ndvi_stack = []
    used_scenes = []

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(read_scene_ndvi_10m, it, h10, w10, transform_10m): it.id for it in items}
        for fut in as_completed(futures):
            sid = futures[fut]
            try:
                ndvi, info = fut.result()
                if info["aoi_valid_pct"] < 20.0:
                    print(f"  [-] {sid} descartada ({info['aoi_valid_pct']:.1f}% válidos)")
                    continue
                ndvi_stack.append(ndvi)
                used_scenes.append(info)
                print(f"  [OK] {sid} (nubes: {info['scene_cloud_cover']:.1f}%, válidos AOI: {info['aoi_valid_pct']:.1f}%)")
            except Exception as exc:
                print(f"  [Aviso] Error leyendo {sid}: {exc}")

    if not ndvi_stack:
        raise RuntimeError(f"No se pudo construir el compuesto NDVI para {year}.")

    used_scenes.sort(key=lambda x: x["datetime"])
    print(f"  Calculando compuesto de mediana a 10 m con {len(ndvi_stack)} escenas...")
    stack_arr = np.stack(ndvi_stack, axis=0)
    with np.errstate(all="ignore"):
        ndvi_10m = np.nanmedian(stack_arr, axis=0).astype(np.float32)

    # Remuestrear exactamente de 10 m -> 30 m usando promedio ignorando NaN (bloques 3x3)
    blocks = ndvi_10m.reshape(ref_profile["height"], 3, ref_profile["width"], 3)
    with np.errstate(all="ignore"):
        ndvi_30m = np.nanmean(blocks, axis=(1, 3)).astype(np.float32)

    nodata_val = -9999.0
    nan_count = int(np.sum(np.isnan(ndvi_30m)))
    ndvi_30m_out = np.where(np.isnan(ndvi_30m), nodata_val, ndvi_30m).astype(np.float32)

    out_profile = ref_profile.copy()
    out_profile.update(dtype="float32", nodata=nodata_val, compress="lzw")
    with rasterio.open(out_path, "w", **out_profile) as dst:
        dst.write(ndvi_30m_out, 1)

    valid_vals = ndvi_30m[~np.isnan(ndvi_30m)]
    stats = {
        "year": year,
        "scenes_used": len(used_scenes),
        "scenes": used_scenes,
        "nan_pixels_30m": nan_count,
        "ndvi_min": round(float(np.min(valid_vals)), 4),
        "ndvi_median": round(float(np.median(valid_vals)), 4),
        "ndvi_max": round(float(np.max(valid_vals)), 4),
    }
    print(
        f"  [OK] {out_path.name}: mediana={stats['ndvi_median']:.3f}, "
        f"rango=[{stats['ndvi_min']:.3f}, {stats['ndvi_max']:.3f}], sin dato={nan_count} px"
    )
    return stats


def download_and_build_water_sources(ref_profile: dict) -> dict:
    """Descarga cenotes, lagunas, manantiales y ríos de OSM y los combina con ESA 80 y 90."""
    print("\n[Agua] Descargando fuentes de agua de OpenStreetMap (cenotes, lagunas, ríos)...")
    raw_path = DATA_RAW_DIR / "osm_water_raw.geojson"

    if not (raw_path.exists() and raw_path.stat().st_size > 0):
        min_lon, min_lat, max_lon, max_lat = AOI_BBOX_WGS84
        bbox_str = f"{min_lat},{min_lon},{max_lat},{max_lon}"
        query = f"""
        [out:json][timeout:90];
        (
          node["natural"~"^(water|spring|sinkhole)$"]({bbox_str});
          node["water"]({bbox_str});
          way["natural"="water"]({bbox_str});
          way["water"]({bbox_str});
          way["waterway"~"^(river|stream|canal)$"]({bbox_str});
          relation["natural"="water"]({bbox_str});
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
            raise RuntimeError(f"No se pudo descargar agua de Overpass: {last_err}")

        features = []
        for elem in data.get("elements", []):
            etype = elem.get("type")
            tags = elem.get("tags", {})
            props = {
                "osm_id": elem.get("id"),
                "osm_type": etype,
                "name": tags.get("name", ""),
                "natural": tags.get("natural", ""),
                "water": tags.get("water", ""),
                "waterway": tags.get("waterway", ""),
            }
            geom = None
            if etype == "node" and "lat" in elem and "lon" in elem:
                geom = {"type": "Point", "coordinates": [elem["lon"], elem["lat"]]}
            elif etype == "way" and "geometry" in elem:
                coords = [[pt["lon"], pt["lat"]] for pt in elem["geometry"]]
                if len(coords) >= 4 and coords[0] == coords[-1]:
                    geom = {"type": "Polygon", "coordinates": [coords]}
                elif len(coords) >= 2:
                    geom = {"type": "LineString", "coordinates": coords}
            elif etype == "relation" and "members" in elem:
                # Extraer anillos exteriores simples de relaciones de agua
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
                continue

            if geom is not None:
                features.append({"type": "Feature", "properties": props, "geometry": geom})

        raw_path.write_text(
            json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"  [OK] Guardados {len(features)} elementos de agua OSM en {raw_path.name}")
    else:
        print(f"  [OK] Ya existe: {raw_path.name}")

    # Reproyectar y recortar al AOI
    aoi_utm = gpd.read_file(DATA_PROCESSED_DIR / "aoi_utm16n.geojson")
    osm_water = gpd.read_file(raw_path)
    if len(osm_water) > 0:
        osm_water_utm = gpd.clip(osm_water.to_crs(TARGET_CRS), aoi_utm)
        osm_water_utm = osm_water_utm[~osm_water_utm.geometry.is_empty].copy()
    else:
        osm_water_utm = gpd.GeoDataFrame(geometry=[], crs=TARGET_CRS)

    osm_water_utm.to_file(DATA_PROCESSED_DIR / "osm_water_utm16n.geojson", driver="GeoJSON")

    # Rasterizar OSM agua sobre la grilla 30x30 m
    osm_mask = np.zeros((ref_profile["height"], ref_profile["width"]), dtype=np.uint8)
    if len(osm_water_utm) > 0:
        shapes = ((g, 1) for g in osm_water_utm.geometry if g is not None and not g.is_empty)
        osm_mask = rasterize(
            shapes=shapes,
            out_shape=(ref_profile["height"], ref_profile["width"]),
            transform=ref_profile["transform"],
            fill=0,
            all_touched=True,
            dtype=np.uint8,
        )

    # Combinar con ESA WorldCover 2021 clase 80 (agua permanente) y 90 (humedal herbáceo)
    with rasterio.open(DATA_PROCESSED_DIR / "landcover_2021_30m.tif") as src:
        lc21 = src.read(1)

    esa_water_mask = np.isin(lc21, [80, 90]).astype(np.uint8)
    combined_water = np.maximum(esa_water_mask, osm_mask).astype(np.uint8)

    water_profile = ref_profile.copy()
    water_profile.update(dtype="uint8", nodata=255, compress="lzw")
    out_water = DATA_PROCESSED_DIR / "water_sources_30m.tif"
    with rasterio.open(out_water, "w", **water_profile) as dst:
        dst.write(combined_water, 1)

    extra_osm_px = int(np.sum((osm_mask == 1) & (esa_water_mask == 0)))
    print(
        f"  [OK] {out_water.name}: {len(osm_water_utm)} elementos OSM "
        f"(+{extra_osm_px} píxeles nuevos de cenotes/lagunas/corrientes fuera de ESA 80/90)"
    )
    return {
        "osm_water_features": len(osm_water_utm),
        "extra_osm_pixels_30m": extra_osm_px,
        "total_water_source_pixels_30m": int(np.sum(combined_water == 1)),
    }


def main() -> None:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    meta_path = DATA_PROCESSED_DIR / "ndvi_metadata.json"
    existing_meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}

    ref_profile, ref_bounds = get_reference_profile()
    meta = dict(existing_meta)
    for yr in (2024, 2025, 2026):
        key = f"ndvi_{yr}"
        res = compute_ndvi_year(yr, ref_profile, ref_bounds)
        if not res.get("cached") or key not in meta:
            meta[key] = res
    meta["water_sources"] = download_and_build_water_sources(ref_profile)

    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nMetadatos guardados en {meta_path}")


if __name__ == "__main__":
    main()

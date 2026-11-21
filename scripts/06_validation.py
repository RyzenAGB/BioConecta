"""
Fase 5 — Validación Científica del Modelo HSM y Corredores (Jaguar — Panthera onca).

Qué hace este script:
1. Recopila registros de presencia de Panthera onca en el recuadro regional ampliado
   (-87.35, 20.90, -86.75, 21.50):
   - GBIF (ya descargado en Paso 0)
   - iNaturalist API (solo grado de investigación, quality_grade=research)
2. Filtra incertidumbre > 5,000 m y elimina duplicados (por ID y por cercanía espacial < 100 m).
3. Corre el mismo modelo HSM (Vista 1, 30x30 m, UTM 16N, mismas reglas de species_rules.py)
   sobre el recuadro regional ampliado (solo para validación; la app muestra la zona piloto).
4. Calcula métricas de validación:
   - ROC-AUC y prueba de Mann-Whitney U (presencias vs 10,000 puntos de fondo terrestres)
   - % de registros reales en hábitat núcleo (H >= 0.70)
   - Distancia de cada registro al parche núcleo y al corredor más cercano (en zona piloto y regional)

Salidas:
  - outputs/validacion.json
  - outputs/validacion_registros.geojson
  - outputs/preview_validacion.png
"""

import json
import math
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import geopandas as gpd
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import requests
from matplotlib.colors import LinearSegmentedColormap
from pystac_client import Client
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds
from scipy.ndimage import distance_transform_edt
from scipy.stats import mannwhitneyu
from shapely.geometry import Point, box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    AOI_BBOX_WGS84,
    DATA_PROCESSED_DIR,
    DATA_RAW_DIR,
    PROJECT_ROOT,
    REGIONAL_BBOX_WGS84,
    TARGET_CRS,
    TARGET_RESOLUTION_M,
)
from species_rules import (
    DIST_95_ROADS_M,
    DIST_95_URBAN_M,
    HSM_WEIGHTS,
    LANDCOVER_SCORES,
    NDVI_SCORE_MAX,
    NDVI_SCORE_MIN,
    PATCH_SUITABILITY_THRESHOLD,
    WATER_DECAY_K_M,
)

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
VAL_DIR = DATA_PROCESSED_DIR / "validation_regional"

STAC_URL = "https://earth-search.aws.element84.com/v1"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
]

ESA_REGIONAL_TILES = ["N21W087", "N21W090", "N18W087", "N18W090"]
SCL_INVALID_CLASSES = {0, 1, 3, 8, 9, 10, 11}

PAVED_MAJOR = {
    "motorway", "motorway_link", "trunk", "trunk_link", "primary", "primary_link",
    "secondary", "secondary_link", "tertiary", "tertiary_link",
}
LOCAL_STREETS = {"residential", "unclassified", "service", "living_street"}
UNPAVED_SURFACES = {"unpaved", "dirt", "gravel", "sand", "ground", "earth", "mud", "compacted"}

HSM_CMAP = LinearSegmentedColormap.from_list(
    "bioconecta_hsm_val",
    [(0.0, "#a50026"), (0.25, "#f46d43"), (0.50, "#fee08b"), (0.70, "#66bd63"), (0.85, "#1a9850"), (1.0, "#00441b")],
)


def download_file(url: str, dest: Path) -> None:
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  [OK] Ya existe: {dest.name}")
        return
    print(f"  Descargando {dest.name} ...")
    with requests.get(url, stream=True, timeout=120) as r:
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    print(f"  [OK] Descargado: {dest.name} ({dest.stat().st_size / 1e6:.2f} MB)")


def download_inaturalist_regional() -> Path:
    dest = DATA_RAW_DIR / "inat_jaguar_regional.geojson"
    if dest.exists() and dest.stat().st_size > 0:
        existing = json.loads(dest.read_text(encoding="utf-8"))
        print(f"  [OK] Ya existe: {dest.name} ({len(existing.get('features', []))} registros)")
        return dest

    min_lon, min_lat, max_lon, max_lat = REGIONAL_BBOX_WGS84
    features = []
    page = 1
    while True:
        params = {
            "taxon_name": "Panthera onca",
            "quality_grade": "research",
            "geo": "true",
            "swlat": min_lat,
            "swlng": min_lon,
            "nelat": max_lat,
            "nelng": max_lon,
            "per_page": 200,
            "page": page,
        }
        r = requests.get(
            "https://api.inaturalist.org/v1/observations",
            params=params,
            headers={"User-Agent": "BioConecta/1.0 (Proyecto educativo Quintana Roo)"},
            timeout=30,
        )
        r.raise_for_status()
        payload = r.json()
        results = payload.get("results", [])
        if not results:
            break
        for obs in results:
            coords = (obs.get("geojson") or {}).get("coordinates")
            if not coords or len(coords) < 2:
                continue
            lon, lat = float(coords[0]), float(coords[1])
            obs_date = obs.get("observed_on") or ""
            yr = int(obs_date[:4]) if len(obs_date) >= 4 and obs_date[:4].isdigit() else None
            acc = obs.get("positional_accuracy") or obs.get("public_positional_accuracy")
            features.append(
                {
                    "type": "Feature",
                    "properties": {
                        "source": "iNaturalist",
                        "record_id": f"inat_{obs.get('id')}",
                        "year": yr,
                        "event_date": obs_date,
                        "locality": obs.get("place_guess") or "",
                        "coordinate_uncertainty_m": float(acc) if acc is not None else None,
                        "obscured": bool(obs.get("obscured", False)),
                    },
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                }
            )
        if page * 200 >= payload.get("total_results", 0):
            break
        page += 1

    dest.write_text(
        json.dumps({"type": "FeatureCollection", "features": features}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"  [OK] iNaturalist (Research Grade): {len(features)} registros guardados en {dest.name}")
    return dest


def load_and_clean_occurrences() -> tuple[gpd.GeoDataFrame, dict]:
    """Combina GBIF + iNaturalist, filtra incertidumbre > 5 km y deduplica a < 100 m."""
    print("\n[1/4] Recopilando y limpiando registros de jaguar (GBIF + iNaturalist)...")
    inat_path = download_inaturalist_regional()
    gbif_raw = gpd.read_file(DATA_RAW_DIR / "gbif_jaguar_regional.geojson")
    inat_raw = gpd.read_file(inat_path)

    rows = []
    for _, r in gbif_raw.iterrows():
        unc = r.get("coordinate_uncertainty_m")
        unc_val = float(unc) if unc is not None and not (isinstance(unc, float) and math.isnan(unc)) else None
        rows.append(
            {
                "source": "GBIF",
                "record_id": f"gbif_{r.get('gbif_id')}",
                "year": int(r["year"]) if r.get("year") is not None and not (isinstance(r["year"], float) and math.isnan(r["year"])) else None,
                "locality": str(r.get("locality") or ""),
                "coordinate_uncertainty_m": unc_val,
                "geometry": r.geometry,
            }
        )
    for _, r in inat_raw.iterrows():
        unc = r.get("coordinate_uncertainty_m")
        unc_val = float(unc) if unc is not None and not (isinstance(unc, float) and math.isnan(unc)) else None
        rows.append(
            {
                "source": "iNaturalist",
                "record_id": str(r.get("record_id")),
                "year": int(r["year"]) if r.get("year") is not None and not (isinstance(r["year"], float) and math.isnan(r["year"])) else None,
                "locality": str(r.get("locality") or ""),
                "coordinate_uncertainty_m": unc_val,
                "geometry": r.geometry,
            }
        )

    combined = gpd.GeoDataFrame(rows, crs="EPSG:4326").to_crs(TARGET_CRS)
    n_raw = len(combined)

    # Descartar incertidumbre > 5,000 m
    ok_unc = combined["coordinate_uncertainty_m"].isna() | (combined["coordinate_uncertainty_m"] <= 5000.0)
    dropped_unc = int((~ok_unc).sum())
    filtered = combined[ok_unc].copy()

    # Ordenar priorizando año más reciente y menor incertidumbre para conservar el mejor registro al deduplicar
    filtered["_sort_yr"] = filtered["year"].fillna(0)
    filtered["_sort_unc"] = filtered["coordinate_uncertainty_m"].fillna(9999.0)
    filtered = filtered.sort_values(["_sort_yr", "_sort_unc"], ascending=[False, True]).reset_index(drop=True)

    # Deduplicar por proximidad espacial < 100 m
    kept_idx = []
    kept_geoms = []
    for idx, row in filtered.iterrows():
        g = row.geometry
        if any(g.distance(prev) < 100.0 for prev in kept_geoms):
            continue
        kept_idx.append(idx)
        kept_geoms.append(g)

    dedup = filtered.loc[kept_idx].drop(columns=["_sort_yr", "_sort_unc"]).reset_index(drop=True)
    n_dedup = len(dedup)
    print(
        f"  GBIF={len(gbif_raw)}, iNaturalist={len(inat_raw)} -> Total bruto={n_raw} | "
        f"Descartados (>5 km)={dropped_unc} | Únicos (≥100 m)={n_dedup}"
    )
    return dedup, {
        "gbif_raw": int(len(gbif_raw)),
        "inat_raw": int(len(inat_raw)),
        "dropped_uncertainty_gt_5km": dropped_unc,
        "deduplicated_100m": n_dedup,
    }


def build_regional_grid() -> tuple[gpd.GeoDataFrame, dict]:
    reg_wgs = gpd.GeoDataFrame(geometry=[box(*REGIONAL_BBOX_WGS84)], crs="EPSG:4326")
    reg_utm = reg_wgs.to_crs(TARGET_CRS)
    minx, miny, maxx, maxy = reg_utm.total_bounds
    res = TARGET_RESOLUTION_M
    minx_s = math.floor(minx / res) * res
    miny_s = math.floor(miny / res) * res
    maxx_s = math.ceil(maxx / res) * res
    maxy_s = math.ceil(maxy / res) * res

    width = int(round((maxx_s - minx_s) / res))
    height = int(round((maxy_s - miny_s) / res))
    transform = from_origin(minx_s, maxy_s, res, res)

    reg_snapped = gpd.GeoDataFrame(geometry=[box(minx_s, miny_s, maxx_s, maxy_s)], crs=TARGET_CRS)
    profile = {
        "driver": "GTiff",
        "crs": TARGET_CRS,
        "transform": transform,
        "width": width,
        "height": height,
        "count": 1,
        "dtype": "uint8",
        "nodata": 0,
        "compress": "lzw",
    }
    return reg_snapped, profile


def build_regional_landcover(profile: dict) -> np.ndarray:
    out_path = VAL_DIR / "regional_lc2021_30m.tif"
    if out_path.exists():
        with rasterio.open(out_path) as src:
            return src.read(1)

    print("\n[2/4] Descargando mosaico ESA WorldCover 2021 para zona regional de validación...")
    mosaic = np.zeros((profile["height"], profile["width"]), dtype=np.uint8)
    for tile in ESA_REGIONAL_TILES:
        url = f"https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif"
        raw_tile = DATA_RAW_DIR / f"esa_worldcover_2021_{tile}.tif"
        download_file(url, raw_tile)

        tmp = np.zeros_like(mosaic)
        with rasterio.open(raw_tile) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=tmp,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=profile["transform"],
                dst_crs=profile["crs"],
                resampling=Resampling.mode,
            )
        mosaic = np.where((mosaic == 0) & (tmp > 0), tmp, mosaic)

    with rasterio.open(out_path, "w", **profile) as dst:
        dst.write(mosaic, 1)
    print(f"  [OK] Mosaico regional guardado: {profile['width']}x{profile['height']} px.")
    return mosaic


def build_regional_osm_roads_and_water(reg_utm: gpd.GeoDataFrame, lc21: np.ndarray, profile: dict) -> tuple[np.ndarray, np.ndarray]:
    roads_tif = VAL_DIR / "regional_roads_30m.tif"
    water_tif = VAL_DIR / "regional_water_30m.tif"
    if roads_tif.exists() and water_tif.exists():
        with rasterio.open(roads_tif) as s1, rasterio.open(water_tif) as s2:
            return s1.read(1), s2.read(1)

    print("\n[3/4] Descargando red vial y fuentes de agua OSM para la zona regional...")
    min_lon, min_lat, max_lon, max_lat = REGIONAL_BBOX_WGS84
    bbox_str = f"{min_lat},{min_lon},{max_lat},{max_lon}"

    # Red vial regional
    raw_roads = DATA_RAW_DIR / "regional_osm_roads.geojson"
    if not (raw_roads.exists() and raw_roads.stat().st_size > 0):
        q_roads = f"""
        [out:json][timeout:120];
        (
          way["highway"~"^(motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|track|path|living_street|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link)$"]({bbox_str});
        );
        out body geom;
        """
        data = None
        for ep in OVERPASS_ENDPOINTS:
            try:
                print(f"  Consultando vías en {ep} ...")
                r = requests.post(ep, data={"data": q_roads}, headers={"User-Agent": "BioConecta/1.0"}, timeout=150)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as exc:
                print(f"  [Aviso] Falló {ep}: {exc}")
        if data is None:
            raise RuntimeError("No se pudo descargar red vial regional de Overpass.")
        feats = []
        for elem in data.get("elements", []):
            if elem.get("type") != "way" or "geometry" not in elem:
                continue
            coords = [[pt["lon"], pt["lat"]] for pt in elem["geometry"]]
            if len(coords) < 2:
                continue
            tags = elem.get("tags", {})
            feats.append({
                "type": "Feature",
                "properties": {"highway": tags.get("highway", ""), "surface": tags.get("surface", "")},
                "geometry": {"type": "LineString", "coordinates": coords},
            })
        raw_roads.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
        print(f"  [OK] Vías regionales descargadas: {len(feats)} segmentos.")

    roads_gdf = gpd.clip(gpd.read_file(raw_roads).to_crs(TARGET_CRS), reg_utm)
    roads_gdf = roads_gdf[~roads_gdf.geometry.is_empty].copy()

    def tier_fn(row) -> int:
        hw = str(row.get("highway", "")).lower()
        sf = str(row.get("surface", "")).lower()
        if hw in {"track", "path"} or sf in UNPAVED_SURFACES:
            return 1
        if hw in PAVED_MAJOR:
            return 3
        if hw in LOCAL_STREETS:
            return 2
        return 1

    roads_gdf["road_tier"] = roads_gdf.apply(tier_fn, axis=1)
    roads_sorted = roads_gdf.sort_values("road_tier", ascending=True)
    roads_raster = rasterize(
        shapes=((g, int(t)) for g, t in zip(roads_sorted.geometry, roads_sorted["road_tier"]) if g and not g.is_empty),
        out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"],
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )

    # Agua OSM regional (cenotes, lagunas, ríos)
    raw_water = DATA_RAW_DIR / "regional_osm_water.geojson"
    if not (raw_water.exists() and raw_water.stat().st_size > 0):
        q_water = f"""
        [out:json][timeout:120];
        (
          node["natural"~"^(water|spring|sinkhole)$"]({bbox_str});
          node["water"]({bbox_str});
          way["natural"="water"]({bbox_str});
          way["water"]({bbox_str});
          way["waterway"~"^(river|stream|canal)$"]({bbox_str});
        );
        out body geom;
        """
        data = None
        for ep in OVERPASS_ENDPOINTS:
            try:
                print(f"  Consultando agua en {ep} ...")
                r = requests.post(ep, data={"data": q_water}, headers={"User-Agent": "BioConecta/1.0"}, timeout=150)
                r.raise_for_status()
                data = r.json()
                break
            except Exception as exc:
                print(f"  [Aviso] Falló {ep}: {exc}")
        feats = []
        if data is not None:
            for elem in data.get("elements", []):
                et = elem.get("type")
                geom = None
                if et == "node" and "lat" in elem and "lon" in elem:
                    geom = {"type": "Point", "coordinates": [elem["lon"], elem["lat"]]}
                elif et == "way" and "geometry" in elem:
                    coords = [[pt["lon"], pt["lat"]] for pt in elem["geometry"]]
                    if len(coords) >= 4 and coords[0] == coords[-1]:
                        geom = {"type": "Polygon", "coordinates": [coords]}
                    elif len(coords) >= 2:
                        geom = {"type": "LineString", "coordinates": coords}
                if geom is not None:
                    feats.append({"type": "Feature", "properties": {}, "geometry": geom})
        raw_water.write_text(json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")
        print(f"  [OK] Fuentes de agua OSM regionales: {len(feats)} elementos.")

    water_gdf = gpd.read_file(raw_water)
    osm_mask = np.zeros((profile["height"], profile["width"]), dtype=np.uint8)
    if len(water_gdf) > 0:
        water_utm = gpd.clip(water_gdf.to_crs(TARGET_CRS), reg_utm)
        water_utm = water_utm[~water_utm.geometry.is_empty]
        if len(water_utm) > 0:
            osm_mask = rasterize(
                shapes=((g, 1) for g in water_utm.geometry if g and not g.is_empty),
                out_shape=(profile["height"], profile["width"]),
                transform=profile["transform"],
                fill=0,
                all_touched=True,
                dtype=np.uint8,
            )

    water_combined = np.maximum(np.isin(lc21, [80, 90]).astype(np.uint8), osm_mask).astype(np.uint8)

    p8 = profile.copy()
    p8.update(dtype="uint8", nodata=255)
    with rasterio.open(roads_tif, "w", **p8) as dst:
        dst.write(roads_raster, 1)
    with rasterio.open(water_tif, "w", **p8) as dst:
        dst.write(water_combined, 1)

    return roads_raster, water_combined


def read_s2_tile_ndvi_30m(it, profile: dict) -> np.ndarray:
    h, w = profile["height"], profile["width"]
    left, bottom, right, top = rasterio.transform.array_bounds(h, w, profile["transform"])

    def _read_band(href: str, resamp: Resampling, dtype):
        with rasterio.open(href) as src:
            # Intersección con la extensión del tile Sentinel-2
            sb = src.bounds
            ileft, ibottom = max(left, sb.left), max(bottom, sb.bottom)
            iright, itop = min(right, sb.right), min(top, sb.top)
            if ileft >= iright or ibottom >= itop:
                return np.zeros((h, w), dtype=dtype)
            win = from_bounds(ileft, ibottom, iright, itop, src.transform).round_offsets().round_lengths()
            # Lectura diezmada directa a ~30 m para máxima velocidad en la zona regional
            scale_factor = max(1, int(round(TARGET_RESOLUTION_M / abs(src.transform.a))))
            out_h = max(1, int(round(win.height / scale_factor)))
            out_w = max(1, int(round(win.width / scale_factor)))
            data = src.read(1, window=win, out_shape=(out_h, out_w), resampling=resamp)
            win_tr = src.window_transform(win)
            dec_tr = rasterio.transform.from_bounds(
                *rasterio.windows.bounds(win, src.transform), out_w, out_h
            )
            dst = np.zeros((h, w), dtype=dtype)
            reproject(
                source=data,
                destination=dst,
                src_transform=dec_tr,
                src_crs=src.crs,
                dst_transform=profile["transform"],
                dst_crs=profile["crs"],
                resampling=resamp,
            )
            return dst

    red_dn = _read_band(it.assets["red"].href, Resampling.average, np.uint16)
    nir_dn = _read_band(it.assets["nir"].href, Resampling.average, np.uint16)
    scl = _read_band(it.assets["scl"].href, Resampling.nearest, np.uint8)

    valid = (red_dn > 0) & (nir_dn > 0) & (~np.isin(scl, list(SCL_INVALID_CLASSES)))
    red = red_dn.astype(np.float32) * 0.0001
    nir = nir_dn.astype(np.float32) * 0.0001
    denom = nir + red
    ndvi = np.full((h, w), np.nan, dtype=np.float32)
    ok = valid & (denom > 1e-5)
    ndvi[ok] = np.clip((nir[ok] - red[ok]) / denom[ok], -1.0, 1.0)
    return ndvi


def build_regional_ndvi_2026(profile: dict) -> np.ndarray:
    out_path = VAL_DIR / "regional_ndvi2026_30m.tif"
    if out_path.exists():
        with rasterio.open(out_path) as src:
            return src.read(1)

    print("  Descargando compuesto NDVI 2026 regional (tiles 16QDJ + 16QEJ a 30 m)...")
    cat = Client.open(STAC_URL)
    search = cat.search(
        collections=["sentinel-2-l2a"],
        bbox=list(REGIONAL_BBOX_WGS84),
        datetime="2026-03-01/2026-05-31",
        query={"eo:cloud_cover": {"lt": 25}},
    )
    items_all = list(search.items())
    selected = []
    for tile in ("16QDJ", "16QEJ"):
        t_items = [it for it in items_all if tile in it.id]
        t_items.sort(key=lambda it: float(it.properties.get("eo:cloud_cover", 100.0)))
        selected.extend(t_items[:4])

    stack = []
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(read_s2_tile_ndvi_30m, it, profile): it.id for it in selected}
        for fut in as_completed(futs):
            sid = futs[fut]
            try:
                stack.append(fut.result())
                print(f"    [OK] {sid}")
            except Exception as exc:
                print(f"    [Aviso] Error en {sid}: {exc}")

    with np.errstate(all="ignore"):
        ndvi = np.nanmedian(np.stack(stack, axis=0), axis=0).astype(np.float32)
    ndvi_out = np.where(np.isnan(ndvi), -9999.0, ndvi).astype(np.float32)

    pf = profile.copy()
    pf.update(dtype="float32", nodata=-9999.0)
    with rasterio.open(out_path, "w", **pf) as dst:
        dst.write(ndvi_out, 1)
    return ndvi_out


def compute_regional_hsm(lc21: np.ndarray, roads: np.ndarray, water: np.ndarray, ndvi26: np.ndarray, profile: dict) -> np.ndarray:
    print("\n[4/4] Calculando HSM regional (misma fórmula de Vista 1) y métricas de validación...")
    s_cob = np.zeros_like(lc21, dtype=np.float32)
    for code, score in LANDCOVER_SCORES.items():
        s_cob[lc21 == code] = score

    ndvi_valid = (ndvi26 != -9999.0) & np.isfinite(ndvi26)
    s_ndvi = np.clip((ndvi26 - NDVI_SCORE_MIN) / (NDVI_SCORE_MAX - NDVI_SCORE_MIN), 0.0, 1.0).astype(np.float32)
    s_ndvi = np.where(ndvi_valid, s_ndvi, s_cob)

    s_roads = np.ones_like(s_cob, dtype=np.float32)
    for tier, d95 in DIST_95_ROADS_M.items():
        mask_t = roads == tier
        if np.any(mask_t):
            dist_m = distance_transform_edt(~mask_t, sampling=TARGET_RESOLUTION_M)
            s_roads = np.minimum(s_roads, (1.0 - np.exp(-dist_m / (d95 / 3.0))).astype(np.float32))

    urban = lc21 == 50
    if np.any(urban):
        dist_u = distance_transform_edt(~urban, sampling=TARGET_RESOLUTION_M)
        s_urban = (1.0 - np.exp(-dist_u / (DIST_95_URBAN_M / 3.0))).astype(np.float32)
    else:
        s_urban = np.ones_like(s_cob, dtype=np.float32)

    if np.any(water == 1):
        dist_w = distance_transform_edt(water != 1, sampling=TARGET_RESOLUTION_M)
        s_water = np.exp(-dist_w / WATER_DECAY_K_M).astype(np.float32)
    else:
        s_water = np.zeros_like(s_cob, dtype=np.float32)

    h = (
        HSM_WEIGHTS["cob"] * s_cob
        + HSM_WEIGHTS["ndvi"] * s_ndvi
        + HSM_WEIGHTS["roads"] * s_roads
        + HSM_WEIGHTS["urban"] * s_urban
        + HSM_WEIGHTS["water"] * s_water
    ).astype(np.float32)

    h[(lc21 == 80) | (lc21 == 50)] = 0.0
    h = np.clip(h, 0.0, 1.0)

    pf = profile.copy()
    pf.update(dtype="float32", nodata=-9999.0)
    with rasterio.open(VAL_DIR / "regional_hsm_30m.tif", "w", **pf) as dst:
        dst.write(h, 1)
    return h


def compute_roc_curve(pos_scores: np.ndarray, bg_scores: np.ndarray) -> tuple[np.ndarray, np.ndarray, float]:
    thresholds = np.linspace(1.0, 0.0, 201)
    tpr = np.array([np.mean(pos_scores >= t) for t in thresholds])
    fpr = np.array([np.mean(bg_scores >= t) for t in thresholds])
    # Garantizar extremos (0,0) y (1,1)
    fpr = np.concatenate([[0.0], fpr, [1.0]])
    tpr = np.concatenate([[0.0], tpr, [1.0]])
    order = np.argsort(fpr)
    fpr, tpr = fpr[order], tpr[order]
    auc_val = float(np.trapezoid(tpr, fpr))
    return fpr, tpr, auc_val


def run_validation() -> None:
    VAL_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)

    occ_utm, clean_stats = load_and_clean_occurrences()
    reg_utm, profile = build_regional_grid()
    lc21 = build_regional_landcover(profile)
    roads, water = build_regional_osm_roads_and_water(reg_utm, lc21, profile)
    ndvi26 = build_regional_ndvi_2026(profile)
    h_reg = compute_regional_hsm(lc21, roads, water, ndvi26, profile)

    # Extraer H(x) y distancia a hábitat núcleo regional y corredores piloto para cada registro
    aoi_pilot = gpd.read_file(DATA_PROCESSED_DIR / "aoi_utm16n.geojson").geometry.iloc[0]
    corridors_pilot = gpd.read_file(DATA_PROCESSED_DIR / "corredores_utm16n.gpkg")
    corridors_union = corridors_pilot.geometry.union_all()
    patches_pilot = gpd.read_file(DATA_PROCESSED_DIR / "parches_utm16n.gpkg")
    patches_union = patches_pilot.geometry.union_all()

    dist_to_core_reg = distance_transform_edt(h_reg < PATCH_SUITABILITY_THRESHOLD, sampling=TARGET_RESOLUTION_M)
    transform = profile["transform"]

    eval_rows = []
    dropped_water = 0
    for _, row in occ_utm.iterrows():
        x, y = row.geometry.x, row.geometry.y
        r, c = rasterio.transform.rowcol(transform, x, y)
        if not (0 <= r < profile["height"] and 0 <= c < profile["width"]):
            continue
        if lc21[r, c] == 80:
            dropped_water += 1
            continue
        h_val = float(h_reg[r, c])
        d_core = float(dist_to_core_reg[r, c])
        in_pilot = bool(aoi_pilot.contains(row.geometry))
        d_corr_pilot = float(row.geometry.distance(corridors_union)) if in_pilot else None
        in_patch_pilot = bool(patches_union.contains(row.geometry)) if in_pilot else False

        rec = row.to_dict()
        rec.update(
            {
                "hsm_score": round(h_val, 4),
                "in_core_h70": bool(h_val >= PATCH_SUITABILITY_THRESHOLD),
                "dist_core_m": round(d_core, 1),
                "in_pilot_aoi": in_pilot,
                "in_pilot_patch": in_patch_pilot,
                "dist_pilot_corridor_m": round(d_corr_pilot, 1) if d_corr_pilot is not None else None,
            }
        )
        eval_rows.append(rec)

    occ_eval = gpd.GeoDataFrame(eval_rows, crs=TARGET_CRS)
    occ_eval.to_crs("EPSG:4326").to_file(OUTPUTS_DIR / "validacion_registros.geojson", driver="GeoJSON")

    pos_scores = occ_eval["hsm_score"].to_numpy(dtype=np.float64)

    # 10,000 puntos de fondo aleatorios sobre tierra (excluyendo agua permanente ESA 80)
    rng = np.random.default_rng(42)
    land_h_all = h_reg[lc21 != 80]
    bg_scores = rng.choice(land_h_all, size=10_000, replace=False).astype(np.float64)

    mw = mannwhitneyu(pos_scores, bg_scores, alternative="greater")
    # AUC exacto por Mann-Whitney: U / (n_pos * n_bg)
    auc_exact = float(mw.statistic / (len(pos_scores) * len(bg_scores)))
    fpr, tpr, _ = compute_roc_curve(pos_scores, bg_scores)

    pct_core = float(np.mean(pos_scores >= PATCH_SUITABILITY_THRESHOLD) * 100.0)
    pct_bg_core = float(np.mean(bg_scores >= PATCH_SUITABILITY_THRESHOLD) * 100.0)

    pilot_occ = occ_eval[occ_eval["in_pilot_aoi"]]
    summary = {
        "species": "Panthera onca",
        "regional_bbox_wgs84": list(REGIONAL_BBOX_WGS84),
        "cleaning": {
            **clean_stats,
            "dropped_on_water": dropped_water,
            "final_presence_n": int(len(occ_eval)),
            "in_pilot_n": int(len(pilot_occ)),
        },
        "metrics": {
            "roc_auc": round(auc_exact, 4),
            "mann_whitney_u": round(float(mw.statistic), 1),
            "mann_whitney_p": float(f"{mw.pvalue:.4e}"),
            "presence_mean_hsm": round(float(np.mean(pos_scores)), 4),
            "presence_median_hsm": round(float(np.median(pos_scores)), 4),
            "background_mean_hsm": round(float(np.mean(bg_scores)), 4),
            "background_median_hsm": round(float(np.median(bg_scores)), 4),
            "pct_presence_in_core_h70": round(pct_core, 1),
            "pct_background_in_core_h70": round(pct_bg_core, 1),
            "presence_median_dist_core_m": round(float(np.median(occ_eval["dist_core_m"])), 1),
        },
        "pilot_records": [
            {
                "record_id": r["record_id"],
                "source": r["source"],
                "year": r["year"],
                "hsm_score": r["hsm_score"],
                "in_pilot_patch": r["in_pilot_patch"],
                "dist_pilot_corridor_m": r["dist_pilot_corridor_m"],
            }
            for _, r in pilot_occ.iterrows()
        ],
        "roc_curve": {
            "fpr": [round(float(x), 4) for x in fpr[::4]],
            "tpr": [round(float(x), 4) for x in tpr[::4]],
        },
    }

    (OUTPUTS_DIR / "validacion.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Generar figura de validación (3 paneles)
    left, bottom, right, top = rasterio.transform.array_bounds(profile["height"], profile["width"], transform)
    extent = [left, right, bottom, top]
    rgba = (HSM_CMAP(np.clip(h_reg, 0.0, 1.0)) * 255).astype(np.uint8)
    rgba[lc21 == 80] = (182, 218, 242, 255)
    rgba[lc21 == 50] = (80, 80, 80, 255)

    fig = plt.figure(figsize=(18, 9.5), dpi=150)
    gs = gridspec.GridSpec(2, 2, width_ratios=[1.35, 1.0], wspace=0.25, hspace=0.32)
    fig.suptitle(
        "BioConecta — Fase 5: Validación Científica del Modelo HSM (Panthera onca)\n"
        f"Zona ampliada norte de Quintana Roo | n = {len(occ_eval)} presencias únicas (GBIF + iNaturalist) vs 10,000 fondo",
        fontsize=13,
        fontweight="bold",
        y=0.98,
    )

    # Panel 1: Mapa regional HSM + recuadro zona piloto + presencias
    ax1 = fig.add_subplot(gs[:, 0])
    ax1.imshow(rgba, extent=extent, origin="upper")
    gpd.GeoSeries([aoi_pilot], crs=TARGET_CRS).boundary.plot(
        ax=ax1, color="#ffffff", linewidth=2.2, linestyle="--", zorder=6, label="Zona piloto BioConecta"
    )
    occ_eval[occ_eval["source"] == "GBIF"].plot(
        ax=ax1, color="#FFD700", edgecolor="black", marker="*", markersize=140, zorder=8, label="GBIF"
    )
    if (occ_eval["source"] == "iNaturalist").any():
        occ_eval[occ_eval["source"] == "iNaturalist"].plot(
            ax=ax1, color="#00e5ff", edgecolor="black", marker="o", markersize=55, zorder=9, label="iNaturalist (RG)"
        )
    ax1.set_xlim(left, right)
    ax1.set_ylim(bottom, top)
    ax1.set_title("1. HSM Regional (30×30 m) y Registros de Presencia de Jaguar", fontweight="bold", fontsize=10.5)
    ax1.set_xlabel("Este UTM 16N (m)")
    ax1.set_ylabel("Norte UTM 16N (m)")
    ax1.legend(loc="lower right", fontsize=8.5, framealpha=0.92)

    # Panel 2: Curva ROC
    ax2 = fig.add_subplot(gs[0, 1])
    ax2.plot(fpr, tpr, color="#1a9850", linewidth=2.4, label=f"Modelo HSM (AUC = {auc_exact:.3f})")
    ax2.plot([0, 1], [0, 1], color="#888888", linestyle="--", linewidth=1.2, label="Azar (AUC = 0.500)")
    ax2.fill_between(fpr, tpr, alpha=0.15, color="#1a9850")
    ax2.set_title(
        f"2. Curva ROC — Mann-Whitney p = {mw.pvalue:.2e}",
        fontweight="bold",
        fontsize=10.5,
    )
    ax2.set_xlabel("Tasa de falsos positivos (Fondo)")
    ax2.set_ylabel("Tasa de verdaderos positivos (Presencias)")
    ax2.legend(loc="lower right", fontsize=9)
    ax2.grid(alpha=0.25)

    # Panel 3: Distribución de H(x) en presencias vs fondo
    ax3 = fig.add_subplot(gs[1, 1])
    bins = np.linspace(0, 1, 26)
    ax3.hist(bg_scores, bins=bins, density=True, alpha=0.45, color="#757575", label=f"Fondo terrestre (mediana={np.median(bg_scores):.2f})")
    ax3.hist(pos_scores, bins=bins, density=True, alpha=0.72, color="#1b7837", edgecolor="black", linewidth=0.5, label=f"Presencias jaguar (mediana={np.median(pos_scores):.2f})")
    ax3.axvline(PATCH_SUITABILITY_THRESHOLD, color="#c62828", linestyle="--", linewidth=1.5, label=f"Umbral núcleo 0.70 ({pct_core:.1f}% presencias)")
    ax3.set_title("3. Idoneidad H(x): Registros Reales vs Fondo Terrestre", fontweight="bold", fontsize=10.5)
    ax3.set_xlabel("Índice de Idoneidad H(x)")
    ax3.set_ylabel("Densidad")
    ax3.legend(loc="upper left", fontsize=8)
    ax3.grid(alpha=0.25)

    out_png = OUTPUTS_DIR / "preview_validacion.png"
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)

    print("\n" + "=" * 78)
    print("RESUMEN — FASE 5: VALIDACIÓN CIENTÍFICA (GBIF + iNATURALIST)")
    print("=" * 78)
    print(f"Registros finales evaluados  : {len(occ_eval)} (en zona piloto: {len(pilot_occ)})")
    print(f"ROC-AUC (vs 10,000 fondo)    : {auc_exact:.4f}")
    print(f"Mann-Whitney U (p-valor)     : {mw.pvalue:.4e}")
    print(f"H(x) presencias (media/med.) : {np.mean(pos_scores):.3f} / {np.median(pos_scores):.3f}")
    print(f"H(x) fondo      (media/med.) : {np.mean(bg_scores):.3f} / {np.median(bg_scores):.3f}")
    print(f"Presencias en núcleo H≥0.70  : {pct_core:.1f}% (vs {pct_bg_core:.1f}% del fondo)")
    print(f"Distancia mediana a núcleo   : {np.median(occ_eval['dist_core_m']):.0f} m")
    print("=" * 78)


if __name__ == "__main__":
    run_validation()

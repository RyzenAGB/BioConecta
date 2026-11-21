"""
Paso 0 (Parte 2): Preparación única y normalización de capas geoespaciales.

Qué hace este script:
1. Define el recuadro exacto (AOI) de la zona piloto en sistema métrico UTM 16N (EPSG:32616)
   con cuadrícula alineada de píxeles de 30 x 30 metros.
2. Recorta, reproyecta y remuestrea (por moda) ESA WorldCover 2020 y 2021 a esa cuadrícula exacta.
3. Extrae la capa de mancha urbana (clase 50 = Built-up) para 2020 y 2021 en la misma cuadrícula.
4. Recorta y reproyecta la red vial (OSM) a UTM 16N, clasifica jerarquía vial
   (1=terracería, 2=calle local, 3=avenida/carretera pavimentada) y la rasteriza a 30x30m.
5. Reproyecta los registros históricos de jaguar (GBIF) a UTM 16N.
6. Imprime un resumen de verificación de alineación y cobertura en hectáreas (2020 vs 2021).
"""

import math
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from rasterio.warp import Resampling, reproject
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    AOI_BBOX_WGS84,
    DATA_PROCESSED_DIR,
    DATA_RAW_DIR,
    ESA_WORLDCOVER_CLASSES,
    TARGET_CRS,
    TARGET_RESOLUTION_M,
)

PAVED_MAJOR = {
    "motorway",
    "motorway_link",
    "trunk",
    "trunk_link",
    "primary",
    "primary_link",
    "secondary",
    "secondary_link",
    "tertiary",
    "tertiary_link",
}
LOCAL_STREETS = {"residential", "unclassified", "service", "living_street"}
UNPAVED_SURFACES = {"unpaved", "dirt", "gravel", "sand", "ground", "earth", "mud", "compacted"}


def build_reference_grid() -> tuple[gpd.GeoDataFrame, dict]:
    """Construye la cuadrícula canónica UTM 16N a 30x30m ajustada a múltiplos de 30m."""
    aoi_wgs84 = gpd.GeoDataFrame(
        {"name": ["Zona Piloto UNICARIBE - Rancho Viejo - Isla Mujeres"]},
        geometry=[box(*AOI_BBOX_WGS84)],
        crs="EPSG:4326",
    )
    aoi_utm = aoi_wgs84.to_crs(TARGET_CRS)
    minx, miny, maxx, maxy = aoi_utm.total_bounds

    res = TARGET_RESOLUTION_M
    minx_s = math.floor(minx / res) * res
    miny_s = math.floor(miny / res) * res
    maxx_s = math.ceil(maxx / res) * res
    maxy_s = math.ceil(maxy / res) * res

    width = int(round((maxx_s - minx_s) / res))
    height = int(round((maxy_s - miny_s) / res))
    transform = from_origin(minx_s, maxy_s, res, res)

    aoi_snapped_utm = gpd.GeoDataFrame(
        {"name": ["Zona Piloto UNICARIBE - Rancho Viejo - Isla Mujeres"]},
        geometry=[box(minx_s, miny_s, maxx_s, maxy_s)],
        crs=TARGET_CRS,
    )
    aoi_snapped_utm.to_file(DATA_PROCESSED_DIR / "aoi_utm16n.geojson", driver="GeoJSON")
    aoi_snapped_utm.to_crs("EPSG:4326").to_file(
        DATA_PROCESSED_DIR / "aoi_wgs84.geojson", driver="GeoJSON"
    )

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
    return aoi_snapped_utm, profile


def process_worldcover(profile: dict) -> dict[int, np.ndarray]:
    """Reproyecta, recorta y alinea ESA WorldCover 2020 y 2021 y extrae mancha urbana."""
    arrays = {}
    for year in (2020, 2021):
        src_path = DATA_RAW_DIR / f"esa_worldcover_{year}_N21W087.tif"
        dst_lc_path = DATA_PROCESSED_DIR / f"landcover_{year}_30m.tif"
        dst_urb_path = DATA_PROCESSED_DIR / f"urban_{year}_30m.tif"

        dst_arr = np.zeros((profile["height"], profile["width"]), dtype=np.uint8)
        with rasterio.open(src_path) as src:
            reproject(
                source=rasterio.band(src, 1),
                destination=dst_arr,
                src_transform=src.transform,
                src_crs=src.crs,
                dst_transform=profile["transform"],
                dst_crs=profile["crs"],
                resampling=Resampling.mode,
            )

        with rasterio.open(dst_lc_path, "w", **profile) as dst:
            dst.write(dst_arr, 1)

        # Extraer mancha urbana (clase 50 = Built-up)
        urban_arr = (dst_arr == 50).astype(np.uint8)
        urb_profile = profile.copy()
        urb_profile["nodata"] = 255
        with rasterio.open(dst_urb_path, "w", **urb_profile) as dst:
            dst.write(urban_arr, 1)

        arrays[year] = dst_arr
        print(f"  [OK] {dst_lc_path.name} y {dst_urb_path.name} generados.")

    return arrays


def classify_road_tier(row) -> int:
    """
    Clasifica cada vía en 3 niveles para modelado de hábitat y resistencia:
      3 = Avenida / carretera principal pavimentada
      2 = Calle local / residencial
      1 = Terracería / camino rural / brecha
    """
    hw = str(row.get("highway", "")).lower()
    surf = str(row.get("surface", "")).lower()

    if hw in {"track", "path"} or surf in UNPAVED_SURFACES:
        return 1
    if hw in PAVED_MAJOR:
        return 3
    if hw in LOCAL_STREETS:
        return 2
    return 1


def process_roads(aoi_utm: gpd.GeoDataFrame, profile: dict) -> gpd.GeoDataFrame:
    """Recorta, reproyecta, clasifica y rasteriza la red vial OSM."""
    src_path = DATA_RAW_DIR / "osm_roads_raw.geojson"
    roads = gpd.read_file(src_path)
    roads_utm = roads.to_crs(TARGET_CRS)
    roads_utm = gpd.clip(roads_utm, aoi_utm)
    roads_utm = roads_utm[~roads_utm.geometry.is_empty].copy()
    roads_utm["road_tier"] = roads_utm.apply(classify_road_tier, axis=1)

    # Guardar vector en UTM 16N (GeoPackage) y WGS84 (GeoJSON ligero para inspección/web)
    roads_utm.to_file(DATA_PROCESSED_DIR / "roads_utm16n.gpkg", driver="GPKG")
    roads_utm.to_crs("EPSG:4326").to_file(
        DATA_PROCESSED_DIR / "roads_wgs84.geojson", driver="GeoJSON"
    )

    # Rasterizar en la cuadrícula exacta de 30x30m (ordenado por tier ascendente para que
    # una avenida principal prevalezca si coincide en el mismo píxel con una terracería)
    roads_sorted = roads_utm.sort_values("road_tier", ascending=True)
    shapes = (
        (geom, int(tier))
        for geom, tier in zip(roads_sorted.geometry, roads_sorted["road_tier"])
        if geom is not None and not geom.is_empty
    )
    roads_raster = rasterize(
        shapes=shapes,
        out_shape=(profile["height"], profile["width"]),
        transform=profile["transform"],
        fill=0,
        all_touched=True,
        dtype=np.uint8,
    )

    road_profile = profile.copy()
    road_profile["nodata"] = 255
    with rasterio.open(DATA_PROCESSED_DIR / "roads_30m.tif", "w", **road_profile) as dst:
        dst.write(roads_raster, 1)

    print(
        f"  [OK] Red vial procesada: {len(roads_utm)} segmentos -> roads_utm16n.gpkg y roads_30m.tif"
    )
    return roads_utm


def process_gbif(aoi_utm: gpd.GeoDataFrame) -> tuple[int, int]:
    """Reproyecta registros históricos de jaguar (GBIF) a UTM 16N."""
    counts = []
    for name, clip_to_aoi in [
        ("gbif_jaguar_pilot", True),
        ("gbif_jaguar_regional", False),
    ]:
        src_path = DATA_RAW_DIR / f"{name}.geojson"
        dst_path = DATA_PROCESSED_DIR / f"{name}_utm16n.geojson"
        gdf = gpd.read_file(src_path)
        if len(gdf) > 0:
            gdf_utm = gdf.to_crs(TARGET_CRS)
            if clip_to_aoi:
                gdf_utm = gpd.clip(gdf_utm, aoi_utm)
        else:
            gdf_utm = gpd.GeoDataFrame(geometry=[], crs=TARGET_CRS)
        gdf_utm.to_file(dst_path, driver="GeoJSON")
        counts.append(len(gdf_utm))
        print(f"  [OK] {dst_path.name}: {len(gdf_utm)} registros")
    return counts[0], counts[1]


def print_summary(profile: dict, lc_arrays: dict[int, np.ndarray], roads_utm: gpd.GeoDataFrame) -> None:
    pixel_ha = (TARGET_RESOLUTION_M * TARGET_RESOLUTION_M) / 10_000.0  # 0.09 ha por píxel
    total_ha = profile["width"] * profile["height"] * pixel_ha

    print("\n" + "=" * 72)
    print("RESUMEN DE VERIFICACIÓN — PASO 0 (CAPAS ALINEADAS)")
    print("=" * 72)
    print(f"CRS destino         : {profile['crs']} (UTM Zona 16N, métrico)")
    print(f"Resolución espacial : {TARGET_RESOLUTION_M:.0f} x {TARGET_RESOLUTION_M:.0f} m ({pixel_ha:.2f} ha/píxel)")
    print(f"Dimensiones grilla  : {profile['width']} cols x {profile['height']} filas ({total_ha:,.1f} ha totales)")

    print("\nCobertura del suelo en la zona piloto (hectáreas):")
    print(f"  {'Clase':<36} {'2020 (ha)':>12} {'2021 (ha)':>12} {'Cambio (ha)':>12}")
    print("  " + "-" * 74)
    all_classes = sorted(set(np.unique(lc_arrays[2020])) | set(np.unique(lc_arrays[2021])))
    for cls in all_classes:
        if cls == 0:
            continue
        ha_20 = np.sum(lc_arrays[2020] == cls) * pixel_ha
        ha_21 = np.sum(lc_arrays[2021] == cls) * pixel_ha
        diff = ha_21 - ha_20
        label = f"{cls} - {ESA_WORLDCOVER_CLASSES.get(int(cls), 'Otra')}"
        print(f"  {label:<36} {ha_20:>12,.1f} {ha_21:>12,.1f} {diff:>+12,.1f}")

    tier_counts = roads_utm["road_tier"].value_counts().sort_index()
    print("\nRed vial clasificada en zona piloto (segmentos OSM):")
    tier_names = {1: "Tier 1 (Terracería/brecha)", 2: "Tier 2 (Calle local)", 3: "Tier 3 (Av./Carretera)"}
    for t in (1, 2, 3):
        print(f"  {tier_names[t]:<30}: {tier_counts.get(t, 0):>6,}")
    print("=" * 72)


def main() -> None:
    DATA_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    print("Preparando cuadrícula canónica y normalizando capas...")

    aoi_utm, profile = build_reference_grid()
    lc_arrays = process_worldcover(profile)
    roads_utm = process_roads(aoi_utm, profile)
    process_gbif(aoi_utm)
    print_summary(profile, lc_arrays, roads_utm)


if __name__ == "__main__":
    main()

"""
Fase 2 — Vista 1: Modelado de Idoneidad de Hábitat (HSM) para Jaguar (Panthera onca).

Calcula las 5 capas normalizadas (0 a 1) en la cuadrícula UTM 16N (30x30 m):
  - S_cob   : Puntaje por cobertura vegetal (ESA WorldCover 2021)
  - S_ndvi  : Calidad/densidad de vegetación actual (Sentinel-2 NDVI secas 2026, 0.2->0 a 0.8->1)
  - S_roads : Distancia exponencial a red vial por jerarquía (mínimo entre Tier 3, 2 y 1)
  - S_urban : Distancia exponencial a mancha urbana (D_0.95 = 2,000 m)
  - S_water : Proximidad exponencial inversa a fuentes de agua (ESA 80/90 + cenotes/lagunas OSM)

Combina:
  H(x) = 0.35*S_cob + 0.15*S_ndvi + 0.20*S_roads + 0.20*S_urban + 0.10*S_water
  con máscara dura: agua permanente (ESA 80) y zona urbana (ESA 50) -> H = 0.

Salidas:
  - outputs/idoneidad.tif
  - data/processed/S_cob.tif, S_ndvi.tif, S_roads.tif, S_urban.tif, S_water.tif, hard_zero_mask.tif
  - outputs/preview_vista1.png
  - outputs/mapa_vista1.html
"""

import base64
import io
import json
import sys
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image
from pyproj import Transformer
from rasterio.warp import Resampling, calculate_default_transform, reproject
from scipy.ndimage import convolve, distance_transform_edt
from skimage.measure import label
from skimage.morphology import disk

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATA_PROCESSED_DIR, LANDMARKS, PROJECT_ROOT, TARGET_CRS, TARGET_RESOLUTION_M
from species_rules import (
    DIST_95_ROADS_M,
    DIST_95_URBAN_M,
    HSM_WEIGHTS,
    LANDCOVER_SCORES,
    MIN_NATURAL_ENCLAVE_HA,
    NDVI_SCORE_MAX,
    NDVI_SCORE_MIN,
    PATCH_SUITABILITY_THRESHOLD,
    URBAN_MATRIX_DENSITY_THRESHOLD,
    URBAN_MATRIX_RADIUS_M,
    WATER_DECAY_K_M,
)

OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# Paleta intuitiva para idoneidad: rojo (baja) -> naranja -> amarillo -> verde -> verde oscuro (alta)
HSM_CMAP = LinearSegmentedColormap.from_list(
    "bioconecta_hsm",
    [
        (0.00, "#a50026"),
        (0.25, "#f46d43"),
        (0.50, "#fee08b"),
        (0.70, "#66bd63"),
        (0.85, "#1a9850"),
        (1.00, "#00441b"),
    ],
)


def save_float_raster(path: Path, arr: np.ndarray, profile: dict) -> None:
    prof = profile.copy()
    prof.update(dtype="float32", nodata=-9999.0, compress="lzw")
    with rasterio.open(path, "w", **prof) as dst:
        dst.write(arr.astype(np.float32), 1)


def compute_hsm() -> dict:
    with rasterio.open(DATA_PROCESSED_DIR / "landcover_2021_30m.tif") as src:
        lc21 = src.read(1)
        profile = src.profile.copy()
        bounds = src.bounds
    with rasterio.open(DATA_PROCESSED_DIR / "urban_2021_30m.tif") as src:
        urban21 = src.read(1)
    with rasterio.open(DATA_PROCESSED_DIR / "roads_30m.tif") as src:
        roads = src.read(1)
    with rasterio.open(DATA_PROCESSED_DIR / "water_sources_30m.tif") as src:
        water_src = src.read(1)
    with rasterio.open(DATA_PROCESSED_DIR / "ndvi_2026_30m.tif") as src:
        ndvi26 = src.read(1)
        ndvi_nodata = src.nodata

    anthro_path = DATA_PROCESSED_DIR / "osm_anthro_30m.tif"
    if anthro_path.exists():
        with rasterio.open(anthro_path) as src:
            osm_anthro = src.read(1)
    else:
        osm_anthro = np.zeros_like(urban21, dtype=np.uint8)

    # Huella urbana/turística efectiva: ESA 2021 + resorts/hoteles/golf/desarrollos OSM
    urban_eff = ((urban21 == 1) | (lc21 == 50) | (osm_anthro == 1)).astype(np.uint8)

    # 1. S_cob
    s_cob = np.zeros_like(lc21, dtype=np.float32)
    for code, score in LANDCOVER_SCORES.items():
        s_cob[lc21 == code] = score

    # 2. S_ndvi (lineal 0.2 -> 0, 0.8 -> 1)
    ndvi_valid = (ndvi26 != ndvi_nodata) & np.isfinite(ndvi26)
    s_ndvi = np.clip((ndvi26 - NDVI_SCORE_MIN) / (NDVI_SCORE_MAX - NDVI_SCORE_MIN), 0.0, 1.0).astype(
        np.float32
    )
    # Respaldo solo si existiera algún píxel sin dato en NDVI
    s_ndvi = np.where(ndvi_valid, s_ndvi, s_cob)

    # 3. S_roads = min(S_tier3, S_tier2, S_tier1), curva exponencial 1 - exp(-d / k)
    s_roads = np.ones_like(s_cob, dtype=np.float32)
    for tier, d95 in DIST_95_ROADS_M.items():
        mask_tier = roads == tier
        if np.any(mask_tier):
            dist_m = distance_transform_edt(~mask_tier, sampling=TARGET_RESOLUTION_M)
            k = d95 / 3.0
            s_tier = (1.0 - np.exp(-dist_m / k)).astype(np.float32)
            s_roads = np.minimum(s_roads, s_tier)

    # 4. S_urban: curva exponencial 1 - exp(-d / k), D_0.95 = 2,000 m (urbano ESA + resorts/hoteles OSM)
    if np.any(urban_eff == 1):
        dist_urb_m = distance_transform_edt(urban_eff != 1, sampling=TARGET_RESOLUTION_M)
        k_urb = DIST_95_URBAN_M / 3.0
        s_urban = (1.0 - np.exp(-dist_urb_m / k_urb)).astype(np.float32)
    else:
        s_urban = np.ones_like(s_cob, dtype=np.float32)

    # 5. S_water: curva exponencial inversa exp(-d / 1000) -> 1 junto al agua, ~0.05 a 3 km
    if np.any(water_src == 1):
        dist_water_m = distance_transform_edt(water_src != 1, sampling=TARGET_RESOLUTION_M)
        s_water = np.exp(-dist_water_m / WATER_DECAY_K_M).astype(np.float32)
    else:
        s_water = np.zeros_like(s_cob, dtype=np.float32)

    # 6. Suma ponderada
    h = (
        HSM_WEIGHTS["cob"] * s_cob
        + HSM_WEIGHTS["ndvi"] * s_ndvi
        + HSM_WEIGHTS["roads"] * s_roads
        + HSM_WEIGHTS["urban"] * s_urban
        + HSM_WEIGHTS["water"] * s_water
    ).astype(np.float32)

    # 7. Máscara dura: agua permanente (ESA 80), zona urbana/turística (ESA 50 + resorts OSM),
    #    matriz urbana/turística consolidada (>= 35% en 300 m) y enclaves/barras aisladas (< 500 ha)
    built_footprint = ((urban_eff == 1) | (roads >= 2)).astype(np.float32)
    radius_px = max(1, int(round(URBAN_MATRIX_RADIUS_M / TARGET_RESOLUTION_M)))
    kernel = disk(radius_px).astype(np.float32)
    kernel /= kernel.sum()
    urb_density = convolve(built_footprint, kernel, mode="nearest")

    urban_matrix = (urban_eff == 1) | (urb_density >= URBAN_MATRIX_DENSITY_THRESHOLD)

    # Identificar y excluir enclaves desconectados (terrenos baldíos urbanos y barra hotelera costera < 500 ha)
    pixel_ha = (TARGET_RESOLUTION_M * TARGET_RESOLUTION_M) / 10_000.0
    natural_candidates = (~urban_matrix) & (lc21 != 80)
    lbl_nat = label(natural_candidates, connectivity=2)
    nat_counts = np.bincount(lbl_nat.ravel())
    small_ids = np.where((nat_counts > 0) & ((nat_counts * pixel_ha) < MIN_NATURAL_ENCLAVE_HA))[0]
    small_ids = small_ids[small_ids > 0]
    small_enclaves = np.isin(lbl_nat, small_ids)

    hard_zero = (lc21 == 80) | urban_matrix | small_enclaves
    h[hard_zero] = 0.0
    h = np.clip(h, 0.0, 1.0)

    removed_urban_noise_ha = float(np.sum((lc21 != 80) & (lc21 != 50) & (urban_matrix | small_enclaves)) * pixel_ha)
    print(
        f"  [OK] Filtro urbano/turístico: {len(small_ids)} enclaves/barras < {MIN_NATURAL_ENCLAVE_HA:.0f} ha "
        f"y matriz urbana/hotelera excluidos ({removed_urban_noise_ha:,.1f} ha removidas)."
    )

    # Guardar capas intermedias (para sliders en vivo en Streamlit) y salida principal
    save_float_raster(DATA_PROCESSED_DIR / "S_cob.tif", s_cob, profile)
    save_float_raster(DATA_PROCESSED_DIR / "S_ndvi.tif", s_ndvi, profile)
    save_float_raster(DATA_PROCESSED_DIR / "S_roads.tif", s_roads, profile)
    save_float_raster(DATA_PROCESSED_DIR / "S_urban.tif", s_urban, profile)
    save_float_raster(DATA_PROCESSED_DIR / "S_water.tif", s_water, profile)

    mask_prof = profile.copy()
    mask_prof.update(dtype="uint8", nodata=255, compress="lzw")
    with rasterio.open(DATA_PROCESSED_DIR / "hard_zero_mask.tif", "w", **mask_prof) as dst:
        dst.write(hard_zero.astype(np.uint8), 1)

    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    save_float_raster(OUTPUTS_DIR / "idoneidad.tif", h, profile)

    return {
        "H": h,
        "S_cob": s_cob,
        "S_ndvi": s_ndvi,
        "S_roads": s_roads,
        "S_urban": s_urban,
        "S_water": s_water,
        "lc21": lc21,
        "hard_zero": hard_zero,
        "bounds": bounds,
        "profile": profile,
    }


def colorize_hsm(
    h: np.ndarray,
    lc21: np.ndarray | None = None,
    hard_zero: np.ndarray | None = None,
    alpha_water: bool = True,
) -> np.ndarray:
    rgba = (HSM_CMAP(np.clip(h, 0.0, 1.0)) * 255).astype(np.uint8)
    if lc21 is not None:
        water = lc21 == 80
        excluded_urb = (hard_zero & ~water) if hard_zero is not None else (lc21 == 50)
        if alpha_water:
            rgba[water] = (175, 215, 240, 0)
            rgba[excluded_urb] = (80, 80, 80, 0)
        else:
            rgba[water] = (180, 218, 242, 255)
            rgba[excluded_urb] = (75, 75, 75, 255)
    return rgba


def plot_landmarks(ax, transformer: Transformer, fontsize: int = 8) -> None:
    for name, (lat, lon) in LANDMARKS.items():
        x, y = transformer.transform(lon, lat)
        ax.scatter(x, y, c="white", edgecolors="black", s=45, zorder=7, linewidth=1.2)
        ax.annotate(
            name,
            (x, y),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=fontsize,
            fontweight="bold",
            color="black",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="black", alpha=0.85),
            zorder=8,
        )


def generate_preview(res: dict) -> Path:
    bounds = res["bounds"]
    extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)

    gbif = gpd.read_file(DATA_PROCESSED_DIR / "gbif_jaguar_pilot_utm16n.geojson")
    roads = gpd.read_file(DATA_PROCESSED_DIR / "roads_utm16n.gpkg")
    roads_major = roads[roads["road_tier"] == 3]

    fig = plt.figure(figsize=(19, 12), dpi=150)
    gs = gridspec.GridSpec(3, 4, width_ratios=[1.45, 1.45, 1.0, 1.0], wspace=0.40, hspace=0.32)

    fig.suptitle(
        "BioConecta — Vista 1: Modelado de Idoneidad de Hábitat (HSM) para Jaguar (Panthera onca)\n"
        "H(x) = 0.35·S_cob + 0.15·S_ndvi + 0.20·S_carreteras + 0.20·S_urbano + 0.10·S_agua  |  UTM 16N (30×30 m)",
        fontsize=13.5,
        fontweight="bold",
        y=0.975,
    )

    # Mapa principal grande (ocupa las 3 filas y las 2 columnas izquierdas)
    ax_main = fig.add_subplot(gs[:, 0:2])
    h_rgba = colorize_hsm(res["H"], res["lc21"], res["hard_zero"], alpha_water=False)
    ax_main.imshow(h_rgba, extent=extent, origin="upper")

    # Contorno del umbral H >= 0.7 (candidato a parches de Vista 2)
    ax_main.contour(
        res["H"],
        levels=[PATCH_SUITABILITY_THRESHOLD],
        colors=["#ffffff"],
        linewidths=0.9,
        extent=extent,
        origin="upper",
        alpha=0.85,
    )

    roads_major.plot(ax=ax_main, color="#1a1a1a", linewidth=1.0, alpha=0.65, label="Av./Carretera (Tier 3)")
    if len(gbif) > 0:
        gbif.plot(
            ax=ax_main,
            color="#FFD700",
            edgecolor="black",
            marker="*",
            markersize=240,
            zorder=9,
            label=f"Jaguar GBIF ({len(gbif)} reg.)",
        )
    plot_landmarks(ax_main, transformer, fontsize=8.5)
    ax_main.set_xlim(bounds.left, bounds.right)
    ax_main.set_ylim(bounds.bottom, bounds.top)
    ax_main.set_title(
        "Idoneidad Final H(x) — Contorno blanco: H ≥ 0.70 (hábitat núcleo)\n"
        "(Gris = zona urbana enmascarada; azul = cuerpos de agua enmascarados)",
        fontweight="bold",
        fontsize=11,
    )
    ax_main.set_xlabel("Este UTM 16N (m)")
    ax_main.set_ylabel("Norte UTM 16N (m)")
    ax_main.legend(loc="upper left", fontsize=8.5, framealpha=0.9)

    sm = plt.cm.ScalarMappable(cmap=HSM_CMAP, norm=plt.Normalize(0, 1))
    sm.set_array([])
    cbar = fig.colorbar(sm, ax=ax_main, fraction=0.036, pad=0.02)
    cbar.set_label("Índice de Idoneidad de Hábitat H(x)  [0 = nulo, 1 = óptimo]", fontsize=9.5)

    # 5 subpaneles con las variables normalizadas S_i (en las 2 columnas derechas)
    factors = [
        ("S_cob (peso 0.35)\nCobertura vegetal (ESA)", res["S_cob"], "YlGn"),
        ("S_ndvi (peso 0.15)\nNDVI secas 2026 (Sentinel-2)", res["S_ndvi"], "YlGn"),
        ("S_carreteras (peso 0.20)\nDistancia exponencial vías", res["S_roads"], "RdYlGn"),
        ("S_urbano (peso 0.20)\nDistancia exponencial urbano", res["S_urban"], "RdYlGn"),
        ("S_agua (peso 0.10)\nProximidad fuentes de agua", res["S_water"], "GnBu"),
    ]
    positions = [(0, 2), (0, 3), (1, 2), (1, 3), (2, 2)]
    for (title, arr, cmap_name), (r, c) in zip(factors, positions):
        ax = fig.add_subplot(gs[r, c])
        im = ax.imshow(arr, cmap=cmap_name, vmin=0, vmax=1, extent=extent, origin="upper")
        ax.set_title(title, fontsize=9, fontweight="bold")
        ax.set_xticks([])
        ax.set_yticks([])
        fig.colorbar(im, ax=ax, fraction=0.046, pad=0.02)

    # Panel 6 (inferior derecho): histograma de H(x) en tierra no urbana
    ax_hist = fig.add_subplot(gs[2, 3])
    land_vals = res["H"][~res["hard_zero"]]
    ax_hist.hist(land_vals, bins=30, range=(0, 1), color="#2e8b57", edgecolor="white", alpha=0.88)
    ax_hist.axvline(PATCH_SUITABILITY_THRESHOLD, color="#d73027", linestyle="--", linewidth=1.6, label="Umbral 0.70")
    ax_hist.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{int(v / 1000)}k" if v >= 1000 else f"{int(v)}"))
    ax_hist.set_title("Distribución de H(x)\n(tierra no urbana)", fontsize=9, fontweight="bold")
    ax_hist.set_xlabel("Idoneidad H(x)", fontsize=8)
    ax_hist.set_ylabel("Píxeles", fontsize=8)
    ax_hist.legend(fontsize=7.5)
    ax_hist.grid(alpha=0.25)

    out_png = OUTPUTS_DIR / "preview_vista1.png"
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] Vista previa guardada en {out_png}")
    return out_png


def generate_interactive_map() -> Path:
    """Genera mapa interactivo Folium para la Vista 1."""
    # Reproyectar idoneidad.tif y landcover_2021_30m.tif a WGS84 para overlay limpio
    with rasterio.open(OUTPUTS_DIR / "idoneidad.tif") as src_h:
        dst_crs = "EPSG:4326"
        transform, width, height = calculate_default_transform(
            src_h.crs, dst_crs, src_h.width, src_h.height, *src_h.bounds
        )
        h_wgs = np.zeros((height, width), dtype=np.float32)
        reproject(
            source=rasterio.band(src_h, 1),
            destination=h_wgs,
            src_transform=src_h.transform,
            src_crs=src_h.crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )
        bounds = rasterio.transform.array_bounds(height, width, transform)
        folium_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]

    with rasterio.open(DATA_PROCESSED_DIR / "landcover_2021_30m.tif") as src_lc:
        lc_wgs = np.zeros((height, width), dtype=np.uint8)
        reproject(
            source=rasterio.band(src_lc, 1),
            destination=lc_wgs,
            src_transform=src_lc.transform,
            src_crs=src_lc.crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
        )

    with rasterio.open(DATA_PROCESSED_DIR / "hard_zero_mask.tif") as src_hz:
        hz_wgs = np.zeros((height, width), dtype=np.uint8)
        reproject(
            source=rasterio.band(src_hz, 1),
            destination=hz_wgs,
            src_transform=src_hz.transform,
            src_crs=src_hz.crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
        )

    rgba = colorize_hsm(h_wgs, lc_wgs, hz_wgs == 1, alpha_water=True)
    rgba[hz_wgs == 1, 3] = 0   # agua, matriz urbana y baldíos excluidos totalmente transparentes

    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    uri_hsm = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"

    m = folium.Map(location=[21.28, -86.88], zoom_start=12, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri WorldImagery",
        name="Satélite (Esri)",
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)

    folium.raster_layers.ImageOverlay(
        image=uri_hsm, bounds=folium_bounds, opacity=0.72, name="Idoneidad de Hábitat H(x)", show=True
    ).add_to(m)

    # Fuentes de agua OSM (cenotes/lagunas)
    osm_water = gpd.read_file(DATA_PROCESSED_DIR / "osm_water_utm16n.geojson").to_crs("EPSG:4326")
    if len(osm_water) > 0:
        water_pts = osm_water[osm_water.geometry.geom_type == "Point"]
        water_shapes = osm_water[osm_water.geometry.geom_type != "Point"]
        wg = folium.FeatureGroup(name="Fuentes de agua OSM (cenotes/lagunas)", show=False)
        if len(water_shapes) > 0:
            folium.GeoJson(
                water_shapes[["name", "natural", "water", "geometry"]],
                style_function=lambda _: {"color": "#00b4d8", "weight": 1.5, "fillColor": "#00b4d8", "fillOpacity": 0.4},
            ).add_to(wg)
        for _, r in water_pts.iterrows():
            folium.CircleMarker(
                location=[r.geometry.y, r.geometry.x],
                radius=5,
                color="#0077b6",
                fill=True,
                fill_color="#90e0ef",
                fill_opacity=0.95,
                tooltip=r.get("name") or r.get("water") or r.get("natural") or "Fuente de agua",
            ).add_to(wg)
        wg.add_to(m)

    # Red vial principal
    roads = gpd.read_file(DATA_PROCESSED_DIR / "roads_utm16n.gpkg").to_crs("EPSG:4326")
    folium.GeoJson(
        roads[roads["road_tier"] == 3][["name", "highway", "geometry"]],
        name="Avenidas / Carreteras (Tier 3)",
        style_function=lambda _: {"color": "#111111", "weight": 2.0, "opacity": 0.8},
        show=True,
    ).add_to(m)

    # Avistamientos GBIF piloto
    gbif = gpd.read_file(DATA_PROCESSED_DIR / "gbif_jaguar_pilot_utm16n.geojson").to_crs("EPSG:4326")
    gg = folium.FeatureGroup(name="Avistamientos Jaguar (GBIF piloto)", show=True)
    for _, row in gbif.iterrows():
        folium.Marker(
            location=[row.geometry.y, row.geometry.x],
            popup=f"<b>Panthera onca (GBIF)</b><br>Año: {row.get('year', 'N/D')}",
            icon=folium.Icon(color="orange", icon="paw", prefix="fa"),
        ).add_to(gg)
    gg.add_to(m)

    # Puntos de referencia
    lm = folium.FeatureGroup(name="Puntos de referencia", show=True)
    for name, (lat, lon) in LANDMARKS.items():
        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            color="#000000",
            fill=True,
            fill_color="#ffffff",
            fill_opacity=1.0,
            tooltip=name,
        ).add_to(lm)
    lm.add_to(m)

    # Leyenda continua
    legend_html = """
    <div style="position:fixed;bottom:25px;left:25px;z-index:9999;background:rgba(255,255,255,0.93);
                padding:10px 14px;border-radius:8px;border:1px solid #888;font-family:sans-serif;font-size:12px;">
      <b>Vista 1 — Idoneidad de Hábitat H(x)</b><br>
      <div style="width:190px;height:14px;margin:6px 0 3px 0;border:1px solid #444;
                  background:linear-gradient(to right,#a50026,#f46d43,#fee08b,#66bd63,#1a9850,#00441b);"></div>
      <div style="display:flex;justify-content:space-between;width:190px;font-size:11px;">
        <span>0.0 (Baja)</span><span>0.5</span><span>0.7</span><span>1.0 (Óptima)</span>
      </div>
      <div style="margin-top:4px;font-size:11px;color:#444;">Gris: zona urbana (H=0)</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl(collapsed=False).add_to(m)

    out_html = OUTPUTS_DIR / "mapa_vista1.html"
    m.save(str(out_html))
    print(f"  [OK] Mapa interactivo guardado en {out_html}")
    return out_html


def print_summary(res: dict) -> None:
    pixel_ha = (TARGET_RESOLUTION_M * TARGET_RESOLUTION_M) / 10_000.0
    h = res["H"]
    land = ~res["hard_zero"]
    land_h = h[land]

    ha_total_land = float(np.sum(land) * pixel_ha)
    ha_high = float(np.sum(h >= PATCH_SUITABILITY_THRESHOLD) * pixel_ha)
    ha_med = float(np.sum((h >= 0.4) & (h < PATCH_SUITABILITY_THRESHOLD) & land) * pixel_ha)
    ha_low = float(np.sum((h < 0.4) & land) * pixel_ha)

    # Extraer H(x) en los 2 registros GBIF piloto
    gbif = gpd.read_file(DATA_PROCESSED_DIR / "gbif_jaguar_pilot_utm16n.geojson")
    gbif_scores = []
    with rasterio.open(OUTPUTS_DIR / "idoneidad.tif") as src:
        for _, row in gbif.iterrows():
            r, c = src.index(row.geometry.x, row.geometry.y)
            val = float(h[r, c])
            gbif_scores.append((row.get("year"), round(val, 3)))

    print("\n" + "=" * 74)
    print("RESUMEN — VISTA 1: IDONEIDAD DE HÁBITAT (HSM — JAGUAR)")
    print("=" * 74)
    print(f"Superficie terrestre no urbana : {ha_total_land:>10,.1f} ha")
    print(f"  Alta idoneidad (H ≥ 0.70)    : {ha_high:>10,.1f} ha ({ha_high / ha_total_land * 100:5.1f}%)")
    print(f"  Media idoneidad (0.40–0.70)  : {ha_med:>10,.1f} ha ({ha_med / ha_total_land * 100:5.1f}%)")
    print(f"  Baja idoneidad (< 0.40)      : {ha_low:>10,.1f} ha ({ha_low / ha_total_land * 100:5.1f}%)")
    print(f"Idoneidad media (tierra)       : {float(np.mean(land_h)):>10.3f}")
    print(f"Idoneidad mediana (tierra)     : {float(np.median(land_h)):>10.3f}")
    print(f"Idoneidad máxima               : {float(np.max(land_h)):>10.3f}")
    print("\nPromedios por variable normalizada (en tierra no urbana):")
    for key in ("S_cob", "S_ndvi", "S_roads", "S_urban", "S_water"):
        print(f"  {key:<10}: {float(np.mean(res[key][land])):.3f}")
    if gbif_scores:
        print("\nChequeo rápido en los registros GBIF dentro de la zona piloto:")
        for yr, sc in gbif_scores:
            print(f"  Registro año {yr}: H(x) = {sc:.3f}")
    print("=" * 74)


def main() -> None:
    print("Calculando Vista 1: Idoneidad de Hábitat (HSM)...")
    res = compute_hsm()
    generate_preview(res)
    generate_interactive_map()
    print_summary(res)


if __name__ == "__main__":
    main()

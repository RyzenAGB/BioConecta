"""
Fase 3 — Vista 2: Análisis de Conectividad Ecológica para Jaguar (Panthera onca).

Qué hace este script:
1. Extrae parches de hábitat núcleo a partir de outputs/idoneidad.tif:
   - Píxeles con H >= 0.70
   - Agrupación de 8 vecinos (skimage.measure.label)
   - Descarta parches menores a 10 ha
   - Calcula área (ha), idoneidad media, cobertura dominante, centroide y bandera `toca_borde`
2. Construye la superficie de resistencia híbrida 50/50 (escala 1 a 100):
   - R = 0.5 * tabla_costos(cobertura + red vial) + 0.5 * (1 + 99 * (1 - H))
3. Calcula la matriz de distancia de costo entre parches (borde interior a borde interior)
   usando skimage.graph.MCP_Geometric (Dijkstra geométrico).
4. Selecciona pares de parches mediante:
   - Árbol de expansión mínima (MST) sobre distancia de costo + 2 vecinos más cercanos por parche
5. Traza los corredores de menor costo (líneas) y genera la franja de corredor estilo Linkage Mapper.

Salidas:
  - outputs/parches.geojson             (WGS84, listo para app web)
  - outputs/corredores.geojson          (WGS84, listo para app web)
  - outputs/resistencia.tif             (UTM 16N, 30x30 m)
  - outputs/corredores_franja.tif       (UTM 16N, 30x30 m, intensidad 0-1)
  - data/processed/parches_utm16n.gpkg  (UTM 16N, para Vista 3)
  - data/processed/parches_labeled_30m.tif (etiquetas enteras 1..N, para Vista 3)
  - outputs/preview_vista2.png
  - outputs/mapa_vista2.html
"""

import base64
import io
import sys
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import rasterio
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image
from pyproj import Transformer
from rasterio.features import shapes
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.geometry import LineString, shape
from shapely.ops import unary_union
from skimage.graph import MCP_Geometric
from skimage.measure import label

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import (
    DATA_PROCESSED_DIR,
    ESA_WORLDCOVER_CLASSES,
    LANDMARKS,
    PROJECT_ROOT,
    TARGET_CRS,
    TARGET_RESOLUTION_M,
)
from species_rules import (
    LANDCOVER_RESISTANCE,
    PATCH_MIN_AREA_HA,
    PATCH_SUITABILITY_THRESHOLD,
    RESISTANCE_HSM_WEIGHT,
    RESISTANCE_TABLE_WEIGHT,
    ROAD_RESISTANCE,
)

OUTPUTS_DIR = PROJECT_ROOT / "outputs"

RES_CMAP = LinearSegmentedColormap.from_list(
    "bioconecta_res",
    [(0.0, "#1a9850"), (0.2, "#a6d96a"), (0.5, "#fee08b"), (0.8, "#f46d43"), (1.0, "#67001f")],
)
SWATH_CMAP = LinearSegmentedColormap.from_list(
    "bioconecta_swath",
    [(0.0, "#00000000"), (0.15, "#ffe57f66"), (0.5, "#ffab00bb"), (0.85, "#ff3d00e6"), (1.0, "#d500f9ff")],
)


def extract_patches(h: np.ndarray, lc21: np.ndarray, profile: dict) -> tuple[gpd.GeoDataFrame, np.ndarray]:
    """Extrae parches de hábitat núcleo (H >= 0.70, área >= 10 ha) con conectividad de 8 vecinos."""
    pixel_ha = (TARGET_RESOLUTION_M * TARGET_RESOLUTION_M) / 10_000.0
    min_pixels = int(np.ceil(PATCH_MIN_AREA_HA / pixel_ha))

    core_mask = h >= PATCH_SUITABILITY_THRESHOLD
    raw_labels = label(core_mask, connectivity=2)
    counts = np.bincount(raw_labels.ravel())

    # Filtrar etiquetas >= min_pixels (ignorando fondo 0) y ordenar de mayor a menor área
    valid_raw = [int(lbl) for lbl in range(1, len(counts)) if counts[lbl] >= min_pixels]
    valid_raw.sort(key=lambda lbl: counts[lbl], reverse=True)

    nrows, ncols = h.shape
    labeled_clean = np.zeros_like(raw_labels, dtype=np.int32)
    for new_idx, old_lbl in enumerate(valid_raw, start=1):
        labeled_clean[raw_labels == old_lbl] = new_idx

    # Guardar ráster de etiquetas para Vista 3
    lbl_prof = profile.copy()
    lbl_prof.update(dtype="int32", nodata=0, compress="lzw")
    with rasterio.open(DATA_PROCESSED_DIR / "parches_labeled_30m.tif", "w", **lbl_prof) as dst:
        dst.write(labeled_clean, 1)

    # Vectorizar polígonos por etiqueta
    geoms_by_id: dict[int, list] = {i: [] for i in range(1, len(valid_raw) + 1)}
    for geom_dict, val in shapes(labeled_clean, mask=(labeled_clean > 0), transform=profile["transform"]):
        geoms_by_id[int(val)].append(shape(geom_dict))

    to_wgs = Transformer.from_crs(TARGET_CRS, "EPSG:4326", always_xy=True)
    records = []
    for idx in range(1, len(valid_raw) + 1):
        mask = labeled_clean == idx
        n_px = int(np.sum(mask))
        area_ha = round(n_px * pixel_ha, 2)
        geom = unary_union(geoms_by_id[idx])

        rows_i, cols_i = np.where(mask)
        toca_borde = bool(
            (rows_i.min() == 0)
            or (rows_i.max() == nrows - 1)
            or (cols_i.min() == 0)
            or (cols_i.max() == ncols - 1)
        )

        # Cobertura dominante dentro del parche
        lc_vals, lc_cnts = np.unique(lc21[mask], return_counts=True)
        dom_code = int(lc_vals[np.argmax(lc_cnts)])
        dom_name = ESA_WORLDCOVER_CLASSES.get(dom_code, str(dom_code))

        # Punto representativo interior (para etiquetas) y centroide
        rep_pt = geom.representative_point()
        lon, lat = to_wgs.transform(rep_pt.x, rep_pt.y)

        records.append(
            {
                "patch_num": idx,
                "patch_id": f"P{idx:02d}",
                "area_ha": area_ha,
                "pixels": n_px,
                "mean_hsm": round(float(np.mean(h[mask])), 3),
                "max_hsm": round(float(np.max(h[mask])), 3),
                "dominant_lc": dom_name,
                "toca_borde": toca_borde,
                "rep_lon": round(float(lon), 6),
                "rep_lat": round(float(lat), 6),
                "geometry": geom,
            }
        )

    gdf_utm = gpd.GeoDataFrame(records, crs=TARGET_CRS)
    gdf_utm.to_file(DATA_PROCESSED_DIR / "parches_utm16n.gpkg", driver="GPKG")
    gdf_utm.to_crs("EPSG:4326").to_file(OUTPUTS_DIR / "parches.geojson", driver="GeoJSON")
    print(f"  [OK] Extraídos {len(gdf_utm)} parches núcleo (H ≥ {PATCH_SUITABILITY_THRESHOLD}, ≥ {PATCH_MIN_AREA_HA} ha).")
    return gdf_utm, labeled_clean


def build_resistance_surface(h: np.ndarray, lc21: np.ndarray, roads: np.ndarray, profile: dict) -> np.ndarray:
    """Construye la superficie de resistencia híbrida 50/50 en escala [1, 100]."""
    table_cost = np.full_like(h, 40.0, dtype=np.float32)
    for code, cost in LANDCOVER_RESISTANCE.items():
        table_cost[lc21 == code] = float(cost)

    # Superponer costo de vías (prevalece el mayor costo si la vía cruza zona urbana/agua)
    for tier, rcost in ROAD_RESISTANCE.items():
        mask = roads == tier
        table_cost[mask] = np.maximum(table_cost[mask], float(rcost))

    hsm_cost = (1.0 + 99.0 * (1.0 - np.clip(h, 0.0, 1.0))).astype(np.float32)
    resistance = (
        RESISTANCE_TABLE_WEIGHT * table_cost + RESISTANCE_HSM_WEIGHT * hsm_cost
    ).astype(np.float32)
    resistance = np.clip(resistance, 1.0, 100.0)

    prof = profile.copy()
    prof.update(dtype="float32", nodata=-9999.0, compress="lzw")
    with rasterio.open(OUTPUTS_DIR / "resistencia.tif", "w", **prof) as dst:
        dst.write(resistance, 1)

    print(
        f"  [OK] Superficie de resistencia guardada (min={resistance.min():.1f}, "
        f"mediana={np.median(resistance):.1f}, max={resistance.max():.1f})."
    )
    return resistance


def compute_corridors(
    patches_utm: gpd.GeoDataFrame,
    labeled: np.ndarray,
    resistance: np.ndarray,
    lc21: np.ndarray,
    profile: dict,
) -> tuple[gpd.GeoDataFrame, np.ndarray]:
    """Calcula corredores de menor costo (MST + 2 vecinos más cercanos) y franja estilo Linkage Mapper."""
    n_patches = len(patches_utm)
    if n_patches < 2:
        raise RuntimeError("Se necesitan al menos 2 parches para calcular corredores.")

    print(f"  Ejecutando Dijkstra geométrico (MCP_Geometric) desde los {n_patches} parches...")
    # Precalcular píxeles de cada parche
    patch_pixels: dict[int, np.ndarray] = {}
    for idx in range(1, n_patches + 1):
        rr, cc = np.where(labeled == idx)
        patch_pixels[idx] = np.column_stack([rr, cc])

    # Ejecutar MCP desde cada parche (borde interior completo) -> costos acumulados y tracebacks
    cum_costs: dict[int, np.ndarray] = {}
    mcps: dict[int, MCP_Geometric] = {}
    cost_matrix = np.full((n_patches, n_patches), np.inf, dtype=np.float64)
    best_target_px: dict[tuple[int, int], tuple[int, int]] = {}

    for i in range(1, n_patches + 1):
        mcp = MCP_Geometric(
            resistance,
            sampling=(TARGET_RESOLUTION_M, TARGET_RESOLUTION_M),
            fully_connected=True,
        )
        costs_i, _ = mcp.find_costs(starts=patch_pixels[i])
        cum_costs[i] = costs_i.astype(np.float32)
        mcps[i] = mcp

        for j in range(1, n_patches + 1):
            if i == j:
                cost_matrix[i - 1, j - 1] = 0.0
                continue
            pts_j = patch_pixels[j]
            vals_j = costs_i[pts_j[:, 0], pts_j[:, 1]]
            k_min = int(np.argmin(vals_j))
            cost_matrix[i - 1, j - 1] = float(vals_j[k_min])
            best_target_px[(i, j)] = (int(pts_j[k_min, 0]), int(pts_j[k_min, 1]))

    # Simetrizar ligeramente por precisión flotante
    sym_cost = 0.5 * (cost_matrix + cost_matrix.T)

    # Grafo completo para MST + 2 vecinos más cercanos por parche
    G = nx.Graph()
    for i in range(1, n_patches + 1):
        G.add_node(i)
    for i in range(1, n_patches + 1):
        for j in range(i + 1, n_patches + 1):
            G.add_edge(i, j, weight=float(sym_cost[i - 1, j - 1]))

    mst = nx.minimum_spanning_tree(G, weight="weight")
    mst_pairs = {(min(u, v), max(u, v)) for u, v in mst.edges()}

    selected_pairs = set(mst_pairs)
    for i in range(1, n_patches + 1):
        neighbors = sorted(
            [(sym_cost[i - 1, j - 1], j) for j in range(1, n_patches + 1) if j != i],
            key=lambda x: x[0],
        )
        for _, nb in neighbors[:2]:
            selected_pairs.add((min(i, nb), max(i, nb)))

    selected_pairs_sorted = sorted(selected_pairs, key=lambda pair: sym_cost[pair[0] - 1, pair[1] - 1])
    print(
        f"  Pares seleccionados: {len(selected_pairs_sorted)} corredores "
        f"({len(mst_pairs)} del MST + {len(selected_pairs_sorted) - len(mst_pairs)} enlaces redundantes 2-NN)."
    )

    transform = profile["transform"]
    corridor_records = []
    swath_intensity = np.zeros_like(resistance, dtype=np.float32)

    for c_idx, (i, j) in enumerate(selected_pairs_sorted, start=1):
        target_rc = best_target_px[(i, j)]
        path_rc = mcps[i].traceback(target_rc)

        # Convertir píxeles (row, col) -> coordenadas UTM (x, y) del centro de cada píxel
        coords_utm = [rasterio.transform.xy(transform, r, c, offset="center") for r, c in path_rc]
        if len(coords_utm) < 2:
            continue

        line = LineString(coords_utm)
        length_m = float(line.length)
        cwd = float(sym_cost[i - 1, j - 1])
        mean_res = cwd / max(length_m, 1.0)

        # Franja de corredor estilo Linkage Mapper: CD_i + CD_j - min_cost
        # Recorte adaptable para mostrar claramente el ancho útil del corredor
        corridor_excess = (cum_costs[i] + cum_costs[j]) - float(cost_matrix[i - 1, j - 1])
        corridor_excess = np.maximum(corridor_excess, 0.0)
        cutoff = max(0.20 * cwd, 12_000.0)  # costo adicional tolerado (~120-400 m en selva o 20% del costo del tramo)
        pair_intensity = np.clip(1.0 - (corridor_excess / cutoff), 0.0, 1.0).astype(np.float32)
        swath_intensity = np.maximum(swath_intensity, pair_intensity)

        corridor_records.append(
            {
                "corridor_id": f"C{c_idx:02d}",
                "from_patch": f"P{i:02d}",
                "to_patch": f"P{j:02d}",
                "in_mst": (i, j) in mst_pairs,
                "length_m": round(length_m, 1),
                "length_km": round(length_m / 1000.0, 2),
                "cost_weighted_dist": round(cwd, 1),
                "mean_resistance": round(mean_res, 2),
                "geometry": line,
            }
        )

    # Enmascarar franja dentro de los parches núcleo y en agua permanente para limpieza visual
    swath_intensity[(labeled > 0) | (lc21 == 80)] = 0.0

    swath_prof = profile.copy()
    swath_prof.update(dtype="float32", nodata=0.0, compress="lzw")
    with rasterio.open(OUTPUTS_DIR / "corredores_franja.tif", "w", **swath_prof) as dst:
        dst.write(swath_intensity, 1)

    corridors_utm = gpd.GeoDataFrame(corridor_records, crs=TARGET_CRS)
    corridors_utm.to_file(DATA_PROCESSED_DIR / "corredores_utm16n.gpkg", driver="GPKG")
    corridors_utm.to_crs("EPSG:4326").to_file(OUTPUTS_DIR / "corredores.geojson", driver="GeoJSON")
    print(f"  [OK] Guardados {len(corridors_utm)} corredores en corredores.geojson y corredores_franja.tif.")
    return corridors_utm, swath_intensity


def plot_landmarks(ax, transformer: Transformer) -> None:
    for name, (lat, lon) in LANDMARKS.items():
        x, y = transformer.transform(lon, lat)
        ax.scatter(x, y, c="white", edgecolors="black", s=40, zorder=9, linewidth=1.1)
        ax.annotate(
            name,
            (x, y),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=8,
            fontweight="bold",
            color="black",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="black", alpha=0.85),
            zorder=10,
        )


def generate_preview(
    patches_utm: gpd.GeoDataFrame,
    corridors_utm: gpd.GeoDataFrame,
    resistance: np.ndarray,
    swath: np.ndarray,
    lc21: np.ndarray,
    bounds,
) -> Path:
    extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    roads = gpd.read_file(DATA_PROCESSED_DIR / "roads_utm16n.gpkg")
    roads_major = roads[roads["road_tier"] == 3]
    gbif = gpd.read_file(DATA_PROCESSED_DIR / "gbif_jaguar_pilot_utm16n.geojson")

    fig = plt.figure(figsize=(19, 10.5), dpi=150)
    gs = gridspec.GridSpec(1, 2, width_ratios=[1.0, 1.25], wspace=0.32)
    fig.suptitle(
        "BioConecta — Vista 2: Conectividad Ecológica para Jaguar (Panthera onca)\n"
        f"Parches núcleo (H ≥ {PATCH_SUITABILITY_THRESHOLD}, ≥ {PATCH_MIN_AREA_HA:.0f} ha) | "
        "Resistencia híbrida 50/50 | Corredores MST + 2 vecinos",
        fontsize=13.5,
        fontweight="bold",
        y=0.98,
    )

    # Panel izquierdo: Superficie de resistencia híbrida
    ax1 = fig.add_subplot(gs[0, 0])
    im1 = ax1.imshow(resistance, cmap=RES_CMAP, vmin=1, vmax=100, extent=extent, origin="upper")
    roads_major.plot(ax=ax1, color="#111111", linewidth=0.9, alpha=0.65)
    plot_landmarks(ax1, transformer)
    ax1.set_xlim(bounds.left, bounds.right)
    ax1.set_ylim(bounds.bottom, bounds.top)
    ax1.set_title("1. Superficie de Resistencia Híbrida (1 = fácil, 100 = barrera)", fontweight="bold", fontsize=10.5)
    ax1.set_xlabel("Este UTM 16N (m)")
    ax1.set_ylabel("Norte UTM 16N (m)")
    cbar1 = fig.colorbar(im1, ax=ax1, fraction=0.04, pad=0.02)
    cbar1.set_label("Costo de desplazamiento (1–100)")

    # Panel derecho: Parches + Franja de corredor + Líneas de menor costo
    ax2 = fig.add_subplot(gs[0, 1])
    # Fondo suave: agua azul pálido, urbano gris oscuro, matriz gris-verde claro
    bg = np.full((lc21.shape[0], lc21.shape[1], 3), (235, 240, 232), dtype=np.uint8)
    bg[lc21 == 80] = (186, 220, 242)
    bg[lc21 == 50] = (95, 95, 95)
    ax2.imshow(bg, extent=extent, origin="upper")

    # Franja de corredor
    swath_masked = np.ma.masked_where(swath <= 0.02, swath)
    im_sw = ax2.imshow(swath_masked, cmap=SWATH_CMAP, vmin=0, vmax=1, extent=extent, origin="upper", zorder=3)

    # Parches núcleo
    patches_utm.plot(
        ax=ax2,
        facecolor="#1b7837",
        edgecolor="#00441b",
        linewidth=1.1,
        alpha=0.82,
        zorder=4,
    )

    # Corredores (MST sólidos y redundantes punteados)
    cor_extra = corridors_utm[~corridors_utm["in_mst"]]
    cor_mst = corridors_utm[corridors_utm["in_mst"]]
    if len(cor_extra) > 0:
        cor_extra.plot(
            ax=ax2, color="#ff6f00", linewidth=1.6, linestyle="--", alpha=0.85, zorder=5, label="Corredor alterno (2-NN)"
        )
    if len(cor_mst) > 0:
        cor_mst.plot(
            ax=ax2, color="#b71c1c", linewidth=2.3, alpha=0.95, zorder=6, label="Corredor troncal (MST)"
        )

    roads_major.plot(ax=ax2, color="#222222", linewidth=0.8, alpha=0.45, zorder=5, label="Av./Carretera (Tier 3)")

    if len(gbif) > 0:
        gbif.plot(
            ax=ax2, color="#FFD700", edgecolor="black", marker="*", markersize=220, zorder=8, label="Jaguar GBIF"
        )

    # Etiquetar parches más importantes (todos si <= 20, o top 15 por área)
    for _, row in patches_utm.head(20).iterrows():
        pt = row.geometry.representative_point()
        tag = f"{row['patch_id']}\n({row['area_ha']:.0f} ha)" if row["area_ha"] >= 50 else row["patch_id"]
        ax2.annotate(
            tag,
            (pt.x, pt.y),
            ha="center",
            va="center",
            fontsize=7.2 if row["area_ha"] >= 50 else 6.5,
            fontweight="bold",
            color="white",
            bbox=dict(boxstyle="round,pad=0.15", fc="#00441b", ec="white", alpha=0.82, lw=0.6),
            zorder=7,
        )

    plot_landmarks(ax2, transformer)
    ax2.set_xlim(bounds.left, bounds.right)
    ax2.set_ylim(bounds.bottom, bounds.top)
    ax2.set_title(
        f"2. Parches Núcleo ({len(patches_utm)}) + Corredores ({len(corridors_utm)}) + Franja Linkage Mapper",
        fontweight="bold",
        fontsize=10.5,
    )
    ax2.set_xlabel("Este UTM 16N (m)")
    ax2.set_ylabel("Norte UTM 16N (m)")
    ax2.legend(loc="upper left", fontsize=8.5, framealpha=0.92)
    cbar2 = fig.colorbar(im_sw, ax=ax2, fraction=0.038, pad=0.02)
    cbar2.set_label("Intensidad de franja de corredor (0–1)")

    out_png = OUTPUTS_DIR / "preview_vista2.png"
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] Vista previa guardada en {out_png}")
    return out_png


def generate_interactive_map() -> Path:
    """Genera mapa interactivo Folium para la Vista 2."""
    # Reproyectar franja de corredor a WGS84 para overlay
    with rasterio.open(OUTPUTS_DIR / "corredores_franja.tif") as src:
        dst_crs = "EPSG:4326"
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        sw_wgs = np.zeros((height, width), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=sw_wgs,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.bilinear,
        )
        bounds = rasterio.transform.array_bounds(height, width, transform)
        folium_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]

    rgba = (SWATH_CMAP(np.clip(sw_wgs, 0.0, 1.0)) * 255).astype(np.uint8)
    rgba[sw_wgs <= 0.02, 3] = 0
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    uri_swath = f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"

    m = folium.Map(location=[21.28, -86.88], zoom_start=12, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri WorldImagery",
        name="Satélite (Esri)",
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)

    folium.raster_layers.ImageOverlay(
        image=uri_swath, bounds=folium_bounds, opacity=0.78, name="Franja de corredores (Linkage Mapper)", show=True
    ).add_to(m)

    patches = gpd.read_file(OUTPUTS_DIR / "parches.geojson")
    folium.GeoJson(
        patches,
        name="Parches de hábitat núcleo (H ≥ 0.70)",
        style_function=lambda _: {
            "fillColor": "#1b7837",
            "color": "#00441b",
            "weight": 1.8,
            "fillOpacity": 0.58,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["patch_id", "area_ha", "mean_hsm", "dominant_lc", "toca_borde"],
            aliases=["Parche:", "Área (ha):", "Idoneidad media:", "Cobertura:", "Toca borde:"],
        ),
        show=True,
    ).add_to(m)

    corridors = gpd.read_file(OUTPUTS_DIR / "corredores.geojson")
    folium.GeoJson(
        corridors,
        name="Corredores de menor costo (rutas)",
        style_function=lambda feat: {
            "color": "#d50000" if feat["properties"].get("in_mst") else "#ff9100",
            "weight": 3.2 if feat["properties"].get("in_mst") else 2.0,
            "dashArray": None if feat["properties"].get("in_mst") else "6 4",
            "opacity": 0.95,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=["corridor_id", "from_patch", "to_patch", "length_km", "mean_resistance", "in_mst"],
            aliases=["Corredor:", "Desde:", "Hacia:", "Longitud (km):", "Resistencia media:", "Troncal (MST):"],
        ),
        show=True,
    ).add_to(m)

    roads = gpd.read_file(DATA_PROCESSED_DIR / "roads_utm16n.gpkg").to_crs("EPSG:4326")
    folium.GeoJson(
        roads[roads["road_tier"] == 3][["name", "highway", "geometry"]],
        name="Avenidas / Carreteras (Tier 3)",
        style_function=lambda _: {"color": "#111111", "weight": 2.0, "opacity": 0.75},
        show=False,
    ).add_to(m)

    gbif = gpd.read_file(DATA_PROCESSED_DIR / "gbif_jaguar_pilot_utm16n.geojson").to_crs("EPSG:4326")
    gg = folium.FeatureGroup(name="Avistamientos Jaguar (GBIF piloto)", show=True)
    for _, row in gbif.iterrows():
        folium.Marker(
            location=[row.geometry.y, row.geometry.x],
            popup=f"<b>Panthera onca (GBIF)</b><br>Año: {row.get('year', 'N/D')}",
            icon=folium.Icon(color="orange", icon="paw", prefix="fa"),
        ).add_to(gg)
    gg.add_to(m)

    lm = folium.FeatureGroup(name="Puntos de referencia", show=True)
    for name, (lat, lon) in LANDMARKS.items():
        folium.CircleMarker(
            location=[lat, lon], radius=6, color="#000", fill=True, fill_color="#fff", fill_opacity=1.0, tooltip=name
        ).add_to(lm)
    lm.add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)
    out_html = OUTPUTS_DIR / "mapa_vista2.html"
    m.save(str(out_html))
    print(f"  [OK] Mapa interactivo guardado en {out_html}")
    return out_html


def print_summary(patches_utm: gpd.GeoDataFrame, corridors_utm: gpd.GeoDataFrame) -> None:
    print("\n" + "=" * 78)
    print("RESUMEN — VISTA 2: CONECTIVIDAD ECOLÓGICA (PARCHES Y CORREDORES)")
    print("=" * 78)
    print(f"Total parches núcleo (≥ {PATCH_MIN_AREA_HA:.0f} ha) : {len(patches_utm)}")
    print(f"Superficie total en parches       : {patches_utm['area_ha'].sum():,.1f} ha")
    print(f"Parches que tocan el borde AOI    : {int(patches_utm['toca_borde'].sum())}")
    print("\nTop parches por superficie:")
    print(f"  {'ID':<5} {'Área (ha)':>10} {'H medio':>8} {'Borde':>6}  {'Cobertura dominante'}")
    print("  " + "-" * 68)
    for _, r in patches_utm.head(12).iterrows():
        b_txt = "Sí" if r["toca_borde"] else "No"
        print(f"  {r['patch_id']:<5} {r['area_ha']:>10,.1f} {r['mean_hsm']:>8.3f} {b_txt:>6}  {r['dominant_lc']}")

    print(f"\nCorredores generados              : {len(corridors_utm)} (MST: {int(corridors_utm['in_mst'].sum())})")
    print(f"Longitud media de corredor        : {corridors_utm['length_km'].mean():.2f} km")
    print(f"Resistencia media en corredores   : {corridors_utm['mean_resistance'].mean():.1f} / 100")
    print("\nPrimeros corredores (ordenados por menor costo):")
    print(f"  {'ID':<5} {'Par':<11} {'MST':>4} {'Long (km)':>10} {'Res. media':>11} {'Costo acum.':>13}")
    print("  " + "-" * 62)
    for _, r in corridors_utm.head(10).iterrows():
        m_txt = "Sí" if r["in_mst"] else "No"
        print(
            f"  {r['corridor_id']:<5} {r['from_patch']}↔{r['to_patch']:<5} {m_txt:>4} "
            f"{r['length_km']:>10.2f} {r['mean_resistance']:>11.1f} {r['cost_weighted_dist']:>13,.0f}"
        )
    print("=" * 78)


def main() -> None:
    print("Calculando Vista 2: Conectividad Ecológica...")
    with rasterio.open(OUTPUTS_DIR / "idoneidad.tif") as src_h:
        h = src_h.read(1)
        profile = src_h.profile.copy()
        bounds = src_h.bounds
    with rasterio.open(DATA_PROCESSED_DIR / "landcover_2021_30m.tif") as src_lc:
        lc21 = src_lc.read(1)
    with rasterio.open(DATA_PROCESSED_DIR / "roads_30m.tif") as src_r:
        roads = src_r.read(1)

    patches_utm, labeled = extract_patches(h, lc21, profile)
    resistance = build_resistance_surface(h, lc21, roads, profile)
    corridors_utm, swath = compute_corridors(patches_utm, labeled, resistance, lc21, profile)
    generate_preview(patches_utm, corridors_utm, resistance, swath, lc21, bounds)
    generate_interactive_map()
    print_summary(patches_utm, corridors_utm)


if __name__ == "__main__":
    main()

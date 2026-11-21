"""
Visualizador de las capas base del Paso 0 (sin necesidad de QGIS).

Genera:
1. outputs/preview_paso0.png  -> Panel estático 2x2 de alta resolución con todas las capas.
2. outputs/mapa_paso0.html    -> Mapa web interactivo (Folium) con selector de capas y zoom.
"""

import base64
import io
import sys
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from PIL import Image
from pyproj import Transformer
from rasterio.warp import Resampling, calculate_default_transform, reproject

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATA_PROCESSED_DIR, LANDMARKS, PROJECT_ROOT, TARGET_CRS

OUTPUTS_DIR = PROJECT_ROOT / "outputs"

# Paleta oficial (RGBA 0-255) para clases ESA WorldCover
WC_COLORS = {
    10: (0, 100, 0, 255),        # Selva / Cobertura arbórea
    20: (255, 187, 34, 255),     # Matorral
    30: (255, 255, 76, 255),     # Pastizal
    40: (240, 150, 255, 255),    # Cultivos
    50: (250, 0, 0, 255),        # Zona urbana / Construida
    60: (180, 180, 180, 255),    # Suelo desnudo
    80: (0, 100, 200, 255),      # Agua permanente
    90: (0, 150, 160, 255),      # Humedal herbáceo
    95: (0, 207, 117, 255),      # Manglar
}

WC_LEGEND = [
    (10, "Selva / Árboles"),
    (95, "Manglar"),
    (90, "Humedal"),
    (30, "Pastizal"),
    (20, "Matorral"),
    (50, "Zona urbana"),
    (60, "Suelo desnudo"),
    (80, "Agua"),
]


def colorize_landcover(arr: np.ndarray) -> np.ndarray:
    rgba = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
    for code, color in WC_COLORS.items():
        mask = arr == code
        rgba[mask] = color
    return rgba


def raster_to_wgs84_rgba(src_path: Path, colorizer) -> tuple[str, list[list[float]]]:
    """Reproyecta un ráster categórico a WGS84 y devuelve data URI PNG + bounds para Folium."""
    with rasterio.open(src_path) as src:
        dst_crs = "EPSG:4326"
        transform, width, height = calculate_default_transform(
            src.crs, dst_crs, src.width, src.height, *src.bounds
        )
        dst_arr = np.zeros((height, width), dtype=src.dtypes[0])
        reproject(
            source=rasterio.band(src, 1),
            destination=dst_arr,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
        )
        bounds = rasterio.transform.array_bounds(height, width, transform)
        # bounds = (west, south, east, north) -> Folium usa [[south, west], [north, east]]
        folium_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]

    rgba = colorizer(dst_arr)
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}", folium_bounds


def plot_landmarks(ax, transformer: Transformer) -> None:
    for name, (lat, lon) in LANDMARKS.items():
        x, y = transformer.transform(lon, lat)
        ax.scatter(x, y, c="white", edgecolors="black", s=45, zorder=6, linewidth=1.2)
        ax.annotate(
            name,
            (x, y),
            xytext=(5, 5),
            textcoords="offset points",
            fontsize=8,
            fontweight="bold",
            color="black",
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="black", alpha=0.82),
            zorder=7,
        )


def generate_static_preview() -> Path:
    with rasterio.open(DATA_PROCESSED_DIR / "landcover_2020_30m.tif") as src20:
        lc20 = src20.read(1)
        bounds = src20.bounds
    with rasterio.open(DATA_PROCESSED_DIR / "landcover_2021_30m.tif") as src21:
        lc21 = src21.read(1)
    with rasterio.open(DATA_PROCESSED_DIR / "urban_2021_30m.tif") as src_u:
        urb21 = src_u.read(1)

    roads = gpd.read_file(DATA_PROCESSED_DIR / "roads_utm16n.gpkg")
    gbif_pilot = gpd.read_file(DATA_PROCESSED_DIR / "gbif_jaguar_pilot_utm16n.geojson")

    extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)

    fig, axes = plt.subplots(2, 2, figsize=(15, 14), dpi=150)
    fig.suptitle(
        "BioConecta — Paso 0: Capas Base Alineadas (UTM 16N, 30×30 m)\n"
        "Zona Piloto: UNICARIBE – Rancho Viejo – Zona Continental de Isla Mujeres",
        fontsize=14,
        fontweight="bold",
        y=0.98,
    )

    # Panel 1: Cobertura 2020
    ax = axes[0, 0]
    ax.imshow(colorize_landcover(lc20), extent=extent, origin="upper")
    plot_landmarks(ax, transformer)
    ax.set_title("1. Cobertura Vegetal 2020 (ESA WorldCover)", fontweight="bold")
    ax.set_xlabel("Este UTM 16N (m)")
    ax.set_ylabel("Norte UTM 16N (m)")

    # Panel 2: Cobertura 2021
    ax = axes[0, 1]
    ax.imshow(colorize_landcover(lc21), extent=extent, origin="upper")
    plot_landmarks(ax, transformer)
    ax.set_title("2. Cobertura Vegetal 2021 (ESA WorldCover)", fontweight="bold")
    ax.set_xlabel("Este UTM 16N (m)")
    ax.set_ylabel("Norte UTM 16N (m)")

    # Panel 3: Mancha Urbana + Red Vial
    ax = axes[1, 0]
    base_rgba = colorize_landcover(lc21).astype(np.float32)
    base_rgba[..., :3] = base_rgba[..., :3] * 0.45 + 255 * 0.55  # aclarar fondo
    ax.imshow(base_rgba.astype(np.uint8), extent=extent, origin="upper")

    # Resaltar mancha urbana 2021
    urb_overlay = np.zeros((urb21.shape[0], urb21.shape[1], 4), dtype=np.uint8)
    urb_overlay[urb21 == 1] = (220, 20, 20, 210)
    ax.imshow(urb_overlay, extent=extent, origin="upper")

    roads[roads["road_tier"] == 1].plot(ax=ax, color="#8B4513", linewidth=0.6, alpha=0.8, label="Terracería (Tier 1)")
    roads[roads["road_tier"] == 2].plot(ax=ax, color="#444444", linewidth=0.45, alpha=0.7, label="Calle local (Tier 2)")
    roads[roads["road_tier"] == 3].plot(ax=ax, color="#111111", linewidth=1.3, alpha=0.95, label="Av./Carretera (Tier 3)")
    plot_landmarks(ax, transformer)
    ax.set_xlim(bounds.left, bounds.right)
    ax.set_ylim(bounds.bottom, bounds.top)
    ax.set_title("3. Mancha Urbana (2021) + Red Vial Clasificada (OSM)", fontweight="bold")
    ax.set_xlabel("Este UTM 16N (m)")
    ax.set_ylabel("Norte UTM 16N (m)")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.9)

    # Panel 4: Cambios 2020 -> 2021 + GBIF Jaguar
    ax = axes[1, 1]
    ax.imshow(base_rgba.astype(np.uint8), extent=extent, origin="upper")

    change_rgba = np.zeros((lc20.shape[0], lc20.shape[1], 4), dtype=np.uint8)
    new_urban = (lc20 != 50) & (lc21 == 50)
    veg_loss = np.isin(lc20, [10, 95, 90]) & ~np.isin(lc21, [10, 95, 90]) & ~new_urban
    change_rgba[veg_loss] = (255, 140, 0, 230)    # Naranja: pérdida de selva/manglar/humedal
    change_rgba[new_urban] = (220, 0, 60, 255)    # Rojo intenso: nueva mancha urbana
    ax.imshow(change_rgba, extent=extent, origin="upper")

    if len(gbif_pilot) > 0:
        gbif_pilot.plot(
            ax=ax,
            color="#FFD700",
            edgecolor="black",
            marker="*",
            markersize=220,
            zorder=8,
            label=f"Jaguar GBIF ({len(gbif_pilot)} registros)",
        )
    plot_landmarks(ax, transformer)
    ax.set_xlim(bounds.left, bounds.right)
    ax.set_ylim(bounds.bottom, bounds.top)
    ax.set_title("4. Cambios 2020→2021 + Avistamientos Jaguar (GBIF)", fontweight="bold")
    ax.set_xlabel("Este UTM 16N (m)")
    ax.set_ylabel("Norte UTM 16N (m)")

    change_handles = [
        mpatches.Patch(color=(220 / 255, 0, 60 / 255), label="Expansión urbana (2020→2021)"),
        mpatches.Patch(color=(1.0, 140 / 255, 0), label="Pérdida selva/manglar/humedal"),
        plt.Line2D([0], [0], marker="*", color="w", markerfacecolor="#FFD700", markeredgecolor="black", markersize=12, label="Jaguar GBIF (validación)"),
    ]
    ax.legend(handles=change_handles, loc="upper left", fontsize=8, framealpha=0.9)

    # Leyenda general de cobertura vegetal al pie
    lc_handles = [
        mpatches.Patch(color=tuple(c / 255 for c in WC_COLORS[code][:3]), label=label)
        for code, label in WC_LEGEND
    ]
    fig.legend(
        handles=lc_handles,
        loc="lower center",
        ncol=len(WC_LEGEND),
        fontsize=9,
        frameon=True,
        bbox_to_anchor=(0.5, 0.01),
    )

    plt.tight_layout(rect=[0, 0.045, 1, 0.94])
    out_png = OUTPUTS_DIR / "preview_paso0.png"
    fig.savefig(out_png, dpi=150)
    plt.close(fig)
    print(f"  [OK] Imagen estática guardada en {out_png}")
    return out_png


def generate_interactive_map() -> Path:
    m = folium.Map(location=[21.28, -86.88], zoom_start=12, tiles=None)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri WorldImagery",
        name="Satélite (Esri)",
    ).add_to(m)

    # Overlays ráster
    uri_21, b21 = raster_to_wgs84_rgba(DATA_PROCESSED_DIR / "landcover_2021_30m.tif", colorize_landcover)
    folium.raster_layers.ImageOverlay(
        image=uri_21, bounds=b21, opacity=0.62, name="Cobertura vegetal 2021 (ESA)", show=True
    ).add_to(m)

    uri_20, b20 = raster_to_wgs84_rgba(DATA_PROCESSED_DIR / "landcover_2020_30m.tif", colorize_landcover)
    folium.raster_layers.ImageOverlay(
        image=uri_20, bounds=b20, opacity=0.62, name="Cobertura vegetal 2020 (ESA)", show=False
    ).add_to(m)

    def colorize_urban(arr: np.ndarray) -> np.ndarray:
        rgba = np.zeros((arr.shape[0], arr.shape[1], 4), dtype=np.uint8)
        rgba[arr == 1] = (225, 20, 20, 210)
        return rgba

    uri_urb, burb = raster_to_wgs84_rgba(DATA_PROCESSED_DIR / "urban_2021_30m.tif", colorize_urban)
    folium.raster_layers.ImageOverlay(
        image=uri_urb, bounds=burb, opacity=0.75, name="Mancha urbana 2021", show=False
    ).add_to(m)

    # Recuadro AOI
    aoi = gpd.read_file(DATA_PROCESSED_DIR / "aoi_wgs84.geojson")
    folium.GeoJson(
        aoi,
        name="Límite zona piloto (AOI)",
        style_function=lambda _: {"fill": False, "color": "#111111", "weight": 2.5, "dashArray": "6 4"},
    ).add_to(m)

    # Red vial (avenidas principales y terracerías para mantener ágil el navegador)
    roads = gpd.read_file(DATA_PROCESSED_DIR / "roads_utm16n.gpkg").to_crs("EPSG:4326")
    roads_major = roads[roads["road_tier"] == 3][["name", "highway", "geometry"]]
    roads_track = roads[roads["road_tier"] == 1][["name", "highway", "geometry"]]

    folium.GeoJson(
        roads_major,
        name="Red vial: Avenidas / Carreteras (Tier 3)",
        style_function=lambda _: {"color": "#111111", "weight": 2.2, "opacity": 0.9},
        tooltip=folium.GeoJsonTooltip(fields=["name", "highway"], aliases=["Nombre:", "Tipo:"]),
        show=True,
    ).add_to(m)

    folium.GeoJson(
        roads_track,
        name="Red vial: Terracerías / Brechas (Tier 1)",
        style_function=lambda _: {"color": "#8B4513", "weight": 1.4, "opacity": 0.85},
        show=False,
    ).add_to(m)

    # Avistamientos GBIF
    gbif_group = folium.FeatureGroup(name="Avistamientos Jaguar (GBIF)", show=True)
    gbif = gpd.read_file(DATA_PROCESSED_DIR / "gbif_jaguar_pilot_utm16n.geojson").to_crs("EPSG:4326")
    for _, row in gbif.iterrows():
        popup = (
            f"<b>Panthera onca (GBIF)</b><br>"
            f"Año: {row.get('year', 'N/D')}<br>"
            f"Localidad: {row.get('locality', 'N/D')}<br>"
            f"Tipo: {row.get('basis_of_record', 'N/D')}"
        )
        folium.Marker(
            location=[row.geometry.y, row.geometry.x],
            popup=folium.Popup(popup, max_width=260),
            icon=folium.Icon(color="orange", icon="paw", prefix="fa"),
        ).add_to(gbif_group)
    gbif_group.add_to(m)

    # Puntos de referencia
    lm_group = folium.FeatureGroup(name="Puntos de referencia", show=True)
    for name, (lat, lon) in LANDMARKS.items():
        folium.CircleMarker(
            location=[lat, lon],
            radius=6,
            color="#000000",
            fill=True,
            fill_color="#FFFFFF",
            fill_opacity=1.0,
            tooltip=name,
        ).add_to(lm_group)
    lm_group.add_to(m)

    # Leyenda flotante
    legend_items = "".join(
        f'<div style="display:flex;align-items:center;margin:3px 0;">'
        f'<span style="width:14px;height:14px;background:rgb{WC_COLORS[code][:3]};'
        f'display:inline-block;margin-right:6px;border:1px solid #444;"></span>{label}</div>'
        for code, label in WC_LEGEND
    )
    legend_html = f"""
    <div style="position:fixed;bottom:25px;left:25px;z-index:9999;background:rgba(255,255,255,0.92);
                padding:10px 12px;border-radius:8px;border:1px solid #999;font-family:sans-serif;font-size:12px;">
      <b>BioConecta — Cobertura (ESA)</b>
      {legend_items}
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl(collapsed=False).add_to(m)

    out_html = OUTPUTS_DIR / "mapa_paso0.html"
    m.save(str(out_html))
    print(f"  [OK] Mapa interactivo guardado en {out_html}")
    return out_html


def main() -> None:
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    print("Generando visualizaciones del Paso 0...")
    generate_static_preview()
    generate_interactive_map()


if __name__ == "__main__":
    main()

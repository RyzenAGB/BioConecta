"""
BioConecta — Aplicación Web Interactiva (Streamlit + Folium).

Ejecución local:
    ./.venv/bin/streamlit run app.py
"""

import base64
import io
import json
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import streamlit as st
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject
from streamlit_folium import st_folium

from config import DATA_PROCESSED_DIR, LANDMARKS, PROJECT_ROOT, TARGET_RESOLUTION_M
from species_rules import HSM_WEIGHTS, PATCH_SUITABILITY_THRESHOLD, SPECIES_PROFILE

OUTPUTS_DIR = PROJECT_ROOT / "outputs"

st.set_page_config(
    page_title="BioConecta — Hábitat y Conectividad del Jaguar",
    page_icon="🐆",
    layout="wide",
    initial_sidebar_state="expanded",
)

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
SWATH_CMAP = LinearSegmentedColormap.from_list(
    "bioconecta_swath",
    [(0.0, "#00000000"), (0.15, "#ffe57f66"), (0.5, "#ffab00bb"), (0.85, "#ff3d00e6"), (1.0, "#d500f9ff")],
)
LEVEL_COLORS = {"Bajo": "#2e7d32", "Moderado": "#f9a825", "Alto": "#c62828"}
LEVEL_BADGE = {"Bajo": "🟢 BAJO", "Moderado": "🟠 MODERADO", "Alto": "🔴 ALTO"}


def _array_to_png_uri(rgba: np.ndarray) -> str:
    img = Image.fromarray(rgba, mode="RGBA")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buf.getvalue()).decode('ascii')}"


@st.cache_data(show_spinner="Cargando capas geoespaciales...")
def load_hsm_layers():
    """Carga las 5 capas S_* en UTM (para métricas exactas) y reproyectadas a WGS84 (para sliders en vivo)."""
    factor_names = ["S_cob", "S_ndvi", "S_roads", "S_urban", "S_water"]
    utm_factors = {}
    with rasterio.open(DATA_PROCESSED_DIR / "landcover_2021_30m.tif") as src_ref:
        lc_utm = src_ref.read(1)
        src_crs = src_ref.crs
        src_transform = src_ref.transform
        src_w, src_h = src_ref.width, src_ref.height
        dst_transform, dst_w, dst_h = calculate_default_transform(
            src_crs, "EPSG:4326", src_w, src_h, *src_ref.bounds
        )
        bounds = rasterio.transform.array_bounds(dst_h, dst_w, dst_transform)
        folium_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]

    with rasterio.open(DATA_PROCESSED_DIR / "hard_zero_mask.tif") as src_m:
        hard_zero_utm = src_m.read(1) == 1

    wgs_factors = {}
    for name in factor_names:
        with rasterio.open(DATA_PROCESSED_DIR / f"{name}.tif") as src:
            arr_utm = src.read(1).astype(np.float32)
            utm_factors[name] = arr_utm
            arr_wgs = np.zeros((dst_h, dst_w), dtype=np.float32)
            reproject(
                source=arr_utm,
                destination=arr_wgs,
                src_transform=src_transform,
                src_crs=src_crs,
                dst_transform=dst_transform,
                dst_crs="EPSG:4326",
                resampling=Resampling.bilinear,
            )
            wgs_factors[name] = arr_wgs

    lc_wgs = np.zeros((dst_h, dst_w), dtype=np.uint8)
    reproject(
        source=lc_utm,
        destination=lc_wgs,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs="EPSG:4326",
        resampling=Resampling.nearest,
    )

    hard_zero_wgs = np.zeros((dst_h, dst_w), dtype=np.uint8)
    reproject(
        source=hard_zero_utm.astype(np.uint8),
        destination=hard_zero_wgs,
        src_transform=src_transform,
        src_crs=src_crs,
        dst_transform=dst_transform,
        dst_crs="EPSG:4326",
        resampling=Resampling.nearest,
    )

    return {
        "utm_factors": utm_factors,
        "wgs_factors": wgs_factors,
        "hard_zero_utm": hard_zero_utm,
        "hard_zero_wgs": hard_zero_wgs == 1,
        "lc_wgs": lc_wgs,
        "folium_bounds": folium_bounds,
    }


@st.cache_data(show_spinner="Cargando franja de corredores...")
def load_swath_overlay():
    with rasterio.open(OUTPUTS_DIR / "corredores_franja.tif") as src:
        dst_transform, dst_w, dst_h = calculate_default_transform(
            src.crs, "EPSG:4326", src.width, src.height, *src.bounds
        )
        sw_wgs = np.zeros((dst_h, dst_w), dtype=np.float32)
        reproject(
            source=rasterio.band(src, 1),
            destination=sw_wgs,
            src_transform=src.transform,
            src_crs=src.crs,
            dst_transform=dst_transform,
            dst_crs="EPSG:4326",
            resampling=Resampling.bilinear,
        )
        bounds = rasterio.transform.array_bounds(dst_h, dst_w, dst_transform)
        folium_bounds = [[bounds[1], bounds[0]], [bounds[3], bounds[2]]]

    rgba = (SWATH_CMAP(np.clip(sw_wgs, 0.0, 1.0)) * 255).astype(np.uint8)
    rgba[sw_wgs <= 0.02, 3] = 0
    return _array_to_png_uri(rgba), folium_bounds


@st.cache_data(show_spinner="Cargando vectores y alertas...")
def load_vector_layers():
    patches = gpd.read_file(OUTPUTS_DIR / "parches.geojson")
    corridors = gpd.read_file(OUTPUTS_DIR / "corredores.geojson")
    alerts = gpd.read_file(OUTPUTS_DIR / "alertas_parches.geojson")
    sightings_path = OUTPUTS_DIR / "avistamientos_jaguar_piloto.geojson"
    if sightings_path.exists():
        pilot_sightings = gpd.read_file(sightings_path)
    else:
        pilot_sightings = gpd.read_file(DATA_PROCESSED_DIR / "gbif_jaguar_pilot_utm16n.geojson").to_crs("EPSG:4326")
    roads = gpd.read_file(DATA_PROCESSED_DIR / "roads_utm16n.gpkg").to_crs("EPSG:4326")
    roads_major = roads[roads["road_tier"] == 3][["name", "highway", "geometry"]].copy()

    val_path = OUTPUTS_DIR / "validacion.json"
    validation = json.loads(val_path.read_text(encoding="utf-8")) if val_path.exists() else None
    val_pts_path = OUTPUTS_DIR / "validacion_registros.geojson"
    val_pts = gpd.read_file(val_pts_path) if val_pts_path.exists() else None

    return {
        "patches": patches,
        "corridors": corridors,
        "alerts": alerts,
        "pilot_sightings": pilot_sightings,
        "roads_major": roads_major,
        "validation": validation,
        "val_pts": val_pts,
    }


def make_base_map(basemap: str, center=(21.28, -86.88), zoom=12) -> folium.Map:
    m = folium.Map(location=list(center), zoom_start=zoom, tiles=None)
    if basemap == "Satélite (Esri)":
        folium.TileLayer(
            tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
            attr="Esri WorldImagery",
            name="Satélite (Esri)",
        ).add_to(m)
    else:
        folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)
    return m


def add_landmarks(m: folium.Map) -> None:
    fg = folium.FeatureGroup(name="Puntos de referencia", show=True)
    for name, (lat, lon) in LANDMARKS.items():
        folium.CircleMarker(
            location=[lat, lon],
            radius=5.5,
            color="#000000",
            fill=True,
            fill_color="#ffffff",
            fill_opacity=1.0,
            tooltip=name,
        ).add_to(fg)
    fg.add_to(m)


def add_jaguar_sightings(m: folium.Map, sightings: gpd.GeoDataFrame) -> None:
    """Agrega los registros oficiales y extraoficiales/prensa de jaguar con iconos diferenciados."""
    for _, r in sightings.iterrows():
        cat = str(r.get("categoria", "Oficial"))
        tipo_ev = str(r.get("tipo_evento", "Avistamiento"))
        es_oficial = bool(r.get("oficial", True))

        if "Atropellamiento" in cat or "Atropellamiento" in tipo_ev:
            color, icon = "darkred", "exclamation-triangle"
        elif es_oficial:
            color, icon = "orange", "paw"
        elif "Ciencia ciudadana" in cat:
            color, icon = "blue", "eye"
        else:
            color, icon = "purple", "video-camera"

        popup_html = (
            f"<div style='font-family:sans-serif;font-size:12px;width:270px;'>"
            f"<b>🐆 Panthera onca — {tipo_ev}</b><br>"
            f"<b>Categoría:</b> {cat}<br>"
            f"<b>Fecha:</b> {r.get('fecha', r.get('year', 'N/D'))}<br>"
            f"<b>Localidad:</b> {r.get('localidad', 'N/D')}<br>"
            f"<b>Fuente:</b> {r.get('fuente', 'GBIF')}<br>"
            f"<hr style='margin:4px 0;'>"
            f"{r.get('descripcion', '')}"
            f"</div>"
        )
        folium.Marker(
            location=[r.geometry.y, r.geometry.x],
            tooltip=f"{r.get('fecha', '')} · {r.get('localidad', 'Jaguar')} ({cat})",
            popup=folium.Popup(popup_html, max_width=290),
            icon=folium.Icon(color=color, icon=icon, prefix="fa"),
        ).add_to(m)


def _reset_weights():
    for k, v in HSM_WEIGHTS.items():
        st.session_state[f"w_{k}"] = float(v)


def main():
    hsm_data = load_hsm_layers()
    swath_uri, swath_bounds = load_swath_overlay()
    vecs = load_vector_layers()

    patches = vecs["patches"]
    corridors = vecs["corridors"]
    alerts = vecs["alerts"]
    validation = vecs["validation"]

    # --- BARRA LATERAL ---
    with st.sidebar:
        st.title("🐆 BioConecta")
        st.caption("UNICARIBE – Rancho Viejo – Zona Continental de Isla Mujeres (Q. Roo)")
        st.divider()

        basemap = st.radio("Mapa base", ["Satélite (Esri)", "OpenStreetMap"], horizontal=True)
        st.divider()

        st.subheader("Métricas generales")
        c1, c2 = st.columns(2)
        c1.metric("Hábitat núcleo", f"{patches['area_ha'].sum():,.0f} ha")
        c2.metric("Parches núcleo", f"{len(patches)}")

        c3, c4 = st.columns(2)
        c3.metric("Corredores", f"{len(corridors)}")
        if validation:
            c4.metric("Validación AUC", f"{validation['metrics']['roc_auc']:.3f}")
        else:
            c4.metric("Validación AUC", "Pendiente")

        st.markdown("**Alertas por nivel (peor caso):**")
        n_alto = int((alerts["nivel_alerta"] == "Alto").sum())
        n_mod = int((alerts["nivel_alerta"] == "Moderado").sum())
        n_bajo = int((alerts["nivel_alerta"] == "Bajo").sum())
        st.markdown(f"🔴 Alto: **{n_alto}** · 🟠 Moderado: **{n_mod}** · 🟢 Bajo: **{n_bajo}**")

        n_p_alto = int((alerts["nivel_perdida"] == "Alto").sum())
        n_p_mod = int((alerts["nivel_perdida"] == "Moderado").sum())
        st.caption(f"Pérdida activa NDVI (2024→2026): **{n_p_alto}** Alto (>10%) y **{n_p_mod}** Moderado (5–10%).")

        st.divider()
        with st.expander("Ficha de especie focal (Jaguar)", expanded=True):
            st.markdown(
                f"**{SPECIES_PROFILE['common_name']}** (*{SPECIES_PROFILE['scientific_name']}*)\n\n"
                f"- **Estatus México:** {SPECIES_PROFILE['status_mexico']}\n"
                f"- **Estatus global:** {SPECIES_PROFILE['status_iucn']}\n"
                f"- **Home range mínimo:** `{SPECIES_PROFILE['home_range_ha']:,.0f} ha` (36 km²)\n\n"
                f"_{SPECIES_PROFILE['home_range_citation']}_"
            )

    # --- PESTAÑAS PRINCIPALES ---
    tab1, tab2, tab3, tab4 = st.tabs(
        [
            "1. Idoneidad de Hábitat (HSM)",
            "2. Conectividad Ecológica",
            "3. Monitor de Umbrales y Alertas",
            "4. Validación Científica",
        ]
    )

    # =========================================================================
    # PESTAÑA 1 — IDONEIDAD DE HÁBITAT (ENFOQUE EN EL MAPA + AJUSTES AVANZADOS)
    # =========================================================================
    with tab1:
        head_l, head_c1, head_c2, head_r = st.columns([2.2, 1.1, 1.1, 1.1], vertical_alignment="center")
        with head_l:
            st.subheader("Vista 1 — Idoneidad de Hábitat (HSM)")
        with head_c1:
            show_roads_1 = st.checkbox("Avenidas principales", value=True, key="r1")
        with head_c2:
            show_gbif_1 = st.checkbox(f"Avistamientos ({len(vecs['pilot_sightings'])})", value=True, key="g1")
        with head_r:
            with st.popover("⚙️ Ajustes avanzados", use_container_width=True):
                st.markdown("**Pesos del modelo $H(x) = \\sum w_i S_i(x)$**")
                w_cob = st.slider("Cobertura vegetal (ESA)", 0.0, 1.0, float(HSM_WEIGHTS["cob"]), 0.05, key="w_cob")
                w_ndvi = st.slider("Densidad vegetal (NDVI 2026)", 0.0, 1.0, float(HSM_WEIGHTS["ndvi"]), 0.05, key="w_ndvi")
                w_roads = st.slider("Distancia a carreteras", 0.0, 1.0, float(HSM_WEIGHTS["roads"]), 0.05, key="w_roads")
                w_urban = st.slider("Distancia a zona urbana", 0.0, 1.0, float(HSM_WEIGHTS["urban"]), 0.05, key="w_urban")
                w_water = st.slider("Proximidad a fuentes de agua", 0.0, 1.0, float(HSM_WEIGHTS["water"]), 0.05, key="w_water")

                w_sum = w_cob + w_ndvi + w_roads + w_urban + w_water
                if w_sum <= 0:
                    wn = dict(HSM_WEIGHTS)
                else:
                    wn = {
                        "cob": w_cob / w_sum,
                        "ndvi": w_ndvi / w_sum,
                        "roads": w_roads / w_sum,
                        "urban": w_urban / w_sum,
                        "water": w_water / w_sum,
                    }

                st.caption(
                    f"Pesos normalizados: Cob `{wn['cob']:.2f}` · NDVI `{wn['ndvi']:.2f}` · "
                    f"Vías `{wn['roads']:.2f}` · Urb `{wn['urban']:.2f}` · Agua `{wn['water']:.2f}`"
                )
                st.button("Restablecer pesos base", on_click=_reset_weights, use_container_width=True)
                st.caption(
                    "Los pesos recalculan en vivo la idoneidad de esta vista. "
                    "Los parches, corredores y alertas de las vistas 2 y 3 usan los pesos base precalculados."
                )

        # Recálculo en vivo de la imagen RGBA en WGS84 (< 20 ms)
        wf = hsm_data["wgs_factors"]
        h_wgs = (
            wn["cob"] * wf["S_cob"]
            + wn["ndvi"] * wf["S_ndvi"]
            + wn["roads"] * wf["S_roads"]
            + wn["urban"] * wf["S_urban"]
            + wn["water"] * wf["S_water"]
        )
        hard_zero_wgs = hsm_data["hard_zero_wgs"]
        h_wgs[hard_zero_wgs] = 0.0
        rgba = (HSM_CMAP(np.clip(h_wgs, 0.0, 1.0)) * 255).astype(np.uint8)
        # Agua, matriz urbana consolidada y lotes baldíos aislados quedan limpios/transparentes
        rgba[hard_zero_wgs, 3] = 0
        hsm_uri = _array_to_png_uri(rgba)

        m1 = make_base_map(basemap)
        folium.raster_layers.ImageOverlay(
            image=hsm_uri,
            bounds=hsm_data["folium_bounds"],
            opacity=0.72,
            name="Idoneidad H(x)",
        ).add_to(m1)

        if show_roads_1:
            folium.GeoJson(
                vecs["roads_major"],
                name="Avenidas principales",
                style_function=lambda _: {"color": "#111111", "weight": 2.0, "opacity": 0.8},
            ).add_to(m1)

        if show_gbif_1:
            add_jaguar_sightings(m1, vecs["pilot_sightings"])

        add_landmarks(m1)
        st_folium(m1, use_container_width=True, height=690, returned_objects=[], key="map_vista1")
        st.caption(
            "Escala: 🔴 0.0 (baja) → 🟡 0.5 → 🟢 0.70+ (núcleo) → 🌲 1.0. "
            "Marcadores: 🟠 Oficial GBIF/CONABIO · 🔵 iNaturalist casual · 🟣 Prensa/PROFEPA · 🚨 Atropellamiento Arco Norte."
        )

        # Recálculo en vivo de métricas en UTM 16N (fila compacta debajo del mapa)
        uf = hsm_data["utm_factors"]
        h_utm = (
            wn["cob"] * uf["S_cob"]
            + wn["ndvi"] * uf["S_ndvi"]
            + wn["roads"] * uf["S_roads"]
            + wn["urban"] * uf["S_urban"]
            + wn["water"] * uf["S_water"]
        )
        h_utm[hsm_data["hard_zero_utm"]] = 0.0
        h_utm = np.clip(h_utm, 0.0, 1.0)

        px_ha = (TARGET_RESOLUTION_M * TARGET_RESOLUTION_M) / 10_000.0
        land_mask = ~hsm_data["hard_zero_utm"]
        ha_alta = float(np.sum(h_utm >= PATCH_SUITABILITY_THRESHOLD) * px_ha)
        ha_media = float(np.sum((h_utm >= 0.40) & (h_utm < PATCH_SUITABILITY_THRESHOLD) & land_mask) * px_ha)
        ha_baja = float(np.sum((h_utm < 0.40) & land_mask) * px_ha)

        m_c1, m_c2, m_c3 = st.columns(3)
        m_c1.metric("Alta idoneidad (H ≥ 0.70)", f"{ha_alta:,.0f} ha")
        m_c2.metric("Media idoneidad (0.40–0.70)", f"{ha_media:,.0f} ha")
        m_c3.metric("Baja idoneidad (< 0.40)", f"{ha_baja:,.0f} ha")

    # =========================================================================
    # PESTAÑA 2 — CONECTIVIDAD ECOLÓGICA
    # =========================================================================
    with tab2:
        st.subheader("Vista 2 — Parches Núcleo y Corredores de Menor Costo")
        c_opt1, c_opt2, c_opt3, c_opt4 = st.columns(4)
        show_swath = c_opt1.checkbox("Franja de corredor (Linkage Mapper)", value=True)
        show_alt = c_opt2.checkbox("Enlaces alternos (2-NN)", value=True)
        show_roads_2 = c_opt3.checkbox("Avenidas principales", value=False)
        show_sight_2 = c_opt4.checkbox(f"Avistamientos ({len(vecs['pilot_sightings'])})", value=True)

        m2 = make_base_map(basemap)
        if show_swath:
            folium.raster_layers.ImageOverlay(
                image=swath_uri,
                bounds=swath_bounds,
                opacity=0.78,
                name="Franja de corredor",
            ).add_to(m2)

        folium.GeoJson(
            patches,
            name="Parches núcleo",
            style_function=lambda _: {
                "fillColor": "#1b7837",
                "color": "#00441b",
                "weight": 1.8,
                "fillOpacity": 0.56,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["patch_id", "area_ha", "mean_hsm", "dominant_lc", "toca_borde"],
                aliases=["Parche:", "Área (ha):", "Idoneidad media:", "Cobertura:", "Toca borde:"],
            ),
        ).add_to(m2)

        cor_plot = corridors if show_alt else corridors[corridors["in_mst"]]
        folium.GeoJson(
            cor_plot,
            name="Corredores",
            style_function=lambda feat: {
                "color": "#d50000" if feat["properties"].get("in_mst") else "#ff9100",
                "weight": 3.2 if feat["properties"].get("in_mst") else 2.0,
                "dashArray": None if feat["properties"].get("in_mst") else "6 4",
                "opacity": 0.95,
            },
            tooltip=folium.GeoJsonTooltip(
                fields=["corridor_id", "from_patch", "to_patch", "length_km", "mean_resistance", "in_mst"],
                aliases=["Corredor:", "Desde:", "Hacia:", "Longitud (km):", "Resistencia media:", "Troncal MST:"],
            ),
        ).add_to(m2)

        if show_roads_2:
            folium.GeoJson(
                vecs["roads_major"],
                name="Avenidas principales",
                style_function=lambda _: {"color": "#111111", "weight": 2.0, "opacity": 0.75},
            ).add_to(m2)

        if show_sight_2:
            add_jaguar_sightings(m2, vecs["pilot_sightings"])

        add_landmarks(m2)
        st_folium(m2, use_container_width=True, height=660, returned_objects=[], key="map_vista2")

        st.markdown("#### Tabla de corredores ecológicos")
        df_cor = pd.DataFrame(corridors.drop(columns="geometry"))
        df_cor = df_cor.rename(
            columns={
                "corridor_id": "ID",
                "from_patch": "Origen",
                "to_patch": "Destino",
                "in_mst": "Troncal (MST)",
                "length_km": "Longitud (km)",
                "mean_resistance": "Resistencia media (1-100)",
                "cost_weighted_dist": "Costo acumulado",
            }
        )
        st.dataframe(
            df_cor[["ID", "Origen", "Destino", "Troncal (MST)", "Longitud (km)", "Resistencia media (1-100)", "Costo acumulado"]],
            use_container_width=True,
            hide_index=True,
        )

    # =========================================================================
    # PESTAÑA 3 — MONITOR DE UMBRALES Y ALERTAS (CON FICHA DE DETALLE AL CLIC)
    # =========================================================================
    with tab3:
        st.subheader("Vista 3 — Monitor de Umbrales Críticos y Alertas Explicables")

        color_mode = st.radio(
            "Criterio de color del semáforo en el mapa:",
            [
                "Semáforo final (peor caso: pérdida 2024→2026 + home range)",
                "Solo pérdida de vegetación NDVI (2024→2026, anillo 90 m)",
            ],
            horizontal=True,
        )
        color_field = "nivel_alerta" if color_mode.startswith("Semáforo") else "nivel_perdida"

        col_m3, col_detail = st.columns([1.85, 1.15])

        with col_m3:
            m3 = make_base_map(basemap)
            for _, row in alerts.iterrows():
                col = LEVEL_COLORS[row[color_field]]
                pid = row["patch_id"]
                folium.GeoJson(
                    row.geometry.__geo_interface__,
                    style_function=lambda _, c=col: {
                        "fillColor": c,
                        "color": "#111111",
                        "weight": 1.8,
                        "fillOpacity": 0.65,
                    },
                    tooltip=f"{pid} | Final: {row['nivel_alerta']} | Pérdida 24→26: {row['perdida_pct']:+.1f}% | {row['area_ha']:,.1f} ha",
                ).add_to(m3)

            folium.GeoJson(
                corridors[corridors["in_mst"]],
                name="Corredores troncales",
                style_function=lambda _: {"color": "#ffffff", "weight": 2.2, "opacity": 0.85},
            ).add_to(m3)
            add_landmarks(m3)

            map_state = st_folium(
                m3,
                use_container_width=True,
                height=630,
                returned_objects=["last_object_clicked_tooltip"],
                key="map_vista3",
            )

        # Detectar clic en parche desde el tooltip devuelto por st_folium
        patch_ids = list(alerts["patch_id"])
        if "selected_patch" not in st.session_state:
            st.session_state["selected_patch"] = "P03" if "P03" in patch_ids else patch_ids[0]

        clicked_tip = (map_state or {}).get("last_object_clicked_tooltip")
        if isinstance(clicked_tip, str) and " | " in clicked_tip:
            cand_id = clicked_tip.split(" | ")[0].strip()
            if cand_id in patch_ids:
                st.session_state["selected_patch"] = cand_id

        with col_detail:
            st.markdown("#### Ficha de detalle del parche")
            sel_id = st.selectbox(
                "Selecciona o haz clic sobre un parche en el mapa:",
                patch_ids,
                index=patch_ids.index(st.session_state["selected_patch"]),
            )
            st.session_state["selected_patch"] = sel_id
            rec = alerts[alerts["patch_id"] == sel_id].iloc[0]

            st.markdown(f"### Parche `{rec['patch_id']}` — {LEVEL_BADGE[rec['nivel_alerta']]}")
            k1, k2 = st.columns(2)
            k1.metric("Superficie núcleo", f"{rec['area_ha']:,.1f} ha", f"{rec['pct_home_range']:.1f}% del home range")
            k2.metric(
                "Pérdida veg. (2024→2026)",
                f"{rec['perdida_pct']:+.1f}%",
                f"{-rec['perdida_ha']:+.1f} ha",
                delta_color="normal",
            )

            k3, k4 = st.columns(2)
            k3.metric("Nivel por pérdida", rec["nivel_perdida"])
            k4.metric("Nivel por tamaño", rec["nivel_tamano"])

            st.markdown("**Motivo de la alerta:**")
            if rec["nivel_alerta"] == "Alto":
                st.error(rec["motivo"])
            elif rec["nivel_alerta"] == "Moderado":
                st.warning(rec["motivo"])
            else:
                st.success(rec["motivo"])

            st.markdown("**Trayectoria de área vegetada (NDVI ≥ 0.50, parche + anillo 90 m):**")
            trend_df = pd.DataFrame(
                {
                    "Año": ["2024", "2025", "2026"],
                    "Hectáreas vegetadas": [rec["veg_2024_ha"], rec["veg_2025_ha"], rec["veg_2026_ha"]],
                }
            ).set_index("Año")
            st.bar_chart(trend_df, height=160)

            st.caption(
                f"Cobertura dominante: **{rec['dominant_lc']}** · "
                f"Idoneidad media: **{rec['mean_hsm']:.3f}** · "
                f"Corredores conectados: **{int(rec['n_corredores'])}** "
                f"(vecino a **{rec['dist_vecino_km']:.2f} km**)"
            )

        st.divider()
        st.markdown("#### Tabla completa de alertas por parche")
        df_al = pd.DataFrame(alerts.drop(columns="geometry")).sort_values("perdida_pct", ascending=False)
        cols_show = [
            "patch_id",
            "area_ha",
            "pct_home_range",
            "veg_2024_ha",
            "veg_2025_ha",
            "veg_2026_ha",
            "perdida_pct",
            "nivel_perdida",
            "nivel_tamano",
            "nivel_alerta",
            "n_corredores",
            "toca_borde",
            "motivo",
        ]
        df_display = df_al[cols_show].rename(
            columns={
                "patch_id": "ID",
                "area_ha": "Área (ha)",
                "pct_home_range": "% Home Range",
                "veg_2024_ha": "Veg 2024 (ha)",
                "veg_2025_ha": "Veg 2025 (ha)",
                "veg_2026_ha": "Veg 2026 (ha)",
                "perdida_pct": "Pérdida 24→26 (%)",
                "nivel_perdida": "Nivel Pérdida",
                "nivel_tamano": "Nivel Tamaño",
                "nivel_alerta": "Alerta Final",
                "n_corredores": "Corredores",
                "toca_borde": "Toca Borde",
                "motivo": "Motivo",
            }
        )
        st.dataframe(df_display, use_container_width=True, hide_index=True)
        st.download_button(
            "Descargar tabla de alertas (CSV)",
            df_display.to_csv(index=False).encode("utf-8"),
            file_name="bioconecta_alertas_parches.csv",
            mime="text/csv",
        )

    # =========================================================================
    # PESTAÑA 4 — VALIDACIÓN CIENTÍFICA
    # =========================================================================
    with tab4:
        st.subheader("Fase 5 — Validación Científica con Registros Reales de Jaguar")
        if validation is None:
            st.warning("Aún no se ha ejecutado `scripts/06_validation.py`.")
        else:
            m_val = validation["metrics"]
            c_clean = validation["cleaning"]

            v1, v2, v3, v4 = st.columns(4)
            v1.metric("ROC-AUC (regional)", f"{m_val['roc_auc']:.3f}")
            v2.metric("Mann-Whitney p-valor", f"{m_val['mann_whitney_p']:.2e}")
            v3.metric("Presencias en núcleo (H ≥ 0.70)", f"{m_val['pct_presence_in_core_h70']:.1f}%")
            v4.metric("Registros únicos evaluados", f"{c_clean['final_presence_n']}")

            st.caption(
                f"Fuentes: GBIF ({c_clean['gbif_raw']}) + iNaturalist Research Grade ({c_clean['inat_raw']}). "
                f"Tras descartar incertidumbre > 5 km ({c_clean['dropped_uncertainty_gt_5km']}), "
                f"deduplicar a < 100 m y excluir puntos sobre mar ({c_clean['dropped_on_water']}), "
                f"quedaron **{c_clean['final_presence_n']} presencias independientes** comparadas contra 10,000 puntos de fondo terrestres."
            )
            st.info(
                f"**Interpretación científica:** El **{m_val['pct_presence_in_core_h70']:.1f}%** de los avistamientos reales de jaguar "
                f"cae dentro del hábitat núcleo predicho ($H \\ge 0.70$, mediana $H = {m_val['presence_median_hsm']:.2f}$, "
                f"distancia mediana al núcleo = `{m_val['presence_median_dist_core_m']:.0f} m`). "
                f"El ROC-AUC frente a fondo aleatorio es `{m_val['roc_auc']:.3f}` porque en el recuadro regional el "
                f"`{m_val['pct_background_in_core_h70']:.1f}%` del territorio terrestre sigue siendo selva apta ($H \\ge 0.70$) "
                f"y los registros ciudadanos en especies amenazadas incluyen sesgo hacia vías o difuminado de coordenadas."
            )

            preview_val = OUTPUTS_DIR / "preview_validacion.png"
            if preview_val.exists():
                st.image(str(preview_val), use_container_width=True)

            if vecs["val_pts"] is not None:
                st.markdown("#### Detalle de registros de validación")
                df_v = pd.DataFrame(vecs["val_pts"].drop(columns="geometry"))
                st.dataframe(
                    df_v[["record_id", "source", "year", "hsm_score", "in_core_h70", "dist_core_m", "in_pilot_aoi", "dist_pilot_corridor_m"]],
                    use_container_width=True,
                    hide_index=True,
                )


if __name__ == "__main__":
    main()

"""
BioConecta — Aplicación Web Interactiva (Streamlit + Folium).

Ejecución local:
    ./.venv/bin/streamlit run app.py
"""

import base64
import io
import json
from html import escape

import folium
from folium.plugins import BeautifyIcon
import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import streamlit as st
from PIL import Image
from rasterio.warp import Resampling, calculate_default_transform, reproject
from streamlit_folium import st_folium

from config import DATA_PROCESSED_DIR, LANDMARKS, PROJECT_ROOT, TARGET_RESOLUTION_M
from species_rules import (
    HOME_RANGE_HIGH_RATIO,
    HOME_RANGE_MODERATE_RATIO,
    HSM_WEIGHTS,
    LOSS_HIGH_PCT,
    LOSS_MODERATE_PCT,
    PATCH_SUITABILITY_THRESHOLD,
    SPECIES_PROFILE,
)
from ui.components import (
    callout,
    card_heading,
    legend_bar,
    metric_grid,
    page_header,
    patch_footer_meta,
    patch_header,
    patch_vegetation_chart,
    section_label,
    sidebar_alert_summary,
    sidebar_brand,
    species_card,
)
from ui.theme import COLORS, HSM_CMAP, LEAFLET_CUSTOM_CSS, LEVEL_COLORS, SWATH_CMAP, inject_css

OUTPUTS_DIR = PROJECT_ROOT / "outputs"
STUDY_AREA_LABEL = "UNICARIBE – Rancho Viejo – Zona Continental de Isla Mujeres (Q. Roo)"

st.set_page_config(
    page_title="BioConecta — Hábitat y Conectividad del Jaguar",
    page_icon="🐆",
    layout="wide",
    initial_sidebar_state="expanded",
)


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
    m.get_root().header.add_child(folium.Element(LEAFLET_CUSTOM_CSS))
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
            color="#1C2421",
            weight=2,
            fill=True,
            fill_color="#F0F1EA",
            fill_opacity=0.95,
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
            bg_hex, icon = COLORS["risk_high"], "exclamation-triangle"
        elif es_oficial:
            bg_hex, icon = COLORS["warn"], "paw"
        elif "Ciencia ciudadana" in cat:
            bg_hex, icon = COLORS["carto_blue"], "eye"
        else:
            bg_hex, icon = COLORS["carto_plum"], "video-camera"

        fecha = escape(str(r.get("fecha", r.get("year", "N/D"))))
        localidad = escape(str(r.get("localidad", "N/D")))
        fuente = escape(str(r.get("fuente", "GBIF")))
        desc = escape(str(r.get("descripcion", "")))

        popup_html = (
            f"<div style=\"font-family:'IBM Plex Sans',sans-serif;font-size:12.5px;width:270px;color:#1C2421;line-height:1.45;\">"
            f"<div style=\"font-family:'IBM Plex Serif',Georgia,serif;font-weight:600;font-size:13.5px;margin-bottom:4px;\">"
            f"Panthera onca &mdash; {escape(tipo_ev)}</div>"
            f"<div><strong>Categoría:</strong> {escape(cat)}</div>"
            f"<div><strong>Fecha:</strong> {fecha}</div>"
            f"<div><strong>Localidad:</strong> {localidad}</div>"
            f"<div><strong>Fuente:</strong> {fuente}</div>"
            f"<hr style='margin:6px 0;border:none;border-top:1px solid #C5CEC4;'>"
            f"<div style='color:#303C35;'>{desc}</div>"
            f"</div>"
        )
        folium.Marker(
            location=[r.geometry.y, r.geometry.x],
            tooltip=f"{r.get('fecha', '')} · {r.get('localidad', 'Jaguar')} ({cat})",
            popup=folium.Popup(popup_html, max_width=295),
            icon=BeautifyIcon(
                icon=icon,
                icon_shape="marker",
                border_width=2,
                border_color="#1C2421",
                text_color="#1C2421",
                background_color=bg_hex,
                inner_icon_style="font-size:11px;padding-top:1px;",
            ),
        ).add_to(m)


def _reset_weights():
    for k, v in HSM_WEIGHTS.items():
        st.session_state[f"w_{k}"] = float(v)


def main():
    inject_css()

    hsm_data = load_hsm_layers()
    swath_uri, swath_bounds = load_swath_overlay()
    vecs = load_vector_layers()

    patches = vecs["patches"]
    corridors = vecs["corridors"]
    alerts = vecs["alerts"]
    validation = vecs["validation"]

    # --- BARRA LATERAL ---
    with st.sidebar:
        sidebar_brand(STUDY_AREA_LABEL)

        section_label("Mapa base", tight=True)
        basemap = st.radio(
            "Mapa base",
            ["Satélite (Esri)", "OpenStreetMap"],
            horizontal=True,
            label_visibility="collapsed",
        )

        section_label("Métricas generales")
        auc_val = f"{validation['metrics']['roc_auc']:.3f}" if validation else "Pendiente"
        metric_grid(
            [
                {
                    "label": "Hábitat núcleo",
                    "value": f"{patches['area_ha'].sum():,.0f}",
                    "unit": "ha",
                    "accent": "sage",
                },
                {
                    "label": "Parches núcleo",
                    "value": f"{len(patches)}",
                    "accent": "low",
                },
                {
                    "label": "Corredores",
                    "value": f"{len(corridors)}",
                    "accent": "mod",
                },
                {
                    "label": "Validación AUC",
                    "value": auc_val,
                    "accent": "info",
                },
            ],
            cols=2,
            compact=True,
        )

        section_label("Alertas por nivel (peor caso)")
        n_alto = int((alerts["nivel_alerta"] == "Alto").sum())
        n_mod = int((alerts["nivel_alerta"] == "Moderado").sum())
        n_bajo = int((alerts["nivel_alerta"] == "Bajo").sum())
        n_p_alto = int((alerts["nivel_perdida"] == "Alto").sum())
        n_p_mod = int((alerts["nivel_perdida"] == "Moderado").sum())
        sidebar_alert_summary(n_alto, n_mod, n_bajo, n_p_alto, n_p_mod)

        section_label("Especie focal")
        with st.expander("Ficha de especie focal (Jaguar)", expanded=True):
            species_card(SPECIES_PROFILE)

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
        page_header(
            "Vista 1 · Modelo de Idoneidad (HSM)",
            "Idoneidad de Hábitat del Jaguar",
            "Evaluación espacial multicriterio a 30 m con ajuste interactivo de pesos y registros de presencia.",
        )

        with st.container(key="toolbar-v1"):
            ctrl_1, ctrl_2, ctrl_spacer, ctrl_adv = st.columns(
                [1.2, 1.35, 0.85, 1.15],
                vertical_alignment="center",
            )
            with ctrl_1:
                show_roads_1 = st.toggle("Avenidas principales", value=True, key="r1")
            with ctrl_2:
                show_gbif_1 = st.toggle(f"Avistamientos ({len(vecs['pilot_sightings'])})", value=True, key="g1")
            with ctrl_adv:
                with st.popover(":material/tune: Ajustes avanzados", use_container_width=True):
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
            opacity=0.78,
            name="Idoneidad H(x)",
        ).add_to(m1)

        if show_roads_1:
            folium.GeoJson(
                vecs["roads_major"],
                name="Avenidas principales",
                style_function=lambda _: {"color": COLORS["carto_road"], "weight": 2.0, "opacity": 0.85},
            ).add_to(m1)

        if show_gbif_1:
            add_jaguar_sightings(m1, vecs["pilot_sightings"])

        add_landmarks(m1)
        with st.container(key="map-v1"):
            st_folium(m1, use_container_width=True, height=690, returned_objects=[], key="map_vista1")

        legend_bar(
            [
                {
                    "title": "Idoneidad H(x)",
                    "items": [
                        {"kind": "box", "color": "#D73027", "label": "Baja", "desc": "(< 0.40)"},
                        {"kind": "box", "color": "#FEE08B", "label": "Media", "desc": "(0.40–0.70)"},
                        {"kind": "box", "color": "#66BD63", "label": "Alta / Núcleo", "desc": "(≥ 0.70)"},
                        {"kind": "box", "color": "#00441B", "label": "Óptima", "desc": "(1.0)"},
                    ],
                },
                {
                    "title": "Registros",
                    "items": [
                        {"kind": "dot", "color": COLORS["warn"], "label": "Oficial GBIF/CONABIO"},
                        {"kind": "dot", "color": COLORS["carto_blue"], "label": "iNaturalist casual"},
                        {"kind": "dot", "color": COLORS["carto_plum"], "label": "Prensa/PROFEPA"},
                        {"kind": "dot", "color": COLORS["risk_high"], "label": "Atropellamiento"},
                    ],
                },
            ]
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

        metric_grid(
            [
                {
                    "label": "Alta idoneidad (H ≥ 0.70)",
                    "value": f"{ha_alta:,.0f}",
                    "unit": "ha",
                    "hint": "Hábitat núcleo apto para la especie",
                    "accent": "low",
                },
                {
                    "label": "Media idoneidad (0.40–0.70)",
                    "value": f"{ha_media:,.0f}",
                    "unit": "ha",
                    "hint": "Matriz permeable de desplazamiento",
                    "accent": "mod",
                },
                {
                    "label": "Baja idoneidad (< 0.40)",
                    "value": f"{ha_baja:,.0f}",
                    "unit": "ha",
                    "hint": "Zonas perturbadas o de alta resistencia",
                    "accent": "sage",
                },
            ],
            cols=3,
        )

    # =========================================================================
    # PESTAÑA 2 — CONECTIVIDAD ECOLÓGICA
    # =========================================================================
    with tab2:
        page_header(
            "Vista 2 · Conectividad Ecológica",
            "Parches Núcleo y Corredores de Menor Costo",
            "Red de parches de hábitat núcleo, rutas troncales (MST), enlaces alternos (2-NN) y franja de conectividad.",
        )

        with st.container(key="toolbar-v2"):
            c_opt1, c_opt2, c_opt3, c_opt4 = st.columns([1.35, 1.1, 1.0, 1.05], vertical_alignment="center")
            show_swath = c_opt1.toggle("Franja de corredor (Linkage Mapper)", value=True)
            show_alt = c_opt2.toggle("Enlaces alternos (2-NN)", value=True)
            show_roads_2 = c_opt3.toggle("Avenidas principales", value=False)
            show_sight_2 = c_opt4.toggle(f"Avistamientos ({len(vecs['pilot_sightings'])})", value=True)

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
                "fillColor": "#1A9850",
                "color": "#00441B",
                "weight": 1.8,
                "fillOpacity": 0.62,
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
                "color": "#FF1744" if feat["properties"].get("in_mst") else "#00E5FF",
                "weight": 3.4 if feat["properties"].get("in_mst") else 2.2,
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
                style_function=lambda _: {"color": COLORS["carto_road"], "weight": 2.0, "opacity": 0.8},
            ).add_to(m2)

        if show_sight_2:
            add_jaguar_sightings(m2, vecs["pilot_sightings"])

        add_landmarks(m2)
        with st.container(key="map-v2"):
            st_folium(m2, use_container_width=True, height=660, returned_objects=[], key="map_vista2")

        legend_bar(
            [
                {
                    "title": "Capas de conectividad",
                    "items": [
                        {"kind": "box", "color": "#1A9850", "label": "Parches núcleo"},
                        {"kind": "line", "color": "#FF1744", "label": "Corredor troncal (MST)"},
                        {"kind": "dashed", "color": "#00E5FF", "label": "Enlace alterno (2-NN)"},
                        {"kind": "box", "color": "#FF9100", "label": "Franja de corredor"},
                        {"kind": "line", "color": COLORS["carto_road"], "label": "Barreras / Avenidas"},
                    ],
                }
            ]
        )

        with st.container(key="card-table-v2"):
            card_heading(
                "Tabla de corredores ecológicos",
                "Resumen de longitud, resistencia media y costo acumulado para cada enlace identificado.",
            )
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
        page_header(
            "Vista 3 · Monitor de Umbrales y Alertas",
            "Monitor de Umbrales Críticos y Alertas Explicables",
            "Evaluación de riesgo por pérdida de vegetación NDVI (2024→2026) y comparación con el home range del jaguar.",
        )

        with st.container(key="toolbar-v3"):
            color_mode = st.radio(
                "Criterio de color del semáforo en el mapa:",
                [
                    "Semáforo final (peor caso: pérdida 2024→2026 + home range)",
                    "Solo pérdida de vegetación NDVI (2024→2026, anillo 90 m)",
                ],
                horizontal=True,
            )
        color_field = "nivel_alerta" if color_mode.startswith("Semáforo") else "nivel_perdida"

        with st.container(key="vista3-split"):
            col_m3, col_detail = st.columns([3, 2], gap="medium", vertical_alignment="top")

            with col_m3:
                m3 = make_base_map(basemap)
                for _, row in alerts.iterrows():
                    col = LEVEL_COLORS[row[color_field]]
                    pid = row["patch_id"]
                    folium.GeoJson(
                        row.geometry.__geo_interface__,
                        style_function=lambda _, c=col: {
                            "fillColor": c,
                            "color": "#1C2421",
                            "weight": 1.8,
                            "fillOpacity": 0.68,
                        },
                        tooltip=f"{pid} | Final: {row['nivel_alerta']} | Pérdida 24→26: {row['perdida_pct']:+.1f}% | {row['area_ha']:,.1f} ha",
                    ).add_to(m3)

                folium.GeoJson(
                    corridors[corridors["in_mst"]],
                    name="Corredores troncales",
                    style_function=lambda _: {"color": "#F0F1EA", "weight": 2.2, "opacity": 0.85},
                ).add_to(m3)
                add_landmarks(m3)

                with st.container(key="map-v3"):
                    map_state = st_folium(
                        m3,
                        use_container_width=True,
                        height=640,
                        returned_objects=["last_object_clicked_tooltip"],
                        key="map_vista3",
                    )

                legend_bar(
                    [
                        {
                            "title": "Nivel de riesgo",
                            "items": [
                                {"kind": "box", "color": LEVEL_COLORS["Alto"], "label": "Alto"},
                                {"kind": "box", "color": LEVEL_COLORS["Moderado"], "label": "Moderado"},
                                {"kind": "box", "color": LEVEL_COLORS["Bajo"], "label": "Bajo"},
                                {"kind": "line", "color": "#F0F1EA", "label": "Corredores troncales"},
                            ],
                        }
                    ]
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
                with st.container(key="patch-card"):
                    card_heading(
                        "Ficha de detalle del parche",
                        "Selecciona un parche o haz clic directamente en el mapa.",
                    )
                    sel_id = st.selectbox(
                        "Selecciona o haz clic sobre un parche en el mapa:",
                        patch_ids,
                        index=patch_ids.index(st.session_state["selected_patch"]),
                        label_visibility="collapsed",
                    )
                    st.session_state["selected_patch"] = sel_id
                    rec = alerts[alerts["patch_id"] == sel_id].iloc[0]

                    patch_header(rec["patch_id"], rec["nivel_alerta"], rec["dominant_lc"])

                    hr_ha = SPECIES_PROFILE["home_range_ha"]
                    metric_grid(
                        [
                            {
                                "label": "Superficie núcleo",
                                "value": f"{rec['area_ha']:,.1f}",
                                "unit": "ha",
                                "hint": f"{rec['pct_home_range']:.1f}% del home range ({hr_ha:,.0f} ha)",
                                "accent": "sage",
                            },
                            {
                                "label": "Pérdida veg. (2024→2026)",
                                "value": f"{rec['perdida_pct']:+.1f}%",
                                "hint": f"{-rec['perdida_ha']:+.1f} ha · umbrales ≥{LOSS_MODERATE_PCT:.0f}% / >{LOSS_HIGH_PCT:.0f}%",
                                "accent": "high" if rec["nivel_perdida"] == "Alto" else ("mod" if rec["nivel_perdida"] == "Moderado" else "low"),
                            },
                            {
                                "label": "Nivel por pérdida",
                                "badge_level": rec["nivel_perdida"],
                                "hint": "Cambio NDVI anillo 90 m",
                            },
                            {
                                "label": "Nivel por tamaño",
                                "badge_level": rec["nivel_tamano"],
                                "hint": f"Alto <{HOME_RANGE_HIGH_RATIO * 100:.0f}% · Mod <{HOME_RANGE_MODERATE_RATIO * 100:.0f}% HR",
                            },
                        ],
                        cols=2,
                        compact=True,
                    )

                    alert_kind = rec["nivel_alerta"].strip().lower()
                    callout(alert_kind, "Motivo de la alerta", str(rec["motivo"]))

                    st.markdown(
                        "<div class='bc-chart-title'>Trayectoria de área vegetada</div>"
                        "<div class='bc-chart-sub'>NDVI &ge; 0.50 en parche + anillo de 90 m (2024–2026)</div>",
                        unsafe_allow_html=True,
                    )
                    chart = patch_vegetation_chart(
                        rec["veg_2024_ha"],
                        rec["veg_2025_ha"],
                        rec["veg_2026_ha"],
                        rec["nivel_alerta"],
                    )
                    st.altair_chart(chart, use_container_width=True)

                    patch_footer_meta(
                        rec["mean_hsm"],
                        rec["n_corredores"],
                        rec["dist_vecino_km"],
                        bool(rec["toca_borde"]),
                    )

        with st.container(key="card-table-v3"):
            card_heading(
                "Tabla completa de alertas por parche",
                "Parches ordenados de mayor a menor pérdida porcentual de vegetación (2024→2026).",
            )
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
                ":material/download: Descargar tabla de alertas (CSV)",
                df_display.to_csv(index=False).encode("utf-8"),
                file_name="bioconecta_alertas_parches.csv",
                mime="text/csv",
            )

    # =========================================================================
    # PESTAÑA 4 — VALIDACIÓN CIENTÍFICA
    # =========================================================================
    with tab4:
        page_header(
            "Vista 4 · Fase 5 · Validación Empírica",
            "Validación Científica con Registros Reales de Jaguar",
            "Contrastación del modelo HSM con presencias independientes de GBIF e iNaturalist en el norte de Quintana Roo.",
        )
        if validation is None:
            callout("warn", "Validación pendiente", "Aún no se ha ejecutado scripts/06_validation.py.")
        else:
            m_val = validation["metrics"]
            c_clean = validation["cleaning"]

            section_label("Métricas de evaluación", tight=True)
            metric_grid(
                [
                    {
                        "label": "ROC-AUC (regional)",
                        "value": f"{m_val['roc_auc']:.3f}",
                        "hint": "Frente a 10,000 puntos de fondo",
                        "accent": "info",
                    },
                    {
                        "label": "Mann-Whitney p-valor",
                        "value": f"{m_val['mann_whitney_p']:.2e}",
                        "hint": "Contraste presencias vs. fondo",
                        "accent": "sage",
                    },
                    {
                        "label": "Presencias en núcleo (H ≥ 0.70)",
                        "value": f"{m_val['pct_presence_in_core_h70']:.1f}%",
                        "hint": f"Mediana H = {m_val['presence_median_hsm']:.2f}",
                        "accent": "low",
                    },
                    {
                        "label": "Registros únicos evaluados",
                        "value": f"{c_clean['final_presence_n']}",
                        "hint": f"Distancia mediana al núcleo: {m_val['presence_median_dist_core_m']:.0f} m",
                        "accent": "mod",
                    },
                ],
                cols=4,
            )

            with st.container(key="val-callouts"):
                col_interp, col_lim = st.columns([1.3, 1.0], gap="medium")
                with col_interp:
                    callout(
                        "info",
                        "Interpretación científica",
                        (
                            f"El <strong>{m_val['pct_presence_in_core_h70']:.1f}%</strong> de los avistamientos reales de jaguar "
                            f"cae dentro del hábitat núcleo predicho (<em>H</em> &ge; 0.70, mediana <em>H</em> = "
                            f"<strong>{m_val['presence_median_hsm']:.2f}</strong>, distancia mediana al núcleo = "
                            f"<strong>{m_val['presence_median_dist_core_m']:.0f} m</strong>). "
                            f"El ROC-AUC frente a fondo aleatorio es <strong>{m_val['roc_auc']:.3f}</strong> porque en el "
                            f"recuadro regional el <strong>{m_val['pct_background_in_core_h70']:.1f}%</strong> del territorio "
                            f"terrestre sigue siendo selva apta (<em>H</em> &ge; 0.70)."
                        ),
                        allow_html=True,
                    )
                with col_lim:
                    callout(
                        "warn",
                        "Limitaciones y filtrado de datos",
                        (
                            f"Fuentes: GBIF ({c_clean['gbif_raw']}) + iNaturalist Research Grade ({c_clean['inat_raw']}). "
                            f"Tras descartar incertidumbre &gt; 5 km ({c_clean['dropped_uncertainty_gt_5km']}), "
                            f"deduplicar a &lt; 100 m y excluir puntos sobre mar ({c_clean['dropped_on_water']}), "
                            f"quedaron <strong>{c_clean['final_presence_n']} presencias independientes</strong> comparadas contra "
                            f"10,000 puntos de fondo terrestres. Los registros ciudadanos en especies amenazadas incluyen "
                            f"sesgo hacia vías o difuminado de coordenadas."
                        ),
                        allow_html=True,
                    )

            preview_val = OUTPUTS_DIR / "preview_validacion.png"
            if preview_val.exists():
                with st.container(key="card-val-results"):
                    card_heading(
                        "Resultados de validación",
                        "Distribución espacial regional, curva ROC y comparación de idoneidad entre presencias reales y fondo terrestre.",
                    )
                    with st.container(key="val-plate"):
                        st.image(str(preview_val), use_container_width=True)

            if vecs["val_pts"] is not None:
                with st.container(key="card-val-table"):
                    card_heading(
                        "Detalle de registros de validación",
                        "Registros independientes evaluados con su puntaje de idoneidad H(x) y distancia al hábitat núcleo.",
                    )
                    df_v = pd.DataFrame(vecs["val_pts"].drop(columns="geometry"))
                    st.dataframe(
                        df_v[["record_id", "source", "year", "hsm_score", "in_core_h70", "dist_core_m", "in_pilot_aoi", "dist_pilot_corridor_m"]],
                        use_container_width=True,
                        hide_index=True,
                    )


if __name__ == "__main__":
    main()

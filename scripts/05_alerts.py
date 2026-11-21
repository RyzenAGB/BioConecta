"""
Fase 4 — Vista 3: Monitor de Umbrales Críticos y Motor de Alertas Explicables.

Para cada parche núcleo de la Vista 2:
1. Mide el área vegetada (NDVI >= 0.50) en temporada seca 2024 (A_{t-2}), 2025 (A_{t-1}) y 2026 (A_t)
   dentro del polígono del parche + un anillo de 90 m (sin invadir otros parches ni agua).
2. Calcula la pérdida porcentual acumulada en 2 años (2024→2026):
   P = (A_2024 - A_2026) / A_2024 * 100
   (y guarda también la tasa del último año 2025→2026 como contexto de tendencia).
   Cortes: < 5% Bajo | 5–10% Moderado | > 10% Alto
3. Evalúa el tamaño del parche frente al home range del jaguar (3,600 ha):
   < 50% (< 1,800 ha) Alto | 50–100% Moderado | >= 100% Bajo
4. Combina ambos criterios con la regla del peor caso (gana el nivel más alto) y redacta
   un texto explicable (`motivo`) + nota de borde si `toca_borde == True`.

Salidas:
  - outputs/alertas_parches.geojson
  - data/processed/alertas_parches_utm16n.gpkg
  - outputs/preview_vista3.png
  - outputs/mapa_vista3.html
"""

import sys
from pathlib import Path

import folium
import geopandas as gpd
import matplotlib.gridspec as gridspec
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from pyproj import Transformer
from scipy.ndimage import distance_transform_edt

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from config import DATA_PROCESSED_DIR, LANDMARKS, PROJECT_ROOT, TARGET_CRS, TARGET_RESOLUTION_M
from species_rules import (
    ALERT_BUFFER_RING_M,
    HOME_RANGE_HIGH_RATIO,
    HOME_RANGE_MODERATE_RATIO,
    LOSS_HIGH_PCT,
    LOSS_MODERATE_PCT,
    NDVI_VEGETATED_THRESHOLD,
    SPECIES_PROFILE,
)

OUTPUTS_DIR = PROJECT_ROOT / "outputs"

LEVEL_ORDER = {"Bajo": 0, "Moderado": 1, "Alto": 2}
LEVEL_COLORS = {
    "Bajo": "#2e7d32",      # Verde
    "Moderado": "#f9a825",  # Ámbar
    "Alto": "#c62828",      # Rojo
}


def classify_loss(loss_pct: float) -> str:
    if loss_pct > LOSS_HIGH_PCT:
        return "Alto"
    if loss_pct >= LOSS_MODERATE_PCT:
        return "Moderado"
    return "Bajo"


def classify_size(area_ha: float, home_range_ha: float) -> str:
    ratio = area_ha / home_range_ha
    if ratio < HOME_RANGE_HIGH_RATIO:
        return "Alto"
    if ratio < HOME_RANGE_MODERATE_RATIO:
        return "Moderado"
    return "Bajo"


def build_reason_text(
    area_ha: float,
    hr_ha: float,
    hr_pct: float,
    loss_pct: float,
    loss_ha: float,
    nivel_perdida: str,
    nivel_tamano: str,
    toca_borde: bool,
) -> str:
    reasons = []

    if nivel_perdida == "Alto":
        reasons.append(
            f"Pérdida acelerada de vegetación de {loss_pct:.1f}% ({loss_ha:,.1f} ha, 2024→2026) > {LOSS_HIGH_PCT:.0f}%"
        )
    elif nivel_perdida == "Moderado":
        reasons.append(
            f"Pérdida moderada de vegetación de {loss_pct:.1f}% ({loss_ha:,.1f} ha, 2024→2026, rango {LOSS_MODERATE_PCT:.0f}–{LOSS_HIGH_PCT:.0f}%)"
        )

    if nivel_tamano == "Alto":
        reasons.append(
            f"Superficie {area_ha:,.1f} ha = {hr_pct:.1f}% del home range del jaguar ({hr_ha:,.0f} ha, umbral crítico < 50%)"
        )
    elif nivel_tamano == "Moderado":
        reasons.append(
            f"Superficie {area_ha:,.1f} ha = {hr_pct:.1f}% del home range del jaguar ({hr_ha:,.0f} ha, por debajo del 100%)"
        )

    if not reasons:
        if loss_pct > 0:
            reasons.append(
                f"Estable: pérdida leve de {loss_pct:.1f}% (< {LOSS_MODERATE_PCT:.0f}%) y superficie {area_ha:,.1f} ha ≥ {hr_ha:,.0f} ha"
            )
        else:
            reasons.append(
                f"Estable: variación de vegetación {loss_pct:+.1f}% (sin pérdida neta, 2024→2026) y superficie {area_ha:,.1f} ha ≥ {hr_ha:,.0f} ha"
            )

    text = "; ".join(reasons) + "."
    if toca_borde:
        text += " El parche continúa fuera de la zona de estudio; su área puede estar subestimada."
    return text


def evaluate_alerts() -> tuple[gpd.GeoDataFrame, dict]:
    patches_utm = gpd.read_file(DATA_PROCESSED_DIR / "parches_utm16n.gpkg")
    corridors_utm = gpd.read_file(DATA_PROCESSED_DIR / "corredores_utm16n.gpkg")

    with rasterio.open(DATA_PROCESSED_DIR / "parches_labeled_30m.tif") as src:
        labeled = src.read(1)
        bounds = src.bounds
    with rasterio.open(DATA_PROCESSED_DIR / "landcover_2021_30m.tif") as src:
        lc21 = src.read(1)
    with rasterio.open(DATA_PROCESSED_DIR / "ndvi_2024_30m.tif") as src:
        ndvi24 = src.read(1)
        nodata24 = src.nodata
    with rasterio.open(DATA_PROCESSED_DIR / "ndvi_2025_30m.tif") as src:
        ndvi25 = src.read(1)
        nodata25 = src.nodata
    with rasterio.open(DATA_PROCESSED_DIR / "ndvi_2026_30m.tif") as src:
        ndvi26 = src.read(1)
        nodata26 = src.nodata

    pixel_ha = (TARGET_RESOLUTION_M * TARGET_RESOLUTION_M) / 10_000.0
    hr_ha = SPECIES_PROFILE["home_range_ha"]

    valid_all = (
        (ndvi24 != nodata24)
        & (ndvi25 != nodata25)
        & (ndvi26 != nodata26)
        & np.isfinite(ndvi24)
        & np.isfinite(ndvi25)
        & np.isfinite(ndvi26)
    )
    veg24 = valid_all & (ndvi24 >= NDVI_VEGETATED_THRESHOLD)
    veg25 = valid_all & (ndvi25 >= NDVI_VEGETATED_THRESHOLD)
    veg26 = valid_all & (ndvi26 >= NDVI_VEGETATED_THRESHOLD)

    conn_count: dict[str, int] = {}
    min_dist_km: dict[str, float] = {}
    min_cost: dict[str, float] = {}
    for _, c in corridors_utm.iterrows():
        for pid in (c["from_patch"], c["to_patch"]):
            conn_count[pid] = conn_count.get(pid, 0) + 1
            d = float(c["length_km"])
            cw = float(c["cost_weighted_dist"])
            if pid not in min_dist_km or d < min_dist_km[pid]:
                min_dist_km[pid] = d
            if pid not in min_cost or cw < min_cost[pid]:
                min_cost[pid] = cw

    rows_out = []
    for _, row in patches_utm.iterrows():
        pnum = int(row["patch_num"])
        pid = str(row["patch_id"])
        area_ha = float(row["area_ha"])
        toca_borde = bool(row["toca_borde"])

        patch_mask = labeled == pnum
        dist_from_patch = distance_transform_edt(~patch_mask, sampling=TARGET_RESOLUTION_M)
        eval_mask = (dist_from_patch <= ALERT_BUFFER_RING_M) & ((labeled == 0) | (labeled == pnum)) & (lc21 != 80)

        a_24_ha = float(np.sum(eval_mask & veg24) * pixel_ha)
        a_25_ha = float(np.sum(eval_mask & veg25) * pixel_ha)
        a_26_ha = float(np.sum(eval_mask & veg26) * pixel_ha)

        # Pérdida principal en ventana de 2 años (2024 → 2026)
        loss_ha = a_24_ha - a_26_ha
        loss_pct = (loss_ha / a_24_ha * 100.0) if a_24_ha > 0 else 0.0
        loss_1yr_pct = ((a_25_ha - a_26_ha) / a_25_ha * 100.0) if a_25_ha > 0 else 0.0

        eval_valid = eval_mask & valid_all
        ndvi_m24 = float(np.mean(ndvi24[eval_valid])) if np.any(eval_valid) else 0.0
        ndvi_m25 = float(np.mean(ndvi25[eval_valid])) if np.any(eval_valid) else 0.0
        ndvi_m26 = float(np.mean(ndvi26[eval_valid])) if np.any(eval_valid) else 0.0

        hr_pct = (area_ha / hr_ha) * 100.0
        nivel_perdida = classify_loss(loss_pct)
        nivel_tamano = classify_size(area_ha, hr_ha)

        nivel_alerta = (
            nivel_perdida
            if LEVEL_ORDER[nivel_perdida] >= LEVEL_ORDER[nivel_tamano]
            else nivel_tamano
        )
        motivo = build_reason_text(
            area_ha, hr_ha, hr_pct, loss_pct, loss_ha, nivel_perdida, nivel_tamano, toca_borde
        )

        rec = row.to_dict()
        rec.update(
            {
                "veg_2024_ha": round(a_24_ha, 2),
                "veg_2025_ha": round(a_25_ha, 2),
                "veg_2026_ha": round(a_26_ha, 2),
                "perdida_ha": round(loss_ha, 2),
                "perdida_pct": round(loss_pct, 2),
                "perdida_1yr_pct": round(loss_1yr_pct, 2),
                "ndvi_mean_2024": round(ndvi_m24, 3),
                "ndvi_mean_2025": round(ndvi_m25, 3),
                "ndvi_mean_2026": round(ndvi_m26, 3),
                "ndvi_delta": round(ndvi_m26 - ndvi_m24, 3),
                "home_range_ha": hr_ha,
                "pct_home_range": round(hr_pct, 2),
                "nivel_perdida": nivel_perdida,
                "nivel_tamano": nivel_tamano,
                "nivel_alerta": nivel_alerta,
                "motivo": motivo,
                "n_corredores": conn_count.get(pid, 0),
                "dist_vecino_km": round(min_dist_km.get(pid, 0.0), 2),
                "costo_vecino": round(min_cost.get(pid, 0.0), 1),
            }
        )
        rows_out.append(rec)

    alerts_utm = gpd.GeoDataFrame(rows_out, crs=TARGET_CRS)
    alerts_utm.to_file(DATA_PROCESSED_DIR / "alertas_parches_utm16n.gpkg", driver="GPKG")
    alerts_utm.to_crs("EPSG:4326").to_file(OUTPUTS_DIR / "alertas_parches.geojson", driver="GeoJSON")
    print(f"  [OK] Guardado {OUTPUTS_DIR / 'alertas_parches.geojson'} ({len(alerts_utm)} parches evaluados).")

    return alerts_utm, {"lc21": lc21, "bounds": bounds}


def plot_landmarks(ax, transformer: Transformer) -> None:
    for name, (lat, lon) in LANDMARKS.items():
        x, y = transformer.transform(lon, lat)
        ax.scatter(x, y, c="white", edgecolors="black", s=38, zorder=9, linewidth=1.1)
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


def generate_preview(alerts_utm: gpd.GeoDataFrame, ctx: dict) -> Path:
    bounds = ctx["bounds"]
    lc21 = ctx["lc21"]
    extent = [bounds.left, bounds.right, bounds.bottom, bounds.top]
    transformer = Transformer.from_crs("EPSG:4326", TARGET_CRS, always_xy=True)
    roads = gpd.read_file(DATA_PROCESSED_DIR / "roads_utm16n.gpkg")
    roads_major = roads[roads["road_tier"] == 3]
    corridors = gpd.read_file(DATA_PROCESSED_DIR / "corredores_utm16n.gpkg")

    bg = np.full((lc21.shape[0], lc21.shape[1], 3), (236, 240, 234), dtype=np.uint8)
    bg[lc21 == 80] = (186, 220, 242)
    bg[lc21 == 50] = (95, 95, 95)

    fig = plt.figure(figsize=(19, 11.5), dpi=150)
    gs = gridspec.GridSpec(2, 2, height_ratios=[3.2, 1.15], hspace=0.28, wspace=0.20)
    fig.suptitle(
        "BioConecta — Vista 3: Monitor de Umbrales Críticos y Alertas Explicables (Jaguar)\n"
        f"Pérdida NDVI ≥ {NDVI_VEGETATED_THRESHOLD} (2024→2026, anillo 90 m) + Tamaño vs Home Range ({SPECIES_PROFILE['home_range_ha']:,.0f} ha)",
        fontsize=13.5,
        fontweight="bold",
        y=0.98,
    )

    ax1 = fig.add_subplot(gs[0, 0])
    ax1.imshow(bg, extent=extent, origin="upper")
    corridors[corridors["in_mst"]].plot(ax=ax1, color="#555555", linewidth=1.2, alpha=0.65, zorder=3)
    for lvl in ("Bajo", "Moderado", "Alto"):
        sub = alerts_utm[alerts_utm["nivel_alerta"] == lvl]
        if len(sub) > 0:
            sub.plot(ax=ax1, facecolor=LEVEL_COLORS[lvl], edgecolor="#222222", linewidth=0.9, alpha=0.82, zorder=4)
    roads_major.plot(ax=ax1, color="#111111", linewidth=0.8, alpha=0.5, zorder=5)
    for _, r in alerts_utm.head(14).iterrows():
        pt = r.geometry.representative_point()
        ax1.annotate(
            r["patch_id"],
            (pt.x, pt.y),
            ha="center",
            va="center",
            fontsize=7,
            fontweight="bold",
            color="white",
            bbox=dict(boxstyle="round,pad=0.14", fc="#111111", ec="white", alpha=0.72, lw=0.5),
            zorder=7,
        )
    plot_landmarks(ax1, transformer)
    ax1.set_xlim(bounds.left, bounds.right)
    ax1.set_ylim(bounds.bottom, bounds.top)
    ax1.set_title("1. Semáforo Final (Regla del Peor Caso: Pérdida 2024→2026 + Home Range)", fontweight="bold", fontsize=10.5)
    ax1.set_xlabel("Este UTM 16N (m)")
    ax1.set_ylabel("Norte UTM 16N (m)")

    counts_final = alerts_utm["nivel_alerta"].value_counts()
    handles1 = [
        mpatches.Patch(color=LEVEL_COLORS[l], label=f"{l} ({counts_final.get(l, 0)} parches)")
        for l in ("Alto", "Moderado", "Bajo")
    ]
    ax1.legend(handles=handles1, loc="upper left", fontsize=8.5, framealpha=0.92, title="Nivel final")

    ax2 = fig.add_subplot(gs[0, 1])
    ax2.imshow(bg, extent=extent, origin="upper")
    corridors[corridors["in_mst"]].plot(ax=ax2, color="#555555", linewidth=1.2, alpha=0.65, zorder=3)
    for lvl in ("Bajo", "Moderado", "Alto"):
        sub = alerts_utm[alerts_utm["nivel_perdida"] == lvl]
        if len(sub) > 0:
            sub.plot(ax=ax2, facecolor=LEVEL_COLORS[lvl], edgecolor="#222222", linewidth=0.9, alpha=0.82, zorder=4)
    roads_major.plot(ax=ax2, color="#111111", linewidth=0.8, alpha=0.5, zorder=5)
    for _, r in alerts_utm.head(16).iterrows():
        pt = r.geometry.representative_point()
        lbl = f"{r['patch_id']} ({r['perdida_pct']:+.1f}%)" if abs(r["perdida_pct"]) >= 4.0 or r["area_ha"] >= 100 else r["patch_id"]
        ax2.annotate(
            lbl,
            (pt.x, pt.y),
            ha="center",
            va="center",
            fontsize=6.8,
            fontweight="bold",
            color="white",
            bbox=dict(boxstyle="round,pad=0.14", fc="#111111", ec="white", alpha=0.72, lw=0.5),
            zorder=7,
        )
    plot_landmarks(ax2, transformer)
    ax2.set_xlim(bounds.left, bounds.right)
    ax2.set_ylim(bounds.bottom, bounds.top)
    ax2.set_title("2. Criterio Pérdida de Vegetación NDVI (2024→2026, anillo 90 m)", fontweight="bold", fontsize=10.5)
    ax2.set_xlabel("Este UTM 16N (m)")
    ax2.set_ylabel("Norte UTM 16N (m)")

    counts_loss = alerts_utm["nivel_perdida"].value_counts()
    handles2 = [
        mpatches.Patch(color=LEVEL_COLORS["Alto"], label=f"Alto (>10% pérdida): {counts_loss.get('Alto', 0)}"),
        mpatches.Patch(color=LEVEL_COLORS["Moderado"], label=f"Moderado (5–10%): {counts_loss.get('Moderado', 0)}"),
        mpatches.Patch(color=LEVEL_COLORS["Bajo"], label=f"Bajo (<5%): {counts_loss.get('Bajo', 0)}"),
    ]
    ax2.legend(handles=handles2, loc="upper left", fontsize=8.5, framealpha=0.92, title="Pérdida 2024→2026")

    ax3 = fig.add_subplot(gs[1, :])
    df_bar = alerts_utm.sort_values("perdida_pct", ascending=False)
    colors_bar = [LEVEL_COLORS[lvl] for lvl in df_bar["nivel_perdida"]]
    x_pos = np.arange(len(df_bar))
    ax3.bar(x_pos, df_bar["perdida_pct"], color=colors_bar, edgecolor="#333333", linewidth=0.6)
    ax3.axhline(LOSS_MODERATE_PCT, color="#f9a825", linestyle="--", linewidth=1.3, label="Umbral Moderado (5%)")
    ax3.axhline(LOSS_HIGH_PCT, color="#c62828", linestyle="--", linewidth=1.3, label="Umbral Alto (10%)")
    ax3.axhline(0.0, color="#222222", linewidth=0.8)
    ax3.set_xticks(x_pos)
    ax3.set_xticklabels(df_bar["patch_id"], fontsize=8.5, fontweight="bold")
    ax3.set_ylabel("Pérdida veg. 2024→2026 (%)")
    ax3.set_title(
        "Cambio porcentual de área vegetada (NDVI ≥ 0.50) en 2 años (2024→2026) por parche",
        fontweight="bold",
        fontsize=10,
    )
    ax3.legend(loc="upper right", fontsize=8.5)
    ax3.grid(axis="y", alpha=0.25)

    out_png = OUTPUTS_DIR / "preview_vista3.png"
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"  [OK] Vista previa guardada en {out_png}")
    return out_png


def generate_interactive_map() -> Path:
    alerts = gpd.read_file(OUTPUTS_DIR / "alertas_parches.geojson")
    corridors = gpd.read_file(OUTPUTS_DIR / "corredores.geojson")

    m = folium.Map(location=[21.28, -86.88], zoom_start=12, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri WorldImagery",
        name="Satélite (Esri)",
    ).add_to(m)
    folium.TileLayer("OpenStreetMap", name="OpenStreetMap").add_to(m)

    g_final = folium.FeatureGroup(name="Semáforo Final (Peor Caso: Pérdida 2024→2026 + Home Range)", show=True)
    for _, row in alerts.iterrows():
        col = LEVEL_COLORS[row["nivel_alerta"]]
        popup_html = (
            f"<div style='font-family:sans-serif;font-size:12px;width:300px;'>"
            f"<b>Parche {row['patch_id']}</b> — Alerta: "
            f"<span style='color:{col};font-weight:bold;'>{row['nivel_alerta'].upper()}</span><br>"
            f"<b>Área:</b> {row['area_ha']:,.1f} ha ({row['pct_home_range']:.1f}% del home range)<br>"
            f"<b>Veg. 2024 → 2025 → 2026:</b> {row['veg_2024_ha']:,.1f} → {row['veg_2025_ha']:,.1f} → {row['veg_2026_ha']:,.1f} ha<br>"
            f"<b>Pérdida 2 años (2024→2026):</b> <b>{row['perdida_pct']:+.1f}%</b> ({row['perdida_ha']:+.1f} ha)<br>"
            f"<b>Nivel pérdida:</b> {row['nivel_perdida']} | <b>Nivel tamaño:</b> {row['nivel_tamano']}<br>"
            f"<b>Corredores:</b> {row['n_corredores']} (vecino más cercano: {row['dist_vecino_km']:.2f} km)<br>"
            f"<hr style='margin:5px 0;'>"
            f"<b>Motivo:</b> {row['motivo']}"
            f"</div>"
        )
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda _, c=col: {"fillColor": c, "color": "#111111", "weight": 1.6, "fillOpacity": 0.62},
            tooltip=f"{row['patch_id']} | Alerta: {row['nivel_alerta']} | Pérdida 24→26: {row['perdida_pct']:+.1f}% | {row['area_ha']:,.1f} ha",
            popup=folium.Popup(popup_html, max_width=330),
        ).add_to(g_final)
    g_final.add_to(m)

    g_loss = folium.FeatureGroup(name="Solo Pérdida de Vegetación NDVI (2024→2026)", show=False)
    for _, row in alerts.iterrows():
        col = LEVEL_COLORS[row["nivel_perdida"]]
        folium.GeoJson(
            row.geometry.__geo_interface__,
            style_function=lambda _, c=col: {"fillColor": c, "color": "#111111", "weight": 1.6, "fillOpacity": 0.62},
            tooltip=f"{row['patch_id']} | Pérdida 2024→2026: {row['perdida_pct']:+.1f}% ({row['nivel_perdida']})",
        ).add_to(g_loss)
    g_loss.add_to(m)

    folium.GeoJson(
        corridors,
        name="Corredores ecológicos",
        style_function=lambda feat: {
            "color": "#ffffff" if feat["properties"].get("in_mst") else "#ffd54f",
            "weight": 2.4 if feat["properties"].get("in_mst") else 1.5,
            "dashArray": None if feat["properties"].get("in_mst") else "5 4",
            "opacity": 0.9,
        },
        show=True,
    ).add_to(m)

    lm = folium.FeatureGroup(name="Puntos de referencia", show=True)
    for name, (lat, lon) in LANDMARKS.items():
        folium.CircleMarker(
            location=[lat, lon], radius=6, color="#000", fill=True, fill_color="#fff", fill_opacity=1.0, tooltip=name
        ).add_to(lm)
    lm.add_to(m)

    legend_html = """
    <div style="position:fixed;bottom:25px;left:25px;z-index:9999;background:rgba(255,255,255,0.93);
                padding:10px 14px;border-radius:8px;border:1px solid #888;font-family:sans-serif;font-size:12px;">
      <b>Vista 3 — Semáforo de Alertas (2024→2026)</b>
      <div style="margin-top:5px;"><span style="display:inline-block;width:13px;height:13px;background:#c62828;margin-right:6px;"></span><b>Alto</b> (pérdida &gt;10% o &lt;50% home range)</div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#f9a825;margin-right:6px;"></span><b>Moderado</b> (pérdida 5–10% o 50–100% HR)</div>
      <div><span style="display:inline-block;width:13px;height:13px;background:#2e7d32;margin-right:6px;"></span><b>Bajo</b> (pérdida &lt;5% y ≥100% HR)</div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))
    folium.LayerControl(collapsed=False).add_to(m)

    out_html = OUTPUTS_DIR / "mapa_vista3.html"
    m.save(str(out_html))
    print(f"  [OK] Mapa interactivo guardado en {out_html}")
    return out_html


def print_summary(alerts_utm: gpd.GeoDataFrame) -> None:
    print("\n" + "=" * 104)
    print("RESUMEN — VISTA 3: MONITOR DE UMBRALES Y ALERTAS EXPLICABLES (JAGUAR, 2024→2026)")
    print("=" * 104)
    c_final = alerts_utm["nivel_alerta"].value_counts()
    c_loss = alerts_utm["nivel_perdida"].value_counts()
    c_size = alerts_utm["nivel_tamano"].value_counts()
    print(
        f"Semáforo FINAL (peor caso) : Alto={c_final.get('Alto', 0)} | "
        f"Moderado={c_final.get('Moderado', 0)} | Bajo={c_final.get('Bajo', 0)}"
    )
    print(
        f"  - Solo por pérdida NDVI  : Alto={c_loss.get('Alto', 0)} | "
        f"Moderado={c_loss.get('Moderado', 0)} | Bajo={c_loss.get('Bajo', 0)}"
    )
    print(
        f"  - Solo por tamaño vs HR  : Alto={c_size.get('Alto', 0)} | "
        f"Moderado={c_size.get('Moderado', 0)} | Bajo={c_size.get('Bajo', 0)}"
    )

    print("\nDetalle por parche (ordenado por mayor pérdida 2024→2026):")
    print(
        f"  {'ID':<4} {'Área(ha)':>9} {'%HR':>6} {'Veg24':>8} {'Veg25':>8} {'Veg26':>8} {'P24→26':>8} "
        f"{'N.Pérd':<8} {'N.Tam':<8} {'FINAL':<8}"
    )
    print("  " + "-" * 96)
    for _, r in alerts_utm.sort_values("perdida_pct", ascending=False).iterrows():
        print(
            f"  {r['patch_id']:<4} {r['area_ha']:>9,.1f} {r['pct_home_range']:>6.1f} "
            f"{r['veg_2024_ha']:>8,.1f} {r['veg_2025_ha']:>8,.1f} {r['veg_2026_ha']:>8,.1f} "
            f"{r['perdida_pct']:>+7.1f}% {r['nivel_perdida']:<8} {r['nivel_tamano']:<8} {r['nivel_alerta']:<8}"
        )
    print("=" * 104)


def main() -> None:
    print("Calculando Vista 3: Monitor de Umbrales y Alertas (2024→2026)...")
    alerts_utm, ctx = evaluate_alerts()
    generate_preview(alerts_utm, ctx)
    generate_interactive_map()
    print_summary(alerts_utm)


if __name__ == "__main__":
    main()

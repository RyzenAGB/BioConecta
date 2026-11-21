"""
Sistema de diseño Soft Dark para BioConecta.
Centraliza la paleta de colores, escalas cartográficas y CSS reutilizable.
"""

import streamlit as st
from matplotlib.colors import LinearSegmentedColormap

COLORS = {
    "bg": "#1C2421",
    "sidebar": "#26332D",
    "surface": "#303C35",
    "surface_2": "#37443D",
    "primary": "#86A991",
    "forest": "#567C65",
    "forest_deep": "#2F5240",
    "sage": "#B7C9B5",
    "text": "#F0F1EA",
    "text_2": "#B6C1B9",
    "border": "#46544B",
    "warn": "#D3AC69",
    "risk_high": "#C77F75",
    "risk_low": "#80A68B",
    "carto_blue": "#7AADB7",
    "carto_teal": "#4F8A94",
    "carto_mustard": "#C9A24D",
    "carto_road": "#8A8178",
    "carto_plum": "#A38FA8",
}

LEVEL_COLORS = {
    "Bajo": "#22C55E",      # Verde semáforo claro
    "Moderado": "#F59E0B",  # Ámbar / Naranja intenso
    "Alto": "#EF4444",      # Rojo semáforo vivo
}

# Escala intuitiva de idoneidad respetando los cortes científicos (<0.40, 0.40-0.70, >=0.70)
HSM_CMAP = LinearSegmentedColormap.from_list(
    "bioconecta_hsm_intuitiva",
    [
        (0.00, "#D73027"),  # Baja (<0.40): rojo
        (0.38, "#F46D43"),  # Naranja
        (0.42, "#FEE08B"),  # Media (0.40-0.70): amarillo
        (0.68, "#D9EF8B"),  # Amarillo-verdoso
        (0.72, "#66BD63"),  # Alta / Núcleo (>=0.70): verde esmeralda
        (0.86, "#1A9850"),  # Verde intenso
        (1.00, "#00441B"),  # Óptima (1.0): verde bosque profundo
    ],
)

# Franja de corredor (Linkage Mapper) con alto contraste sobre selva verde
SWATH_CMAP = LinearSegmentedColormap.from_list(
    "bioconecta_swath_contraste",
    [
        (0.00, "#00000000"),
        (0.15, "#FFE57F77"),
        (0.50, "#FF9100CC"),
        (0.85, "#FF1744E6"),
        (1.00, "#D500F9FF"),
    ],
)

LEAFLET_CUSTOM_CSS = """
<style>
  @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Serif:wght@500;600;700&display=swap');

  .leaflet-container {
    font-family: 'IBM Plex Sans', system-ui, -apple-system, sans-serif !important;
    background: #1C2421 !important;
  }
  .leaflet-popup-content-wrapper {
    background: #F0F1EA !important;
    color: #1C2421 !important;
    border-radius: 12px !important;
    border: 1px solid #C5CEC4 !important;
    box-shadow: 0 8px 24px rgba(15, 22, 19, 0.32) !important;
    padding: 2px !important;
  }
  .leaflet-popup-tip {
    background: #F0F1EA !important;
  }
  .leaflet-popup-close-button {
    color: #46544B !important;
    font-size: 18px !important;
    padding: 6px 8px 0 0 !important;
  }
  .leaflet-tooltip {
    background: rgba(28, 36, 33, 0.94) !important;
    color: #F0F1EA !important;
    border: 1px solid #46544B !important;
    border-radius: 8px !important;
    padding: 6px 10px !important;
    font-size: 12.5px !important;
    line-height: 1.4 !important;
    box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35) !important;
  }
  .leaflet-tooltip-top:before { border-top-color: #46544B !important; }
  .leaflet-tooltip-bottom:before { border-bottom-color: #46544B !important; }
  .leaflet-tooltip-left:before { border-left-color: #46544B !important; }
  .leaflet-tooltip-right:before { border-right-color: #46544B !important; }
  .leaflet-bar {
    border: 1px solid rgba(70, 84, 75, 0.85) !important;
    border-radius: 10px !important;
    overflow: hidden;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.28) !important;
  }
  .leaflet-bar a {
    background-color: rgba(38, 51, 45, 0.92) !important;
    color: #F0F1EA !important;
    border-bottom: 1px solid #46544B !important;
    width: 30px !important;
    height: 30px !important;
    line-height: 30px !important;
  }
  .leaflet-bar a:hover {
    background-color: #37443D !important;
    color: #B7C9B5 !important;
  }
  .leaflet-control-attribution {
    background: rgba(28, 36, 33, 0.78) !important;
    color: #B6C1B9 !important;
    font-size: 11px !important;
    border-top-left-radius: 6px !important;
  }
  .leaflet-control-attribution a {
    color: #B7C9B5 !important;
  }
</style>
"""

APP_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&family=IBM+Plex+Serif:wght@500;600;700&display=swap');

:root {
  --bc-bg: #1C2421;
  --bc-sidebar: #26332D;
  --bc-surface: #303C35;
  --bc-surface-2: #37443D;
  --bc-primary: #86A991;
  --bc-forest: #567C65;
  --bc-sage: #B7C9B5;
  --bc-text: #F0F1EA;
  --bc-text-2: #B6C1B9;
  --bc-border: #46544B;
  --bc-warn: #D3AC69;
  --bc-risk-high: #C77F75;
  --bc-risk-low: #80A68B;
  --bc-carto-blue: #7AADB7;

  --bc-radius-sm: 10px;
  --bc-radius-md: 12px;
  --bc-radius-lg: 14px;
  --bc-shadow-sm: 0 2px 8px rgba(10, 15, 13, 0.22);
  --bc-shadow-md: 0 6px 20px rgba(10, 15, 13, 0.28);

  --bc-font-heading: 'IBM Plex Serif', Georgia, 'Times New Roman', serif;
  --bc-font-body: 'IBM Plex Sans', 'Segoe UI', system-ui, -apple-system, sans-serif;
}

/* --- Base tipográfica y layout --- */
html, body, [data-testid="stAppViewContainer"] {
  font-family: var(--bc-font-body);
  color: var(--bc-text);
  background-color: var(--bc-bg);
}

h1, h2, h3, .bc-title, .bc-brand-name, .bc-card-heading {
  font-family: var(--bc-font-heading);
  letter-spacing: -0.01em;
}

h4, .bc-metric-val {
  font-family: var(--bc-font-body);
  letter-spacing: -0.015em;
}

[data-testid="stDecoration"] {
  display: none;
}

[data-testid="stHeader"] {
  background: rgba(28, 36, 33, 0.85);
  backdrop-filter: blur(6px);
}

[data-testid="stMain"] {
  overflow-x: hidden;
  min-width: 0;
}

[data-testid="stMainBlockContainer"] {
  padding-top: 2rem;
  padding-bottom: 2.5rem;
  padding-left: 2rem;
  padding-right: 2rem;
  max-width: 1720px;
  min-width: 0;
}

/* --- Accesibilidad: foco visible --- */
button:focus-visible,
[role="tab"]:focus-visible,
[role="radiogroup"] label:focus-within,
input:focus-visible,
select:focus-visible {
  outline: 2px solid var(--bc-sage) !important;
  outline-offset: 2px !important;
}

/* --- Sidebar --- */
[data-testid="stSidebar"] {
  background-color: var(--bc-sidebar);
  border-right: 1px solid var(--bc-border);
}

[data-testid="stSidebar"] > div:first-child {
  padding-top: 1.25rem;
}

[data-testid="stSidebarUserContent"] {
  padding-top: 0.75rem;
  padding-bottom: 1.5rem;
}

.bc-brand {
  padding: 0.25rem 0 0.75rem 0;
  border-bottom: 1px solid var(--bc-border);
  margin-bottom: 0.9rem;
}

.bc-brand-top {
  display: flex;
  align-items: center;
  gap: 0.65rem;
}

.bc-brand-mark {
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: var(--bc-sage);
  flex-shrink: 0;
}

.bc-brand-name {
  font-size: 23px;
  font-weight: 600;
  color: var(--bc-text);
  line-height: 1.15;
  margin: 0;
}

.bc-brand-tagline {
  font-size: 13.5px;
  color: var(--bc-text-2);
  margin: 0.35rem 0 0.65rem 0;
  line-height: 1.4;
}

.bc-zone-chip {
  display: inline-flex;
  align-items: flex-start;
  gap: 0.4rem;
  padding: 0.42rem 0.65rem;
  border-radius: var(--bc-radius-sm);
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  font-size: 12px;
  line-height: 1.38;
  color: var(--bc-sage);
  width: 100%;
  box-sizing: border-box;
}

.bc-zone-chip svg {
  flex-shrink: 0;
  margin-top: 2px;
  color: var(--bc-primary);
}

.bc-section-label {
  font-family: var(--bc-font-body);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.07em;
  color: var(--bc-text-2);
  margin: 1.05rem 0 0.5rem 0;
}

.bc-section-label--tight {
  margin-top: 0.35rem;
}

/* Control segmentado para radios horizontales (mapa base y criterio de alertas) */
[data-testid="stRadio"] [role="radiogroup"] {
  gap: 0.4rem;
}

[data-testid="stSidebar"] [data-testid="stRadio"],
[data-testid="stSidebar"] [data-testid="stRadio"] > div {
  width: 100%;
}

[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  background: rgba(28, 36, 33, 0.5);
  padding: 5px;
  border-radius: var(--bc-radius-sm);
  border: 1px solid var(--bc-border);
  width: 100%;
  box-sizing: border-box;
}

[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label {
  background: transparent;
  border: 1px solid transparent;
  border-radius: 8px;
  padding: 0.44rem 0.65rem;
  margin: 0 !important;
  width: 100%;
  box-sizing: border-box;
  transition: background-color 140ms ease, border-color 140ms ease;
}

[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:hover {
  background: rgba(55, 68, 61, 0.65);
}

[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
  background: var(--bc-surface-2);
  border-color: var(--bc-primary);
}

[data-testid="stSidebar"] [data-testid="stRadio"] [role="radiogroup"] label p {
  font-size: 13px !important;
  font-weight: 600;
  color: var(--bc-text);
  white-space: nowrap;
}

/* --- Navegación principal (st.tabs) --- */
[data-testid="stTabs"] [data-baseweb="tab-list"] {
  gap: 0.35rem;
  border-bottom: 1px solid var(--bc-border);
  padding-bottom: 0;
  margin-bottom: 1.15rem;
  overflow-x: auto;
  scrollbar-width: thin;
}

[data-testid="stTabs"] [role="tab"] {
  font-family: var(--bc-font-body);
  font-size: 14px;
  font-weight: 600;
  color: var(--bc-text-2);
  background: transparent;
  border: 1px solid transparent;
  border-bottom: 2px solid transparent;
  border-radius: 10px 10px 0 0;
  padding: 0.65rem 1.05rem;
  white-space: nowrap;
  flex-shrink: 0;
  transition: color 140ms ease, background-color 140ms ease, border-color 140ms ease;
}

[data-testid="stTabs"] [role="tab"]:hover {
  color: var(--bc-text);
  background: rgba(48, 60, 53, 0.55);
}

[data-testid="stTabs"] [role="tab"][aria-selected="true"] {
  color: var(--bc-text);
  background: rgba(48, 60, 53, 0.85);
  border-color: var(--bc-border);
  border-bottom-color: var(--bc-primary);
}

[data-testid="stTabs"] [data-baseweb="tab-highlight"] {
  background-color: var(--bc-primary) !important;
  height: 3px !important;
  border-radius: 3px 3px 0 0;
}

[data-testid="stTabs"] [data-baseweb="tab-border"] {
  background-color: var(--bc-border) !important;
}

/* --- Encabezados de vista --- */
.bc-header {
  margin-bottom: 0.9rem;
}

.bc-eyebrow {
  font-family: var(--bc-font-body);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.09em;
  color: var(--bc-primary);
  margin-bottom: 0.2rem;
}

.bc-title {
  font-size: clamp(23px, 2vw, 28px);
  font-weight: 600;
  color: var(--bc-text);
  margin: 0;
  line-height: 1.24;
}

.bc-subtitle {
  font-size: 14.5px;
  color: var(--bc-text-2);
  margin: 0.3rem 0 0 0;
  line-height: 1.45;
}

/* --- Tarjetas de métricas --- */
.bc-metric-grid {
  display: grid;
  gap: 0.65rem;
  margin: 0.45rem 0 0.75rem 0;
}

.bc-metric-grid--2 {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.bc-metric-grid--3 {
  grid-template-columns: repeat(3, minmax(0, 1fr));
}

.bc-metric-grid--4 {
  grid-template-columns: repeat(4, minmax(0, 1fr));
}

.bc-metric-card {
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-md);
  padding: 0.85rem 0.95rem;
  box-shadow: var(--bc-shadow-sm);
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  min-width: 0;
  transition: border-color 140ms ease, background-color 140ms ease;
}

.bc-metric-card:hover {
  border-color: #5A6B61;
}

.bc-metric-card--compact {
  padding: 0.68rem 0.75rem;
}

.bc-metric-label {
  font-size: 12.5px;
  font-weight: 500;
  color: var(--bc-text-2);
  line-height: 1.3;
  margin-bottom: 0.35rem;
}

.bc-metric-val-row {
  display: flex;
  align-items: baseline;
  gap: 0.28rem;
  flex-wrap: wrap;
}

.bc-metric-val {
  font-size: clamp(22px, 1.9vw, 30px);
  font-weight: 700;
  color: var(--bc-text);
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}

.bc-metric-card--compact .bc-metric-val {
  font-size: 19px;
}

.bc-metric-unit {
  font-size: 13px;
  font-weight: 600;
  color: var(--bc-sage);
  white-space: nowrap;
}

.bc-metric-hint {
  font-size: 12px;
  color: var(--bc-text-2);
  margin-top: 0.3rem;
  line-height: 1.35;
}

/* --- Resumen compacto de alertas en sidebar --- */
.bc-alert-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 0.35rem;
  margin: 0.4rem 0 0.5rem 0;
}

.bc-alert-tile {
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-sm);
  padding: 0.48rem 0.2rem;
  text-align: center;
}

.bc-alert-tile-num {
  font-family: var(--bc-font-body);
  font-size: 20px;
  font-weight: 600;
  color: var(--bc-text);
  line-height: 1.15;
  font-variant-numeric: tabular-nums;
}

.bc-alert-tile-lbl {
  font-size: 12px;
  font-weight: 600;
  margin-top: 0.18rem;
  white-space: nowrap;
}

.bc-alert-tile--alto .bc-alert-tile-lbl { color: #E6B3AB; }
.bc-alert-tile--moderado .bc-alert-tile-lbl { color: #E5C78E; }
.bc-alert-tile--bajo .bc-alert-tile-lbl { color: #A8CCB2; }

.bc-sidebar-note {
  font-size: 12px;
  color: var(--bc-text-2);
  line-height: 1.45;
  margin: 0.25rem 0 0.4rem 0;
}

/* --- Badges de riesgo (forma + texto + color accesible) --- */
.bc-badge {
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  padding: 0.22rem 0.62rem;
  border-radius: 6px;
  font-family: var(--bc-font-body);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  white-space: nowrap;
  border: 1px solid var(--bc-border);
}

.bc-badge--alto {
  background: rgba(199, 127, 117, 0.14);
  color: #EBC0B9;
}

.bc-badge--moderado {
  background: rgba(211, 172, 105, 0.14);
  color: #ECD19E;
}

.bc-badge--bajo {
  background: rgba(128, 166, 139, 0.14);
  color: #B4D4BD;
}

/* --- Callouts sobrios --- */
.bc-callout {
  border-radius: var(--bc-radius-md);
  padding: 0.9rem 1.05rem;
  background: var(--bc-surface-2);
  border: 1px solid var(--bc-border);
  margin: 0.65rem 0;
  line-height: 1.55;
  font-size: 14px;
  color: var(--bc-text);
}

.bc-callout-title {
  font-family: var(--bc-font-body);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  margin-bottom: 0.38rem;
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.bc-callout--alto .bc-callout-title { color: #EBC0B9; }
.bc-callout--moderado .bc-callout-title { color: #ECD19E; }
.bc-callout--bajo .bc-callout-title { color: #B4D4BD; }
.bc-callout--info .bc-callout-title { color: #B2D4DB; }
.bc-callout--warn .bc-callout-title { color: #ECD19E; }

/* --- Leyendas cartográficas --- */
.bc-legend-bar {
  display: flex;
  flex-wrap: wrap;
  gap: 0.75rem 1.35rem;
  align-items: center;
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-md);
  padding: 0.7rem 1rem;
  margin: 0.6rem 0 0.85rem 0;
}

.bc-legend-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.55rem 0.95rem;
}

.bc-legend-title {
  font-family: var(--bc-font-body);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--bc-text-2);
  margin-right: 0.15rem;
}

.bc-legend-item {
  display: inline-flex;
  align-items: center;
  gap: 0.42rem;
  font-size: 13px;
  color: var(--bc-text);
  line-height: 1.3;
}

.bc-legend-desc {
  color: var(--bc-text-2);
  font-size: 12.5px;
}

.bc-swatch {
  display: inline-block;
  flex-shrink: 0;
}

.bc-swatch--box {
  width: 14px;
  height: 14px;
  border-radius: 4px;
  border: 1px solid rgba(240, 241, 234, 0.25);
}

.bc-swatch--dot {
  width: 11px;
  height: 11px;
  border-radius: 999px;
  border: 1.5px solid rgba(240, 241, 234, 0.45);
}

.bc-swatch--line {
  width: 22px;
  height: 3px;
  border-radius: 2px;
}

.bc-swatch--dashed {
  width: 22px;
  height: 0;
  border-top: 2.5px dashed;
}

.bc-legend-sep {
  width: 1px;
  height: 20px;
  background: var(--bc-border);
}

/* --- Ficha de especie en sidebar --- */
.bc-species-card {
  display: flex;
  flex-direction: column;
  gap: 0.55rem;
  font-size: 13px;
}

.bc-species-head {
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
  padding-bottom: 0.45rem;
  border-bottom: 1px solid var(--bc-border);
}

.bc-species-common {
  font-family: var(--bc-font-heading);
  font-size: 16px;
  font-weight: 600;
  color: var(--bc-text);
}

.bc-species-sci {
  font-size: 13px;
  font-style: italic;
  color: var(--bc-sage);
}

.bc-species-kv {
  display: flex;
  flex-direction: column;
  gap: 0.12rem;
}

.bc-species-k {
  font-size: 12px;
  color: var(--bc-text-2);
}

.bc-species-v {
  font-size: 13px;
  color: var(--bc-text);
  font-weight: 500;
  line-height: 1.38;
}

.bc-species-cite {
  font-size: 12px;
  color: var(--bc-text-2);
  font-style: italic;
  line-height: 1.42;
  padding-top: 0.4rem;
  border-top: 1px dashed var(--bc-border);
}

/* --- Panel de detalle del parche (Vista 3) --- */
.bc-patch-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.6rem;
  flex-wrap: wrap;
  padding: 0.65rem 0.85rem;
  background: var(--bc-surface-2);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-sm);
  margin: 0.35rem 0 0.65rem 0;
}

.bc-patch-id {
  font-family: var(--bc-font-heading);
  font-size: 20px;
  font-weight: 600;
  color: var(--bc-text);
}

.bc-patch-sub {
  font-size: 12.5px;
  color: var(--bc-text-2);
}

.bc-meta-row {
  display: flex;
  flex-wrap: wrap;
  gap: 0.45rem 0.9rem;
  font-size: 12.5px;
  color: var(--bc-text-2);
  padding-top: 0.55rem;
  border-top: 1px solid var(--bc-border);
  margin-top: 0.35rem;
}

.bc-meta-row strong {
  color: var(--bc-text);
  font-weight: 600;
}

.bc-chart-title {
  font-family: var(--bc-font-body);
  font-size: 13px;
  font-weight: 600;
  color: var(--bc-text);
  margin: 0.7rem 0 0.25rem 0;
}

.bc-chart-sub {
  font-size: 12px;
  color: var(--bc-text-2);
  margin-bottom: 0.35rem;
}

/* --- Contenedores nombrados con st.container(key=...) --- */
.st-key-toolbar-v1,
.st-key-toolbar-v2,
.st-key-toolbar-v3 {
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-md);
  padding: 0.65rem 1rem;
  margin-bottom: 0.75rem;
  box-shadow: var(--bc-shadow-sm);
}

.st-key-map-v1,
.st-key-map-v2,
.st-key-map-v3 {
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-lg);
  overflow: hidden;
  background: var(--bc-surface);
  box-shadow: var(--bc-shadow-md);
  padding: 0 !important;
}

.st-key-map-v1 iframe,
.st-key-map-v2 iframe,
.st-key-map-v3 iframe {
  display: block;
  border-radius: var(--bc-radius-lg);
}

.st-key-map-v1 [data-testid="stElementContainer"],
.st-key-map-v2 [data-testid="stElementContainer"],
.st-key-map-v3 [data-testid="stElementContainer"] {
  margin-bottom: -6px !important;
}

.st-key-patch-card {
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-lg);
  padding: 1.05rem 1.15rem;
  box-shadow: var(--bc-shadow-sm);
}

.st-key-card-table-v2,
.st-key-card-table-v3,
.st-key-card-val-results,
.st-key-card-val-table {
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-lg);
  padding: 1rem 1.15rem;
  margin-top: 0.85rem;
  box-shadow: var(--bc-shadow-sm);
}

.st-key-val-plate img {
  border-radius: 10px;
  border: 1px solid var(--bc-border);
}

.bc-card-heading,
[data-testid="stMarkdownContainer"] .bc-card-heading {
  font-family: var(--bc-font-heading);
  font-size: 19px !important;
  font-weight: 600;
  color: var(--bc-text);
  margin: 0 0 0.25rem 0;
  line-height: 1.3;
  padding: 0;
}

[data-testid="stMarkdownContainer"] .bc-title {
  font-size: clamp(24px, 2vw, 28px) !important;
  font-weight: 600;
  color: var(--bc-text);
  margin: 0;
  padding: 0;
  line-height: 1.24;
}

.bc-card-desc {
  font-size: 13.5px;
  color: var(--bc-text-2);
  margin: 0 0 0.65rem 0;
  line-height: 1.45;
}

/* Popover scroll seguro en pantallas de 768-900px de alto */
[data-testid="stPopoverBody"] {
  max-height: 76vh;
  overflow-y: auto;
  border-radius: var(--bc-radius-md) !important;
  border: 1px solid var(--bc-border) !important;
  background-color: var(--bc-sidebar) !important;
}

/* Refinamiento de widgets nativos (expander, popover, botones, dataframe) */
[data-testid="stExpander"] {
  background: var(--bc-surface);
  border: 1px solid var(--bc-border);
  border-radius: var(--bc-radius-md);
}

[data-testid="stExpander"] summary {
  font-family: var(--bc-font-body);
  font-weight: 600;
  font-size: 13.5px;
  color: var(--bc-text);
}

[data-testid="stPopover"] button,
[data-testid="stDownloadButton"] button,
[data-testid="stButton"] button {
  border-radius: var(--bc-radius-sm) !important;
  border: 1px solid var(--bc-border) !important;
  background-color: var(--bc-surface-2) !important;
  color: var(--bc-text) !important;
  font-weight: 600 !important;
  font-size: 13.5px !important;
  transition: border-color 140ms ease, background-color 140ms ease;
}

[data-testid="stPopover"] button:hover,
[data-testid="stDownloadButton"] button:hover,
[data-testid="stButton"] button:hover {
  border-color: var(--bc-primary) !important;
  background-color: rgba(86, 124, 101, 0.28) !important;
}

[data-testid="stCheckbox"] label p,
[data-testid="stToggle"] label p {
  font-size: 13.5px !important;
  color: var(--bc-text) !important;
  font-weight: 500;
}

/* --- Responsive --- */
@media (max-width: 1400px) {
  [data-testid="stMainBlockContainer"] {
    padding-left: 1.35rem;
    padding-right: 1.35rem;
    padding-top: 1.65rem;
  }
  .bc-metric-val {
    font-size: clamp(20px, 1.8vw, 26px);
  }
}

@media (max-width: 1120px) {
  .bc-metric-grid--4 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .st-key-vista3-split [data-testid="stHorizontalBlock"],
  .st-key-val-callouts [data-testid="stHorizontalBlock"] {
    flex-direction: column !important;
    gap: 0.85rem !important;
  }
  .st-key-vista3-split [data-testid="stColumn"],
  .st-key-val-callouts [data-testid="stColumn"] {
    width: 100% !important;
    min-width: 0 !important;
    flex: 1 1 100% !important;
  }
  .st-key-toolbar-v1 [data-testid="stHorizontalBlock"],
  .st-key-toolbar-v2 [data-testid="stHorizontalBlock"] {
    flex-wrap: wrap !important;
  }
}

@media (max-width: 860px) {
  [data-testid="stMainBlockContainer"] {
    padding-left: 0.9rem;
    padding-right: 0.9rem;
  }
  .bc-metric-grid--3,
  .bc-metric-grid--4 {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .bc-legend-sep {
    display: none;
  }
}

@media (max-width: 600px) {
  .bc-metric-grid--2,
  .bc-metric-grid--3,
  .bc-metric-grid--4 {
    grid-template-columns: 1fr;
  }
}
</style>
"""


def inject_css() -> None:
    """Inyecta la hoja de estilos centralizada Soft Dark en la aplicación."""
    st.markdown(APP_CSS, unsafe_allow_html=True)

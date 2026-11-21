"""
Componentes de presentación reutilizables para BioConecta.
Solo renderizan HTML/visualizaciones a partir de datos ya calculados.
"""

from html import escape
from typing import Iterable, Optional

import altair as alt
import pandas as pd
import streamlit as st

from ui.theme import COLORS


def _svg_brand_mark() -> str:
    return (
        "<svg width='20' height='20' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='1.9' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>"
        "<path d='M12 21c4.5-2.6 8-6.4 8-11.5A8 8 0 0 0 4 9.5C4 14.6 7.5 18.4 12 21Z'/>"
        "<circle cx='12' cy='9.5' r='2.5'/>"
        "</svg>"
    )


def _svg_pin() -> str:
    return (
        "<svg width='13' height='13' viewBox='0 0 24 24' fill='none' "
        "stroke='currentColor' stroke-width='2' stroke-linecap='round' stroke-linejoin='round' aria-hidden='true'>"
        "<path d='M20 10c0 6-8 12-8 12s-8-6-8-12a8 8 0 0 1 16 0Z'/>"
        "<circle cx='12' cy='10' r='3'/>"
        "</svg>"
    )


def sidebar_brand(study_area: str) -> None:
    """Renderiza el encabezado de marca y la zona de estudio en el sidebar."""
    st.markdown(
        f"""
        <div class="bc-brand">
          <div class="bc-brand-top">
            <span class="bc-brand-mark">{_svg_brand_mark()}</span>
            <h1 class="bc-brand-name">BioConecta</h1>
          </div>
          <p class="bc-brand-tagline">Inteligencia geoespacial para la conservación</p>
          <div class="bc-zone-chip">
            {_svg_pin()}
            <span><strong>Zona de estudio:</strong> {escape(study_area)}</span>
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def section_label(text: str, tight: bool = False) -> None:
    cls = "bc-section-label bc-section-label--tight" if tight else "bc-section-label"
    st.markdown(f"<div class='{cls}'>{escape(text)}</div>", unsafe_allow_html=True)


def page_header(eyebrow: str, title: str, subtitle: str = "") -> None:
    sub_html = f"<p class='bc-subtitle'>{escape(subtitle)}</p>" if subtitle else ""
    st.markdown(
        f"""
        <div class="bc-header">
          <div class="bc-eyebrow">{escape(eyebrow)}</div>
          <h2 class="bc-title">{escape(title)}</h2>
          {sub_html}
        </div>
        """,
        unsafe_allow_html=True,
    )


def card_heading(title: str, desc: str = "") -> None:
    desc_html = f"<p class='bc-card-desc'>{escape(desc)}</p>" if desc else ""
    st.markdown(
        f"<div class='bc-card-heading' role='heading' aria-level='3'>{escape(title)}</div>{desc_html}",
        unsafe_allow_html=True,
    )


def risk_badge_html(level: str) -> str:
    """Devuelve HTML de un badge de riesgo con forma geométrica + texto."""
    norm = level.strip().lower()
    if norm == "alto":
        cls, sym, lbl = "bc-badge--alto", "&#9650;", "Alto"
    elif norm == "moderado":
        cls, sym, lbl = "bc-badge--moderado", "&#9670;", "Moderado"
    else:
        cls, sym, lbl = "bc-badge--bajo", "&#9679;", "Bajo"
    return f"<span class='bc-badge {cls}'><span aria-hidden='true'>{sym}</span> {lbl}</span>"


def metric_grid(items: Iterable[dict], cols: int = 3, compact: bool = False) -> None:
    """
    Renderiza una grilla de tarjetas métricas sin truncamiento.
    Cada item admite: label, value, unit (opcional), hint (opcional),
    accent (opcional: 'high'|'mod'|'low'|'info'|'sage'), badge_level (opcional).
    """
    cards_html = []
    for item in items:
        accent = item.get("accent")
        accent_cls = f" bc-metric-card--accent-{accent}" if accent else ""
        compact_cls = " bc-metric-card--compact" if compact else ""

        if item.get("badge_level"):
            val_block = f"<div class='bc-metric-val-row'>{risk_badge_html(item['badge_level'])}</div>"
        else:
            unit_html = f"<span class='bc-metric-unit'>{escape(item['unit'])}</span>" if item.get("unit") else ""
            val_block = (
                "<div class='bc-metric-val-row'>"
                f"<span class='bc-metric-val'>{escape(str(item['value']))}</span>"
                f"{unit_html}"
                "</div>"
            )

        hint_html = f"<div class='bc-metric-hint'>{escape(item['hint'])}</div>" if item.get("hint") else ""
        cards_html.append(
            f"<div class='bc-metric-card{compact_cls}{accent_cls}'>"
            f"<div class='bc-metric-label'>{escape(item['label'])}</div>"
            f"{val_block}"
            f"{hint_html}"
            "</div>"
        )

    st.markdown(
        f"<div class='bc-metric-grid bc-metric-grid--{cols}'>{''.join(cards_html)}</div>",
        unsafe_allow_html=True,
    )


def sidebar_alert_summary(n_alto: int, n_mod: int, n_bajo: int, n_p_alto: int, n_p_mod: int) -> None:
    """Bloque de conteo de alertas por nivel en el sidebar."""
    st.markdown(
        f"""
        <div class="bc-alert-strip">
          <div class="bc-alert-tile bc-alert-tile--alto">
            <div class="bc-alert-tile-num">{n_alto}</div>
            <div class="bc-alert-tile-lbl">&#9650; Alto</div>
          </div>
          <div class="bc-alert-tile bc-alert-tile--moderado">
            <div class="bc-alert-tile-num">{n_mod}</div>
            <div class="bc-alert-tile-lbl">&#9670; Moderado</div>
          </div>
          <div class="bc-alert-tile bc-alert-tile--bajo">
            <div class="bc-alert-tile-num">{n_bajo}</div>
            <div class="bc-alert-tile-lbl">&#9679; Bajo</div>
          </div>
        </div>
        <p class="bc-sidebar-note">
          Pérdida activa NDVI (2024&rarr;2026): <strong>{n_p_alto}</strong> Alto (&gt;10%) y
          <strong>{n_p_mod}</strong> Moderado (5&ndash;10%).
        </p>
        """,
        unsafe_allow_html=True,
    )


def species_card(profile: dict) -> None:
    """Ficha limpia de la especie focal usando los datos de SPECIES_PROFILE."""
    hr_ha = profile["home_range_ha"]
    st.markdown(
        f"""
        <div class="bc-species-card">
          <div class="bc-species-head">
            <span class="bc-species-common">{escape(profile['common_name'])}</span>
            <span class="bc-species-sci">{escape(profile['scientific_name'])}</span>
          </div>
          <div class="bc-species-kv">
            <span class="bc-species-k">Estatus en México</span>
            <span class="bc-species-v">{escape(profile['status_mexico'])}</span>
          </div>
          <div class="bc-species-kv">
            <span class="bc-species-k">Estatus global</span>
            <span class="bc-species-v">{escape(profile['status_iucn'])}</span>
          </div>
          <div class="bc-species-kv">
            <span class="bc-species-k">Home range mínimo</span>
            <span class="bc-species-v">{hr_ha:,.0f} ha (36 km&sup2;)</span>
          </div>
          <div class="bc-species-cite">{escape(profile['home_range_citation'])}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def callout(kind: str, title: str, body: str, allow_html: bool = False) -> None:
    """
    Bloque destacado suave (kind: 'alto'|'moderado'|'bajo'|'info'|'warn').
    """
    icons = {
        "alto": "&#9650;",
        "moderado": "&#9670;",
        "bajo": "&#9679;",
        "info": "&#8505;",
        "warn": "&#9888;",
    }
    sym = icons.get(kind, "&#8505;")
    body_safe = body if allow_html else escape(body)
    st.markdown(
        f"""
        <div class="bc-callout bc-callout--{escape(kind)}">
          <div class="bc-callout-title"><span aria-hidden="true">{sym}</span> {escape(title)}</div>
          <div>{body_safe}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def legend_bar(groups: Iterable[dict]) -> None:
    """
    Barra de leyenda cartográfica con uno o más grupos.
    Cada grupo: {"title": str, "items": [{"kind": "box"|"dot"|"line"|"dashed", "color": str, "label": str, "desc": str}]}
    """
    parts = []
    group_list = list(groups)
    for idx, grp in enumerate(group_list):
        if idx > 0:
            parts.append("<span class='bc-legend-sep' aria-hidden='true'></span>")
        items_html = []
        for it in grp["items"]:
            kind = it.get("kind", "box")
            color = escape(it["color"])
            if kind == "dashed":
                sw = f"<span class='bc-swatch bc-swatch--dashed' style='border-top-color:{color};'></span>"
            elif kind == "line":
                sw = f"<span class='bc-swatch bc-swatch--line' style='background:{color};'></span>"
            elif kind == "dot":
                sw = f"<span class='bc-swatch bc-swatch--dot' style='background:{color};'></span>"
            else:
                sw = f"<span class='bc-swatch bc-swatch--box' style='background:{color};'></span>"

            desc = f" <span class='bc-legend-desc'>{escape(it['desc'])}</span>" if it.get("desc") else ""
            items_html.append(f"<span class='bc-legend-item'>{sw}<span>{escape(it['label'])}{desc}</span></span>")

        parts.append(
            "<div class='bc-legend-group'>"
            f"<span class='bc-legend-title'>{escape(grp['title'])}</span>"
            f"{''.join(items_html)}"
            "</div>"
        )

    st.markdown(f"<div class='bc-legend-bar'>{''.join(parts)}</div>", unsafe_allow_html=True)


def patch_header(patch_id: str, level: str, dominant_lc: str) -> None:
    st.markdown(
        f"""
        <div class="bc-patch-head">
          <div>
            <div class="bc-patch-id">Parche {escape(patch_id)}</div>
            <div class="bc-patch-sub">{escape(dominant_lc)}</div>
          </div>
          {risk_badge_html(level)}
        </div>
        """,
        unsafe_allow_html=True,
    )


def patch_vegetation_chart(veg_2024: float, veg_2025: float, veg_2026: float, level: str) -> alt.Chart:
    """Gráfico temporal de área vegetada (NDVI >= 0.50) con tipografía y paleta Soft Dark."""
    df = pd.DataFrame(
        {
            "Año": ["2024", "2025", "2026"],
            "Hectáreas vegetadas": [float(veg_2024), float(veg_2025), float(veg_2026)],
        }
    )
    bar_color = {
        "Alto": COLORS["risk_high"],
        "Moderado": COLORS["warn"],
        "Bajo": COLORS["primary"],
    }.get(level, COLORS["primary"])

    max_val = max(df["Hectáreas vegetadas"].max(), 1.0)
    y_domain = [0, max_val * 1.18]

    base = alt.Chart(df).encode(
        x=alt.X(
            "Año:N",
            axis=alt.Axis(
                title=None,
                labelAngle=0,
                labelColor=COLORS["text"],
                labelFont="IBM Plex Sans",
                labelFontSize=12.5,
                domainColor=COLORS["border"],
                tickSize=0,
            ),
        ),
        y=alt.Y(
            "Hectáreas vegetadas:Q",
            scale=alt.Scale(domain=y_domain),
            axis=alt.Axis(
                title="ha",
                titleColor=COLORS["text_2"],
                titleFont="IBM Plex Sans",
                titleFontSize=12,
                labelColor=COLORS["text_2"],
                labelFont="IBM Plex Sans",
                labelFontSize=12,
                gridColor="#3E4C44",
                gridDash=[3, 3],
                domain=False,
                tickSize=0,
                tickCount=4,
            ),
        ),
    )

    bars = base.mark_bar(
        cornerRadiusTopLeft=6,
        cornerRadiusTopRight=6,
        width=48,
        color=bar_color,
    ).encode(
        tooltip=[
            alt.Tooltip("Año:N", title="Año"),
            alt.Tooltip("Hectáreas vegetadas:Q", title="Área vegetada (ha)", format=",.1f"),
        ]
    )

    labels = base.mark_text(
        dy=-8,
        color=COLORS["text"],
        font="IBM Plex Sans",
        fontSize=12,
        fontWeight=600,
    ).encode(
        text=alt.Text("Hectáreas vegetadas:Q", format=",.1f")
    )

    return (
        (bars + labels)
        .properties(height=185, width="container")
        .configure_view(strokeWidth=0, fill="transparent")
        .configure(background="transparent")
    )


def patch_footer_meta(mean_hsm: float, n_corridors: int, dist_vecino_km: float, toca_borde: Optional[bool] = None) -> None:
    borde_txt = ""
    if toca_borde is not None:
        borde_txt = f"<span>Toca borde AOI: <strong>{'Sí' if toca_borde else 'No'}</strong></span>"
    st.markdown(
        f"""
        <div class="bc-meta-row">
          <span>Idoneidad media: <strong>{mean_hsm:.3f}</strong></span>
          <span>Corredores conectados: <strong>{int(n_corridors)}</strong></span>
          <span>Vecino más cercano: <strong>{dist_vecino_km:.2f} km</strong></span>
          {borde_txt}
        </div>
        """,
        unsafe_allow_html=True,
    )

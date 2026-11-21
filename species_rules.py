"""
Fase 1: Caracterización ecológica de la especie focal — Jaguar (Panthera onca).

Centraliza todas las reglas biológicas, parámetros de modelado de idoneidad (HSM),
superficie de resistencia (conectividad) y umbrales de alerta aprobados en el plan.
"""

SPECIES_PROFILE = {
    "common_name": "Jaguar",
    "scientific_name": "Panthera onca",
    "status_mexico": "En Peligro de Extinción (NOM-059-SEMARNAT-2010)",
    "status_iucn": "Casi Amenazado (NT — UICN)",
    "home_range_ha": 3600.0,  # 36 km²
    "home_range_citation": (
        "Chávez, C. & Ceballos, G. (telemetría en la Reserva de la Biosfera de Calakmul, "
        "Península de Yucatán: estimación base de 36–56 km², con rangos extendidos mayores "
        "por GPS de largo plazo)."
    ),
    "ecological_notes": (
        "Depredador tope que requiere cobertura de selva continua, acceso a fuentes de agua "
        "(cenotes, humedales, lagunas) y baja perturbación por carreteras y expansión urbana."
    ),
}

# --- VISTA 1: IDONEIDAD DE HÁBITAT (HSM) ---

# Puntaje S_cob (0 a 1) por clase de ESA WorldCover
LANDCOVER_SCORES = {
    10: 1.0,  # Selva / Cobertura arbórea
    95: 0.7,  # Manglar
    90: 0.5,  # Humedal herbáceo
    20: 0.5,  # Matorral
    30: 0.3,  # Pastizal
    40: 0.2,  # Cultivos
    60: 0.1,  # Suelo desnudo / Vegetación escasa
    50: 0.0,  # Zona urbana / Construida
    80: 0.0,  # Cuerpos de agua permanentes
}

# Reescalado lineal de NDVI (estado actual) -> S_ndvi en [0, 1]
NDVI_SCORE_MIN = 0.2
NDVI_SCORE_MAX = 0.8

# Parámetros de decaimiento exponencial para distancias (en metros)
# Para perturbación (carreteras y urbano): S(d) = 1 - exp(-d / k), alcanza ~0.95 en D_0.95 = 3*k
DIST_95_ROADS_M = {
    3: 1000.0,  # Avenida / carretera principal (k ≈ 333.3 m)
    2: 500.0,   # Calle local / residencial     (k ≈ 166.7 m)
    1: 250.0,   # Terracería / brecha           (k ≈ 83.3 m)
}
DIST_95_URBAN_M = 2000.0  # k ≈ 666.7 m

# Para agua (inversa: estar cerca es bueno): S_agua(d) = exp(-d / k), cae a ~0.05 en 3*k = 3000 m
WATER_DECAY_K_M = 1000.0

# Pesos de la suma ponderada H(x) = sum(w_i * S_i(x))
HSM_WEIGHTS = {
    "cob": 0.35,
    "ndvi": 0.15,
    "roads": 0.20,
    "urban": 0.20,
    "water": 0.10,
}

# Filtro de exclusión de matriz urbana/turística consolidada y enclaves aislados
# (evita marcar lotes baldíos urbanos o la barra hotelera costera como hábitat de jaguar)
URBAN_MATRIX_RADIUS_M = 300.0           # Radio de vecindad para densidad urbana/turística/vial
URBAN_MATRIX_DENSITY_THRESHOLD = 0.35   # >= 35% construido/resorts/calles en 300 m -> matriz urbana/turística
MIN_NATURAL_ENCLAVE_HA = 500.0          # Enclaves completamente desconectados por ciudad/resorts y agua < 500 ha (< 14% HR) se excluyen

# --- VISTA 2: CONECTIVIDAD ECOLÓGICA ---

PATCH_SUITABILITY_THRESHOLD = 0.70
PATCH_MIN_AREA_HA = 10.0

# Tabla base de costos de resistencia (escala 1 a 100)
LANDCOVER_RESISTANCE = {
    10: 1.0,    # Selva
    95: 5.0,    # Manglar
    90: 10.0,   # Humedal
    20: 15.0,   # Matorral
    30: 15.0,   # Pastizal
    40: 30.0,   # Cultivos
    60: 40.0,   # Suelo desnudo
    50: 100.0,  # Zona urbana
    80: 100.0,  # Agua permanente (barrera)
}

ROAD_RESISTANCE = {
    1: 20.0,  # Terracería / brecha
    2: 50.0,  # Calle local
    3: 80.0,  # Avenida / carretera pavimentada
}

# Mezcla híbrida 50/50 entre tabla de costos e idoneidad invertida
RESISTANCE_TABLE_WEIGHT = 0.50
RESISTANCE_HSM_WEIGHT = 0.50

# --- VISTA 3: UMBRALES Y ALERTAS ---

NDVI_VEGETATED_THRESHOLD = 0.50
ALERT_BUFFER_RING_M = 90.0  # Anillo de 90 m (3 píxeles) alrededor del parche

# Cortes de pérdida porcentual P = (A_{t-1} - A_t) / A_{t-1} * 100
LOSS_MODERATE_PCT = 5.0
LOSS_HIGH_PCT = 10.0

# Cortes de tamaño relativo respecto al home range (3,600 ha)
HOME_RANGE_HIGH_RATIO = 0.50      # < 50% (< 1,800 ha) -> Alto
HOME_RANGE_MODERATE_RATIO = 1.00  # 50% a < 100% -> Moderado; >= 100% -> Bajo

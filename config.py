from pathlib import Path

# Rutas del proyecto
PROJECT_ROOT = Path(__file__).resolve().parent
DATA_DIR = PROJECT_ROOT / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
DATA_PROCESSED_DIR = DATA_DIR / "processed"

# Zona piloto: UNICARIBE – Rancho Viejo – Zona Continental de Isla Mujeres (Quintana Roo)
# Formato: (min_lon, min_lat, max_lon, max_lat) en WGS84 (EPSG:4326)
AOI_BBOX_WGS84 = (-86.98, 21.18, -86.78, 21.39)

# Bbox regional ampliado solo para contexto de avistamientos GBIF (norte de Quintana Roo)
REGIONAL_BBOX_WGS84 = (-87.35, 20.90, -86.75, 21.50)

# Sistema de coordenadas métrico (UTM Zona 16N para Quintana Roo) y resolución espacial
TARGET_CRS = "EPSG:32616"
TARGET_RESOLUTION_M = 30.0  # píxeles de 30 x 30 metros

# Puntos de referencia de la zona piloto
LANDMARKS = {
    "UNICARIBE": (21.2005, -86.8236),
    "Rancho Viejo": (21.2566, -86.9104),
    "Ciudad Mujeres": (21.2414, -86.8599),
    "Isla Blanca": (21.3744, -86.7929),
}

# Clases de ESA WorldCover 10m
ESA_WORLDCOVER_CLASSES = {
    10: "Selva / Cobertura arbórea",
    20: "Matorral",
    30: "Pastizal",
    40: "Cultivos",
    50: "Zona urbana / Construida",
    60: "Suelo desnudo / Vegetación escasa",
    70: "Nieve y hielo",
    80: "Cuerpos de agua permanentes",
    90: "Humedal herbáceo",
    95: "Manglar",
    100: "Musgo y liquen",
}

# URLs públicas de ESA WorldCover (Tile N21W087 cubre 21°N-24°N, 87°W-84°W)
ESA_WORLDCOVER_URLS = {
    2020: "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v100/2020/map/ESA_WorldCover_10m_2020_v100_N21W087_Map.tif",
    2021: "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N21W087_Map.tif",
}

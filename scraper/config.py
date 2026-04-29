import os

SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

BASE_URL = "https://www.plusvalia.com/venta"

# Slugs confirmados desde plusvalia.com
# Los que tienen "q_" usan búsqueda por keyword en lugar de sector directo
SECTORES = {
    "samborondon":          "Samborondón",
    "la-puntilla":          "La Puntilla",
    "norte-de-guayaquil":   "Norte de Guayaquil",
    "los-ceibos":           "Los Ceibos",
    # Sectores por query keyword (no tienen slug propio en Plusvalía)
    "q-centro":             "Centro de Guayaquil",
    "q-via-a-la-costa":     "Vía a la Costa",
    "q-leon-febres-cordero":"Av. León Febres Cordero",
    "q-via-a-salitre":      "Vía a Salitre",
    "q-narcisa-de-jesus":   "Narcisa de Jesús",
}

TIPOS = {
    "casas":              "Casa",
    "departamentos":      "Departamento",
    "oficinas":           "Oficina",
    "consultorios":       "Consultorio",
    "terrenos":           "Terreno",
    "locales-comerciales":"Local Comercial",
}

MAX_PAGINAS    = 5    # robots.txt permite hasta página 5
DELAY_SEGUNDOS = 3    # pausa entre requests (respetuoso con el servidor)
TIMEOUT_MS     = 30_000


def build_url(tipo: str, sector_key: str, page: int = 1) -> str:
    """
    Construye la URL de búsqueda de Plusvalía.
    Sectores que empiezan con 'q-' usan el path /q-keyword en lugar de /sector-slug.
    """
    if sector_key.startswith("q-"):
        keyword = sector_key[2:]  # quitar el prefijo "q-"
        path = f"{BASE_URL}/{tipo}/guayas/guayaquil/q-{keyword}"
    else:
        path = f"{BASE_URL}/{tipo}/guayas/guayaquil/{sector_key}"

    if page > 1:
        return f"{path}?page={page}"
    return path

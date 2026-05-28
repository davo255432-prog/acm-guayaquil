import os
import pathlib

# Cargar variables desde .env en la raíz del proyecto (un nivel arriba de scraper/)
_env_path = pathlib.Path(__file__).parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _v = _line.split("=", 1)
                os.environ.setdefault(_k.strip(), _v.strip())

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

MAX_PAGINAS          = 2   # páginas por sector (conserva créditos)
MAX_PAGINAS_URB      = 3   # 3 páginas × ~20 props = ~60 por urb (La Joya tiene 112 en Plusvalía)
DELAY_SEGUNDOS       = 3
MAX_ENRIQUECIMIENTO  = 3   # detalles a visitar por página (0 = desactivado)
TIMEOUT_MS      = 30_000

# Tipos que se scrapeán a nivel de urbanización (los más relevantes para ACM)
TIPOS_URB = {"casas", "departamentos"}

# Urbanizaciones por sector — se scrapeán con q-slug dentro del sector
URBANIZACIONES = {
    "samborondon": [
        "villa-club", "volare", "la-joya", "la-rioja", "terrasol",
        "ciudad-celeste", "aires-del-batan", "parques-del-rio",
        "savali", "isla-mocoli", "boreal", "la-gran-victoria",
        "punta-barranca", "blue-bay", "guayaquil-tenis-club",
        "isla-celeste", "bouganville", "estancias-del-rio",
    ],
    "la-puntilla": [
        "ciudad-celeste", "isla-celeste", "los-lagos", "entre-rios",
        "parques-del-rio", "colinas-del-sol", "parques-del-salado",
    ],
    "norte-de-guayaquil": [
        "urdesa", "kennedy", "alborada", "la-garzota",
        "sauces", "guayacanes", "miraflores", "los-vergeles",
    ],
    "los-ceibos": [
        "ceibos-norte", "los-olivos", "colinas-de-los-ceibos",
        "parques-de-los-ceibos", "las-cumbres", "santa-cecilia",
    ],
    "q-via-a-la-costa": [
        "puerto-azul", "laguna-club", "bosques-de-la-costa",
        "costalmar", "alba-del-bosque", "bosquetto",
        "los-arrayanes", "buenaventura",
    ],
    "q-leon-febres-cordero": [
        # La Joya — búsqueda general + etapas clave por separado
        "la-joya", "la-joya-aguamarina", "la-joya-quarzo",
        "la-joya-opalo", "la-joya-turquesa", "la-joya-onix",
        # Otras urbs del sector
        "volare", "villa-club",
        "la-rioja", "la-gran-victoria", "el-condado", "vicolinci",
        "vistana", "la-aurora", "plaza-madeira",
    ],
    "q-narcisa-de-jesus": [
        "metropolis", "ciudad-del-rio", "la-perla",
        "acuarela-del-rio", "paraiso-del-rio", "victoria-del-rio",
        "narcisa-club", "horizonte-dorado", "la-romareda",
    ],
    "q-via-a-salitre": [
        "las-orquideas", "los-almendros", "villa-hermosa",
        "la-gran-victoria", "la-rioja", "savali", "mallorca-village",
        "arboletta", "los-pinos-del-rio", "santa-maria-casa-grande",
        "ciudad-del-sol", "parques-del-sol", "los-rosales",
        "villa-del-rey", "la-campiña", "san-jose-del-rio",
        "los-jardines", "portal-del-rio", "los-cerezos",
    ],
}


def build_url(tipo: str, sector_key: str, page: int = 1) -> str:
    if sector_key.startswith("q-"):
        keyword = sector_key[2:]
        path = f"{BASE_URL}/{tipo}/guayas/guayaquil/q-{keyword}"
    else:
        path = f"{BASE_URL}/{tipo}/guayas/guayaquil/{sector_key}"
    if page > 1:
        return f"{path}?page={page}"
    return path


def build_url_urb(tipo: str, sector_key: str, urb_slug: str, page: int = 1) -> str:
    """URL para una urbanización específica dentro de un sector."""
    if sector_key.startswith("q-"):
        keyword = sector_key[2:]
        path = f"{BASE_URL}/{tipo}/guayas/guayaquil/q-{keyword}/q-{urb_slug}"
    else:
        path = f"{BASE_URL}/{tipo}/guayas/guayaquil/{sector_key}/q-{urb_slug}"
    if page > 1:
        return f"{path}?page={page}"
    return path

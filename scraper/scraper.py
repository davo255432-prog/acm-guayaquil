"""
ACM Guayaquil — Scraper de Plusvalía.com
Usa httpx + BeautifulSoup (sin navegador) para máxima compatibilidad.
Corre automáticamente cada 24h en Render.com.

REQUISITO SUPABASE STORAGE:
  1. Crear bucket "imagenes" en Supabase → Storage → New bucket
  2. Activar "Public bucket" al crearlo (o agregar policy SELECT para anon)
"""

import hashlib
import json
import logging
import re
import time

import httpx
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from supabase import create_client

from config import (
    SUPABASE_URL, SUPABASE_KEY,
    SECTORES, TIPOS, URBANIZACIONES, TIPOS_URB,
    MAX_PAGINAS, MAX_PAGINAS_URB, DELAY_SEGUNDOS, MAX_ENRIQUECIMIENTO,
    build_url, build_url_urb,
)
from detalle_propiedad import extraer_detalle_propiedad

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/136.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "es-EC,es;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "sec-ch-ua": '"Chromium";v="136", "Google Chrome";v="136", "Not.A/Brand";v="99"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "sec-fetch-user": "?1",
    "upgrade-insecure-requests": "1",
    "cache-control": "max-age=0",
    "connection": "keep-alive",
}


# ---------------------------------------------------------------------------
# Parsers de texto
# ---------------------------------------------------------------------------

def _to_float(val) -> float | None:
    """Convierte un valor a float de forma segura; retorna None si falla o si val es falsy."""
    try:
        return float(val) if val is not None else None
    except (ValueError, TypeError):
        return None


def parsear_precio(texto: str) -> float | None:
    if not texto:
        return None
    solo_numeros = re.sub(r"[^\d]", "", texto)
    return float(solo_numeros) if solo_numeros else None


def parsear_area(texto: str) -> float | None:
    if not texto:
        return None
    m = re.search(r"([\d,.]+)\s*m", texto.replace(",", ""))
    return float(m.group(1)) if m else None


def parsear_entero(texto: str) -> int | None:
    if not texto:
        return None
    m = re.search(r"\d+", texto)
    return int(m.group()) if m else None


# ---------------------------------------------------------------------------
# Imágenes → Supabase Storage
# ---------------------------------------------------------------------------

_EXT_MAP = {
    "image/jpeg": ".jpg",
    "image/jpg":  ".jpg",
    "image/png":  ".png",
    "image/webp": ".webp",
    "image/gif":  ".gif",
}


def descargar_imagen(url: str) -> tuple[bytes, str] | tuple[None, None]:
    """Descarga imagen directamente (sin proxy) y retorna (bytes, content_type)."""
    if not url:
        return None, None
    try:
        with httpx.Client(timeout=15, follow_redirects=True) as c:
            resp = c.get(url)
        if resp.status_code == 200:
            ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
            return resp.content, ct
    except Exception as e:
        log.error(f"Error descargando imagen {url}: {e}")
    return None, None


def subir_imagen_supabase(supabase_client, imagen_bytes: bytes, nombre: str, content_type: str) -> str | None:
    """Sube al bucket 'imagenes' y retorna URL pública, o None si falla."""
    try:
        supabase_client.storage.from_("imagenes").upload(
            nombre,
            imagen_bytes,
            {"content-type": content_type, "x-upsert": "true"},
        )
        return f"{SUPABASE_URL}/storage/v1/object/public/imagenes/{nombre}"
    except Exception as e:
        log.error(f"Error subiendo imagen a Supabase Storage: {e}")
        return None


def procesar_imagen(supabase_client, listing: dict, pw_request=None) -> None:
    """Descarga imagen con sesión Playwright (Referer: plusvalia.com) y sube a Supabase Storage."""
    url_original = listing.get("imagen_url")
    if not url_original:
        return
    if listing.get("supabase_imagen_url"):
        return

    imagen_bytes, content_type = None, None

    # Intentar con Playwright (tiene cookies/sesión de Plusvalía — naventcdn lo acepta)
    if pw_request:
        try:
            resp = pw_request.get(
                url_original,
                headers={"Referer": "https://www.plusvalia.com/"},
                timeout=15_000,
            )
            if resp.status == 200:
                ct = resp.headers.get("content-type", "image/jpeg").split(";")[0].strip()
                imagen_bytes, content_type = resp.body(), ct
        except Exception as e:
            log.error(f"Error descargando imagen con Playwright {url_original}: {e}")

    # Fallback: httpx directo
    if not imagen_bytes:
        imagen_bytes, content_type = descargar_imagen(url_original)

    if not imagen_bytes:
        return  # Mantener URL original

    ext = _EXT_MAP.get(content_type, ".jpg")
    nombre = hashlib.md5(listing["url_fuente"].encode()).hexdigest() + ext
    url_publica = subir_imagen_supabase(supabase_client, imagen_bytes, nombre, content_type)
    if url_publica:
        listing["supabase_imagen_url"] = url_publica


# ---------------------------------------------------------------------------
# Extracción de urbanización
# ---------------------------------------------------------------------------

_STOP_WORDS = {
    "casa", "departamento", "oficina", "terreno", "local", "consultorio",
    "venta", "alquiler", "renta", "vendo", "arriendo", "propiedad",
    "de", "en", "la", "el", "los", "las", "un", "una", "con", "por",
    "del", "al", "y", "e", "o", "a", "se", "km",
    "guayaquil", "guayas", "ecuador", "samborondon", "puntilla",
    "norte", "ceibos", "costa", "salitre", "narcisa", "jesus", "leon",
    "febres", "cordero", "via",
    # Prefijos de anuncios clasificados en Plusvalía
    "clasificado", "veclcain", "veclapin", "veclcapa", "veclcoin",
    "veclocin", "vecltein", "veclcasa", "clasif",
}

# Mapa keyword → nombre canónico de urbanización
# Aplica a título del listing cuando la URL no es concluyente
_KEYWORD_URB = [
    # Av. León Febres Cordero
    ("villa club",        "Villa Club"),
    ("vicolinci",         "Vicolinci"),
    ("el condado",        "El Condado"),
    ("condado",           "El Condado"),
    ("villa nova",        "Villa Nova"),
    ("villanova",         "Villa Nova"),
    ("vistana",           "Vistana"),
    ("porton del rio",    "Portón Del Rio"),
    ("porton rio",        "Portón Del Rio"),
    ("portón del río",    "Portón Del Rio"),
    ("la aurora",         "La Aurora"),
    ("aurora",            "La Aurora"),
    ("brisas del norte",  "Brisas Del Norte"),
    ("la rioja",          "La Rioja"),
    ("los vergeles",      "Los Vergeles"),
    ("vergeles",          "Los Vergeles"),
    ("miraflores",        "Miraflores"),
    ("alborada",          "Alborada"),
    ("guayacanes",        "Guayacanes"),
    ("volare",            "Volare"),
    ("logare",            "Logare"),
    ("la joya",           "La Joya"),
    # Samborondón / La Puntilla
    ("ciudad celeste",    "Ciudad Celeste"),
    ("isla celeste",      "Isla Celeste"),
    ("isla mocoli",       "Isla Mócolí"),
    ("isla mócolí",       "Isla Mócolí"),
    ("aires del batan",   "Aires Del Batán"),
    ("parques del rio",   "Parques Del Rio"),
    ("parques del río",   "Parques Del Rio"),
    ("savali",            "Savali"),
    ("boreal",            "Boreal"),
    ("terrasol",          "Terrasol"),
    ("punta barranca",    "Punta Barranca"),
    ("blue bay",          "Blue Bay"),
    ("la gran victoria",  "La Gran Victoria"),
    ("gran victoria",     "La Gran Victoria"),
    ("bouganville",       "Bouganville"),
    ("estancias del rio", "Estancias Del Rio"),
    # Vía a la Costa
    ("puerto azul",       "Puerto Azul"),
    ("laguna club",       "Laguna Club"),
    ("bosquetto",         "Bosquetto"),
    ("buenaventura",      "Buenaventura"),
    # Norte Guayaquil
    ("kennedy",           "Kennedy"),
    ("la garzota",        "La Garzota"),
    ("los sauces",        "Los Sauces"),
    ("colinas del sol",   "Colinas Del Sol"),
    ("parques del salado","Parques Del Salado"),
    ("urdesa",            "Urdesa"),
    ("lomas de urdesa",   "Lomas de Urdesa"),
    ("los olivos",        "Los Olivos"),
    ("ceibos norte",      "Ceibos Norte"),
    ("las cumbres",       "Las Cumbres"),
    ("santa cecilia",     "Santa Cecilia"),
    # Vía a la Costa
    ("portofino",         "Portofino"),
    ("costalmar",         "Costalmar"),
    ("alba del bosque",   "Alba Del Bosque"),
    ("los arrayanes",     "Los Arrayanes"),
    # Vía a Salitre
    ("las orquideas",     "Las Orquídeas"),
    ("orquideas",         "Las Orquídeas"),
    ("los almendros",     "Los Almendros"),
    ("villa hermosa",     "Villa Hermosa"),
    ("mallorca",          "Mallorca Village"),
    ("arboletta",         "Arboletta"),
    ("los pinos del rio", "Los Pinos Del Rio"),
    ("santa maria",       "Santa María Casa Grande"),
    ("ciudad del sol",    "Ciudad Del Sol"),
    ("parques del sol",   "Parques Del Sol"),
    ("los rosales",       "Los Rosales"),
    ("villa del rey",     "Villa Del Rey"),
    ("la campina",        "La Campiña"),
    ("san jose del rio",  "San José Del Rio"),
    ("portal del rio",    "Portal Del Rio"),
    ("los cerezos",       "Los Cerezos"),
    # Narcisa de Jesús
    ("metropolis",        "Metrópolis"),
    ("ciudad del rio",    "Ciudad Del Rio"),
    ("la perla",          "La Perla"),
    ("acuarela",          "Acuarela Del Rio"),
    ("paraiso del rio",   "Paraíso Del Rio"),
    ("victoria del rio",  "Victoria Del Rio"),
    ("narcisa club",      "Narcisa Club"),
    ("horizonte dorado",  "Horizonte Dorado"),
    ("la romareda",       "La Romareda"),
    # Otros conocidos
    ("entre rios",        "Entre Ríos"),
    ("entre río",         "Entre Ríos"),
    ("los lagos",         "Los Lagos"),
    ("san bernardo",      "San Bernardo"),
    ("ciudad millenium",  "Ciudad Millenium"),
    ("platinium",         "Platinium"),
    ("platinum",          "Platinium"),
    ("provenza",          "Provenza"),
    ("quo",               "Quo"),
    ("titanium aurora",   "Titanium Aurora"),
]


def extraer_urbanizacion_json(item: dict, sector_nombre: str) -> str | None:
    loc = item.get("location") or {}

    # Método 1: subdivisions (estructura ZonaProp/Navent)
    for s in (loc.get("subdivisions") or []):
        tipo = (s.get("type") or "").upper()
        label = (s.get("label") or "").strip()
        if tipo in ("NEIGHBORHOOD", "URBANIZATION", "SUBDIVISION", "BARRIO") and label:
            if label.lower() not in (sector_nombre.lower(), "guayaquil", "guayas"):
                return label

    # Método 2: full_location → "Villa Club, Samborondón, Guayas"
    full = (loc.get("full_location") or loc.get("full_address") or "").strip()
    if full:
        parts = [p.strip() for p in full.split(",")]
        if parts and parts[0].lower() not in (sector_nombre.lower(), "guayaquil", "guayas"):
            return parts[0]

    return None


def extraer_urbanizacion_titulo(titulo: str) -> str | None:
    """Busca keywords de urbanización en el título del listing."""
    if not titulo:
        return None
    t = titulo.lower()
    for kw, urb in _KEYWORD_URB:
        if kw in t:
            return urb
    return None


def extraer_urbanizacion_url(url: str, sector_nombre: str) -> str | None:
    m = re.search(r'/propiedades/(.+?)(?:-\d{5,})?(?:\.html)?$', url)
    if not m:
        return None
    slug = m.group(1)

    # Si la URL es un clasificado, no extraer urb del slug (sería basura)
    if slug.startswith("clasificado"):
        return None

    stop = _STOP_WORDS | {w.lower() for w in sector_nombre.split()}
    words = [w for w in slug.split("-") if w and w not in stop and not w.isdigit()]
    if len(words) >= 2:
        candidato = " ".join(w.capitalize() for w in words[:4])
        # Descartar si parece descripción genérica (más de 4 palabras distintas)
        if len(words) <= 5:
            return candidato
    return None


# ---------------------------------------------------------------------------
# Extracción desde JSON de Next.js (__NEXT_DATA__)
# ---------------------------------------------------------------------------

def extraer_json_nextjs(html: str) -> list[dict]:
    try:
        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("script", id="__NEXT_DATA__")
        if not tag:
            return []
        data = json.loads(tag.string)
        props = data.get("props", {}).get("pageProps", {})
        listings_raw = (
            props.get("listings") or
            props.get("postings") or
            props.get("results") or
            props.get("items") or
            []
        )
        return listings_raw if isinstance(listings_raw, list) else []
    except Exception as e:
        log.debug(f"JSON Next.js no disponible: {e}")
        return []


def parsear_listing_json(item: dict, sector_nombre: str, tipo_nombre: str) -> dict | None:
    try:
        url = item.get("permalink") or item.get("url") or item.get("link")
        if not url:
            return None
        if not url.startswith("http"):
            url = "https://www.plusvalia.com" + url
        url = url.split("?")[0]  # quitar parámetros de tracking

        precio_raw = (
            item.get("price") or
            item.get("precio") or
            (item.get("prices") or {}).get("price")
        )
        precio = _to_float(precio_raw)

        # Extracción separada de áreas
        area_total    = _to_float(item.get("totalArea") or item.get("surface") or item.get("area"))
        area_cubierta = _to_float(item.get("coveredArea"))

        # Precios por m² discriminados
        pm2_total    = round(precio / area_total,    2) if precio and area_total    else None
        pm2_cubierta = round(precio / area_cubierta, 2) if precio and area_cubierta else None

        # Confianza: 2=ambos tipos, 1=solo uno, 0=ninguno
        if area_total and area_cubierta:
            confianza = 2
        elif area_total or area_cubierta:
            confianza = 1
        else:
            confianza = 0

        # Legacy: cubierta tiene prioridad (más coherente con el ACM)
        area_legacy = area_cubierta or area_total
        pm2_legacy  = round(precio / area_legacy, 2) if precio and area_legacy else None

        # Logs [AREA] — visibles con nivel DEBUG
        if area_total:    log.debug(f"[AREA] totalArea detectada: {area_total}")
        if area_cubierta: log.debug(f"[AREA] coveredArea detectada: {area_cubierta}")
        if pm2_total:     log.debug(f"[AREA] precio_m2_total: {pm2_total}")
        if pm2_cubierta:  log.debug(f"[AREA] precio_m2_cubierta: {pm2_cubierta}")
        log.debug(f"[AREA] confianza_area: {confianza}")

        titulo_str = str(item.get("title") or item.get("titulo") or "")
        urb = (
            extraer_urbanizacion_json(item, sector_nombre) or
            extraer_urbanizacion_url(url, sector_nombre) or
            extraer_urbanizacion_titulo(titulo_str)
        )
        return {
            "sector":        sector_nombre,
            "tipo":          tipo_nombre,
            "precio":        precio,
            # Legacy (mantener para compatibilidad durante transición)
            "area_m2":       area_legacy,
            "precio_m2":     pm2_legacy,
            # Áreas discriminadas
            "area_total_m2":      area_total,
            "area_cubierta_m2":   area_cubierta,
            "precio_m2_total":    pm2_total,
            "precio_m2_cubierta": pm2_cubierta,
            "confianza_area":     confianza,
            "habitaciones":  parsear_entero(str(item.get("rooms", "") or item.get("bedrooms", ""))),
            "banos":         parsear_entero(str(item.get("bathrooms", "") or item.get("banos", ""))),
            "parqueos":      parsear_entero(str(item.get("parking", "") or item.get("garages", ""))),
            "titulo":        str(item.get("title") or item.get("titulo") or "")[:500],
            "direccion":     str(item.get("address") or (item.get("location") or {}).get("label") or "")[:300],
            "url_fuente":    url,
            "imagen_url":          (str(item.get("photos", [{}])[0].get("url")) if item.get("photos") else None),
            "urbanizacion":        urb[:200] if urb else None,
            "supabase_imagen_url": None,
        }
    except Exception as e:
        log.debug(f"Error parseando item JSON: {e}")
        return None


# ---------------------------------------------------------------------------
# Extracción desde HTML (fallback)
# ---------------------------------------------------------------------------

def parsear_cards_dom(html: str, sector_nombre: str, tipo_nombre: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    resultados = []

    cards = []
    for selector in [
        {"data-qa": "posting CARD"},
        {"data-qa": "POSTING_CARD"},
    ]:
        cards = soup.find_all(attrs=selector)
        if cards:
            break

    if not cards:
        for cls in ["posting-card", "listing-card", "property-card"]:
            cards = soup.find_all(class_=re.compile(cls, re.I))
            if cards:
                break

    if not cards:
        log.warning("  No se encontraron cards en el HTML")
        return []

    log.info(f"  {len(cards)} cards encontrados en DOM")

    for card in cards:
        try:
            link = card.find("a", href=True)
            if not link:
                continue
            url = link["href"]
            if not url.startswith("http"):
                url = "https://www.plusvalia.com" + url
            url = url.split("?")[0]  # quitar parámetros de tracking

            texto = card.get_text(" ", strip=True)

            precio_el = (
                card.find(attrs={"data-qa": "POSTING_CARD_PRICE"}) or
                card.find(class_=re.compile(r"price|precio", re.I))
            )
            precio = parsear_precio(precio_el.get_text() if precio_el else "")
            area = parsear_area(texto)

            titulo_el = (
                card.find(attrs={"data-qa": "POSTING_CARD_DESCRIPTION"}) or
                card.find(["h2", "h3"])
            )
            titulo = titulo_el.get_text(strip=True)[:500] if titulo_el else ""

            dir_el = card.find(attrs={"data-qa": "POSTING_CARD_LOCATION"})
            direccion = dir_el.get_text(strip=True)[:300] if dir_el else ""

            imagen_url = ""
            for img in card.find_all("img"):
                for attr in ["src", "data-src", "data-lazy-src"]:
                    val = img.get(attr, "")
                    if "naventcdn" in val or "plusvalia" in val:
                        imagen_url = val.split(" ")[0]
                        break
                if imagen_url:
                    break

            hab = banos = parq = None
            m = re.search(r"(\d+)\s*(?:dorm|hab|recám)", texto, re.I)
            if m:
                hab = int(m.group(1))
            m = re.search(r"(\d+)\s*(?:baño|bano|bath)", texto, re.I)
            if m:
                banos = int(m.group(1))
            m = re.search(r"(\d+)\s*(?:parq|garage|est)", texto, re.I)
            if m:
                parq = int(m.group(1))

            resultados.append({
                "sector":        sector_nombre,
                "tipo":          tipo_nombre,
                "precio":        precio,
                # Legacy (el DOM no distingue tipo de área)
                "area_m2":       area,
                "precio_m2":     round(precio / area, 2) if precio and area else None,
                # Áreas discriminadas — no disponibles en scraping HTML
                "area_total_m2":      None,
                "area_cubierta_m2":   None,
                "precio_m2_total":    None,
                "precio_m2_cubierta": None,
                "confianza_area":     0,
                "habitaciones":  hab,
                "banos":         banos,
                "parqueos":      parq,
                "titulo":        titulo,
                "direccion":     direccion,
                "url_fuente":    url,
                "imagen_url":          imagen_url[:500] or None,
                "urbanizacion":        (extraer_urbanizacion_url(url, sector_nombre) or extraer_urbanizacion_titulo(titulo)),
                "supabase_imagen_url": None,
            })
        except Exception as e:
            log.debug(f"Error parseando card: {e}")

    return resultados


# ---------------------------------------------------------------------------
# Scraping de una URL
# ---------------------------------------------------------------------------

def scrape_pagina(page, url: str, sector_nombre: str, tipo_nombre: str, urbanizacion: str | None = None) -> list[dict]:
    log.info(f"  Scrapeando: {url}")
    try:
        page.goto(url, timeout=60_000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector("script#__NEXT_DATA__", timeout=15_000)
        except Exception:
            log.warning(f"  Sin __NEXT_DATA__ en {url} (posible challenge)")
        # Scroll para activar lazy loading de imágenes
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1500)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(500)
        html = page.content()
    except Exception as e:
        log.warning(f"  Error al cargar {url}: {e}")
        return []

    items_json = extraer_json_nextjs(html)
    if items_json:
        log.info(f"  JSON Next.js: {len(items_json)} items")
        resultados = [parsear_listing_json(i, sector_nombre, tipo_nombre) for i in items_json]
        results = [r for r in resultados if r]
    else:
        results = parsear_cards_dom(html, sector_nombre, tipo_nombre)

    # Si venimos de una búsqueda por urbanización, la inyectamos directamente
    if urbanizacion:
        for r in results:
            if not r.get("urbanizacion"):
                r["urbanizacion"] = urbanizacion

    return results


def hay_mas_paginas(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    return bool(
        soup.find("a", rel="next") or
        soup.find(attrs={"data-qa": "PAGINATION_NEXT"}) or
        soup.find("a", class_=re.compile("next", re.I))
    )


# ---------------------------------------------------------------------------
# Enriquecimiento desde página individual
# ---------------------------------------------------------------------------

def enriquecer_listing(page, listing: dict) -> None:
    """
    Visita la URL individual de una propiedad y completa sus campos de área.
    Modifica el dict in-place. No guarda en Supabase.

    Campos actualizados en Supabase (existen en schema):
        area_total_m2, area_cubierta_m2, precio_m2_total, precio_m2_cubierta,
        confianza_area, banos, parqueos, area_m2 (legacy), precio_m2 (legacy)

    Campos solo logueados (aún no en schema):
        medio_bano, antiguedad_anios
    """
    url = listing.get("url_fuente")
    if not url:
        return

    # Skip si ya tiene ambas áreas discriminadas
    if (listing.get("confianza_area") or 0) >= 2:
        log.info(f"[DETALLE] Ya confianza_area=2, omitiendo: {url[-60:]}")
        return

    log.info(f"[DETALLE] Enriqueciendo: {url[-80:]}")

    precio  = listing.get("precio")
    detalle = extraer_detalle_propiedad(page, url, precio=precio)

    if not detalle:
        log.warning(f"[DETALLE] Sin datos del detalle para {url[-60:]}")
        return

    # ── Campos de área discriminada (schema OK) ───────────────────────────
    at = detalle.get("area_total_m2")
    ac = detalle.get("area_cubierta_m2")
    pt = detalle.get("precio_m2_total")
    pc = detalle.get("precio_m2_cubierta")
    cf = detalle.get("confianza_area", 0)

    if at is not None:
        listing["area_total_m2"]    = at
        log.info(f"[DETALLE] area_total_m2    = {at}")
    if ac is not None:
        listing["area_cubierta_m2"] = ac
        log.info(f"[DETALLE] area_cubierta_m2 = {ac}")
    if pt is not None:
        listing["precio_m2_total"]    = pt
        log.info(f"[DETALLE] precio_m2_total    = {pt}")
    if pc is not None:
        listing["precio_m2_cubierta"] = pc
        log.info(f"[DETALLE] precio_m2_cubierta = {pc}")

    listing["confianza_area"] = cf
    log.info(f"[DETALLE] confianza_area   = {cf}")

    # ── Legacy: usar área cubierta si existe (schema OK) ──────────────────
    if ac:
        listing["area_m2"]   = ac
        listing["precio_m2"] = pc  # ya calculado en detalle, puede ser None

    # ── Completar banos/parqueos solo si el listing no los tenía ──────────
    if listing.get("banos") is None and detalle.get("banos") is not None:
        listing["banos"] = detalle["banos"]
    if listing.get("parqueos") is None and detalle.get("parqueos") is not None:
        listing["parqueos"] = detalle["parqueos"]

    # ── Solo log — campos sin columna en schema aún ───────────────────────
    mb  = detalle.get("medio_bano")
    ant = detalle.get("antiguedad_anios")
    if mb  is not None: log.info(f"[DETALLE] medio_bano (solo log)       = {mb}")
    if ant is not None: log.info(f"[DETALLE] antiguedad_anios (solo log) = {ant}")


# ---------------------------------------------------------------------------
# Guardar en Supabase
# ---------------------------------------------------------------------------

def guardar_listings(supabase_client, listings: list[dict]) -> int:
    if not listings:
        return 0
    # Deduplicar por url_fuente antes de enviar
    seen = {}
    for l in listings:
        seen[l["url_fuente"]] = l
    listings = list(seen.values())
    try:
        result = supabase_client.table("listings").upsert(
            listings,
            on_conflict="url_fuente",
            ignore_duplicates=False,
        ).execute()
        return len(result.data) if result.data else 0
    except Exception as e:
        log.error(f"Error guardando en Supabase: {e}")
        return 0


# ---------------------------------------------------------------------------
# Loop principal
# ---------------------------------------------------------------------------

def main():
    log.info("=== ACM Guayaquil — Scraper iniciado ===")
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

    total_guardados = 0
    combinaciones = [(t, s) for t in TIPOS for s in SECTORES]
    log.info(f"Combinaciones: {len(combinaciones)} ({len(TIPOS)} tipos × {len(SECTORES)} sectores)")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
        context = browser.new_context(user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ))
        page = context.new_page()

        for tipo_slug, sector_key in combinaciones:
            tipo_nombre   = TIPOS[tipo_slug]
            sector_nombre = SECTORES[sector_key]
            log.info(f"\n→ {tipo_nombre} en {sector_nombre}")

            for pagina in range(1, MAX_PAGINAS + 1):
                url = build_url(tipo_slug, sector_key, pagina)
                listings = scrape_pagina(page, url, sector_nombre, tipo_nombre)

                if not listings:
                    log.info(f"  Página {pagina}: sin resultados")
                    break

                enriquecidos = 0
                for listing in listings:
                    if MAX_ENRIQUECIMIENTO > 0 and enriquecidos < MAX_ENRIQUECIMIENTO:
                        enriquecer_listing(page, listing)
                        enriquecidos += 1
                        time.sleep(DELAY_SEGUNDOS)
                    procesar_imagen(supabase, listing, page.request)

                if MAX_ENRIQUECIMIENTO > 0:
                    log.info(f"  Enriquecidos: {enriquecidos} de {len(listings)}")

                guardados = guardar_listings(supabase, listings)
                total_guardados += guardados
                log.info(f"  Página {pagina}: {len(listings)} encontrados, {guardados} guardados")

                time.sleep(DELAY_SEGUNDOS)

        # ── Urbanizaciones específicas (casas + departamentos, 1 página) ──
        log.info("\n=== Scraping por urbanizaciones ===")
        for sector_key, urbs in URBANIZACIONES.items():
            sector_nombre = SECTORES.get(sector_key)
            if not sector_nombre:
                continue
            for tipo_slug, tipo_nombre in TIPOS.items():
                if tipo_slug not in TIPOS_URB:
                    continue
                for urb_slug in urbs:
                    urb_nombre = urb_slug.replace("-", " ").title()
                    url = build_url_urb(tipo_slug, sector_key, urb_slug, 1)
                    listings = scrape_pagina(page, url, sector_nombre, tipo_nombre, urb_nombre)
                    if not listings:
                        continue
                    enriquecidos = 0
                    for listing in listings:
                        if MAX_ENRIQUECIMIENTO > 0 and enriquecidos < MAX_ENRIQUECIMIENTO:
                            enriquecer_listing(page, listing)
                            enriquecidos += 1
                            time.sleep(DELAY_SEGUNDOS)
                        procesar_imagen(supabase, listing)
                    guardados = guardar_listings(supabase, listings)
                    total_guardados += guardados
                    log.info(f"  {tipo_nombre} · {sector_nombre} · {urb_slug}: {len(listings)} encontrados, {guardados} guardados")
                    time.sleep(DELAY_SEGUNDOS)

        page.close()

    log.info(f"\n=== Scraping completado: {total_guardados} listings guardados ===")


if __name__ == "__main__":
    main()

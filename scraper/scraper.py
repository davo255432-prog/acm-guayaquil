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
from bs4 import BeautifulSoup
from supabase import create_client

from config import (
    SUPABASE_URL, SUPABASE_KEY,
    SECTORES, TIPOS, URBANIZACIONES, TIPOS_URB,
    MAX_PAGINAS, MAX_PAGINAS_URB, DELAY_SEGUNDOS,
    build_url, build_url_urb,
)

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
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-EC,es;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


# ---------------------------------------------------------------------------
# Parsers de texto
# ---------------------------------------------------------------------------

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
        log.debug(f"Error descargando imagen {url}: {e}")
    return None, None


def subir_imagen_supabase(supabase_client, imagen_bytes: bytes, nombre: str, content_type: str) -> str | None:
    """Sube al bucket 'imagenes' y retorna URL pública, o None si falla."""
    try:
        supabase_client.storage.from_("imagenes").upload(
            nombre,
            imagen_bytes,
            {"contentType": content_type, "upsert": True},
        )
        return f"{SUPABASE_URL}/storage/v1/object/public/imagenes/{nombre}"
    except Exception as e:
        log.debug(f"Error subiendo imagen a Supabase Storage: {e}")
        return None


def procesar_imagen(supabase_client, listing: dict) -> None:
    """Reemplaza imagen_url de Plusvalía CDN por URL de Supabase Storage. Modifica in-place."""
    url_original = listing.get("imagen_url")
    if not url_original:
        return
    # Si ya es Supabase, nada que hacer (re-runs)
    if url_original.startswith(SUPABASE_URL):
        return

    imagen_bytes, content_type = descargar_imagen(url_original)
    if not imagen_bytes:
        listing["imagen_url"] = None
        return

    ext = _EXT_MAP.get(content_type, ".jpg")
    nombre = hashlib.md5(listing["url_fuente"].encode()).hexdigest() + ext
    url_publica = subir_imagen_supabase(supabase_client, imagen_bytes, nombre, content_type)
    listing["imagen_url"] = url_publica  # None si falló la subida


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
}


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


def extraer_urbanizacion_url(url: str, sector_nombre: str) -> str | None:
    m = re.search(r'/propiedades/(.+?)(?:-\d{5,})?(?:\.html)?$', url)
    if not m:
        return None
    slug = m.group(1)
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
        area_raw = (
            item.get("surface") or
            item.get("area") or
            item.get("totalArea") or
            item.get("coveredArea")
        )

        precio = float(precio_raw) if precio_raw else None
        area   = float(area_raw)   if area_raw   else None

        urb = (
            extraer_urbanizacion_json(item, sector_nombre) or
            extraer_urbanizacion_url(url, sector_nombre)
        )
        return {
            "sector":        sector_nombre,
            "tipo":          tipo_nombre,
            "precio":        precio,
            "area_m2":       area,
            "precio_m2":     round(precio / area, 2) if precio and area else None,
            "habitaciones":  parsear_entero(str(item.get("rooms", "") or item.get("bedrooms", ""))),
            "banos":         parsear_entero(str(item.get("bathrooms", "") or item.get("banos", ""))),
            "parqueos":      parsear_entero(str(item.get("parking", "") or item.get("garages", ""))),
            "titulo":        str(item.get("title") or item.get("titulo") or "")[:500],
            "direccion":     str(item.get("address") or (item.get("location") or {}).get("label") or "")[:300],
            "url_fuente":    url,
            "imagen_url":    (str(item.get("photos", [{}])[0].get("url")) if item.get("photos") else None),
            "urbanizacion":  urb[:200] if urb else None,
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

            img = card.find("img")
            imagen_url = (img.get("src") or img.get("data-src") or "") if img else ""

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
                "area_m2":       area,
                "precio_m2":     round(precio / area, 2) if precio and area else None,
                "habitaciones":  hab,
                "banos":         banos,
                "parqueos":      parq,
                "titulo":        titulo,
                "direccion":     direccion,
                "url_fuente":    url,
                "imagen_url":    imagen_url[:500] or None,
                "urbanizacion":  extraer_urbanizacion_url(url, sector_nombre),
            })
        except Exception as e:
            log.debug(f"Error parseando card: {e}")

    return resultados


# ---------------------------------------------------------------------------
# Scraping de una URL
# ---------------------------------------------------------------------------

def scrape_pagina(client: httpx.Client, url: str, sector_nombre: str, tipo_nombre: str, urbanizacion: str | None = None) -> list[dict]:
    log.info(f"  Scrapeando: {url}")
    try:
        resp = client.get(url, timeout=60, follow_redirects=True)
        if resp.status_code != 200:
            log.warning(f"  HTTP {resp.status_code} en {url}")
            return []
        html = resp.text
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

    with httpx.Client(headers=HEADERS) as client:
        for tipo_slug, sector_key in combinaciones:
            tipo_nombre   = TIPOS[tipo_slug]
            sector_nombre = SECTORES[sector_key]
            log.info(f"\n→ {tipo_nombre} en {sector_nombre}")

            for pagina in range(1, MAX_PAGINAS + 1):
                url = build_url(tipo_slug, sector_key, pagina)
                listings = scrape_pagina(client, url, sector_nombre, tipo_nombre)

                if not listings:
                    log.info(f"  Página {pagina}: sin resultados")
                    break

                for listing in listings:
                    procesar_imagen(supabase, listing)

                guardados = guardar_listings(supabase, listings)
                total_guardados += guardados
                log.info(f"  Página {pagina}: {len(listings)} encontrados, {guardados} guardados")

                if pagina < MAX_PAGINAS:
                    try:
                        resp = client.get(url, timeout=30, follow_redirects=True)
                        if not hay_mas_paginas(resp.text):
                            log.info("  No hay más páginas")
                            break
                    except Exception:
                        break

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
                    listings = scrape_pagina(client, url, sector_nombre, tipo_nombre, urb_nombre)
                    if not listings:
                        continue
                    for listing in listings:
                        procesar_imagen(supabase, listing)
                    guardados = guardar_listings(supabase, listings)
                    total_guardados += guardados
                    log.info(f"  {tipo_nombre} · {sector_nombre} · {urb_slug}: {len(listings)} encontrados, {guardados} guardados")
                    time.sleep(DELAY_SEGUNDOS)

    log.info(f"\n=== Scraping completado: {total_guardados} listings guardados ===")


if __name__ == "__main__":
    main()

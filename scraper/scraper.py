"""
ACM Guayaquil — Scraper de Plusvalía.com
Usa Playwright (navegador real) para evitar bloqueos.
Corre automáticamente cada 24h en Render.com.
"""

import json
import logging
import re
import time

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
from supabase import create_client

from config import (
    SUPABASE_URL, SUPABASE_KEY,
    SECTORES, TIPOS,
    MAX_PAGINAS, DELAY_SEGUNDOS, TIMEOUT_MS,
    build_url,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Extracción de datos
# ---------------------------------------------------------------------------

def extraer_numero(texto: str) -> float | None:
    """Extrae el primer número (con decimales) de un string."""
    if not texto:
        return None
    limpio = texto.replace(",", "").replace(".", "")
    # Volver a poner el separador decimal correcto
    match = re.search(r"[\d]+(?:[.,]\d+)?", texto.replace(".", "").replace(",", "."))
    m = re.search(r"[\d]+(?:\.\d+)?", limpio)
    return float(m.group()) if m else None


def parsear_precio(texto: str) -> float | None:
    if not texto:
        return None
    # Quitar símbolos y espacios, dejar solo dígitos
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


def extraer_json_nextjs(page) -> list[dict]:
    """
    Intenta extraer listings del JSON embebido de Next.js (__NEXT_DATA__).
    Si Plusvalía usa Next.js, esto devuelve datos estructurados sin parsear HTML.
    """
    try:
        raw = page.evaluate("() => document.getElementById('__NEXT_DATA__')?.textContent")
        if not raw:
            return []
        data = json.loads(raw)
        # Navegar la estructura hasta encontrar los listings
        # La ruta exacta depende de la versión de Plusvalía — ajustar si cambia
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
    """Convierte un item del JSON de Next.js en el formato de Supabase."""
    try:
        url = item.get("permalink") or item.get("url") or item.get("link")
        if not url:
            return None
        if not url.startswith("http"):
            url = "https://www.plusvalia.com" + url

        precio_raw = (
            item.get("price") or
            item.get("precio") or
            item.get("prices", {}).get("price")
        )
        area_raw = (
            item.get("surface") or
            item.get("area") or
            item.get("totalArea") or
            item.get("coveredArea")
        )

        precio = float(precio_raw) if precio_raw else None
        area   = float(area_raw)   if area_raw   else None

        return {
            "sector":       sector_nombre,
            "tipo":         tipo_nombre,
            "precio":       precio,
            "area_m2":      area,
            "precio_m2":    round(precio / area, 2) if precio and area else None,
            "habitaciones": parsear_entero(str(item.get("rooms", "") or item.get("bedrooms", ""))),
            "banos":        parsear_entero(str(item.get("bathrooms", "") or item.get("banos", ""))),
            "parqueos":     parsear_entero(str(item.get("parking", "") or item.get("garages", ""))),
            "titulo":       str(item.get("title") or item.get("titulo") or "")[:500],
            "direccion":    str(item.get("address") or item.get("location", {}).get("label") or "")[:300],
            "url_fuente":   url,
            "imagen_url":   str(item.get("photos", [{}])[0].get("url") if item.get("photos") else "")[:500] or None,
        }
    except Exception as e:
        log.debug(f"Error parseando item JSON: {e}")
        return None


def parsear_cards_dom(page, sector_nombre: str, tipo_nombre: str) -> list[dict]:
    """
    Parsea los listing cards desde el DOM cuando no hay JSON disponible.
    Prueba múltiples selectores en orden — ajustar si Plusvalía cambia su HTML.
    """
    resultados = []

    # Selectores de cards (probar en orden hasta encontrar el correcto)
    card_selectors = [
        "[data-qa='posting CARD']",
        "[data-qa='POSTING_CARD']",
        ".posting-card",
        ".listing-card",
        ".property-card",
        "article[class*='posting']",
        "article[class*='listing']",
        "div[class*='postingCard']",
        "div[class*='listing-item']",
    ]

    cards = []
    for selector in card_selectors:
        cards = page.query_selector_all(selector)
        if cards:
            log.info(f"  Selector encontrado: {selector} ({len(cards)} cards)")
            break

    if not cards:
        log.warning("  No se encontraron cards — verificar selectores en config")
        return []

    for card in cards:
        try:
            # URL del listing
            link_el = card.query_selector("a[href*='/propiedades/'], a[href*='/inmuebles/'], a[href]")
            url = link_el.get_attribute("href") if link_el else None
            if not url:
                continue
            if not url.startswith("http"):
                url = "https://www.plusvalia.com" + url

            # Precio
            precio_el = card.query_selector(
                "[data-qa='POSTING_CARD_PRICE'], "
                ".price, .precio, "
                "[class*='price'], [class*='Price']"
            )
            precio = parsear_precio(precio_el.inner_text() if precio_el else "")

            # Título
            titulo_el = card.query_selector(
                "[data-qa='POSTING_CARD_DESCRIPTION'], "
                "h2, h3, [class*='title'], [class*='Title']"
            )
            titulo = titulo_el.inner_text().strip()[:500] if titulo_el else ""

            # Dirección
            dir_el = card.query_selector(
                "[data-qa='POSTING_CARD_LOCATION'], "
                "[class*='location'], [class*='address'], [class*='direccion']"
            )
            direccion = dir_el.inner_text().strip()[:300] if dir_el else ""

            # Imagen
            img_el = card.query_selector("img")
            imagen_url = (img_el.get_attribute("src") or img_el.get_attribute("data-src") or "") if img_el else ""

            # Características (m², habitaciones, baños, parqueos)
            features_text = card.inner_text()
            area   = parsear_area(features_text)
            hab    = None
            banos  = None
            parq   = None

            # Buscar números junto a palabras clave
            m = re.search(r"(\d+)\s*(?:dorm|hab|recám)", features_text, re.IGNORECASE)
            if m:
                hab = int(m.group(1))
            m = re.search(r"(\d+)\s*(?:baño|bano|bath)", features_text, re.IGNORECASE)
            if m:
                banos = int(m.group(1))
            m = re.search(r"(\d+)\s*(?:parq|garage|est)", features_text, re.IGNORECASE)
            if m:
                parq = int(m.group(1))

            resultados.append({
                "sector":       sector_nombre,
                "tipo":         tipo_nombre,
                "precio":       precio,
                "area_m2":      area,
                "precio_m2":    round(precio / area, 2) if precio and area else None,
                "habitaciones": hab,
                "banos":        banos,
                "parqueos":     parq,
                "titulo":       titulo,
                "direccion":    direccion,
                "url_fuente":   url,
                "imagen_url":   imagen_url[:500] if imagen_url else None,
            })
        except Exception as e:
            log.debug(f"Error parseando card DOM: {e}")
            continue

    return resultados


# ---------------------------------------------------------------------------
# Scraping de una URL
# ---------------------------------------------------------------------------

def scrape_pagina(page, url: str, sector_nombre: str, tipo_nombre: str) -> list[dict]:
    log.info(f"  Scrapeando: {url}")
    try:
        page.goto(url, wait_until="networkidle", timeout=TIMEOUT_MS)
    except PWTimeout:
        log.warning(f"  Timeout cargando {url}")
        return []

    # Intentar JSON primero (más confiable)
    items_json = extraer_json_nextjs(page)
    if items_json:
        log.info(f"  JSON Next.js: {len(items_json)} items")
        resultados = [parsear_listing_json(i, sector_nombre, tipo_nombre) for i in items_json]
        return [r for r in resultados if r]

    # Fallback: parsear DOM
    return parsear_cards_dom(page, sector_nombre, tipo_nombre)


def hay_mas_paginas(page) -> bool:
    """Detecta si hay un botón/link de siguiente página."""
    siguiente = page.query_selector(
        "a[rel='next'], "
        "[data-qa='PAGINATION_NEXT'], "
        ".pagination-next, "
        "a[class*='next']"
    )
    return siguiente is not None


# ---------------------------------------------------------------------------
# Guardar en Supabase
# ---------------------------------------------------------------------------

def guardar_listings(supabase_client, listings: list[dict]) -> int:
    if not listings:
        return 0
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
    log.info(f"Combinaciones a scrapesr: {len(combinaciones)} ({len(TIPOS)} tipos × {len(SECTORES)} sectores)")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="es-EC",
            extra_http_headers={"Accept-Language": "es-EC,es;q=0.9"},
        )
        page = context.new_page()

        for tipo_slug, sector_key in combinaciones:
            tipo_nombre   = TIPOS[tipo_slug]
            sector_nombre = SECTORES[sector_key]
            log.info(f"\n→ {tipo_nombre} en {sector_nombre}")

            for pagina in range(1, MAX_PAGINAS + 1):
                url = build_url(tipo_slug, sector_key, pagina)
                listings = scrape_pagina(page, url, sector_nombre, tipo_nombre)

                if not listings:
                    log.info(f"  Página {pagina}: sin resultados, siguiente combinación")
                    break

                guardados = guardar_listings(supabase, listings)
                total_guardados += guardados
                log.info(f"  Página {pagina}: {len(listings)} encontrados, {guardados} guardados")

                if pagina < MAX_PAGINAS and not hay_mas_paginas(page):
                    log.info(f"  No hay más páginas")
                    break

                time.sleep(DELAY_SEGUNDOS)

        browser.close()

    log.info(f"\n=== Scraping completado: {total_guardados} listings guardados en total ===")


if __name__ == "__main__":
    main()

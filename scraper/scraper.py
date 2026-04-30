"""
ACM Guayaquil — Scraper de Plusvalía.com
Usa httpx + BeautifulSoup (sin navegador) para máxima compatibilidad.
Corre automáticamente cada 24h en Render.com.
"""

import json
import logging
import re
import time

import httpx
from bs4 import BeautifulSoup
from supabase import create_client

from config import (
    SUPABASE_URL, SUPABASE_KEY, SCRAPERAPI_KEY,
    SECTORES, TIPOS,
    MAX_PAGINAS, DELAY_SEGUNDOS,
    build_url,
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
            "direccion":    str(item.get("address") or (item.get("location") or {}).get("label") or "")[:300],
            "url_fuente":   url,
            "imagen_url":   (str(item.get("photos", [{}])[0].get("url")) if item.get("photos") else None),
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
                "imagen_url":   imagen_url[:500] or None,
            })
        except Exception as e:
            log.debug(f"Error parseando card: {e}")

    return resultados


# ---------------------------------------------------------------------------
# Scraping de una URL
# ---------------------------------------------------------------------------

def scrape_pagina(client: httpx.Client, url: str, sector_nombre: str, tipo_nombre: str) -> list[dict]:
    log.info(f"  Scrapeando: {url}")
    proxy_url = "https://api.scraperapi.com/"
    params = {"api_key": SCRAPERAPI_KEY, "url": url, "render": "false"}
    try:
        resp = client.get(proxy_url, params=params, timeout=60)
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
        return [r for r in resultados if r]

    return parsear_cards_dom(html, sector_nombre, tipo_nombre)


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

    log.info(f"\n=== Scraping completado: {total_guardados} listings guardados ===")


if __name__ == "__main__":
    main()

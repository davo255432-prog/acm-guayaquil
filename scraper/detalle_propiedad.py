"""
Extracción de datos finos desde la página individual de una propiedad en Plusvalía.com.

No guarda nada en Supabase. Diseñado para ser llamado desde el scraper principal
o desde scripts de prueba de forma independiente.
"""

import re
import logging
from bs4 import BeautifulSoup

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers internos
# ---------------------------------------------------------------------------

def _primer_float(patron: str, texto: str, flags=re.I) -> float | None:
    """Retorna el primer número que coincide con el patrón, o None."""
    m = re.search(patron, texto, flags)
    if m:
        try:
            return float(m.group(1).replace(",", "."))
        except (ValueError, IndexError):
            return None
    return None


def _primer_int(patron: str, texto: str, flags=re.I) -> int | None:
    v = _primer_float(patron, texto, flags)
    return int(v) if v is not None else None


# ---------------------------------------------------------------------------
# Función principal
# ---------------------------------------------------------------------------

def extraer_detalle_propiedad(page, url: str, precio: float | None = None) -> dict:
    """
    Abre la URL de una propiedad y extrae sus características desde el DOM.

    Parámetros:
        page    — objeto Playwright page (ya conectado)
        url     — URL completa de la propiedad en Plusvalía.com
        precio  — precio en USD (opcional); si se pasa, calcula precio_m2_total
                  y precio_m2_cubierta automáticamente.

    Retorna un dict con los campos extraídos. En caso de error retorna {}.
    Los campos ausentes se devuelven como None, no se omiten.
    """
    resultado = {
        "area_total_m2":      None,
        "area_cubierta_m2":   None,
        "precio_m2_total":    None,
        "precio_m2_cubierta": None,
        "confianza_area":     0,
        "banos":              None,
        "medio_bano":         None,
        "parqueos":           None,
        "antiguedad_anios":   None,
    }

    try:
        log.info(f"[DETALLE] → {url}")
        page.goto(url, timeout=60_000, wait_until="domcontentloaded")

        # Esperar la sección de características si existe
        try:
            page.wait_for_selector(
                "[data-qa='POSTING_DETAIL_FEATURES'], "
                "[class*='feature'], [class*='characteristic'], "
                "[class*='surface'], [class*='detail']",
                timeout=8_000,
            )
        except Exception:
            pass  # continuar con lo que haya

        # Scroll para activar lazy load
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(1_500)

        html = page.content()

    except Exception as e:
        log.warning(f"[DETALLE] Error cargando {url}: {e}")
        return resultado

    try:
        soup = BeautifulSoup(html, "html.parser")
        texto = soup.get_text(" ", strip=True)

        # ── Áreas ──────────────────────────────────────────────────────────
        # Plusvalía muestra "128 m² tot." y "85 m² cub." en las fichas
        area_total = _primer_float(
            r"([\d,\.]+)\s*m[²2]\.?\s*tot(?:al(?:es)?)?",
            texto,
        )
        area_cubierta = _primer_float(
            r"([\d,\.]+)\s*m[²2]\.?\s*cub(?:ierto(?:s)?|ierta(?:s)?)?",
            texto,
        )

        # Fallback: buscar en el DOM etiquetas con data-qa o spans específicos
        if not area_total or not area_cubierta:
            area_total, area_cubierta = _buscar_areas_dom(soup, area_total, area_cubierta)

        resultado["area_total_m2"]    = area_total
        resultado["area_cubierta_m2"] = area_cubierta

        # ── Confianza ──────────────────────────────────────────────────────
        if area_total and area_cubierta:
            resultado["confianza_area"] = 2
        elif area_total or area_cubierta:
            resultado["confianza_area"] = 1
        else:
            resultado["confianza_area"] = 0

        # ── Precios por m² ────────────────────────────────────────────────
        if precio:
            if area_total:
                resultado["precio_m2_total"]    = round(precio / area_total,    2)
            if area_cubierta:
                resultado["precio_m2_cubierta"] = round(precio / area_cubierta, 2)

        # ── Baños ─────────────────────────────────────────────────────────
        # "2 baños" — buscar antes de "medio baño" para no confundirlos
        resultado["banos"] = _primer_int(
            r"(\d+)\s*baños(?!\s*y?\s*medio)",
            texto,
        ) or _primer_int(
            r"(\d+)\s*baño(?!s?\s*y?\s*medio)",
            texto,
        )

        # ── Medio baño ────────────────────────────────────────────────────
        resultado["medio_bano"] = _primer_int(
            r"(\d+)\s*medio\s*baño",
            texto,
        )

        # ── Estacionamientos / parqueos ───────────────────────────────────
        resultado["parqueos"] = _primer_int(
            r"(\d+)\s*(?:estacionamiento|garage|parking|cochera|parqueo)s?",
            texto,
        )

        # ── Antigüedad ────────────────────────────────────────────────────
        # Primero patrones contextuales, luego fallback genérico
        resultado["antiguedad_anios"] = (
            _primer_int(r"antigüedad[^\d]{0,20}(\d+)\s*años?", texto)
            or _primer_int(r"(\d+)\s*años?\s+de\s+antig", texto)
            or _primer_int(r"(\d+)\s*años?\s+construi", texto)
            or _primer_int(r"(\d+)\s*años?(?=\s|$)", texto)  # fallback genérico
        )

        # Logs de resultado
        log.info(
            f"[DETALLE] area_total={area_total}  area_cubierta={area_cubierta}"
            f"  confianza={resultado['confianza_area']}"
            f"  baños={resultado['banos']}  estac={resultado['parqueos']}"
            f"  medio={resultado['medio_bano']}  años={resultado['antiguedad_anios']}"
        )

    except Exception as e:
        log.warning(f"[DETALLE] Error parseando {url}: {e}")

    return resultado


# ---------------------------------------------------------------------------
# Helper DOM para áreas (complementa la búsqueda por texto)
# ---------------------------------------------------------------------------

def _buscar_areas_dom(soup: BeautifulSoup, area_total_actual, area_cubierta_actual):
    """
    Intenta extraer áreas desde estructuras de lista o data-qa del DOM.
    Solo sobrescribe si el valor actual es None.
    """
    area_total    = area_total_actual
    area_cubierta = area_cubierta_actual

    # Estrategia 1: buscar elementos con data-qa que contengan m²
    for el in soup.find_all(attrs={"data-qa": True}):
        texto_el = el.get_text(" ", strip=True)
        if re.search(r"m[²2]", texto_el, re.I):
            if not area_total and re.search(r"tot", texto_el, re.I):
                v = _primer_float(r"([\d,\.]+)\s*m[²2]", texto_el)
                if v:
                    area_total = v
            if not area_cubierta and re.search(r"cub", texto_el, re.I):
                v = _primer_float(r"([\d,\.]+)\s*m[²2]", texto_el)
                if v:
                    area_cubierta = v

    # Estrategia 2: buscar en <li>, <dt>, <span> cerca de palabras clave
    PATRONES_TOTAL    = re.compile(r"total|terreno|lote|lot", re.I)
    PATRONES_CUBIERTA = re.compile(r"cubierto|cubierta|construc|edificad", re.I)

    for el in soup.find_all(["li", "dt", "span", "p", "div"]):
        texto_el = el.get_text(" ", strip=True)
        if not re.search(r"m[²2]", texto_el, re.I):
            continue
        if not area_total and PATRONES_TOTAL.search(texto_el):
            v = _primer_float(r"([\d,\.]+)\s*m[²2]", texto_el)
            if v:
                area_total = v
        if not area_cubierta and PATRONES_CUBIERTA.search(texto_el):
            v = _primer_float(r"([\d,\.]+)\s*m[²2]", texto_el)
            if v:
                area_cubierta = v

    return area_total, area_cubierta

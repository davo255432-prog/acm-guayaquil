"""Recupera y conserva las fotografías reales de la muestra verificada de Napoli.

Este proceso no modifica precios, áreas, características ni la metodología ACM.
Solo completa ``imagen_url`` en los registros controlados cuyo anuncio público
todavía expone una fotografía válida.
"""

from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import Page, sync_playwright
from supabase import create_client

from config import SUPABASE_KEY, SUPABASE_URL
from importar_napoli_verificado import FUENTE


logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
log = logging.getLogger("imagenes-napoli")

BUCKET = "imagenes"
MARCADOR = f"%{FUENTE}%"
EXTENSIONES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
}


def _es_imagen_propiedad(url: str | None) -> bool:
    if not url or not url.startswith(("http://", "https://")):
        return False
    texto = url.lower()
    bloqueadas = ("logo", "favicon", "avatar", "sprite", "placeholder")
    return not any(palabra in texto for palabra in bloqueadas)


def _imagen_desde_html(html: str, base_url: str) -> str | None:
    soup = BeautifulSoup(html, "html.parser")
    candidatos: list[str] = []

    for selector, atributo in (
        ('meta[property="og:image"]', "content"),
        ('meta[name="twitter:image"]', "content"),
        ('meta[itemprop="image"]', "content"),
    ):
        nodo = soup.select_one(selector)
        if nodo and nodo.get(atributo):
            candidatos.append(urljoin(base_url, nodo.get(atributo)))

    for script in soup.select('script[type="application/ld+json"]'):
        texto = script.string or script.get_text()
        candidatos.extend(
            urljoin(base_url, u)
            for u in re.findall(r'"(?:image|contentUrl)"\s*:\s*"([^"]+)"', texto)
        )

    for nodo in soup.select("img[src], img[data-src], img[srcset]"):
        valor = nodo.get("data-src") or nodo.get("src") or nodo.get("srcset", "").split(" ")[0]
        if valor:
            candidatos.append(urljoin(base_url, valor))

    return next((url for url in candidatos if _es_imagen_propiedad(url)), None)


def _extraer_imagen(page: Page, url: str) -> str | None:
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        page.wait_for_timeout(2_500)
        imagen = _imagen_desde_html(page.content(), url)
        if imagen:
            return imagen
    except Exception as exc:
        log.warning("Navegador bloqueado para %s: %s", url, exc)

    try:
        respuesta = httpx.get(
            url,
            follow_redirects=True,
            timeout=25,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/136 Safari/537.36"
                ),
                "Accept-Language": "es-EC,es;q=0.9",
            },
        )
        if respuesta.status_code == 200:
            return _imagen_desde_html(respuesta.text, str(respuesta.url))
    except Exception as exc:
        log.warning("HTTP bloqueado para %s: %s", url, exc)
    return None


def _descargar(page: Page, imagen_url: str, anuncio_url: str) -> tuple[bytes, str] | None:
    try:
        respuesta = page.request.get(
            imagen_url,
            headers={"Referer": anuncio_url},
            timeout=30_000,
        )
        content_type = respuesta.headers.get("content-type", "").split(";")[0].lower()
        if respuesta.status == 200 and content_type in EXTENSIONES:
            return respuesta.body(), content_type
    except Exception as exc:
        log.warning("No se pudo descargar con sesión: %s", exc)

    try:
        respuesta = httpx.get(
            imagen_url,
            follow_redirects=True,
            timeout=25,
            headers={"Referer": anuncio_url},
        )
        content_type = respuesta.headers.get("content-type", "").split(";")[0].lower()
        if respuesta.status_code == 200 and content_type in EXTENSIONES:
            return respuesta.content, content_type
    except Exception as exc:
        log.warning("No se pudo descargar directamente: %s", exc)
    return None


def main() -> None:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
    consulta = (
        supabase.table("listings")
        .select("id,url_fuente,imagen_url,direccion")
        .ilike("direccion", MARCADOR)
        .execute()
    )
    registros = consulta.data or []
    pendientes = [r for r in registros if not r.get("imagen_url")]
    log.info("Napoli: %s registros; %s sin fotografía", len(registros), len(pendientes))

    recuperadas = 0
    with sync_playwright() as playwright:
        navegador = playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        contexto = navegador.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/136 Safari/537.36"
            ),
            locale="es-EC",
        )
        pagina = contexto.new_page()

        for indice, registro in enumerate(pendientes, start=1):
            anuncio_url = registro["url_fuente"]
            log.info("[%s/%s] %s", indice, len(pendientes), anuncio_url)
            imagen_original = _extraer_imagen(pagina, anuncio_url)
            if not imagen_original:
                log.warning("Sin fotografía verificable")
                continue

            descarga = _descargar(pagina, imagen_original, anuncio_url)
            if not descarga:
                log.warning("La fotografía fue detectada, pero no pudo conservarse")
                continue

            contenido, content_type = descarga
            extension = EXTENSIONES[content_type]
            nombre = f"napoli/{hashlib.sha256(anuncio_url.encode()).hexdigest()}{extension}"
            supabase.storage.from_(BUCKET).upload(
                nombre,
                contenido,
                {"content-type": content_type, "x-upsert": "true"},
            )
            url_publica = f"{SUPABASE_URL}/storage/v1/object/public/{BUCKET}/{nombre}"
            supabase.table("listings").update({"imagen_url": url_publica}).eq(
                "id", registro["id"]
            ).execute()
            recuperadas += 1
            log.info("Fotografía almacenada")

        navegador.close()

    log.info(
        "Resultado: %s recuperadas; %s continúan sin foto verificable",
        recuperadas,
        len(pendientes) - recuperadas,
    )


if __name__ == "__main__":
    main()

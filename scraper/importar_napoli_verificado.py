"""Importación controlada de anuncios públicos verificados de Urb. Napoli.

Se usa únicamente cuando el listado de Plusvalía está indexado públicamente
pero su protección anti-bot impide que el scraper diario lea la página.
Cada registro conserva su URL individual como evidencia y se actualiza por
``url_fuente`` para que ejecutar este proceso varias veces no cree duplicados.
"""

from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_KEY, SUPABASE_URL


FUENTE = "Plusvalía · muestra Napoli verificada 2026-07-28"


def ficha(
    *,
    precio: int,
    total: float | None,
    cubierta: float | None,
    habitaciones: int,
    banos: int,
    parqueos: int | None,
    titulo: str,
    url: str,
    amenidades: str = "",
) -> dict:
    precio_m2 = round(precio / cubierta, 2) if cubierta else None
    return {
        "sector": "Vía a Salitre",
        "tipo": "Casa",
        "precio": precio,
        "moneda": "USD",
        "area_m2": cubierta,
        "precio_m2": precio_m2,
        "area_total_m2": total,
        "area_cubierta_m2": cubierta,
        "precio_m2_total": round(precio / total, 2) if total else None,
        "precio_m2_cubierta": precio_m2,
        "confianza_area": 2 if total and cubierta else 1,
        "habitaciones": habitaciones,
        "banos": banos,
        "parqueos": parqueos,
        "titulo": titulo,
        "direccion": f"Urbanización Napoli · Vía a Salitre · {amenidades} · {FUENTE}",
        "url_fuente": url,
        "urbanizacion": "Napoli",
        "activo": True,
        "fecha_scrape": datetime.now(timezone.utc).isoformat(),
    }


LISTINGS = [
    ficha(
        precio=135000, total=130, cubierta=120, habitaciones=3, banos=3, parqueos=2,
        titulo="Casa de 130 m², 3 dormitorios, Napoli, Vía a Salitre",
        amenidades="3 dormitorios con baño",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-casa-de-130-m-sup2--3-dorm-napoli-via-a-salitre-150137351.html",
    ),
    ficha(
        precio=118000, total=121, cubierta=114, habitaciones=3, banos=2, parqueos=1,
        titulo="Venta casa Urb. Napoli, La Aurora, 3 habitaciones",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-venta-casa-urb.-napoli-la-aurora-daule-3-149591583.html",
    ),
    ficha(
        precio=125000, total=120, cubierta=None, habitaciones=3, banos=2, parqueos=2,
        titulo="Casa con jacuzzi en Urb. Napoli",
        amenidades="jacuzzi",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-vendo-casa-con-jacuzzi-en-urb-napoli-144606767.html",
    ),
    ficha(
        precio=145000, total=138, cubierta=None, habitaciones=3, banos=3, parqueos=1,
        titulo="Oportunidad casa Napoli de venta",
        amenidades="piscina",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-oportunidad-casa-napoli-de-venta-149927878.html",
    ),
    ficha(
        precio=180000, total=198.9, cubierta=153, habitaciones=3, banos=3, parqueos=1,
        titulo="Casa de 3 dormitorios en venta, Urbanización Napoli",
        amenidades="piscina y área BBQ",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-casa-de-3-dorm.-en-venta-urbanizacion-napoli-150239279.html",
    ),
    ficha(
        precio=169900, total=167, cubierta=None, habitaciones=3, banos=3, parqueos=1,
        titulo="Acogedora casa en venta en Napoli",
        amenidades="piscina",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-acogedora-casa-en-venta-en-napoli-66423726.html",
    ),
    ficha(
        precio=135000, total=137.7, cubierta=113.38, habitaciones=3, banos=2, parqueos=2,
        titulo="Casa esquinera con jacuzzi en Urb. Napoli",
        amenidades="jacuzzi",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-se-vende-o-se-alquila-casa-esquinera-en-urb.-napoli-149797146.html",
    ),
    ficha(
        precio=115000, total=121, cubierta=114, habitaciones=3, banos=2, parqueos=2,
        titulo="Oportunidad casa en Napoli, 3 habitaciones",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-oportunidad-casa-en-napoli-3-habitaciones-150380045.html",
    ),
    ficha(
        precio=138000, total=122.4, cubierta=None, habitaciones=4, banos=3, parqueos=2,
        titulo="Casa esquinera en Urbanización Napoli",
        amenidades="piscina",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-venta-de-casa-en-urbanizacion-napoli-cg-149235295.html",
    ),
    ficha(
        precio=145000, total=130, cubierta=120, habitaciones=3, banos=3, parqueos=2,
        titulo="Casa con piscina en Urbanización Napoli",
        amenidades="piscina con cascada",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-se-vende-casa-con-piscina-en-urbanizacion-napoli-150481906.html",
    ),
    ficha(
        precio=135000, total=160, cubierta=118, habitaciones=3, banos=3, parqueos=2,
        titulo="Napoli esquinera junto al club, modelo Daniele",
        amenidades="jacuzzi",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-urb.-napoli-esquinera-junto-al-club-modelo-daniele-144659764.html",
    ),
    ficha(
        precio=149000, total=130, cubierta=120, habitaciones=3, banos=3, parqueos=2,
        titulo="Urbanización Napoli, casa con piscina y cascada",
        amenidades="piscina con cascada",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-urbanizacion-napoli-se-vende-linda-casa%21-149890495.html",
    ),
    ficha(
        precio=167000, total=182, cubierta=168, habitaciones=3, banos=3, parqueos=1,
        titulo="Casa con piscina en venta Napoli Vía Salitre",
        amenidades="piscina",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-casa-con-piscina-en-venta-napoli-via-salitre-aurora-148635808.html",
    ),
    ficha(
        precio=168000, total=160, cubierta=136, habitaciones=3, banos=3, parqueos=3,
        titulo="Casa esquinera en Urbanización Napoli, 3 dormitorios",
        amenidades="piscina",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-alquiler-o-venta-casa-urbanizacion-napoli-3-dorm.-148106570.html",
    ),
    ficha(
        precio=160000, total=185, cubierta=160, habitaciones=4, banos=4, parqueos=2,
        titulo="Casa modelo Florencia, Urbanización Napoli",
        amenidades="jacuzzi y dormitorio de servicio con baño",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-en-venta-casa-modelo-florencia-urbanizacion-napoli-146675938.html",
    ),
]


def main() -> None:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    result = client.table("listings").upsert(
        LISTINGS,
        on_conflict="url_fuente",
        ignore_duplicates=False,
    ).execute()
    guardados = len(result.data or [])
    if guardados != len(LISTINGS):
        raise RuntimeError(f"Se esperaban {len(LISTINGS)} fichas y Supabase confirmó {guardados}")
    print(f"Napoli: {guardados} fichas verificadas insertadas/actualizadas")


if __name__ == "__main__":
    main()

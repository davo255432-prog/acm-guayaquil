"""Importación controlada de anuncios públicos verificados de Urb. Veranda.

La muestra distingue propiedades independientes, conserva la URL original como
evidencia y desactiva cuatro copias antiguas del scraper sin borrar historial.
Los precios son precios publicados, no precios de cierre.
"""

from datetime import datetime, timezone

from supabase import create_client

from config import SUPABASE_KEY, SUPABASE_URL


FUENTE = "Muestra Veranda verificada 2026-08-19"

# Dos anuncios reales ingresaron dos veces, con y sin parámetros de seguimiento.
# Se conservan en la base, pero no deben formar parte del universo estadístico.
REGISTROS_DUPLICADOS = [
    "08e14f0a-58a0-4aba-af51-ab97bb7b1609",
    "be2d6e27-2ac3-40c5-bd27-5ea64989e9f2",
    "7c0b45da-8847-420f-838f-e902e81be439",
    "b124d8e6-8a58-4e92-9c9f-bcfadffbb8c9",
]


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
        "sector": "Narcisa de Jesús",
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
        "direccion": f"Urbanización Veranda · Av. Narcisa de Jesús · {amenidades} · {FUENTE}",
        "url_fuente": url,
        "urbanizacion": "Veranda",
        "activo": True,
        "fecha_scrape": datetime.now(timezone.utc).isoformat(),
    }


LISTINGS = [
    ficha(
        precio=117000, total=120, cubierta=169.9, habitaciones=3, banos=2, parqueos=1,
        titulo="Casa de 3 dormitorios en venta, Urb. Veranda",
        amenidades="2,5 baños · patio en L · usada",
        url="https://planetainmobiliarioec.com/property/en-venta-casa-de-3-dormitorios-en-urb-veranda/",
    ),
    ficha(
        precio=125000, total=None, cubierta=127, habitaciones=3, banos=2, parqueos=None,
        titulo="Casa usada de 3 dormitorios en Urbanización Veranda",
        amenidades="2,5 baños · cocina integral · lavandería",
        url="https://inmnovagroup.com/casa-venta-nueva-zona-guayaquil/7502713",
    ),
    ficha(
        precio=126000, total=123, cubierta=134, habitaciones=3, banos=3, parqueos=None,
        titulo="Casa de venta, Urb. Veranda, Av. Narcisa de Jesús",
        amenidades="año 2013 · usada normal",
        url="https://www.fazwaz.com.ec/propiedad-3-habitacion-en-venta/ecuador/guayas/guayaquil?page=18",
    ),
    ficha(
        precio=128000, total=138, cubierta=141, habitaciones=3, banos=2, parqueos=2,
        titulo="Casa esquinera modelo Violeta B en Urbanización Veranda",
        amenidades="2,5 baños · patio esquinero en L · junto al área social",
        url="https://www.remax.com.ec/agent/alexandra-jurado-alarcon",
    ),
    ficha(
        precio=130000, total=122.1, cubierta=147.58, habitaciones=4, banos=4, parqueos=2,
        titulo="Casa modelo Begonia de 4 dormitorios en Urb. Veranda",
        amenidades="baño social · BBQ · 2 parqueos",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-casa-en-venta-av-narcisa-de-jesus-urb-veranda-148943734.html",
    ),
    ficha(
        precio=145000, total=134, cubierta=134, habitaciones=3, banos=3, parqueos=2,
        titulo="Casa totalmente remodelada y semiamoblada en Urb. Veranda",
        amenidades="acabados de lujo · BBQ · baño de servicio",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-casa-en-venta-ubicada-en-urb.-veranda-142928496.html",
    ),
    ficha(
        precio=148000, total=129.93, cubierta=168.96, habitaciones=4, banos=2, parqueos=2,
        titulo="Casa remodelada de 4 dormitorios en Urbanización Veranda",
        amenidades="patio BBQ · cuarto de servicio · diagonal a la cancha",
        url="https://www.plusvalia.com/propiedades/clasificado/veclcain-casa-en-venta-urbanizacion-veranda.-autopista-149136152.html",
    ),
]


def main() -> None:
    client = create_client(SUPABASE_URL, SUPABASE_KEY)
    client.table("listings").update({"activo": False}).in_(
        "id", REGISTROS_DUPLICADOS
    ).execute()

    result = client.table("listings").upsert(
        LISTINGS,
        on_conflict="url_fuente",
        ignore_duplicates=False,
    ).execute()
    guardados = len(result.data or [])
    if guardados != len(LISTINGS):
        raise RuntimeError(
            f"Se esperaban {len(LISTINGS)} fichas y Supabase confirmó {guardados}"
        )
    print(
        f"Veranda: {guardados} fichas verificadas; "
        f"{len(REGISTROS_DUPLICADOS)} copias antiguas conservadas como inactivas"
    )


if __name__ == "__main__":
    main()

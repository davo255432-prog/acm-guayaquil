"""
Limpieza de urbanizaciones mal extraídas en la DB.

Busca registros donde urbanizacion empieza con 'Clasificado/'
o tiene patrones de slug URL, y los corrige usando el título del listing.

Uso:
    python limpiar_urbanizaciones.py
"""
import logging
from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY
from scraper import extraer_urbanizacion_titulo

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


def es_urb_basura(urb: str) -> bool:
    """True si la urbanización parece un artefacto del scraper, no un nombre real."""
    if not urb:
        return False
    u = urb.lower()
    return (
        u.startswith("clasificado") or
        "veclcain" in u or "veclapin" in u or "veclcapa" in u or
        "veclcoin" in u or "veclocin" in u or "vecltein" in u
    )


def main():
    sb = create_client(SUPABASE_URL, SUPABASE_KEY)

    # Traer todos los listings con urbanizacion potencialmente mala
    log.info("Consultando listings con urbanizacion sospechosa...")
    res = sb.table("listings").select("id, urbanizacion, titulo").execute()
    todos = res.data or []

    malos = [l for l in todos if es_urb_basura(l.get("urbanizacion", ""))]
    log.info(f"Total listings: {len(todos)} — Con urb basura: {len(malos)}")

    corregidos = 0
    sin_correccion = 0

    for l in malos:
        titulo = l.get("titulo") or ""
        nueva_urb = extraer_urbanizacion_titulo(titulo)

        if nueva_urb:
            sb.table("listings").update({"urbanizacion": nueva_urb}).eq("id", l["id"]).execute()
            log.info(f"  ✓ [{l['id']}] '{l['urbanizacion'][:40]}' → '{nueva_urb}'")
            corregidos += 1
        else:
            # Si no podemos identificar la urb del título, ponemos null
            # (es mejor null que basura)
            sb.table("listings").update({"urbanizacion": None}).eq("id", l["id"]).execute()
            log.info(f"  ○ [{l['id']}] '{l['urbanizacion'][:40]}' → null (sin match en título)")
            sin_correccion += 1

    log.info(f"\n=== Limpieza completada: {corregidos} corregidos / {sin_correccion} → null ===")


if __name__ == "__main__":
    main()

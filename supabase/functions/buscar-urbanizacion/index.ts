import { serve } from "https://deno.land/std@0.168.0/http/server.ts"
import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, apikey, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
}

const SECTOR_SLUG: Record<string, string> = {
  "Samborondón":              "samborondon",
  "La Puntilla":              "la-puntilla",
  "Norte de Guayaquil":       "norte-de-guayaquil",
  "Los Ceibos":               "los-ceibos",
  "Centro de Guayaquil":      "q-centro",
  "Vía a la Costa":           "q-via-a-la-costa",
  "Av. León Febres Cordero":  "q-leon-febres-cordero",
  "Vía a Salitre":            "q-via-a-salitre",
  "Narcisa de Jesús":         "q-narcisa-de-jesus",
}

const TIPO_SLUG: Record<string, string> = {
  "Casa":            "casas",
  "Departamento":    "departamentos",
  "Oficina":         "oficinas",
  "Consultorio":     "consultorios",
  "Terreno":         "terrenos",
  "Local Comercial": "locales-comerciales",
}

function toSlug(text: string): string {
  return text.toLowerCase()
    .normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/\s+/g, "-")
    .replace(/[^a-z0-9-]/g, "")
}

function buildUrl(tipoSlug: string, sectorKey: string, urbSlug: string): string {
  const base = "https://www.plusvalia.com/venta"
  if (sectorKey.startsWith("q-")) {
    return `${base}/${tipoSlug}/guayas/guayaquil/${sectorKey}/q-${urbSlug}`
  }
  return `${base}/${tipoSlug}/guayas/guayaquil/${sectorKey}/q-${urbSlug}`
}

function parsearEntero(v: unknown): number | null {
  const m = String(v ?? "").match(/\d+/)
  return m ? parseInt(m[0]) : null
}

function extraerListings(html: string, sector: string, tipo: string, urbanizacion: string) {
  const match = html.match(/<script id="__NEXT_DATA__"[^>]*>([\s\S]*?)<\/script>/)
  if (!match) return []
  try {
    const data = JSON.parse(match[1])
    const props = data?.props?.pageProps ?? {}
    const items: any[] = props.listings ?? props.postings ?? props.results ?? props.items ?? []
    if (!Array.isArray(items) || items.length === 0) return []

    return items.map((item: any) => {
      const url = item.permalink ?? item.url ?? item.link ?? ""
      const fullUrl = url.startsWith("http") ? url : "https://www.plusvalia.com" + url
      const precio = item.price ?? item.precio ?? item.prices?.price
      const area = item.surface ?? item.area ?? item.totalArea ?? item.coveredArea
      const p = precio ? parseFloat(precio) : null
      const a = area ? parseFloat(area) : null
      return {
        sector, tipo, urbanizacion,
        precio: p,
        area_m2: a,
        precio_m2: p && a ? Math.round(p / a * 100) / 100 : null,
        habitaciones: parsearEntero(item.rooms ?? item.bedrooms),
        banos:        parsearEntero(item.bathrooms ?? item.banos),
        parqueos:     parsearEntero(item.parking ?? item.garages),
        titulo:       String(item.title ?? item.titulo ?? "").slice(0, 500),
        direccion:    String(item.address ?? item.location?.label ?? "").slice(0, 300),
        url_fuente:   fullUrl,
        imagen_url:   item.photos?.[0]?.url ?? null,
        activo:       true,
      }
    }).filter((r: any) => r.url_fuente && r.url_fuente.length > 10)
  } catch {
    return []
  }
}

serve(async (req) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS })

  try {
    const { sector, tipo, urbanizacion } = await req.json()
    const sectorKey = SECTOR_SLUG[sector]
    const tipoSlug  = TIPO_SLUG[tipo]

    if (!sectorKey || !tipoSlug || !urbanizacion) {
      return new Response(JSON.stringify({ listings: [], error: "Parámetros inválidos" }), {
        headers: { ...CORS, "Content-Type": "application/json" }
      })
    }

    const urbSlug      = toSlug(urbanizacion)
    const plusvaliaUrl = buildUrl(tipoSlug, sectorKey, urbSlug)
    const apiKey       = Deno.env.get("SCRAPERAPI_KEY") ?? ""

    const resp = await fetch(
      `https://api.scraperapi.com/?api_key=${apiKey}&url=${encodeURIComponent(plusvaliaUrl)}&render=false`,
      { signal: AbortSignal.timeout(55000) }
    )

    if (!resp.ok) throw new Error(`ScraperAPI HTTP ${resp.status}`)

    const html     = await resp.text()
    const listings = extraerListings(html, sector, tipo, urbanizacion)

    if (listings.length > 0) {
      const supabase = createClient(
        Deno.env.get("SUPABASE_URL") ?? "",
        Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? ""
      )
      await supabase.from("listings").upsert(listings, { onConflict: "url_fuente" })
    }

    return new Response(JSON.stringify({ listings, count: listings.length }), {
      headers: { ...CORS, "Content-Type": "application/json" }
    })
  } catch (err) {
    return new Response(JSON.stringify({ listings: [], error: String(err) }), {
      headers: { ...CORS, "Content-Type": "application/json" }
    })
  }
})

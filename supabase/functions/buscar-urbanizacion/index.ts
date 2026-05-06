import { createClient } from "https://esm.sh/@supabase/supabase-js@2"

const CORS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers": "Content-Type, Authorization, apikey, x-client-info",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
}

function dedup(listings: any[]): any[] {
  const seen = new Set<string>()
  return listings.filter(l => {
    const base = (l.url_fuente || "").split("?")[0]
    if (seen.has(base)) return false
    seen.add(base)
    return true
  })
}

Deno.serve(async (req: Request) => {
  if (req.method === "OPTIONS") return new Response(null, { headers: CORS })

  try {
    const { sector, tipo, urbanizacion } = await req.json()

    if (!sector || !tipo || !urbanizacion) {
      return new Response(
        JSON.stringify({ listings: [], error: "Parámetros inválidos" }),
        { status: 200, headers: { ...CORS, "Content-Type": "application/json" } }
      )
    }

    const supabase = createClient(
      Deno.env.get("SUPABASE_URL")!,
      Deno.env.get("SUPABASE_SERVICE_ROLE_KEY")!
    )

    // 1. Campo urbanizacion exacto
    const { data: porUrb } = await supabase
      .from("listings").select("*")
      .eq("sector", sector).eq("tipo", tipo)
      .ilike("urbanizacion", urbanizacion).eq("activo", true).limit(100)

    const r1 = dedup(porUrb ?? [])
    if (r1.length > 0) return ok(r1)

    // 2. Título contiene el nombre completo de la urbanización
    const { data: porTitulo } = await supabase
      .from("listings").select("*")
      .eq("sector", sector).eq("tipo", tipo)
      .ilike("titulo", `%${urbanizacion}%`).eq("activo", true).limit(100)

    const r2 = dedup(porTitulo ?? [])
    if (r2.length > 0) return ok(r2)

    // 3. Primera palabra en campo urbanizacion (solo si tiene 2+ palabras)
    const palabras = urbanizacion.trim().split(/\s+/)
    if (palabras.length >= 2) {
      const { data: porPalabra } = await supabase
        .from("listings").select("*")
        .eq("sector", sector).eq("tipo", tipo)
        .ilike("urbanizacion", `%${palabras[0]}%`).eq("activo", true).limit(100)

      const r3 = dedup(porPalabra ?? [])
      if (r3.length >= 3) return ok(r3)
    }

    // 4. Fallback: sector + tipo completo
    const { data: loose } = await supabase
      .from("listings").select("*")
      .eq("sector", sector).eq("tipo", tipo)
      .eq("activo", true).limit(50)

    return ok(dedup(loose ?? []))

  } catch (err) {
    return new Response(
      JSON.stringify({ listings: [], error: String(err) }),
      { status: 200, headers: { ...CORS, "Content-Type": "application/json" } }
    )
  }
})

function ok(listings: any[]) {
  return new Response(
    JSON.stringify({ listings, count: listings.length }),
    { status: 200, headers: { ...CORS, "Content-Type": "application/json" } }
  )
}

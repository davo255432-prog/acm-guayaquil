-- ACM Bienes Raíces Guayaquil — Schema Supabase
-- Ejecutar en: Supabase Dashboard > SQL Editor

CREATE TABLE IF NOT EXISTS listings (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sector        TEXT NOT NULL,
    tipo          TEXT NOT NULL,
    precio        NUMERIC,
    moneda        TEXT DEFAULT 'USD',
    area_m2       NUMERIC,
    precio_m2     NUMERIC,
    habitaciones  SMALLINT,
    banos         SMALLINT,
    parqueos      SMALLINT,
    titulo        TEXT,
    direccion     TEXT,
    url_fuente    TEXT UNIQUE NOT NULL,
    imagen_url    TEXT,
    fecha_scrape  TIMESTAMPTZ DEFAULT NOW(),
    activo        BOOLEAN DEFAULT TRUE
);

-- Índices para consultas frecuentes del ACM
CREATE INDEX IF NOT EXISTS idx_sector_tipo      ON listings(sector, tipo);
CREATE INDEX IF NOT EXISTS idx_fecha_scrape     ON listings(fecha_scrape DESC);
CREATE INDEX IF NOT EXISTS idx_precio_m2        ON listings(precio_m2) WHERE precio_m2 IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_activo           ON listings(activo) WHERE activo = TRUE;

-- Vista pública para el frontend (solo listings activos)
CREATE OR REPLACE VIEW listings_activos AS
SELECT
    id, sector, tipo, precio, moneda, area_m2, precio_m2,
    habitaciones, banos, parqueos, titulo, direccion,
    url_fuente, imagen_url, fecha_scrape
FROM listings
WHERE activo = TRUE;

-- Habilitar acceso anónimo de lectura (para el frontend JS)
ALTER TABLE listings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Lectura publica de listings activos"
    ON listings FOR SELECT
    USING (activo = TRUE);

-- Solo el service_role (scraper) puede insertar/actualizar
CREATE POLICY "Solo service role puede escribir"
    ON listings FOR ALL
    USING (auth.role() = 'service_role');

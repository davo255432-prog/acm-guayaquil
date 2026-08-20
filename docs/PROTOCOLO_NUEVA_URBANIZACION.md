# Protocolo ACM para una urbanización nueva

Este protocolo se aplica cuando Plusvalía no entrega suficientes comparables
directos para una urbanización. Amplía las fuentes sin modificar la lógica
general de homologación y valoración del ACM.

## Regla principal

La lógica estadística y de homologación permanece igual para todas las zonas.
Lo que se amplía es únicamente el universo de evidencia disponible para la
urbanización nueva.

## Flujo obligatorio

1. Registrar la propiedad objetivo: sector, urbanización, etapa, tipo,
   dormitorios, baños, parqueos, pisos, condición, terreno y construcción.
2. Consultar primero la base ACM alimentada desde Plusvalía.
3. Si existen menos de cinco propiedades directas o la muestra es débil,
   investigar fuentes inmobiliarias adicionales.
4. Aceptar únicamente anuncios que permitan verificar una propiedad
   individual. Se pueden usar Plusvalía, REMAX, BuscoCasita, sitios de
   inmobiliarias y otros portales con ficha técnica identificable.
5. Confirmar en cada ficha: urbanización, precio publicado, áreas, dormitorios,
   baños, parqueos, condición y URL de origen.
6. Comparar título, áreas, descripción y fotografías para evitar republicaciones
   de una misma casa. El mismo precio no significa por sí solo que sea duplicado.
7. Rechazar páginas de resultados generales, perfiles sin datos de la propiedad,
   anuncios de otra urbanización y fichas sin evidencia suficiente.
8. Importar la muestra de forma controlada en Supabase. Un anuncio retirado o
   reemplazado se marca inactivo; no se borra el historial.
9. Ejecutar el ACM con la lógica general, revisar dispersión, compatibilidad y
   posibles valores atípicos.
10. Agregar manualmente las capturas de las propiedades cuando el portal no
    permita obtenerlas de forma confiable. Las imágenes no determinan el valor;
    documentan visualmente la evidencia y se incorporan al PDF.
11. Generar el preliminar y verificar que cada enlace abra la fuente esperada
    antes de producir el informe profesional.

## Criterios de calidad de las fuentes

- **Fuerte:** anuncio individual, activo, misma urbanización y ficha técnica
  completa.
- **Aceptable:** anuncio individual con datos suficientes, aunque falte un campo
  secundario.
- **Débil:** datos parciales o fuente indirecta; solo se conserva con advertencia.
- **No utilizable:** página general, enlace que no identifica la casa, duplicado
  o inmueble de otra urbanización.

## Controles que nunca deben omitirse

- No inventar datos ausentes ni interpretar “no informado” como “no tiene”.
- No mezclar urbanizaciones similares para aumentar artificialmente la muestra.
- No contar dos veces una propiedad republicada en plataformas distintas.
- Conservar el precio como precio publicado, no como precio de cierre.
- Mantener la URL exacta como trazabilidad para el preliminar y el PDF.
- Informar confianza baja cuando el universo siga siendo pequeño.

## Caso de referencia: Veranda

Veranda inauguró este protocolo. Ante una muestra insuficiente en Plusvalía se
contrastaron anuncios individuales de Plusvalía, REMAX, BuscoCasita y sitios de
inmobiliarias. Se retiró del universo una página general de FazWaz, se conservaron
los datos históricos como inactivos y se incorporó una ficha individual de
BuscoCasita. Las fotografías faltantes se añadieron manualmente mediante el flujo
de capturas del ACM.


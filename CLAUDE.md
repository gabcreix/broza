# broza — contexto persistente

Utilidad de agregación e inteligencia de contenido: a partir de una configuración de
usuario (fuentes + consultas), ingiere contenido heterogéneo (foros, prensa, redes), lo
normaliza/entiende, y permite generar informes/newsletters. Monorepo gestionado como
**uv workspace** con dos miembros con frontera de paquete clara.

## Las dos capas

- **`core/`** (paquete `broza-core`, import `core`) — adquisición, normalización,
  enriquecimiento, almacenamiento y motor de consulta. Agnóstico de fuente y de proyecto.
  Depende solo del modelo canónico `Item` y de una interfaz de almacenamiento. No importa
  nada de `app/`. Pensado para poder extraerse a repo propio el día que otro proyecto
  (p. ej. `ai-social`) lo necesite — por eso vive como miembro de workspace independiente
  desde ya, no como módulo suelto.
- **`app/`** (paquete `broza-app`, import `app`) — la newsletter. Consume `core`, construye
  Gold (curación/ranking por feed), plantillas, UI de configuración (Streamlit) y
  orquestación (bajo demanda + programada).

## Abstracciones centrales

1. **`Item` canónico** (`core/models/item.py`) — el contrato. Todo el contenido, sea cual
   sea la fuente, se mapea a este modelo pydantic. Nada aguas abajo conoce la fuente concreta.
2. **Conectores** (`core/connectors/base.py`) — cada fuente implementa `Connector` y declara
   `capabilities` (keyword search, filtro por fecha, categorías nativas, paginación) y
   `acquisition` (cascada API → RSS → scraping). Una fuente = instancia de conector (tipo +
   parámetros, p. ej. reddit + subreddit). Registro en código (`register_connector`) que la
   UI lee (`list_connector_descriptors`) para poblar el desplegable; mismo dato se refleja
   en `config.connectors`.
3. **Consultas = tópicos (unificado)** — una consulta vive en una librería reutilizable
   (`config.queries`) y se adjunta (bind) a fuentes en relación N:N. Hay consultas globales
   (`feed_global_queries`, aplican a todas las fuentes del feed) y por fuente
   (`feed_bindings`). Mismo mecanismo para boolean y lenguaje natural.
4. **Motor de consulta** (`core/query/`, pendiente de implementar) — planificador
   capability-aware: empuja a la fuente lo que soporta (pushdown) y evalúa el resto con un
   embudo barato→caro: filtro nativo/keyword → similitud por embeddings (pgvector) → juez
   LLM (Claude Haiku) sobre la lista corta. Nunca el corpus entero al LLM.
5. **Enriquecimiento** (`core/enrichment/`, pendiente) — pasos pluggables sobre el `Item`:
   texto completo → idioma → dedup → clasificación de tópicos → embeddings → entidades →
   resumen. Re-ejecutable sin re-fetch.
6. **`FeedDefinition`** (`core/models/config.py`) — ata nombre + bindings + consultas
   globales + salida (formato/canal/plantilla) + ejecución (modo/frecuencia/ventana). Es a
   la vez búsqueda guardada, spec de newsletter e input de API.
7. **Generación de newsletter** (`app/reports/`, pendiente) — consumidor del motor de
   consulta + curación/ranking (`app/gold/`) + plantilla + envío.

## Arquitectura de datos: medallion en Postgres (NO lakehouse)

Esquemas en Supabase/Postgres, migraciones SQL versionadas en `migrations/` (pgvector
habilitado en `0001_extensions.sql`).

- **`bronze.raw_items`** — crudo tal cual lo trae el conector, append-only e inmutable.
  Existe para poder reprocesar sin re-scrapear. Sin unicidad en `(connector_type,
  external_id)`: el mismo item puede re-fetchearse en sucesivas ejecuciones.
- **`silver.items`** — el `Item` canónico, conformado/deduplicado/enriquecido. **Frontera
  de reutilización**: el núcleo produce hasta aquí; cada app construye su propio Oro.
  Upsert keyed on `canonical_url` (o, en su ausencia, `source_instance_id` + clave natural
  del raw). `silver.item_embeddings` (vector(1536), modelo `text-embedding-3-small`,
  índice hnsw cosine). `silver.translations` cachea traducción bajo demanda.
- **`gold.feed_items`** — selección rankeada por feed y ventana (`gold.feed_runs`),
  recomputada por `run_id` para que re-ejecutar no duplique. `gold.topic_trends` opcional.

## Convenciones y no-negociables

- **ELT, no ETL**: aterriza en Bronce primero, transforma in situ.
- **Idempotencia**: Bronce append-only; watermarks por `source_instance`; Plata
  upsert/merge; Oro recomputado por `run_id`.
- **Frontera de reutilización**: cero lógica de newsletter/Gold dentro de `core/`.
- **Planificador capability-aware**: lo que la fuente no sabe filtrar cae al embudo
  semántico.
- **Contenido completo por tipo de fuente**: prensa → cuerpo del texto; foro (Reddit) →
  post + top 10 comentarios; social → post + hilo + enlaces externos resueltos como
  `Item` hijos (el enlazado usa el conector de prensa).
- **Multilingüe**: guarda siempre el original; traducción bajo demanda cacheada en
  `silver.translations`.
- **Embudo de coste**: nativo/keyword → embeddings → Haiku solo sobre la lista corta.
- **Secretos por entorno**: nada de credenciales en código; `.env` (ver `.env.example`).
- **Conectores extensibles**: una fuente nueva = un conector que se auto-registra; no
  toca `Item`, motor ni UI.

## Decisiones tomadas

- Monorepo con `core/` y `app/` como miembros de un **uv workspace** (no repos
  independientes); cada uno tiene su propio `pyproject.toml` y vive bajo `src/` (src-layout)
  para mantener la frontera de paquete clara y poder extraerse sin fricción si hiciera falta.
- Embeddings: **OpenAI `text-embedding-3-small`**, 1536 dims (`silver.item_embeddings`).
- UI de configuración v1: **Streamlit**.
- Reddit: **scraping** de los endpoints JSON públicos (sin OAuth/praw) — elegido sobre la
  API oficial; `acquisition = [scraping]`.
- Medios RSS de v1 (para validar el conector `press_rss`): **El País + BBC News**. El
  conector no los hardcodea: cada medio es una `source_instance` (`feed_url` como param).

## Decisiones pendientes

Ninguna abierta por ahora.

## Alcance v1

**Dentro**: conectores Reddit (subforo) + Prensa RSS (un par de medios); Bronce/Plata/Oro
completas; motor de consulta con juez Haiku; una newsletter; UI Streamlit; modo bajo
demanda + programado.

**Fuera (post-v1)**: X/Twitter (sin vía de adquisición viable); muros de pago; marts de
tendencia avanzados; multi-tenant.

## Orden de construcción

1. Scaffolding + `CLAUDE.md` + migraciones + `Item` + contrato de conector — **hecho**.
   Migraciones validadas contra un proyecto Supabase real (config/bronze/silver/gold +
   pgvector confirmados).
2. Conectores Reddit y RSS — **hecho**. `core/connectors/reddit.py` (scraping JSON público,
   post + top 10 comentarios como raw_items separados) y `core/connectors/rss.py`
   (RSS para descubrir entradas + trafilatura sobre la página del artículo para el cuerpo
   completo). Probados offline con `httpx.MockTransport`; aún no se han ejecutado contra
   las fuentes reales (Reddit/El País/BBC) ni conectado a la ingesta.
3. Ingesta Bronce (aterrizaje de crudo, watermarks, idempotencia).
4. Pipeline de enriquecimiento Bronce→Plata.
5. Motor de consulta (pushdown + embeddings + juez Haiku) y librería de consultas.
6. Gold: ejecución de feed (curación/ranking por feed y ventana).
7. Generación de newsletter (plantilla + render + envío).
8. UI de configuración (Streamlit) sobre las tablas de config.
9. Orquestación (bajo demanda + programada).

## Estructura de repo

```
repo/
  core/                    # paquete broza-core (workspace member)
    pyproject.toml
    src/core/
      models/              # Item canónico, RawPayload, modelos de config
      connectors/           # base.py: contrato Connector + registro + capabilities
                             # reddit.py, rss.py: conectores Reddit y Prensa-RSS
      enrichment/           # pasos pluggables (pendiente)
      query/                # planificador (pendiente)
      storage/              # interfaz + impl Supabase (pendiente)
      ingestion/             # orquestación bronce→plata (pendiente)
  app/                     # paquete broza-app (workspace member, depende de core)
    pyproject.toml
    src/app/
      gold/                # curación/ranking por feed (pendiente)
      reports/             # plantillas + render + envío (pendiente)
      ui/                   # Streamlit (pendiente)
      scheduler/            # bajo demanda + programado (pendiente)
  migrations/              # SQL por capas (config, bronze, silver, gold)
  pyproject.toml           # raíz del uv workspace (virtual, sin [project])
  .env.example
```

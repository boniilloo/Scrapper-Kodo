# Kodo People Scraper

Servicio HTTP que recibe la URL pública de un informe **Soft Skills PRO** de Kodo People y devuelve su contenido en JSON: cabecera, los 18 *behavioral drivers* del radar (puntuaciones 0–100) y, por cada uno, su análisis detallado con todas las sub-variables (escala −150…+150, descripciones polares y posición del marcador).

- **Producción:** https://kodo.fqsource.com
- **Docs interactivas (Swagger UI):** https://kodo.fqsource.com/docs

## Cómo funciona

La página renderiza el radar con [ECharts](https://echarts.apache.org/) sobre un `<canvas>`, así que el listado de los 18 drivers solo existe en el JS del cliente, no en el HTML. Por eso usamos Playwright + Chromium headless:

1. Cargamos la URL y esperamos a que la instancia de ECharts esté montada.
2. Leemos los drivers directamente del objeto del chart (`echarts.getInstanceByDom(...).getOption()`).
3. Recorremos la sección *"Behavioral Variables Analysis"* para extraer definición y sub-variables de cada driver.
4. Devolvemos todo serializado en un único JSON.

## Requisitos

- Docker 20+ y Docker Compose v2

Para uso local sin Docker: Python 3.12 y `playwright install chromium`.

## Quick start

Usa la instancia desplegada o levántate una local con Docker.

**Instancia en producción:**

```bash
curl https://kodo.fqsource.com/health
```

**Local con Docker:**

```bash
docker compose up -d --build
curl http://localhost:8000/health
```

En ambos casos `/health` devolverá `{"status":"ok","browser_connected":true,"max_concurrency":2}`.

Para apagar la local:

```bash
docker compose down
```

## API

Docs interactivas (Swagger UI generado por FastAPI):

- Prod: [`https://kodo.fqsource.com/docs`](https://kodo.fqsource.com/docs)
- Local: [`http://localhost:8000/docs`](http://localhost:8000/docs)

### `POST /scrape`

Body JSON:

```json
{ "url": "https://app.kodopeople.com/index.php?r=report%2Fshare&id=..." }
```

Respuesta `200 OK` (resumida):

```json
{
  "source_url": "https://app.kodopeople.com/...",
  "header": {
    "name": null,
    "start_date": "15/01/2025",
    "finish_date": "15/01/2025",
    "assessment": "Soft Skills PRO Assessment"
  },
  "behavioral_scoring": {
    "driver_count": 18,
    "drivers": [
      { "name": "Teamwork", "value": 98.03, "max": 100 },
      { "name": "Creativity", "value": 57.42, "max": 100 }
    ]
  },
  "behavioral_variables_analysis": {
    "driver_count": 18,
    "drivers": [
      {
        "name": "Trabajo en equipo",
        "score": 98.03,
        "definition": "High score: People who collaborate effectively...",
        "variables": [
          {
            "name": "Cooperativeness",
            "value": 130,
            "marker_percent": 93.52,
            "low_description": "Unwilling to cooperate with others for the common good",
            "high_description": "Willing to cooperate with others for the common good, even at personal cost"
          }
        ]
      }
    ]
  }
}
```

Ejemplo de llamada contra producción:

```bash
curl -X POST https://kodo.fqsource.com/scrape \
  -H "Content-Type: application/json" \
  -d '{"url":"https://app.kodopeople.com/index.php?r=report%2Fshare&id=..."}'
```

(en local, sustituye `https://kodo.fqsource.com` por `http://localhost:8000`)

Códigos de error:

| Código | Significado |
|--------|-------------|
| `422`  | Body inválido (URL ausente o mal formada). |
| `502`  | El destino devolvió un error o no fue alcanzable (DNS, TLS, 4xx/5xx remoto). |
| `503`  | El navegador del servicio no está disponible. |
| `504`  | La navegación o el render superaron el timeout. |
| `500`  | Error inesperado (revisar logs). |

### `GET /health`

Health check usado también por el `HEALTHCHECK` del contenedor.

```json
{ "status": "ok", "browser_connected": true, "max_concurrency": 2 }
```

## Configuración

Variables de entorno (definidas en [`docker-compose.yml`](docker-compose.yml)):

| Variable            | Default | Descripción |
|---------------------|---------|-------------|
| `MAX_CONCURRENCY`   | `2`     | Scrapes simultáneos permitidos por instancia. |
| `SCRAPE_TIMEOUT_MS` | `60000` | Timeout máximo de la navegación por request. |
| `LOG_LEVEL`         | `INFO`  | Nivel de logging del servicio. |

Para Chromium dentro del contenedor: `shm_size: 1gb` está fijado en el compose porque el `/dev/shm` por defecto de Docker (64 MB) hace que el navegador se caiga bajo carga.

## CLI (sin Docker)

El módulo `scrape_kodo.py` también funciona como script standalone:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

python scrape_kodo.py "<report_url>" --out report.json
```

Opciones:

- `--out PATH`   archivo de salida (default `report.json`).
- `--headful`    abrir el navegador con UI (útil para depurar).

## Estructura del repo

```
.
├── app.py                # FastAPI: endpoints y ciclo de vida del browser
├── scrape_kodo.py        # Lógica de scraping (función + CLI)
├── requirements.txt
├── Dockerfile            # Imagen oficial de Playwright + nuestro código
├── docker-compose.yml
└── .dockerignore
```

## Notas y limitaciones

- **Idioma mixto.** La página de Kodo People rinde el radar con etiquetas en inglés (`Teamwork`, `Creativity`, …) pero los títulos de la sección 2 vienen en español (`Trabajo en equipo`, …) aunque la UI esté en inglés. El JSON refleja ambas tal cual aparecen; los drivers están en el mismo orden en ambas secciones, así que es trivial mapearlos si se necesita un único idioma.
- **Anonimato.** Si la URL es un share link anónimo, `header.name` saldrá `null`.
- **Hotjar.** La página intenta cargar Hotjar y emite un warning al detectar el user-agent de HeadlessChrome; es ruido inofensivo.
- **Rendimiento.** ~4–6 s por request en una máquina decente. El cuello de botella es la navegación + `networkidle`, no el parsing.
- **Escalado.** Subir `MAX_CONCURRENCY` consume memoria proporcionalmente (cada `BrowserContext` cuesta ~50–80 MB). Para más throughput es mejor escalar horizontalmente con varias réplicas.

## Licencia

Pendiente.

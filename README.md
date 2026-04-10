# EdilCloud Backend DN

Backend v3 ufficiale di EdilCloud, costruito come modular monolith Django per servire `edilcloud-next` senza dipendenze runtime residue dal backend legacy nei domini core locali.

## Stato reale

Ad oggi il repository copre in locale:

- stack Docker-first con `db`, `redis`, `web` e `assistant-worker`
- backend pubblico su `http://localhost:8001`
- `identity`, `workspaces`, `projects`, `feed/files`, `notifications/realtime`, `search` e `assistant`
- matrix frontend-backend rigenerata con `0` riferimenti runtime residui a `/api/frontend/...` in `edilcloud-next/src`
- runtime dev con `X-Request-ID`, logging configurabile `console/json`, healthcheck esteso e CI dev backend

Roadmap operativa: [docs/ROADMAP_V3.md](docs/ROADMAP_V3.md)  
Roadmap assistant retrieval: [docs/ASSISTANT_RETRIEVAL_ROADMAP.md](docs/ASSISTANT_RETRIEVAL_ROADMAP.md)  
Compatibility matrix: [docs/FRONTEND_COMPATIBILITY_MATRIX.md](docs/FRONTEND_COMPATIBILITY_MATRIX.md)

## Stack

- Python 3.13
- Django 5.2 LTS
- Django Ninja
- PostgreSQL 18
- pgvector
- Redis
- Channels / ASGI
- OpenAI `gpt-4o-mini`
- OpenAI embeddings `text-embedding-3-large`

## Quickstart

### Docker-first

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
docker compose up --build -d
docker compose logs -f web
docker compose logs -f assistant-worker
```

Per la produzione prepara prima il file `.env.production` partendo da `.env.production.example`.

Comandi utili:

```powershell
docker compose ps
docker compose down
docker compose down -v
```

Questo flusso:

- avvia `PostgreSQL/pgvector` e `Redis` nella rete Docker
- applica automaticamente `migrate`
- esegue `collectstatic`
- avvia il worker di indicizzazione assistant
- espone il backend su `http://localhost:8001`

### Venv locale

```powershell
cd "c:\Users\acoti\Desktop\EDILCLOUD\EDILCLOUD 3.0\edilcloud-back-dn"
..\venv\Scripts\python.exe -m pip install -e .[dev]
..\venv\Scripts\python.exe manage.py check
..\venv\Scripts\python.exe manage.py runserver 0.0.0.0:8001
```

## Endpoint utili

- root: `http://localhost:8001/`
- health: `http://localhost:8001/api/v1/health`
- docs OpenAPI: `http://localhost:8001/api/v1/docs`
- auth: `http://localhost:8001/api/v1/auth/*`
- workspaces: `http://localhost:8001/api/v1/workspaces/*`
- projects: `http://localhost:8001/api/v1/projects/*`
- notifications: `http://localhost:8001/api/v1/notifications/*`
- search: `http://localhost:8001/api/v1/search/global`

## Dataset e smoke

- progetto demo ricco: `Residenza Parco Naviglio - Lotto A`
- smoke AI locale: `..\venv\Scripts\python.exe scripts\smoke_ai_flows.py`
- CI backend: `.github/workflows/ci.yml`
- deploy produzione: `.github/workflows/deploy-production.yml`
- compose server produzione: `docker-compose.server.yml`
- reindex manuale assistant: `..\venv\Scripts\python.exe manage.py run_assistant_indexer --project-id 1`

## Priorita residue

- smoke browser completi su feed, realtime e search
- audit permessi `owner/delegate/manager/worker`
- geocoding/mappe e media end-to-end
- quality pass retrieval/rerank su dataset piu grandi
- hardening e produzione

Billing resta esplicitamente fuori priorita in questa fase.

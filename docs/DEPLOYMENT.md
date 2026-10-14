# Reproducible container deployment

This release adds real API and static frontend images, an Nginx reverse proxy, a private pgvector database, persistent storage, non-root application containers and health-gated startup. The frontend uses built production assets, not the Vite development server. This is a locally tested deployment architecture; it is not a public cloud production deployment.

## Run from a clean checkout

Prerequisites: Docker Desktop/Engine with Compose, Python to configure secrets, and an Ollama endpoint with qwen3:1.7b and nomic-embed-text installed. On Docker Desktop, host.docker.internal reaches the host inference endpoint. Make sure Ollama is reachable from containers. On a server, use DEPLOY_OLLAMA_BASE_URL in .env for the private inference service. Do not expose Ollama publicly.

```powershell
python scripts/configure.py
docker compose -f compose.deploy.yml up -d --build --wait
docker compose -f compose.deploy.yml exec api python /app/scripts/seed.py
docker compose -f compose.deploy.yml exec api python -m pytest -q
```

Open http://localhost:15174. The browser API uses the same-origin /api reverse proxy. API documentation is at http://localhost:15174/api/docs. Read local credentials in LOGIN.txt. The separate deployment database and storage volumes leave the original development data intact. Initial seed requires real embedding inference. CPU-only inference is supported but slower.

```powershell
docker compose -f compose.deploy.yml ps
docker compose -f compose.deploy.yml logs --tail 100 api
docker compose -f compose.deploy.yml down
```

The last command preserves volumes. Avoid down --volumes unless intentionally deleting this deployment's data. Model service availability must also be checked; API readiness alone does not prove that both inference models are installed.

## Public hosting requirements

Choose a host with enough RAM/GPU capacity for Ollama or a private inference service. Configure DNS and TLS, replace seeded demo credentials, use secret storage, restrict network access and implement backups/restore tests. Keep one API worker because the MVP uses in-process tasks and local checkpoint state. Durable workers, stronger session management, rate limiting and monitored recovery are required before organizational production use. Do not list a public demo URL until its authenticated workflows have been tested.

The prepared-format procurement parser, preview-only notifications and human-recorded remediation limitations remain unchanged. See GUIDE_COVERAGE.md and the detailed interview document.

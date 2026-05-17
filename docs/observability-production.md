# Osservabilita produzione

## Componenti

- Grafana: dashboard operative e drill-down tecnico.
- Prometheus: metriche host, container, database, Redis, probe pubbliche e backend.
- Loki: log container con retention di 14 giorni.
- Tempo: trace OTLP con retention di 7 giorni.
- Alloy: raccolta log Docker e ricezione OTLP.
- node-exporter: CPU, RAM, filesystem e rete host.
- cAdvisor: CPU, RAM, filesystem e rete dei container.
- postgres-exporter e redis-exporter: stato datastore.
- blackbox-exporter: disponibilita pubblica di backend e frontend.

## Sicurezza iniziale

Grafana e Prometheus sono esposti solo su `127.0.0.1`:

- Grafana: `${GRAFANA_BIND_PORT:-13000}`
- Prometheus: `${PROMETHEUS_BIND_PORT:-19090}`

Prima di pubblicare Grafana su un dominio:

1. impostare `GRAFANA_ADMIN_PASSWORD`;
2. metterlo dietro reverse proxy HTTPS;
3. mantenere signup anonimo disabilitato;
4. preferire SSO o IP allowlist per l'area operativa.

## Avvio server

```bash
docker compose --env-file .env.production -f docker-compose.server.yml up -d \
  prometheus node-exporter cadvisor postgres-exporter redis-exporter \
  blackbox-exporter loki tempo alloy grafana
```

## Prime viste disponibili

- `EdilCloud Operations`: CPU, memoria, disco, health pubblica, p95 backend,
  memoria container, richieste HTTP e log recenti.
- Explore Grafana:
  - Prometheus per metriche;
  - Loki per log;
  - Tempo per trace.

## Metriche applicative backend

Il backend espone metriche Prometheus su:

```text
/api/v1/health/metrics/prometheus
```

Le serie principali sono:

- `edilcloud_counter_total`
- `edilcloud_timing_p95_milliseconds`
- `edilcloud_timing_p99_milliseconds`
- `edilcloud_timing_max_milliseconds`

## Prossimi innesti

1. Collegare OTLP del backend a Alloy per popolare Tempo.
2. Aggiungere alert rule Prometheus/Grafana per:
   - CPU, memoria e disco;
   - probe pubbliche fallite;
   - p95 route core;
   - error ratio HTTP;
   - database e Redis down.
3. Inserire link Grafana dal Test Center per issue, route e finestre temporali.

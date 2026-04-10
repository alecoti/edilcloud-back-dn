# Deploy Zero-Downtime

Il repository supporta due modalita di deploy server:

- `rolling`: aggiorna lo slot attivo e puo introdurre un micro-riavvio del backend
- `blue_green`: alza il nuovo slot su una seconda porta, lo valida, poi sposta il traffico e solo dopo spegne quello precedente

## Variabili

File richiesti sul server:

- `.env.production`
- `.deploy.production`

Parti minime di `.env.production`:

- `BACKEND_BIND_IP=127.0.0.1`
- `BACKEND_BLUE_PORT=18001`
- `BACKEND_GREEN_PORT=18002`

Parti minime di `.deploy.production`:

- `DEPLOY_STRATEGY=blue_green`
- `PROXY_SWITCH_STRATEGY=nginx_upstream_file`
- `PROXY_UPSTREAM_FILE=/etc/nginx/conf.d/edilcloud-back-upstream.conf`
- `PROXY_VALIDATE_COMMAND=nginx -t`
- `PROXY_RELOAD_COMMAND=systemctl reload nginx`
- `LIVE_HOST_HEADER=back.edilcloud.eu`

## Come funziona

1. GitHub Actions valida il backend con check Django e test.
2. Il server riceve il nuovo archivio e aggiorna il codice in `/opt/edilcloud/back-dn`.
3. Lo slot inattivo (`blue` o `green`) viene buildato e avviato sulla sua porta dedicata.
4. Il workflow aspetta l'healthcheck locale dello slot nuovo.
5. Se il proxy e configurato, aggiorna l'upstream live verso la nuova porta.
6. Avvia il worker dello slot nuovo e ferma quello vecchio.
7. Se qualcosa fallisce, ripristina il codice precedente e riporta attivo lo slot vecchio.

## Requisito proxy

Per arrivare davvero a zero downtime il traffico pubblico deve passare da un reverse proxy che possa puntare alternativamente a:

- `127.0.0.1:18001`
- `127.0.0.1:18002`

Con `PROXY_SWITCH_STRATEGY=nginx_upstream_file` il workflow scrive un file upstream compatibile con Nginx:

```nginx
upstream edilcloud_backend_upstream {
    server 127.0.0.1:18001;
    keepalive 32;
}
```

Il virtual host Nginx deve poi usare:

```nginx
proxy_pass http://edilcloud_backend_upstream;
```

## Nota operativa

Il web puo andare a downtime zero reale solo quando il proxy live viene aggiornato via switch. Se lasci `PROXY_SWITCH_STRATEGY=none`, il workflow resta compatibile ma torna a comportamento rolling.

La primissima migrazione dal vecchio servizio singolo `web` al modello `web-blue/web-green` puo comunque introdurre un riavvio una tantum, perche deve liberare la porta storica prima di stabilizzare i due slot.

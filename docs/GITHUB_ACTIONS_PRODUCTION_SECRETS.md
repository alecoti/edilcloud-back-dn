# GitHub Actions Production Secrets

Per questo repository usa un environment GitHub chiamato `production` e salva qui le credenziali del deploy.

Percorso UI GitHub:

`Repository > Settings > Environments > production`

Dentro `production` crea questi secrets:

- `PROD_HOST`: hostname o IP del server
- `PROD_PORT`: porta SSH, di solito `22`
- `PROD_USER`: utente SSH che esegue il deploy
- `PROD_SSH_KEY`: chiave privata SSH usata dal workflow
- `PROD_ENV_FILE`: contenuto completo multilinea di `.env.production`
- `PROD_DEPLOY_CONFIG`: contenuto completo multilinea di `.deploy.production`

`PROD_DEPLOY_CONFIG` e facoltativo, ma e il modo corretto per controllare la strategia `blue_green` senza committare file server-specifici.

## Best practice

- Non committare mai `.env*` o `.deploy.production`
- Mantieni nel repo solo `.env.production.example` e `.deploy.production.example`
- Usa environment secrets GitHub per i dati sensibili
- Se vuoi regole extra, aggiungi protection rules all'environment `production`

## Sync del file env sul server

Il workflow non legge `.env.production` dal repository. Ad ogni deploy:

1. legge `PROD_ENV_FILE` da GitHub Secrets
2. lo carica in modo temporaneo sul server
3. lo installa come `/opt/edilcloud/back-dn/.env.production`
4. usa quel file per build e restart dello slot applicativo

Quindi puoi aggiornare il file env di produzione cambiando il secret GitHub, senza versionarlo.

## Comandi utili con GitHub CLI

Caricare la chiave SSH:

```powershell
gh secret set --env production PROD_SSH_KEY < C:\path\to\id_ed25519
```

Caricare il file env di produzione:

```powershell
gh secret set --env production PROD_ENV_FILE < .env.production
```

Caricare la config deploy:

```powershell
gh secret set --env production PROD_DEPLOY_CONFIG < .deploy.production
```

Impostare host, porta e utente:

```powershell
'your-server.example.com' | gh secret set --env production PROD_HOST
'22' | gh secret set --env production PROD_PORT
'deploy' | gh secret set --env production PROD_USER
```

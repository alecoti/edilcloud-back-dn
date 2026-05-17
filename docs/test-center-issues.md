# Test Center Issues

Questo documento descrive il primo livello del percorso verso il Test Center agentico:
trasformare segnali tecnici in casi operativi leggibili da persone e, in seguito,
da un agente di remediation.

## Obiettivo

La dashboard non deve limitarsi a mostrare report separati. Ogni anomalia deve
diventare una issue normalizzata con:

- severita
- piattaforma e target
- categoria
- evidenza
- sorgente tecnica
- playbook
- comandi suggeriti
- stato di automazione

Il primo endpoint e:

```text
GET /api/v1/test-center/issues
```

L'endpoint e riservato ai superuser e viene consumato dalla route Next:

```text
/dashboard/admin/test-center/issues
```

## Modello issue

Ogni issue contiene:

| Campo | Scopo |
| --- | --- |
| `id` | identificatore stabile derivato da sorgente, piattaforma e categoria |
| `status` | stato operativo della issue, oggi sempre `open` |
| `severity` | `critical`, `warning` o `info` |
| `platform` | `backend`, `frontend-next`, `flutter` o altra piattaforma futura |
| `target` | `android`, `ios` o `null` |
| `category` | `quality`, `performance`, `runtime-budget`, `instrumentation` |
| `summary` | spiegazione breve leggibile in dashboard |
| `source` | report o segnale che ha generato il caso |
| `evidence` | prove testuali estratte da report, focus e metriche |
| `playbook` | sequenza di passi da seguire |
| `suggested_commands` | comandi sicuri da rilanciare manualmente |
| `automation` | stato e limiti per futura esecuzione automatica |

## Stati di automazione

| Stato | Significato |
| --- | --- |
| `candidate` | l'azione puo diventare automatica dopo ulteriori guardrail |
| `manual_review_required` | serve lettura umana prima di modificare codice o performance |
| `blocked` | manca una sorgente dati stabile o un prerequisito operativo |

Questa distinzione impedisce all'agente futuro di agire in modo impulsivo:
prima osserva, poi classifica, poi propone, poi verifica.

## Sorgenti attuali

Il builder legge l'overview del Test Center e genera issue da:

- runtime budget backend fuori soglia
- load test Locust non verde
- quality suite backend/frontend/flutter non verde
- piattaforme ancora in `pending_instrumentation`

## Prossimo passo agentico

Il prossimo blocco naturale e aggiungere un registro azioni, separato dalla
generazione issue:

1. selezione issue
2. proposta azione
3. dry-run o rerun test
4. esecuzione controllata
5. verifica post-azione
6. marcatura issue come risolta o ancora aperta

L'agente non deve modificare codice finche non ha:

- issue normalizzata
- sorgente verificabile
- playbook associato
- test di conferma
- rollback o confine di modifica chiaro

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
| `id` | identificatore stabile derivato da categoria, piattaforma e target logico |
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

## Ciclo di vita

Le issue correnti espongono ora anche `verification`, cioe l'ultima run del
ledger associata allo stesso identificatore stabile. Questo permette di leggere:

- quale tentativo ha verificato per ultimo la issue;
- se l'ultima verifica e stata `pass`, `fail`, `planned` o `running`;
- quale operazione e stata eseguita;
- quale action ha prodotto la run.

La risposta dell'endpoint include inoltre `recently_resolved`: issue che non
sono piu presenti tra i segnali correnti e la cui ultima run collegata e `pass`.
Questa lista non sostituisce ancora uno storico persistente completo, ma chiude
il primo ciclo operativo:

```text
issue aperta -> action -> run -> nuova lettura segnali -> issue ancora aperta o risolta di recente
```

Perche questo funzioni nel tempo gli ID non dipendono piu dal singolo artifact o
dal valore puntuale di p95: una quality issue frontend, una runtime rule o un
profilo Locust mantengono la stessa identita logica attraverso piu report.

## Prossimo passo agentico

Il prossimo blocco naturale e trasformare il ciclo di vita in stato persistente:

1. snapshot storico delle transizioni `open`, `verified`, `resolved`, `reopened`
2. SLA di permanenza e aging delle issue
3. trigger automatici solo per casi `candidate`
4. confronto tra verifica passata e nuova evidenza
5. escalation quando una issue resta aperta oltre soglia

L'agente non deve modificare codice finche non ha:

- issue normalizzata
- sorgente verificabile
- playbook associato
- test di conferma
- rollback o confine di modifica chiaro

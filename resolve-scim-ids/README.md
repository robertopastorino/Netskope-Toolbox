# resolve-scim-ids

Script Python che risolve gli UUID SCIM di Netskope negli utenti corrispondenti, partendo dagli ID presenti nei log di audit.

## Contesto

Quando un IdP (es. Microsoft Entra ID) esegue il provisioning SCIM verso Netskope, l'audit log del tenant registra le chiamate con il solo identificativo SCIM dell'oggetto:

```
Rest API V2 Call: 204, PATCH, /api/v2/scim/Users/<uuid>, trid=<id-transazione>
```

L'UUID non dice di quale utente si tratta. Lo script interroga l'endpoint SCIM di Netskope per ciascun ID e restituisce `userName`, email, `externalId`, stato `active` e gruppi (se presenti), così da poter correlare gli eventi di audit con gli utenti segnalati e con i provisioning log dell'IdP.

Caso d'uso tipico: troubleshooting di un provisioning SCIM che apparentemente non sincronizza utenti o membership.

## Caratteristiche

- Accetta un file con un UUID per riga **oppure** righe copiate direttamente dall'audit log: gli UUID vengono estratti via regex e deduplicati mantenendo l'ordine.
- Solo chiamate in lettura (`GET`): nessuna modifica al tenant.
- Gestione del rate limit (HTTP 429) con rispetto dell'header `Retry-After` e fino a 3 tentativi.
- Interruzione immediata su 401/403 (token non valido o senza permessi).
- Output tabellare a video (separatore tab) ed export CSV opzionale (separatore `;`, compatibile con Excel in locale italiano).
- Nessuna dipendenza esterna: solo libreria standard.

## Requisiti

- Python 3.9 o superiore
- Token REST API v2 di Netskope con permesso di **lettura** sull'endpoint `/api/v2/scim/Users`

Si consiglia di creare un token dedicato, separato da quello usato dall'integrazione SCIM dell'IdP, e di revocarlo al termine dell'attività.

## Installazione

```bash
git clone <url-repository>
cd resolve-scim-ids
```

Non serve installare pacchetti.

## Uso

```bash
python resolve_scim_ids.py --tenant <tenant>.goskope.com --file ids.txt
```

Con export CSV:

```bash
python resolve_scim_ids.py --tenant <tenant>.goskope.com --file ids.txt --out risultati.csv
```

### Parametri

| Parametro  | Obbligatorio | Descrizione |
|------------|--------------|-------------|
| `--tenant` | sì | Hostname del tenant (es. `tenant.goskope.com`). Il prefisso `https://` viene rimosso se presente. |
| `--file`   | sì | File di testo con gli UUID o con le righe dell'audit log. |
| `--token`  | no | Token REST API v2. |
| `--out`    | no | Percorso del CSV da generare. |

### Token

Il token viene letto, in ordine di priorità, da:

1. parametro `--token`
2. variabile d'ambiente `NETSKOPE_TOKEN`
3. prompt interattivo (input nascosto)

Il prompt interattivo è l'opzione consigliata: il token non finisce nella history della shell.

```bash
# Linux / macOS
export NETSKOPE_TOKEN="..."

# Windows PowerShell
$env:NETSKOPE_TOKEN = "..."
```

## Formato del file di input

Entrambi i formati sono validi, anche mescolati:

```
00000000-0000-0000-0000-000000000001
00000000-0000-0000-0000-000000000002
Rest API V2 Call: 204, PATCH, /api/v2/scim/Users/00000000-0000-0000-0000-000000000003, trid=...
```

## Output

Colonne restituite:

| Colonna       | Descrizione |
|---------------|-------------|
| `id`          | UUID SCIM in Netskope |
| `userName`    | Username SCIM |
| `displayName` | Nome visualizzato |
| `email`       | Email primaria (o la prima disponibile) |
| `externalId`  | Identificativo lato IdP, se mappato |
| `active`      | Stato dell'utente |
| `groups`      | Gruppi, se restituiti dall'endpoint |
| `status`      | `OK`, oppure codice HTTP / errore di rete |

Gli UUID non risolti compaiono comunque nell'output con lo stato corrispondente (es. `HTTP 404` per un utente eliminato).

## Correlazione con Entra ID

L'UUID SCIM restituito da Netskope è lo stesso ID che i provisioning log di Entra ID riportano come identificativo dell'oggetto nel sistema target. Incrociando ID e timestamp è possibile risalire all'evento lato Entra, dove le *Modified properties* mostrano il contenuto effettivo della PATCH (non visibile nell'audit log di Netskope).

Il campo `trid` presente nell'audit log è generato da Netskope e non è utilizzabile per la correlazione con l'IdP; può essere utile come riferimento in un caso di supporto Netskope.

## Limitazioni

- La colonna `groups` è valorizzata solo se Netskope include l'attributo `groups` nella risorsa User SCIM. In caso contrario le membership vanno ricavate dall'endpoint `/api/v2/scim/Groups`, non coperto da questo script.
- Le richieste sono sequenziali: per grandi volumi di ID l'esecuzione può richiedere tempo.

## Sicurezza

- Non committare token, file di input o output contenenti dati reali: UUID, username ed email sono dati del cliente.
- Si consiglia di aggiungere al `.gitignore`:

```
*.txt
*.csv
```

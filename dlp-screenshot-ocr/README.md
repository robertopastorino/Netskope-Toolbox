# dlp-screenshot-ocr

Estrazione OCR **completamente locale** (Tesseract) da screenshot applicativi, con:

- elaborazione ricorsiva di una cartella di immagini;
- output che mantiene la struttura delle cartelle **oppure** dizionario comune di termini, a scelta;
- cattura opzionale di frame da registrazioni video dello schermo, con deduplica dei frame quasi identici;
- esclusione dei dati personali dal dizionario (codici fiscali, email, nomi e cognomi da elenchi esterni, lista di esclusione personalizzata) e loro oscuramento nel testo estratto;
- report sulla qualità dell'OCR per immagine;
- cache dell'OCR per rifare dizionario e filtri con parametri diversi senza rileggere le immagini.

Nato per costruire dizionari di etichette e termini distintivi di un gestionale, da usare come segnale OCR in regole DLP (es. Netskope), ma utilizzabile per qualsiasi raccolta di screenshot.

Nessuna chiamata di rete: immagini, video e risultati restano sulla macchina.

---

## Indice

- [Requisiti](#requisiti)
- [Installazione su Windows](#installazione-su-windows)
  - [1. Python](#1-python)
  - [2. Dipendenze Python](#2-dipendenze-python)
  - [3. Tesseract OCR](#3-tesseract-ocr)
  - [4. Lingua italiana per Tesseract](#4-lingua-italiana-per-tesseract)
  - [5. ffmpeg (solo per i video)](#5-ffmpeg-solo-per-i-video)
  - [6. Verifica finale](#6-verifica-finale)
- [Utilizzo](#utilizzo)
- [Parametri](#parametri)
- [Output](#output)
- [Come vengono estratti i termini](#come-vengono-estratti-i-termini)
- [Filtri dati personali](#filtri-dati-personali)
- [Seconda passata dalla cache](#seconda-passata-dalla-cache)
- [Deduplica dei frame video](#deduplica-dei-frame-video)
- [Ottimizzazione dei risultati](#ottimizzazione-dei-risultati)
- [Risoluzione problemi](#risoluzione-problemi)
- [Dati sensibili e repository](#dati-sensibili-e-repository)

---

## Requisiti

| Componente | Versione | Necessario per |
|---|---|---|
| Python | 3.9+ | sempre |
| `pytesseract`, `pillow` | recenti | sempre |
| Tesseract OCR | 5.x consigliata | sempre |
| Language pack Tesseract | `ita`, `eng` (o quelli richiesti) | sempre |
| ffmpeg | qualsiasi build recente | solo `--video` |

Lo script funziona anche su Linux e macOS; la guida di installazione che segue è per Windows.

---

## Installazione su Windows

I comandi sono pensati per **PowerShell**. Dopo ogni modifica al `PATH` apri un **nuovo** terminale: quelli già aperti non vedono la modifica.

### 1. Python

Da [python.org](https://www.python.org/downloads/windows/) (spunta *Add python.exe to PATH* durante l'installazione) oppure:

```powershell
winget install -e --id Python.Python.3.12
```

Verifica:

```powershell
python --version
```

### 2. Dipendenze Python

Consigliato un ambiente virtuale nella cartella del progetto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install pytesseract pillow
```

Se PowerShell blocca l'attivazione dell'ambiente per la execution policy, abilitala solo per la sessione corrente:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

> `pytesseract` è solo un wrapper: l'eseguibile Tesseract va installato a parte (passo successivo).

### 3. Tesseract OCR

La build Windows di riferimento è quella mantenuta da UB Mannheim, linkata dalla documentazione ufficiale di Tesseract.

**Opzione A, installer grafico (consigliata):** scarica l'installer da <https://github.com/UB-Mannheim/tesseract/wiki> ed eseguilo. Nella schermata di selezione dei componenti espandi le opzioni sui dati linguistici aggiuntivi e seleziona **Italian** (più eventuali altre lingue). Così eviti il passo 4.

**Opzione B, winget:**

```powershell
winget install -e --id UB-Mannheim.TesseractOCR
```

L'installazione via winget è non interattiva e installa i componenti predefiniti: con ogni probabilità avrai solo l'inglese. Controlla le lingue e, se `ita` manca, segui il passo 4.

**PATH.** Il percorso di installazione tipico è `C:\Program Files\Tesseract-OCR`. Verifica se l'eseguibile è raggiungibile:

```powershell
where.exe tesseract
```

Se il comando non trova nulla hai due alternative:

- aggiungi `C:\Program Files\Tesseract-OCR` al `PATH` (Impostazioni → Sistema → Informazioni → Impostazioni di sistema avanzate → Variabili d'ambiente);
- oppure passa sempre il percorso allo script con `--tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"`.

> Se sul sistema ci sono più installazioni di Tesseract (installer, choco, scoop), `where.exe tesseract` mostra quale viene trovata per prima. Usare `--tesseract-cmd` elimina l'ambiguità.

### 4. Lingua italiana per Tesseract

Controlla quali lingue vede **l'eseguibile che userai**:

```powershell
& "C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
```

La prima riga dell'output indica la cartella `tessdata` effettivamente in uso; le righe successive sono le lingue disponibili. `osd` non è una lingua (serve al rilevamento di orientamento e script).

Se `ita` non compare:

1. Scarica `ita.traineddata` da uno dei repository ufficiali:
   - [`tessdata_best`](https://github.com/tesseract-ocr/tessdata_best): più accurato, più lento (**consigliato** per poche decine o centinaia di screenshot);
   - [`tessdata_fast`](https://github.com/tesseract-ocr/tessdata_fast): più veloce, meno accurato;
   - [`tessdata`](https://github.com/tesseract-ocr/tessdata): modelli standard, includono anche il motore legacy.
2. Copia il file nella cartella `tessdata` indicata da `--list-langs` (tipicamente `C:\Program Files\Tesseract-OCR\tessdata`; servono privilegi di amministratore).
3. Ripeti `--list-langs` e verifica che `ita` compaia.

> Se la variabile d'ambiente `TESSDATA_PREFIX` è impostata, Tesseract usa quella cartella. Il percorso stampato da `--list-langs` tiene già conto di questo: è quello a cui fare riferimento.

**Controllo funzionale.** La presenza del file non basta a dire che il modello funziona come previsto. Prova su uno screenshot con lettere accentate:

```powershell
tesseract .\schermata.png - -l eng --psm 11
tesseract .\schermata.png - -l ita+eng --psm 11
```

Con `ita` attivo, parole come "Città", "Qualità", "più" devono uscire corrette; con il solo `eng` le lettere accentate vengono tipicamente perse o sostituite.

### 5. ffmpeg (solo per i video)

ffmpeg non distribuisce un installer Windows proprio: la pagina ufficiale rimanda a build di terze parti, tra cui quelle di gyan.dev.

**Opzione A, winget:**

```powershell
winget install -e --id Gyan.FFmpeg
```

Apri un nuovo terminale e verifica con `ffmpeg -version`. Se il comando non viene trovato, individua l'eseguibile (tipicamente sotto `%LOCALAPPDATA%\Microsoft\WinGet\`) e aggiungi la sua cartella `bin` al `PATH`, oppure passa il percorso allo script con `--ffmpeg`.

**Opzione B, archivio manuale:**

1. Scarica la *release essentials* da <https://www.gyan.dev/ffmpeg/builds/>.
2. Estrai l'archivio, ad esempio in `C:\ffmpeg`.
3. Aggiungi `C:\ffmpeg\bin` al `PATH` (la cartella `bin`, non `ffmpeg.exe` e non la cartella superiore) tramite le Variabili d'ambiente di Windows.

> Evita `setx PATH "...;%PATH%"`: `setx` tronca i valori oltre 1024 caratteri e mescola il PATH utente con quello di sistema. Meglio l'interfaccia grafica delle Variabili d'ambiente.

### 6. Verifica finale

```powershell
python --version
tesseract --version
tesseract --list-langs
ffmpeg -version          # solo se userai --video
python ocr_extract.py -h
```

All'avvio lo script verifica comunque che Tesseract risponda e che tutte le lingue richieste con `--lang` siano installate; in caso contrario si ferma ed elenca le lingue disponibili.

---

## Utilizzo

### OCR su una cartella di screenshot

Struttura di input attesa (una sottocartella per ambito; la profondità può essere maggiore):

```
screenshot\
├── Anagrafica_Clienti\
│   ├── lista.png
│   └── dettaglio.png
├── Ordini\
│   └── ...
└── Magazzino\
    └── ...
```

Testo per immagine con la stessa struttura **e** dizionario comune:

```powershell
python ocr_extract.py -i .\screenshot -o .\ocr_out --mode entrambi
```

Solo dizionario, con percorso esplicito di Tesseract:

```powershell
python ocr_extract.py -i .\screenshot -o .\ocr_out --mode dizionario `
  --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Solo testo per immagine, con anche parole, confidenza e coordinate in `.tsv`:

```powershell
python ocr_extract.py -i .\screenshot -o .\ocr_out --mode struttura --tsv
```

### Cattura frame da video

Registra lo schermo mentre navighi il gestionale (meglio in ambiente di test), un video per ambito, chiamando i file come gli ambiti: `Anagrafica_Clienti.mp4`, `Ordini.mp4`, …

Solo estrazione dei frame (uno ogni 2 secondi, con deduplica):

```powershell
python ocr_extract.py --video .\registrazioni --frames-dir .\frames --frames-only
```

Estrazione frame e OCR in un solo passaggio (senza `-i` l'OCR viene eseguito sulla cartella dei frame):

```powershell
python ocr_extract.py --video .\registrazioni --frames-dir .\frames -o .\ocr_out
```

`--video` accetta un file o una cartella ed è ripetibile. Ogni video produce una sottocartella in `--frames-dir` con il nome del file, che diventa l'ambito nel dizionario.

---

## Parametri

### OCR

| Parametro | Default | Descrizione |
|---|---|---|
| `-i`, `--input` | – | Cartella immagini, letta ricorsivamente. Se omessa insieme a `--video`, viene usata `--frames-dir` |
| `-o`, `--output` | `ocr_output` | Cartella di output |
| `--mode` | `entrambi` | `struttura`, `dizionario` o `entrambi` |
| `--lang` | `ita+eng` | Lingue Tesseract |
| `--psm` | `11` | Page segmentation mode. 11 = testo sparso, adatto alle GUI; prova 6 o 3 per testo a blocchi |
| `--upscale` | `2.0` | Ingrandimento prima dell'OCR (lato lungo limitato a 8000 px) |
| `--invert` | `auto` | Inversione colori per temi scuri: `auto`, `always`, `never` |
| `--tsv` | off | In modalità struttura salva anche parola, confidenza e bounding box |
| `--workers` | metà dei core | Processi paralleli |
| `--tesseract-cmd` | – | Percorso di `tesseract.exe` |
| `--from-cache` | – | Seconda passata da una cache OCR (file `ocr_cache.jsonl.gz` o cartella che lo contiene), senza rifare l'OCR. Incompatibile con `-i` e `--video` |
| `--no-cache` | off | Non salvare la cache OCR |

Formati immagine supportati: `png`, `jpg`, `jpeg`, `bmp`, `tif`, `tiff`, `webp`.

### Dizionario

| Parametro | Default | Descrizione |
|---|---|---|
| `--min-conf` | `60` | Confidenza minima Tesseract (0–100) per ogni parola |
| `--ngram-max` | `3` | Lunghezza massima delle frasi estratte |
| `--min-len` | `3` | Lunghezza minima dei termini di una parola |
| `--max-digit-ratio` | `0.3` | Quota massima di cifre in un token: scarta valori e codici, tiene le etichette |
| `--min-images` | `2` | Un termine entra in `dizionario.txt` solo se compare in almeno N immagini |
| `--no-collapse` | off | Tiene anche i termini che compaiono solo come parte di un termine più lungo |
| `--collapse-min` | `1` | Un termine contenuto in uno più lungo resta in `dizionario.txt` solo se compare da solo, come intero segmento, almeno N volte |
| `--stopwords` | – | File con stopword aggiuntive, una per riga |

### Dati personali

| Parametro | Default | Descrizione |
|---|---|---|
| `--names` | – | Elenco di nomi e/o cognomi, uno per riga (ripetibile) |
| `--names-vocab` | – | Vocabolario di parole comuni (ripetibile): i nomi presenti anche qui sono considerati ambigui |
| `--keep` | – | Etichette da tenere sempre: mai trattate come nomi e mai assorbite in termini più lunghi (ripetibile) |
| `--ignore` | – | Termini da escludere sempre; supporta frasi e regex `re:` (ripetibile) |
| `--review-names` | off | Scrive `scartati_nomi_da_verificare.csv` per la revisione dei falsi positivi |
| `--no-redact` | off | Non oscura i dati personali nel testo per immagine |

Codici fiscali ed email sono sempre filtrati, senza parametri. Dettagli in [Filtri dati personali](#filtri-dati-personali).

### Video

| Parametro | Default | Descrizione |
|---|---|---|
| `--video` | – | File video o cartella (ripetibile). Formati: `mp4`, `mkv`, `avi`, `mov`, `wmv`, `webm`, `m4v` |
| `--frames-dir` | `frames` | Cartella dei frame, una sottocartella per video |
| `--fps` | `0.5` | Frame estratti al secondo (0.5 = uno ogni 2 s) |
| `--dedup-threshold` | `0.1` | Percentuale minima di pixel cambiati perché un frame venga tenuto; 0 disattiva la deduplica |
| `--dedup-tol` | `32` | Differenza minima di grigio (0–255) perché un pixel conti come cambiato |
| `--dedup-global` | off | Confronta con tutti i frame già tenuti, non solo con l'ultimo |
| `--frames-only` | off | Estrai solo i frame, senza OCR |
| `--ffmpeg` | `ffmpeg` | Percorso di `ffmpeg.exe` |

---

## Output

Con `--mode entrambi`:

```
ocr_out\
├── ocr_cache.jsonl.gz           # cache OCR, salvo --no-cache (testo NON oscurato)
├── ocr_report.csv
├── testo\                       # stessa struttura dell'input
│   ├── Anagrafica_Clienti\
│   │   ├── lista.png.txt
│   │   └── lista.png.tsv        # solo con --tsv
│   └── ...
└── dizionario\
    ├── dizionario_termini.csv
    ├── dizionario.txt
    ├── scartati_riepilogo.csv
    ├── scartati_nomi_da_verificare.csv   # solo con --review-names
    └── per_ambito\
        ├── Anagrafica_Clienti.txt
        ├── Anagrafica_Clienti_esclusivi.txt
        └── ...
```

Con `--mode struttura` o `--mode dizionario` i rispettivi file finiscono direttamente nella cartella di output, senza la sottocartella `testo\` o `dizionario\`.

| File | Contenuto |
|---|---|
| `ocr_cache.jsonl.gz` | Risultato grezzo dell'OCR (parole, confidenza, posizione) per la [seconda passata](#seconda-passata-dalla-cache). **Testo non oscurato** |
| `ocr_report.csv` | Per ogni immagine: ambito, parole riconosciute, confidenza media, se è stata invertita, eventuali errori. Serve a capire su quali schermate l'OCR rende male |
| `*.png.txt` | Testo riconosciuto, riga per riga, con i dati personali oscurati (`[CF]`, `[EMAIL]`, `[NOME]`, `[IGNORATO]`) salvo `--no-redact`. Il nome conserva l'estensione originale per evitare collisioni (`a.png` e `a.jpg`) |
| `dizionario_termini.csv` | Tutti i termini, compresi quelli inclusi in termini più lunghi, con: numero di parole, immagini e ambiti in cui compare, elenco ambiti, ambito di esclusività, occorrenze, occorrenze isolate, termine in cui è incluso, confidenza media, file di esempio |
| `dizionario.txt` | Termini presenti in almeno `--min-images` immagini e non inclusi in termini più lunghi, uno per riga |
| `per_ambito\<ambito>.txt` | Termini trovati in quell'ambito |
| `per_ambito\<ambito>_esclusivi.txt` | Termini che compaiono **solo** in quell'ambito |
| `scartati_riepilogo.csv` | Numero di termini scartati per motivo (`codice_fiscale`, `email`, `lista_esclusione`, `nome`), senza i termini stessi |
| `scartati_nomi_da_verificare.csv` | Solo con `--review-names`: termini scartati come nomi presenti in almeno `--min-images` immagini. **Contiene nomi reali** |

I CSV usano `;` come separatore e codifica UTF-8 con BOM, così si aprono direttamente in Excel con impostazioni italiane.

L'**ambito** è la cartella di primo livello sotto `--input`; i file direttamente nella radice finiscono nell'ambito `(root)`.

---

## Come vengono estratti i termini

1. Le parole sotto `--min-conf` vengono escluse.
2. Ogni riga viene spezzata in segmenti sui separatori isolati (`|`, `-`, …) e dopo ogni parola che termina con `:`, così un'etichetta come `Codice cliente:` non si fonde con il valore o il campo accanto.
3. Da ogni segmento si estraggono termini singoli e frasi fino a `--ngram-max` parole.
4. I termini che contengono dati personali vengono scartati e conteggiati nel riepilogo (vedi [Filtri dati personali](#filtri-dati-personali)).
5. Tra i restanti vengono scartati:
   - i token senza lettere o con troppe cifre (`--max-digit-ratio`);
   - i termini singoli più corti di `--min-len` o presenti nelle stopword;
   - le frasi che iniziano o finiscono con una stopword.
6. I termini vengono aggregati senza distinzione tra maiuscole e minuscole; nei file di output compare la forma più frequente.
7. I termini che compaiono solo come parte di un termine più lungo vengono esclusi da `dizionario.txt` (vedi sotto).

### Termini inclusi in termini più lunghi

Estraendo tutte le frasi fino a `--ngram-max` parole, un'etichetta come `RISPOSTA PEC GENERICA` genera anche `RISPOSTA`, `RISPOSTA PEC`, `PEC`, `PEC GENERICA` e `GENERICA`, che non esistono come etichette autonome.

Per distinguerli, lo script conta per ogni termine le **occorrenze isolate**: quelle in cui il termine occupa da solo un intero segmento (una riga dell'OCR, spezzata sui separatori e dopo i `:`). Un termine contenuto in un termine più lungo del dizionario viene escluso da `dizionario.txt` se non compare mai isolato (soglia `--collapse-min`). Esempio:

| Termine | Occorrenze | Isolate | Esito |
|---|---|---|---|
| `RISPOSTA PEC GENERICA` | 3 | 3 | tenuto |
| `RISPOSTA PEC` | 3 | 0 | incluso in `RISPOSTA PEC GENERICA` |
| `RISPOSTA` | 6 | 3 | tenuto: compare anche da solo in altre schermate |

I termini esclusi restano in `dizionario_termini.csv` con la colonna `incluso_in`, per la revisione.

Casi da controllare:

- **Etichetta seguita da un valore testuale senza `:`** (es. `STATO APERTO`, `STATO CHIUSO`): `STATO` non compare mai isolato e viene assorbito, mentre restano le combinazioni con il valore. Aggiungi l'etichetta al file `--keep`, che la esenta da questo meccanismo.
- **Etichette più lunghe di `--ngram-max` parole:** nessun termine copre l'intera etichetta, quindi restano più frasi sovrapposte. Alza `--ngram-max` alla lunghezza dell'etichetta più lunga.
- **OCR che spezza un'etichetta su due righe:** i pezzi risultano isolati e vengono tenuti. Si vede dalla colonna `occorrenze_isolate`.

Il meccanismo si disattiva con `--no-collapse` e si può tarare dalla cache, senza rifare l'OCR.

### Apostrofi

Gli apostrofi tipografici (`’`, `‘`, `` ` ``, `´`) vengono convertiti in `'`, così `ATTIVITA’` e `ATTIVITA'` diventano lo stesso termine. L'apostrofo finale dopo una vocale viene mantenuto, perché nei gestionali sostituisce l'accento sulle maiuscole (`ATTIVITA'` = `ATTIVITÀ`), tranne quando la parola è tra virgolette.

Non è stato verificato come il motore OCR del DLP renda l'apostrofo, né come il dizionario del DLP lo tratti in fase di confronto: va testato prima di usare in una regola termini che lo contengono.

Interpretazione utile per il DLP:

- i termini presenti in **molti ambiti** sono tipicamente l'interfaccia comune del gestionale (menu, intestazioni, barra del titolo): buoni candidati per riconoscere "questo è il gestionale";
- i termini **esclusivi** di un ambito identificano il modulo specifico.

> **Rivedi sempre il dizionario prima di usarlo.** I filtri riducono i dati personali, non li azzerano: vedi i limiti in [Filtri dati personali](#filtri-dati-personali).

---

## Filtri dati personali

Obiettivo: il dizionario deve contenere le **etichette** del gestionale, non i **dati** mostrati nelle schermate.

### Codici fiscali ed email (sempre attivi)

- **Codice fiscale.** Regex sulla struttura (6 lettere, 2 cifre, lettera del mese, 2 cifre, lettera, 3 cifre, carattere di controllo) tollerante a:
  - omocodia: cifre sostituite dalle lettere `LMNPQRSTUV`;
  - scambi tipici dell'OCR: `O`/`0`, `I`/`1`, `S`/`5`, `B`/`8`.

  Per evitare falsi positivi è richiesto che almeno 3 delle 7 posizioni numeriche siano cifre reali: senza questo vincolo la regex tollerante riconosceva come codici fiscali circa 50 parole italiane lunghe (es. "affezionatissimo"). Il carattere di controllo non viene verificato, perché un errore OCR su un solo carattere farebbe passare il codice.
- **Email.** Qualsiasi token del tipo `utente@dominio.tld`.

Entrambi vengono esclusi dal dizionario e sostituiti con `[CF]` ed `[EMAIL]` nel testo per immagine. Non compaiono in nessun file di output.

### Nomi e cognomi (`--names`)

Lo script non include elenchi di nomi: vanno scaricati una volta e passati con `--names`. Una fonte già pronta è il repository [napolux/paroleitaliane](https://github.com/napolux/paroleitaliane) (licenza MIT), che contiene tra l'altro:

- `9000_nomi_propri.txt`: circa 9.000 nomi propri;
- `lista_38000_cognomi.txt`: circa 38.000 cognomi italiani;
- `lista_cognomi.txt`: circa 175.000 cognomi italiani e stranieri;
- `60000_parole_italiane.txt`: circa 60.000 parole italiane, utile come vocabolario.

Download in PowerShell:

```powershell
New-Item -ItemType Directory -Force liste | Out-Null
$base = "https://raw.githubusercontent.com/napolux/paroleitaliane/master/paroleitaliane"
foreach ($f in "lista_38000_cognomi.txt", "9000_nomi_propri.txt", "60000_parole_italiane.txt") {
    Invoke-WebRequest "$base/$f" -OutFile "liste\$f"
}
```

Il formato accettato è una voce per riga. Righe vuote, righe che iniziano con `#` o `--` vengono ignorate; per righe tipo `nome,m` viene usato il primo campo. Le voci di più parole (es. `de luca`) vengono trattate come frasi.

#### Il problema dei falsi positivi

Molte etichette di gestionale coincidono con nomi o cognomi. Su un elenco di 186 etichette tipiche, 36 compaiono in `lista_38000_cognomi.txt` + `9000_nomi_propri.txt`, tra cui `data`, `conto`, `saldo`, `dare`, `iva`, `stampa`, `cassa`, `lotto`, `anno`, `giorno`. Usare l'elenco così com'è svuoterebbe il dizionario proprio dei termini più utili. Per questo il filtro lavora su tre livelli:

1. **Vocabolario (`--names-vocab`).** Le voci dell'elenco nomi presenti anche nel vocabolario sono considerate **ambigue** (es. `rossi`, `costa`, `sala`). Un nome ambiguo isolato viene tenuto; viene scartato solo dentro una sequenza di almeno due nomi (es. `Mario Rossi`, anche con particelle come `de`, `di` in mezzo). I nomi **non** presenti nel vocabolario (es. `esposito`, `giulia`) bastano da soli a scartare un termine.
2. **Etichette da tenere (`--keep`).** Le voci di questo file vengono tolte dall'elenco nomi. Il file `keep_etichette_gestionali.txt` incluso nel repo contiene le 36 collisioni trovate sopra ed è un punto di partenza da completare.
3. **Revisione (`--review-names`).** Scrive `scartati_nomi_da_verificare.csv` con i termini scartati come nomi presenti in almeno `--min-images` immagini. Un nome di persona compare di solito in poche schermate, un'etichetta in molte: le righe in cima al file sono i candidati falsi positivi da aggiungere al file `--keep`.

> Il file di revisione contiene anche nomi reali ricorrenti (es. l'utente collegato nella barra del titolo): usalo solo in locale e cancellalo dopo la taratura.

Come vocabolario **non** usare `280000_parole_italiane.txt` dello stesso repository: contiene anche nomi propri comuni (`mario`, `giuseppe`, `francesca`, …), che diventerebbero ambigui e smetterebbero di essere filtrati da soli.

Senza `--names-vocab` ogni voce dell'elenco nomi basta a scartare un termine e lo script lo segnala con un avviso.

### Lista di esclusione (`--ignore`)

Per tutto ciò che gli elenchi non coprono: ragione sociale del cliente, nomi utente, nomi di server o reparti. Una voce per riga:

```text
# parola singola: esclude ogni termine che la contiene
acme
mrossi
# frase: esclude i termini che contengono la frase
acme spa
# regex (case-insensitive) su ogni parola e sul termine intero
re:[a-z]\.[a-z]+
```

La lista di esclusione prevale su `--keep`. Nel testo per immagine le voci vengono sostituite con `[IGNORATO]`.

### Esempio completo

```powershell
python ocr_extract.py -i .\screenshot -o .\ocr_out `
  --names .\liste\lista_38000_cognomi.txt --names .\liste\9000_nomi_propri.txt `
  --names-vocab .\liste\60000_parole_italiane.txt `
  --keep .\keep_etichette_gestionali.txt --ignore .\ignora.txt
```

Per la prima taratura aggiungi `--review-names`, aggiorna `keep_etichette_gestionali.txt` e rilancia senza.

### Limiti

- **Ragioni sociali e nomi composti da parole comuni** (es. "Fontana Costruzioni Srl") non vengono riconosciuti: vanno nella lista di esclusione, oppure vengono esclusi da `dizionario.txt` se compaiono in meno di `--min-images` immagini. Restano comunque in `dizionario_termini.csv`.
- **Cognomi ambigui isolati** (es. "Rossi" da solo in un campo) vengono tenuti per non perdere etichette.
- **Nomi assenti dagli elenchi** (molti nomi stranieri, nomi rari) e **nomi letti male dall'OCR** non vengono riconosciuti.
- **Altri dati personali** (indirizzi, telefoni, IBAN): numeri, telefoni e IBAN vengono in genere scartati dal filtro sulle cifre (`--max-digit-ratio`), gli indirizzi no.

---

## Seconda passata dalla cache

L'OCR è la parte lenta. Ogni esecuzione salva in `ocr_cache.jsonl.gz` il risultato grezzo di Tesseract (parole, confidenza, posizione, riga), così dizionario, filtri e testo per immagine si possono rigenerare con parametri diversi senza rileggere le immagini:

```powershell
# prima passata: OCR + cache
python ocr_extract.py -i .\screenshot -o .\ocr_out

# passate successive: solo rielaborazione, in pochi secondi
python ocr_extract.py --from-cache .\ocr_out -o .\ocr_out_v2 `
  --names .\liste\lista_38000_cognomi.txt --names .\liste\9000_nomi_propri.txt `
  --names-vocab .\liste\60000_parole_italiane.txt `
  --keep .\keep_etichette_gestionali.txt --ignore .\ignora.txt --min-images 3 --review-names
```

Con le stesse opzioni, la seconda passata produce file identici alla prima.

**Cosa si può cambiare** in una seconda passata: tutti i parametri del dizionario (`--min-conf`, `--ngram-max`, `--min-len`, `--max-digit-ratio`, `--min-images`, `--stopwords`), tutti i filtri dati personali, `--mode`, `--tsv`, `--no-redact`.

**Cosa non si può cambiare:** i parametri dell'OCR (`--lang`, `--psm`, `--upscale`, `--invert`). Vengono presi dai metadati della cache e mostrati all'avvio; quelli passati sulla riga di comando vengono ignorati. Per cambiarli serve un nuovo OCR.

Note pratiche:

- la seconda passata non richiede Tesseract, Pillow né `pytesseract`: basta Python, quindi si può fare anche su un'altra macchina;
- la cache contiene solo i percorsi relativi delle immagini e il percorso della cartella di input nei metadati, non le immagini;
- conviene scrivere su una cartella diversa (`-o .\ocr_out_v2`) per confrontare i risultati; se si usa la stessa cartella, i file vengono sovrascritti tranne la cache;
- aggiungendo nuovi screenshot o frame serve un nuovo OCR completo: la cache non viene aggiornata in modo incrementale.

> La cache contiene il testo **non oscurato**, compresi nomi, codici fiscali ed email: deve esserlo, altrimenti una seconda passata con filtri diversi non potrebbe recuperare un'etichetta scartata per errore. Trattala come gli screenshot: solo in locale, mai nel repository né condivisa insieme al dizionario.

---

## Deduplica dei frame video

Ogni frame viene ridotto a una miniatura in scala di grigi larga 640 px e confrontato con il frame tenuto in precedenza (o con tutti, con `--dedup-global`). Se la percentuale di pixel cambiati oltre `--dedup-tol` è sotto `--dedup-threshold`, il frame viene scartato.

Si usa la differenza di pixel invece di un hash percettivo perché sulle GUI due schermate diverse con lo stesso layout producono hash quasi identici: il testo cambia, la struttura no.

Linee guida per la taratura:

- con soglie basse restano più frame, anche quelli che differiscono solo per i dati visualizzati;
- con soglie alte vengono scartati anche cambi minori, come lo scorrimento di una lista;
- il movimento del puntatore del mouse incide in genere per una frazione molto piccola dei pixel e viene scartato con i valori predefiniti;
- se nel video torni più volte sulla stessa schermata, usa `--dedup-global`.

---

## Ottimizzazione dei risultati

- **Parti da `ocr_report.csv`.** Immagini con poche parole o confidenza media bassa indicano schermate su cui anche l'OCR del DLP renderà male.
- **Testo piccolo o screenshot a bassa risoluzione:** aumenta `--upscale` (es. 3).
- **Temi scuri non rilevati:** forza `--invert always` su quella cartella.
- **Layout a blocchi (report, stampe):** prova `--psm 6` o `--psm 3`.
- **Troppi termini spazzatura:** alza `--min-conf` (es. 75) e `--min-images`.
- **Pezzi di etichette nel dizionario** (es. `RISPOSTA PEC` accanto a `RISPOSTA PEC GENERICA`): controlla che `--ngram-max` copra le etichette più lunghe.
- **Etichetta sparita perché assorbita in combinazioni con valori** (es. `STATO` in `STATO APERTO`): aggiungila al file `--keep`.
- **Etichette del gestionale sparite dal dizionario:** rilancia con `--review-names` e aggiungi i falsi positivi a `keep_etichette_gestionali.txt`.
- **Etichette ripetute ma poco utili** (es. "Salva", "Annulla", "Chiudi"): mettile in un file e passalo con `--stopwords`.

---

## Risoluzione problemi

| Sintomo | Causa probabile | Soluzione |
|---|---|---|
| `Tesseract non utilizzabile` | Eseguibile non nel `PATH` | `--tesseract-cmd` con il percorso completo, oppure aggiungi la cartella al `PATH` |
| `Lingue Tesseract mancanti: ita` | Language pack non installato | Passo 4 dell'installazione |
| `ffmpeg non trovato` | Eseguibile non nel `PATH` | `--ffmpeg` con il percorso completo, oppure aggiungi la cartella `bin` al `PATH` |
| Lettere accentate sbagliate | Si sta usando solo `eng` | Verifica `--lang ita+eng` e `tesseract --list-langs` |
| `Nessuna immagine trovata` | Estensioni non supportate o cartella errata | Verifica il percorso di `-i` e i formati supportati |
| Molti frame scartati nonostante cambi visibili | Soglia di deduplica troppo alta | Abbassa `--dedup-threshold` |
| Etichette come "Data" o "Conto" assenti dal dizionario | Filtro nomi senza vocabolario o senza file `--keep` | Aggiungi `--names-vocab` e `--keep`, verifica con `--review-names` |
| Nomi di persona ancora presenti nel dizionario | Nomi ambigui isolati, assenti dagli elenchi o letti male dall'OCR | Aggiungili alla lista `--ignore` |
| `Cache non trovata` | Percorso errato o prima passata eseguita con `--no-cache` | Indica il file `ocr_cache.jsonl.gz` o la cartella di output della prima passata |
| `--from-cache non si combina con --input o --video` | Opzioni incompatibili | La seconda passata lavora solo sulla cache: togli `-i` e `--video` |
| Elaborazione lenta | Immagini molto grandi o upscale elevato | Riduci `--upscale`, aumenta `--workers` |

---

## Dati sensibili e repository

Gli screenshot e i video contengono tipicamente dati reali, e lo stesso vale per i file di output (testo estratto, dizionari, frame). **Non vanno mai committati.**

Esempio di `.gitignore`:

```gitignore
# ambiente
.venv/
__pycache__/

# dati e risultati
screenshot/
registrazioni/
frames/
ocr_out/
ocr_output/
*.png
*.jpg
*.jpeg
*.mp4
*.mkv
*.csv
*.tsv
*.jsonl.gz
ignora.txt
```

La cache OCR (`ocr_cache.jsonl.gz`) contiene il testo non oscurato ed è coperta dalla riga `*.jsonl.gz`. Il file `scartati_nomi_da_verificare.csv` è coperto da `*.csv`; la lista di esclusione (`ignora.txt`) contiene nomi del cliente e va tenuta fuori dal repo, aggiungendola al `.gitignore`. Il file `keep_etichette_gestionali.txt` invece contiene solo etichette generiche e fa parte del repo.

Quando possibile, lavora su ambienti di test o con dati anonimizzati.

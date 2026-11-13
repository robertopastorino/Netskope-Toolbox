# ocr_extract

Estrazione OCR **completamente locale** (Tesseract) da screenshot applicativi, con:

- elaborazione ricorsiva di una cartella di immagini;
- output che mantiene la struttura delle cartelle **oppure** dizionario comune di termini, a scelta;
- cattura opzionale di frame da registrazioni video dello schermo, con deduplica dei frame quasi identici;
- report sulla qualità dell'OCR per immagine.

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

Formati immagine supportati: `png`, `jpg`, `jpeg`, `bmp`, `tif`, `tiff`, `webp`.

### Dizionario

| Parametro | Default | Descrizione |
|---|---|---|
| `--min-conf` | `60` | Confidenza minima Tesseract (0–100) per ogni parola |
| `--ngram-max` | `3` | Lunghezza massima delle frasi estratte |
| `--min-len` | `3` | Lunghezza minima dei termini di una parola |
| `--max-digit-ratio` | `0.3` | Quota massima di cifre in un token: scarta valori e codici, tiene le etichette |
| `--min-images` | `2` | Un termine entra in `dizionario.txt` solo se compare in almeno N immagini |
| `--stopwords` | – | File con stopword aggiuntive, una per riga |

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
├── ocr_report.csv
├── testo\                       # stessa struttura dell'input
│   ├── Anagrafica_Clienti\
│   │   ├── lista.png.txt
│   │   └── lista.png.tsv        # solo con --tsv
│   └── ...
└── dizionario\
    ├── dizionario_termini.csv
    ├── dizionario.txt
    └── per_ambito\
        ├── Anagrafica_Clienti.txt
        ├── Anagrafica_Clienti_esclusivi.txt
        └── ...
```

Con `--mode struttura` o `--mode dizionario` i rispettivi file finiscono direttamente nella cartella di output, senza la sottocartella `testo\` o `dizionario\`.

| File | Contenuto |
|---|---|
| `ocr_report.csv` | Per ogni immagine: ambito, parole riconosciute, confidenza media, se è stata invertita, eventuali errori. Serve a capire su quali schermate l'OCR rende male |
| `*.png.txt` | Testo riconosciuto, riga per riga. Il nome conserva l'estensione originale per evitare collisioni (`a.png` e `a.jpg`) |
| `dizionario_termini.csv` | Un termine per riga con: numero di parole, immagini e ambiti in cui compare, elenco ambiti, ambito di esclusività, occorrenze, confidenza media, file di esempio |
| `dizionario.txt` | Termini presenti in almeno `--min-images` immagini, uno per riga |
| `per_ambito\<ambito>.txt` | Termini trovati in quell'ambito |
| `per_ambito\<ambito>_esclusivi.txt` | Termini che compaiono **solo** in quell'ambito |

I CSV usano `;` come separatore e codifica UTF-8 con BOM, così si aprono direttamente in Excel con impostazioni italiane.

L'**ambito** è la cartella di primo livello sotto `--input`; i file direttamente nella radice finiscono nell'ambito `(root)`.

---

## Come vengono estratti i termini

1. Le parole sotto `--min-conf` vengono escluse.
2. Ogni riga viene spezzata in segmenti sui separatori isolati (`|`, `-`, …) e dopo ogni parola che termina con `:`, così un'etichetta come `Codice cliente:` non si fonde con il valore o il campo accanto.
3. Da ogni segmento si estraggono termini singoli e frasi fino a `--ngram-max` parole.
4. Vengono scartati:
   - i token senza lettere o con troppe cifre (`--max-digit-ratio`);
   - i termini singoli più corti di `--min-len` o presenti nelle stopword;
   - le frasi che iniziano o finiscono con una stopword.
5. I termini vengono aggregati senza distinzione tra maiuscole e minuscole; nei file di output compare la forma più frequente.

Interpretazione utile per il DLP:

- i termini presenti in **molti ambiti** sono tipicamente l'interfaccia comune del gestionale (menu, intestazioni, barra del titolo): buoni candidati per riconoscere "questo è il gestionale";
- i termini **esclusivi** di un ambito identificano il modulo specifico.

> **Rivedi sempre il dizionario prima di usarlo.** Il filtro sulle cifre elimina codici e importi, ma dati testuali come nomi utente, ragioni sociali o nominativi passano comunque e vanno rimossi a mano.

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
```

Quando possibile, lavora su ambienti di test o con dati anonimizzati.

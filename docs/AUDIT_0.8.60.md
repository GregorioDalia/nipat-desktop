# Audit tecnico 0.8.60 — 13 novembre 2026

## Perimetro e metodo

Revisione delle modifiche successive alla 0.8.50: preparazione e diagnostica
Windows, verifica del payload, passaggio all'installer e riavvio, collaudo
installato, selezione della CI, riuso delle evidenze e pubblicazione. Il controllo
statico Python copre client, runtime, engine, script e procedure di rilascio.
Le suite automatiche esercitano anche i componenti non modificati. La revisione
manuale si concentra sui percorsi citati e sui contratti dei risultati;
non viene presentata come lettura riga per riga dell'intero repository.

## Rilievi e correzioni

| Priorità | Evidenza e impatto | Correzione e verifica |
| --- | --- | --- |
| Alta | Il Python incorporato usa `._pth`; il verificatore CPIN importava un helper adiacente senza rendere visibile la cartella. Il setup 0.8.50 poteva fallire durante l'autotest. | Percorso dello script inserito esplicitamente negli import; esecuzione di tutti i verificatori distribuiti con il vero Python incorporato. Il setup continua a richiedere il successo dell'autotest. |
| Alta | Il solo transcript PowerShell non conservava in modo affidabile gli errori dei processi nativi. | Acquisizione separata di stdout/stderr e del codice di uscita, codifica UTF-8 e log consultabili dal setup. La riparazione resta limitata alla 0.8.50 originale. |
| Media | Il primo driver di collaudo passava opzioni riservate alle analisi anche a `doctor`, causando un errore CLI prima delle prove scientifiche. | Opzioni di analisi applicate solo ai run; regressione attraverso parser e validazione reali, più prova del comando `settings`. Il report espone il messaggio effettivo. |
| Media | Il test del riavvio si collegava a un processo molto breve senza conservarne l'handle e poteva saltare il controllo se il processo era già terminato. CI push riuscita e CI PR fallita sugli stessi sorgenti. | Conferma fra fixture e osservatore, handle trattenuto prima del rilascio e controllo obbligatorio di identità e codice di uscita. Nessuna riduzione dei controlli dell'aggiornamento. |
| Media | Il collaudo precedente era vincolato alla 0.8.50 e non poteva verificare il nuovo pacchetto. | Driver con identità attesa esplicita e launcher locale incluso nella 0.8.60; rifiuto di versioni, commit, stato o immagine discordanti. Hash dei quattro file e fixture controllati prima dell'esecuzione. |
| Media | Un Ctrl+C immediato alla comparsa del campo BAM può restare sospeso nel `input()` di CPython su terminale POSIX; riprodotto due volte in dieci prove. | Lettura testuale del terminale con propagazione immediata dell’interruzione, mantenendo il comportamento Windows e i lettori personalizzati. La stessa prova PTY, senza ritardi aggiunti o controlli rimossi, viene ripetuta dopo la correzione. |
| Media | Il controllo del manifest Windows deve coincidere con la versione distribuita. | Gate aggiornato alla 0.8.60; manifest precedenti rifiutati. Le fixture del riparatore storico mantengono esplicitamente il contratto 0.8.50. |

## Affidabilità scientifica e manutenzione

I cinque modelli R e i rispettivi riferimenti congelati non vengono modificati
in questa release. Il riuso CI→build richiede lo stesso albero Git e la stessa
immagine immutabile, una CI conclusa con successo, tutti i rapporti attesi
e hash coerenti. I test includono i percorsi di rifiuto delle evidenze mancanti,
alterate o riferite a sorgenti/immagini diversi. Il riuso non sostituisce la
verifica dei pacchetti costruiti.

Il controllo statico ordinario cerca errori di sintassi e nomi non definiti.
Un passaggio aggiuntivo con regole `F` e `B` serve a individuare candidati alla
revisione, senza trasformare automaticamente segnalazioni stilistiche in
difetti: import inutilizzati, callback sincrone in cicli e `zip` preceduti da
controlli di lunghezza richiedono valutazione del contesto. Non sono una misura
del numero di bug. La copertura dei rami viene conservata dalla CI senza
introdurre una soglia percentuale arbitraria.

Il collaudo installato confronta valori attesi e tabelle, non soltanto codici
di uscita. Distingue rifiuti attesi, errori d'ambiente, prove bloccate e interrotte.
Ogni sessione conserva identità dei sorgenti, immagine realmente usata, comandi,
durate e hash. Gli output dei workflow riutilizzano i conteggi già prodotti;
la release non introduce nuovi pool scientifici o modifiche alle formule.

## Evidenze e limiti

Il 13 novembre il collaudo sul PC dell'utente ha prodotto **70 PASS e nessun
FAIL/BLOCKED/INTERRUPTED** in 657,169 secondi sulla 0.8.50 ufficiale con
riparazione CPIN. I risultati archiviati sono stati ricontrollati con i
validatori del repository: 48 analisi positive, sei rifiuti attesi, nove
confronti e 320 hash di input invariati. Il contenuto privato e i percorsi
personali non sono pubblicati nel repository.

Sul candidato 0.8.60 la suite locale completa ha superato **1.272 test**,
con 32 esclusioni legate ai prerequisiti/piattaforme. I **311 test** delle
regole CI/pubblicazione sono riusciti. Sono riusciti anche Ruff, i collegamenti
di 69 documenti Markdown e 20 ripetizioni consecutive della regressione
Ctrl+C. La copertura combinata di istruzioni e rami rilevata è **86,8%**;
non prova da sola la correttezza scientifica. I controlli nell’immagine
scientifica e sui runner Windows/macOS rimangono separati.

Questa evidenza mantiene la propria versione: non attesta l'installazione
del nuovo setup. I risultati della CI e della qualificazione degli installer
0.8.60 sono identificati nel record `.github/release-acceptance/v0.8.60.json`,
creato dopo la build e vincolato ai suoi hash. Le fixture Windows verificano
il setup compilato e i percorsi di errore/aggiornamento; non equivalgono a
una nuova installazione WSL su un PC Windows 10/11. Analoga distinzione vale
per il client Mac e l'esecuzione completa nella VM Lima.

Rimangono la validazione di dominio su dati reali e le prove desktop esplicitate
nel record. Non è emerso un motivo per cambiare le formule scientifiche o
ridurre le verifiche numeriche per accelerare la pubblicazione.

# Guida per l’utilizzo

NIPAT mette a disposizione quattro workflow tramite un menu testuale o la
riga di comando. Gli input e i risultati rimangono sul computer.
Gli autotest inclusi verificano casi noti; la validazione con altri input e
riferimenti scientifici indipendenti resta necessaria.

Questa guida accompagna **NIPAT 0.4.1**, pre-release destinata alle prove di
dominio su Windows 11 x64. La disponibilità per il testing non equivale a
validazione scientifica completata. I due pacchetti contengono la stessa
interfaccia e gli stessi workflow.

## Installazione e avvio di NIPAT 0.4.1

Il percorso principale richiede un solo file, **`NIPAT-Setup.exe`**:

1. Scaricare [NIPAT-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-Setup.exe)
   dalla [pre-release v0.4.1](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.4.1).
2. Fare doppio clic dal proprio account Windows e attendere il completamento
   della configurazione e degli autotest: **`NIPAT: ready`**.
3. Aprire l'icona **NIPAT** sul desktop o nel menu Start.

L'installatore contiene l'applicazione e i componenti per le analisi; li prepara
automaticamente. Non occorre aprire PowerShell, installare Python, R, samtools
oppure Docker Desktop, né scaricare o spostare archivi separati.
L'icona avvia **`NIPAT.exe`**, che apre il menu testuale descritto sotto.

Il perimetro iniziale resta **Windows 11 x64 con WSL2 funzionante**. WSL permette
a Windows di eseguire l'ambiente Linux interno di NIPAT. Se va attivato,
possono servire Internet, autorizzazione amministrativa e riavvio; questo
percorso resta da verificare separatamente e può essere limitato dalle policy
del computer.

Per chi dispone già di **Docker Desktop** con container Linux, l'alternativa è
[NIPAT-DockerDesktop-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-DockerDesktop-Setup.exe):

1. Avviare Docker Desktop in modalità Linux.
2. Scaricare l'EXE ed eseguirlo con doppio clic.
3. Aprire l'icona **NIPAT (Docker Desktop)**. La preparazione degli strumenti e
   gli autotest partono automaticamente quando necessari; al termine compare
   il menu. Agli avvii successivi si apre il menu senza ripetere gli autotest
   già completati per quella versione.

**Docker Desktop può essere vuoto, senza immagini né container.** L'EXE
`0.4.1` contiene già l'archivio del runtime scientifico: durante la preparazione
NIPAT ne verifica l'integrità e lo importa automaticamente in Docker Desktop,
prima di eseguire gli autotest. Non occorre scaricare altri componenti NIPAT,
eseguire `docker pull` o costruire immagini. Il prerequisito è Docker Desktop
installato e avviato in modalità Linux.

Non occorre estrarre archivi né eseguire `1_SETUP.cmd`. Se la preparazione
fallisce, conservare il log, verificare che Docker Desktop sia disponibile e
riaprire la stessa icona per riprovare. Le due installazioni possono coesistere:
per questa prova usare **NIPAT (Docker Desktop)**, non l'icona della copia WSL.
Per una prima analisi seguire la [procedura Docker Desktop](VALIDAZIONE.md#prima-prova-con-docker-desktop).

Per la copia WSL, quando si installa una nuova versione NIPAT prepara anche
il proprio ambiente Linux se necessario. Questa preparazione riguarda NIPAT, non una procedura
manuale di aggiornamento di Windows o WSL. Conserva l'ambiente precedente e
le cartelle dati e risultati, e attiva il nuovo ambiente dopo gli autotest.

Per la copia WSL, se la preparazione fallisce, conservare il log e aprire **NIPAT - completa
preparazione** dal menu Start. I componenti necessari alla ripresa vengono
conservati automaticamente. La nuova applicazione resta bloccata finché la
preparazione non termina. Le prove reali del pacchetto finale, sia di prima
installazione sia di aggiornamento, restano da registrare; i dettagli sono
nella [procedura di verifica](INSTALLATORE_WINDOWS.md#prova-prima-della-pubblicazione).

## Versione già pubblicata: 0.3.0a1

La [pre-release v0.3.0a1](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.3.0a1)
contiene la precedente interfaccia. Il suo setup scarica automaticamente gli
archivi runtime e non include la nuova procedura di aggiornamento; non è il
pacchetto da usare per verificare l'interfaccia della versione `0.4.1`.
Le [note di quella versione](RELEASE_0.3.0a1.md) ne descrivono il perimetro.
Non eliminare ambienti già installati per forzare il setup di una versione
precedente.

## Installazione da sorgenti con Docker già disponibile

Questo è anche il percorso della release `0.2.0a2`:

1. Installare e avviare Docker Desktop con container Linux.
2. Scaricare **Source code (zip)** dalla release GitHub ed estrarlo interamente
   in una cartella locale scrivibile.
3. Avviare `1_SETUP.cmd`, quindi, a configurazione completata, `2_AVVIA.cmd`.

Il setup da sorgenti prepara Python locale e il runtime scientifico ed esegue
gli autotest. Non servono Git, PyCharm o installazioni separate di Python, R
e samtools. Questo percorso richiede Docker già disponibile e non attiva WSL.
L'archivio dei soli sorgenti non contiene il runtime incorporato negli EXE:
la preparazione può quindi richiedere download e la costruzione dell'immagine.

Per sviluppatori che utilizzano il checkout dei sorgenti, dopo il setup è
possibile compilare `NIPAT.exe` nella radice del progetto con il compilatore
.NET Framework presente in Windows:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\installer\windows\build-launcher.ps1 -OutputPath .\NIPAT.exe
```

La compilazione è un passaggio per chi usa i sorgenti; il launcher è già incluso
nei pacchetti Windows costruiti per la distribuzione. `2_AVVIA.cmd` e `nipat.cmd`
restano disponibili.

## Menu guidato

All'apertura, il banner NIPAT riporta la versione. Il menu presenta i quattro
workflow con una breve descrizione. Nei terminali interattivi supportati si
usano **frecce e Invio** oppure i numeri; negli altri terminali resta la scelta
numerica in testo semplice. Ogni workflow mostra indicazioni contestuali anche
dopo la selezione della modalità e durante l'inserimento dei dati: formato
richiesto, esempi e significato di Invio. Le indicazioni sono grigie nei terminali
che supportano i colori e restano disponibili in testo semplice negli altri.

| Scelta | Funzione |
| --- | --- |
| 1–4 | DNPcall, SNPcall, Contamination e CPI, con le modalità di input descritte sotto. |
| 5 | Cambiare la cartella risultati per le analisi successive della sessione. |
| 6 | Riaprire la schermata dell'ultima esecuzione della sessione. |
| 7 | Aprire **Guida all'uso**. |
| 0 | Uscire dal programma. |

**Guida all'uso** distingue **1 — Come usare NIPAT** da
**2 — Verifica strumenti di analisi**; **0** torna al menu principale.
La seconda voce controlla gli strumenti solo su richiesta: aprire la guida
non esegue il controllo. In `--dry-run` il controllo non viene eseguito.

Durante la compilazione, NIPAT controlla i percorsi e segnala gli errori nel
campo interessato. Per un file si può inserire, per esempio,
`..\data\campione.bam` o un percorso completo, anche tra virgolette.
**`:indietro`** permette di tornare all'input precedente; **`:annulla`** torna
al menu principale. Nei campi di testo e nei percorsi, **`0` non è un comando
di annullamento**. I valori già inseriti vengono conservati durante la
correzione. Nei menu che lo prevedono, Esc torna indietro.

Nelle liste di file, il primo elemento è richiesto: premere Invio senza
inserirlo ripropone le istruzioni e lascia aperto il campo. Dopo il primo file,
si può aggiungerne un altro oppure premere Invio per terminare l'elenco e
controllarlo prima di proseguire. Nei campi con un valore predefinito, Invio
mantiene il valore mostrato tra parentesi; **`:vuoto`** cancella un valore
facoltativo, per esempio il nome del run o un prefisso CPI. Il completamento
dei percorsi con Tab non è incluso in questa revisione.

Al termine della compilazione viene mostrato un riepilogo di file, parametri
e destinazione. Controllarlo, modificare i campi necessari e scegliere
**Avvia analisi**. Questa conferma esegue gli script R e gli altri strumenti
previsti dal workflow, come samtools quando occorre preparare il pileup da BAM.
Il calcolo scientifico è reale. Il workflow è lo stesso della CLI diretta e
non modifica automaticamente parametri scientifici o input.
Se l'avvio segnala un errore, correggere i valori conservati prima di riprovare.

La schermata finale permette di aprire la cartella dei risultati, l'intero
run o il log e di visualizzare un riepilogo dell'esecuzione. Il riepilogo
descrive metadati e file disponibili: non interpreta i risultati scientifici.
Un `dry-run` viene presentato come **Esecuzione pianificata**, senza attribuirgli
risultati di un'analisi eseguita.

La simulazione si richiede esplicitamente, per esempio con
`NIPAT.exe --dry-run wizard`. Per l'analisi reale si usa `NIPAT.exe` senza
argomenti, oppure `nipat.cmd wizard`: si rimuove solo `--dry-run`, mantenendo
`wizard` se si usa il comando diretto.

Il richiamo dell'ultima esecuzione e la scelta della cartella risultati valgono
solo per la sessione corrente. Questa revisione non introduce preferenze
persistenti, cronologia tra sessioni o concatenamento automatico dei workflow.
Se un workflow fallisce, il codice di uscita della sessione rimane 2 anche
dopo una successiva esecuzione riuscita; la correzione di un campo prima
dell'avvio non viene conteggiata come fallimento del workflow.

## Dove tenere input e risultati

Gli input possono restare nelle loro cartelle originali: selezionarli con il
percorso completo, anche su un’altra unità locale accessibile al runtime. Non occorre
copiare BAM e FASTA nel progetto. Il backend WSL inizialmente non accetta
condivisioni UNC o unità di rete. Sono ammessi percorsi contenenti spazi;
il programma assegna ai file nomi interni compatibili con gli script R.

L’installatore WSL usa `%LOCALAPPDATA%\NIPAT\data` e
`%LOCALAPPDATA%\NIPAT\runs`; quello Docker Desktop usa
`%LOCALAPPDATA%\NIPAT-DockerDesktop\data` e `runs`. Il setup da sorgenti crea `data` e `runs`
accanto al progetto. `data` non è
un vincolo: i file selezionati possono trovarsi altrove. La cartella dei
risultati si sceglie con **5 — Cartella risultati** nel menu: la scelta vale
per le analisi successive nella sessione corrente e Invio mantiene il percorso
mostrato. La nuova cartella viene controllata e creata; non può sovrapporsi
al progetto o alla cartella dati. `:annulla` torna al menu senza cambiarla.
Per configurare l'avvio si possono usare `--runs-dir` e `--data-dir`, oppure
`NIPAT_RUNS_DIR` e `NIPAT_DATA_DIR`; le opzioni CLI prevalgono sulle variabili
di ambiente. La scelta fatta nel menu non viene salvata per l'avvio successivo.

Nei comandi CLI le opzioni globali vanno **prima del workflow**. I percorsi
relativi partono dalla cartella corrente del terminale; quelli dentro una
lista BAM partono dalla cartella della lista stessa. Nell'esempio seguente,
eseguito dalla cartella contenente `nipat.cmd`, sostituire le cartelle con le
proprie. Per l'applicazione installata, la cartella è
`%LOCALAPPDATA%\Programs\NIPAT`; per i sorgenti è la cartella del progetto:

```powershell
.\nipat.cmd --data-dir "..\miei-dati" --runs-dir "..\miei-risultati" wizard
```

Ogni analisi crea una nuova sottocartella sotto la destinazione scelta,
conservando i nomi degli output scientifici. Non è necessario rinominare
manualmente i risultati e un run esistente non viene sovrascritto.

## Input dei quattro workflow

**DNPcall.** Selezionare uno o più BAM, oppure una lista di BAM: un percorso
per riga, senza intestazione. CLI: ripetere `--bam` oppure usare `--bamlist`,
senza combinare le due modalità. Il FASTA richiede il relativo indice
`.fai`; se compresso in BGZF richiede anche `.gzi`. Gli indici BAM sono
facoltativi per l'attuale percorso `samtools mpileup -l`.
Il pannello DNP è tabulato, senza intestazione, con cinque colonne:
`chr`, `pos1`, `pos2`, `REF`, `ALT`. Le posizioni devono essere adiacenti e
REF/ALT devono essere dinucleotidi.
Il programma prepara in `work` una piccola copia del pannello con gli alleli
REF/ALT in maiuscolo, lasciando invariato l'originale.
L'esecuzione è seriale per impostazione predefinita; il menu e `--parallel`
consentono quella parallela. DNPcall usa alias `sample_0001.bam`, ecc.:
consultare la corrispondenza nei metadati del run per risalire ai campioni
originali. Con un solo campione il grafico UpSet è intenzionalmente omesso.

**SNPcall.** Scegliere BAM e FASTA indicizzato, per generare automaticamente
il pileup, oppure fornire un pileup già pronto. In CLI: `--bam` con
`--reference`, oppure `--pileup`. Il pileup deve avere almeno sette colonne
samtools, con i nomi delle letture (QNAME) nella settima; le eventuali colonne
successive sono ignorate da R. Un pileup standard senza QNAME non è equivalente.
La lista SNP è tabulata, con intestazione
`pos`, `ref`, `alt`, dove `pos` ha forma `chr1:1770788`.
Il totale dei conteggi include le letture “altre”; il rapporto REF usa
soltanto REF e ALT nel denominatore.

**Contamination.** Selezionare singole tabelle oppure una cartella.
La modalità cartella cerca ricorsivamente file `.txt` e `.tsv`, senza
distinguere maiuscole e minuscole, ed esclude il pannello selezionato.
Le tabelle devono contenere `chr`, `pos1`, `pos2`, `N_REF`, `N_ALT`,
`N_Other`; gli output individuali DNPcall sono compatibili. Una cartella
con riepiloghi o altri TXT/TSV non compatibili va filtrata scegliendo
esplicitamente i singoli file. Nomi che collidono dopo l'adattamento per R
sono segnalati e non vengono sovrascritti.
Se presente, `ratio_REF_ALT` viene usato dallo script; altrimenti viene
calcolato dai conteggi. Le stime sono frazioni: `0.025` significa 2.5%.
Il pannello può essere il precedente DNP a cinque colonne oppure una tabella
di coordinate: con intestazione deve includere `chr`, `pos1`, `pos2`;
senza intestazione queste devono essere le prime tre colonne, in tale ordine.

**CPI.** Selezionare la cartella delle tabelle della componente cfDNA materna
e del presunto padre, le coppie e le frequenze di popolazione. Con i prefissi
predefiniti, `A1:A1` individua `MotherA1.txt` e `FatherA1.txt`; più coppie si
separano con virgole. Le frequenze richiedono `chr`, `pos1`, `pos2`,
`Ref_f.pop`, `Alt_f.pop`. La scelta deve essere coerente con i campioni e
il riferimento genomico; i nomi dei file non determinano il ruolo biologico.

Per CPI si può usare un solo pannello (`--panel`), più pannelli etichettati
(`--cutoff LABEL PATH`, ripetibile), una mappa nativa (`--cutoff-map`) oppure
tutti i siti, omettendo i filtri. Le tre opzioni di filtro sono alternative.
Sono accettati il pannello DNP a cinque colonne e i pannelli di coordinate
native. Le etichette dei cutoff devono essere uniche e non contenere virgole
né `=`. Preferire `--cutoff` per indicare separatamente etichetta e percorso,
soprattutto se i nomi dei file contengono delimitatori della mappa nativa.
Il parametro `err_const` è modificabile nel menu e tramite `--err-const`:
il valore predefinito rimane `0.0000892303778101497`.

## Esecuzione e controlli

`2_AVVIA.cmd` mostra la destinazione dei risultati e chiede workflow, modalità
di input e parametri. L'opzione 5 consente di cambiare la destinazione prima
della prossima analisi. È possibile incollare percorsi completi tra virgolette.
Scegliere un nome nuovo per il run oppure lasciare quello automatico.
Per i comandi diretti, aprire PowerShell nella cartella di `nipat.cmd`.
Per raggiungere la cartella dell'applicazione installata:

```powershell
Set-Location (Join-Path $env:LOCALAPPDATA "Programs\NIPAT")
```

Quindi, ad esempio:

```powershell
.\nipat.cmd --help
.\nipat.cmd dnp-call --help
.\nipat.cmd --runs-dir "..\risultati" --dry-run contamination `
    --input "..\campioni\sample.txt" --panel "..\pannelli\DNPpanel.txt"
```

`--dry-run` controlla e prepara l'esecuzione senza avviare l'analisi
scientifica; anche la successiva prova reale richiede un nuovo run.
Il setup esegue quattro gruppi di controlli: l'esempio SNPcall, i casi sintetici
CPI e Contamination e le nuove modalità con input esterni. Quest'ultimo gruppo
prova SNPcall da pileup, Contamination da cartella e CPI con due cutoff oppure
con tutti i siti. Per ripetere i controlli:

```powershell
.\nipat.cmd doctor --runtime
.\nipat.cmd self-test
.\.runtime\python\python.exe scripts/verify_input_modes.py
```

Attendere l'esito finale di ciascun comando. Nei test CPI e Contamination
il confronto numerico segue il completamento del workflow: un `run.json`
positivo non basta a dimostrare il superamento dell'autotest. Il controllo
aggiuntivo usa piccoli input di prova in percorsi esterni al progetto ed è
già incluso in `self-test`; il comando separato ripete soltanto quel gruppo.
Non aggiunge una verifica numerica DNPcall da BAM. La valutazione scientifica
sui propri campioni rimane distinta.

Ogni run conserva `run.json`, `execution.log`, `work` e `output`.
`work/input-mounts.json` e i metadati del run permettono di collegare i percorsi
originali a quelli usati nel container. L'esito positivo indica che i comandi
sono terminati correttamente; `NA` può essere un risultato atteso in assenza
di siti informativi. Una cartella di output parziale non prova il completamento.

## Risultati intermedi e analisi in sequenza

Al termine viene mostrato il percorso del run. In `0.4.1`,
la schermata finale permette anche di aprire direttamente le cartelle e il log;
con **6 — Ultima esecuzione** si può richiamare la stessa schermata durante la
sessione. Per le esecuzioni precedenti, aprire il percorso in Esplora file:

| Contenuto | Utilizzo |
| --- | --- |
| `output` | Tabelle e grafici prodotti dall'analisi. |
| `work` | File preparati e intermedi conservati dal workflow. |
| `run.json` | Input, parametri, corrispondenza dei campioni e stato finale. |
| `execution.log` | Comandi eseguiti, messaggi e dettagli degli errori. |

La CLI esegue un workflow per volta. Per una sequenza **DNPcall → Contamination**:

1. Completare DNPcall e verificare lo stato `succeeded`.
2. Tornare al menu e scegliere **3 — Contamination**.
3. Selezionare le tabelle desiderate in `output\individual_outputs` del run
   DNPcall, oppure quella sola sottocartella come input. Non selezionare la
   radice del run, che contiene anche file non compatibili.
4. Indicare il pannello coerente con l'analisi e creare un nuovo run.

Il secondo run conserva il riferimento ai file del primo. Conservare entrambi;
per preparare input modificati usare copie separate. CPI richiede inoltre le
tabelle dei campioni appropriati, le coppie e le frequenze di popolazione:
la sola presenza di un output DNPcall non definisce il ruolo biologico del campione.

## Problemi e feedback

- **Installatore WSL:** se il setup non termina con `NIPAT: ready`, conservare
  `%LOCALAPPDATA%\Programs\NIPAT\.runtime\installer\setup.log` e `state.json`.
  Dopo aver risolto l'errore, usare **NIPAT - completa preparazione** nel menu
  Start. Docker Desktop non è necessario; il launcher avvia il motore dedicato.
- **Installazione da sorgenti con Docker Desktop:** avviare Docker Desktop
  e attendere che il motore Linux sia pronto.
- **Installatore Docker Desktop:** dopo un errore di preparazione conservare
  `setup.log` e `setup-checks.log` in
  `%LOCALAPPDATA%\Programs\NIPAT-DockerDesktop\.runtime`, verificare
  che Docker Desktop sia avviato in modalità Linux e riaprire l'icona
  **NIPAT (Docker Desktop)**.
- Se un file non è accessibile, controllare percorso, disponibilità dell'unità
  e permessi Windows. Il backend WSL richiede un disco locale fisso; per il
  percorso Docker Desktop controllare anche l'accesso ai file in Docker Desktop.
- Se manca l'indice FASTA, fornire quello corrispondente al riferimento scelto.
- Se il nome del run esiste già, sceglierne uno nuovo.
- Per una prova fallita, conservare il run e compilare la
  [scheda di validazione](VALIDAZIONE.md) con atteso e osservato.

Nomi e percorsi dei campioni compaiono nei metadati e non sono anonimizzati.
Verificare i contenuti prima di allegarli a segnalazioni pubbliche; non
caricare su GitHub dati genomici o risultati dei campioni.

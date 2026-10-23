# Guida per l'utilizzo di NIPAT

Questa guida descrive **NIPAT 0.5.0a1**, con interfaccia testuale guidata e CLI
diretta. La versione non è ancora pubblicata: le istruzioni Windows descrivono
il pacchetto predisposto, non un installatore già disponibile al download.
Per Ubuntu 24.04 LTS x86_64 è disponibile l'esecuzione da sorgenti;
l'installatore Linux non è disponibile.

NIPAT esegue DNPcall, SNPcall, Contamination e CPI sul computer dell'utente.
Il motore scientifico contiene gli script R e gli strumenti necessari.
Gli autotest verificano casi noti; la correttezza scientifica sui propri
campioni richiede una valutazione appropriata al contesto di utilizzo.

## Requisiti e avvio su Windows

Il pacchetto richiede **Windows 11 x64**, virtualizzazione disponibile e WSL2.
L'attivazione di WSL può richiedere Internet, autorizzazione amministrativa
e riavvio, secondo la configurazione del computer. Le policy dell'istituzione
possono richiedere l'intervento del servizio informatico. Non sono necessarie
installazioni separate di Python, R, samtools o Docker Desktop.

Il pacchetto Windows si presenta come un solo file `NIPAT-Setup.exe`:

1. Eseguire l'EXE con doppio clic dal proprio account Windows, senza usare
   «Esegui come amministratore».
2. Seguire la configurazione. Se richiesta, autorizzare l'attivazione di WSL
   e completare il riavvio.
3. Attendere il completamento della preparazione e degli autotest, indicato
   da **`NIPAT: ready`**.
4. Aprire **NIPAT 0.5 Preview** dal menu Start o dal collegamento sul desktop.

Il collegamento avvia `NIPAT.exe` e apre il menu. Non occorre organizzare
archivi, spostare componenti o aprire PowerShell. L'ambiente WSL dedicato
viene avviato automaticamente quando serve.

Se la preparazione si interrompe, conservare il messaggio e il log, risolvere
la causa indicata e aprire **NIPAT 0.5 Preview - completa preparazione** dal
menu Start. L'applicazione non avvia analisi finché il setup non è completato.
I dettagli dell'installazione e dei suoi limiti sono in
[DISTRIBUZIONE.md](DISTRIBUZIONE.md).

## Menu guidato

Il banner riporta la versione e il menu mostra le analisi disponibili.
Nei terminali interattivi supportati si usano frecce e Invio oppure i numeri;
negli altri terminali è disponibile la scelta numerica in testo semplice.

| Scelta | Funzione |
| --- | --- |
| 1 | DNPcall: dinucleotidi da uno o più BAM. |
| 2 | SNPcall: SNP da BAM o pileup esistente. |
| 3 | Contamination: stime da tabelle compatibili. |
| 4 | CPI: frazione fetale e indice di paternità. |
| 5 | Cartella risultati per le analisi successive della sessione. |
| 6 | Risultati e log dell'ultima esecuzione della sessione. |
| 7 | Guida all'uso e verifica degli strumenti di analisi. |
| 0 | Uscita dal programma. |

Ogni campo presenta indicazioni sul formato richiesto e sul significato di
Invio. Nei terminali con colori, le indicazioni contestuali sono grigie;
restano leggibili in testo semplice negli altri terminali.

| Comando durante l'inserimento | Effetto |
| --- | --- |
| Invio in un campo con valore predefinito | Mantiene il valore mostrato. |
| Invio in una lista con almeno un file | Termina l'elenco. |
| Invio in una lista vuota | Ripropone le istruzioni; serve almeno un file. |
| `:indietro` | Torna al campo precedente conservando i valori inseriti. |
| `:annulla` | Abbandona la compilazione e torna al menu. |
| `:vuoto` | Cancella un valore facoltativo, come nome del run o prefisso CPI. |

Nei campi di testo e nei percorsi, `0` è un valore: per annullare usare
`:annulla`. Nei menu che lo prevedono, Esc torna indietro. Il completamento
dei percorsi con Tab non è disponibile.

Al termine della compilazione, controllare input, parametri e destinazione
nel riepilogo. È possibile correggere i campi prima di scegliere
**Avvia analisi**. Questa conferma esegue il motore scientifico, inclusi gli
script R e samtools quando il workflow lo richiede.

La schermata finale consente di aprire risultati, cartella del run e log,
o di visualizzare il riepilogo dell'esecuzione. Il riepilogo descrive file
e metadati; non interpreta il significato scientifico dei risultati.
La scelta della cartella risultati e il richiamo dell'ultima esecuzione
valgono per la sessione corrente. Non sono presenti una cronologia tra
sessioni o il concatenamento automatico delle analisi.

**7 — Guida all'uso** contiene **Come usare NIPAT** e **Verifica strumenti
di analisi**. La seconda voce avvia un controllo dell'ambiente senza
elaborare campioni. Aprire la guida non avvia automaticamente il controllo.

## Percorsi e cartelle

Gli input possono restare nelle cartelle originali. Non occorre copiare BAM
e FASTA dentro NIPAT. Su Windows sono supportati dischi locali fissi;
condivisioni UNC, unità di rete e unità rimovibili non sono supportate dal
backend WSL. Su Linux i file devono essere accessibili al motore Docker locale.

Si possono incollare percorsi completi, anche tra virgolette, oppure percorsi
relativi alla cartella corrente mostrata dal programma. In Windows, **Copia
come percorso** di Esplora file produce un valore utilizzabile. Le voci relative
in un file BAM list partono invece dalla cartella della lista.

| Contenuto | Percorso predefinito Windows |
| --- | --- |
| Applicazione | `%LOCALAPPDATA%\Programs\NIPAT-0.5-Preview` |
| Cartella dati di riferimento | `%LOCALAPPDATA%\NIPAT-0.5-Preview\data` |
| Risultati | `%LOCALAPPDATA%\NIPAT-0.5-Preview\runs` |

Per il checkout da sorgenti, `data` e `runs` si trovano accanto alla cartella
del progetto. `data` è una cartella di comodità e non limita la selezione
degli input. La cartella dei risultati deve essere scrivibile e separata
dalla cartella applicativa e da `data`, senza annidamenti tra queste tre radici.

**5 — Cartella risultati** imposta la destinazione per il resto della
sessione e crea la cartella se necessario. Ogni analisi genera una propria
sottocartella; un nome di run già esistente viene rifiutato. È possibile
lasciare vuoto il nome per ottenere quello automatico.

Nella CLI, `--data-dir` e `--runs-dir` impostano esplicitamente i percorsi.
Il checkout da sorgenti accetta anche `NIPAT_DATA_DIR` e `NIPAT_RUNS_DIR`.
L'applicazione Windows installata utilizza la propria configurazione e
ignora eventuali variabili ereditate per questi percorsi; usare le opzioni
CLI o il menu per selezionare una destinazione diversa.

## Input dei quattro workflow

### DNPcall

Selezionare uno o più BAM oppure un file lista con un percorso BAM per riga,
senza intestazione. In CLI, ripetere `--bam` o usare `--bamlist`; le modalità
sono alternative. Sono richiesti un FASTA e il pannello DNP.

Il FASTA deve avere il proprio indice `.fai`; se compresso in BGZF richiede
anche `.gzi`. Gli indici BAM sono facoltativi per il percorso mpileup usato
da NIPAT. Riferimento, BAM e pannello devono essere coerenti per assemblaggio
genomico e nomi dei cromosomi.

Il pannello contiene cinque colonne senza intestazione, separate da tabulazioni
o spazi: `chr`, `pos1`, `pos2`, `REF`, `ALT`. Le coordinate sono positive e
adiacenti (`pos2 = pos1 + 1`); gli alleli sono dinucleotidi composti da A, C,
G e T. Non sono ammesse coordinate duplicate. NIPAT prepara una copia con
alleli maiuscoli senza modificare l'originale.

L'esecuzione è seriale per impostazione predefinita; il menu e `--parallel`
consentono quella parallela. I BAM ricevono alias `sample_0001`, ecc.; la
corrispondenza con i nomi originali è registrata nel run. Con un solo campione
non viene prodotto il grafico UpSet.

### SNPcall

Selezionare BAM e FASTA indicizzato per generare il pileup oppure indicare
un pileup esistente. In CLI usare `--bam` con `--reference` oppure `--pileup`.
Il pannello SNP è richiesto in entrambe le modalità.

Il pileup deve essere tabulato, senza intestazione, con almeno sette colonne
samtools e i nomi delle letture (QNAME) nella settima, come prodotti da
`--output-QNAME`. Le colonne successive sono ignorate dallo script R.
Un pileup a sei colonne non contiene le informazioni richieste.

La lista SNP è tabulata, con intestazioni `pos`, `ref`, `alt`. La posizione
ha forma `chr1:1770788`. Nella modalità BAM la posizione deve essere almeno 2,
per consentire la costruzione della finestra di tre basi.
L'output `SNPcall_output.txt` include conteggi REF, ALT e altre letture.
Il totale comprende le letture altre; il rapporto REF usa solo REF e ALT
nel denominatore.

### Contamination

Selezionare singole tabelle oppure una cartella. La modalità cartella cerca
ricorsivamente file `.txt` e `.tsv`, senza distinguere maiuscole e minuscole,
ed esclude il pannello selezionato. Una cartella contenente riepiloghi o altri
TXT/TSV incompatibili va sostituita con una selezione esplicita dei file.

Sono richieste le colonne tabulate `chr`, `pos1`, `pos2`, `N_REF`, `N_ALT`,
`N_Other`. Le tabelle individuali DNPcall sono compatibili. Se presente,
`ratio_REF_ALT` viene utilizzato; altrimenti lo script lo calcola dai conteggi.
I nomi che collidono dopo l'adattamento vengono rifiutati.

Il pannello può essere un DNP a cinque colonne o un pannello di coordinate:
con intestazione deve contenere `chr`, `pos1`, `pos2`; senza intestazione
queste devono essere le prime tre colonne, nell'ordine indicato.
Le stime sono frazioni: `0.025` corrisponde al 2,5%. L'assenza di siti
informativi può produrre conteggio zero e stime `NA`.

### CPI

Selezionare la cartella delle tabelle cfDNA materne e del presunto padre,
le coppie e il file delle frequenze di popolazione. Le tabelle devono contenere
`chr`, `pos1`, `pos2`, `REF`, `ALT`, `N_REF`, `N_ALT`, `N_Other`, `total_count`.
Le frequenze richiedono `chr`, `pos1`, `pos2`, `Ref_f.pop`, `Alt_f.pop`.

Con i prefissi predefiniti, la coppia `A1:A1` seleziona `MotherA1.txt` e
`FatherA1.txt`. Più coppie si separano con virgole, per esempio
`A1:A1,A2:A2`. I prefissi sono configurabili e possono essere vuoti;
il suffisso dei file rimane `.txt`. La scelta dei campioni e delle frequenze
deve essere scientificamente appropriata: il nome di un file non verifica
il ruolo biologico del campione.

| Selezione dei siti | Opzione CLI |
| --- | --- |
| Tutti i siti disponibili | Nessuna opzione di filtro. |
| Un pannello | `--panel PATH` |
| Più pannelli etichettati | `--cutoff LABEL PATH`, ripetibile. |
| Mappa nativa CPI | `--cutoff-map "LABEL=PATH,LABEL2=PATH2"` |

Le tre opzioni di filtro sono alternative. Sono ammessi pannelli DNP a cinque
colonne e pannelli di coordinate con lo schema descritto per Contamination.
Le etichette devono essere uniche, senza virgole o `=`. `--cutoff` evita le
ambiguità della mappa quando i percorsi contengono tali delimitatori.

La costante d'errore `--err-const` è modificabile anche nel menu. Il valore
predefinito è `0.0000892303778101497`; è richiesto un numero finito non negativo,
con il punto come separatore decimale. I parametri configurabili sono quelli
esposti nel menu e in `cpi --help`; le costanti interne degli algoritmi R
sono parte del motore scientifico distribuito.

## Comandi diretti

Su Windows, aprire PowerShell nella cartella applicativa:

```powershell
Set-Location (Join-Path $env:LOCALAPPDATA "Programs\NIPAT-0.5-Preview")
.\NIPAT.exe --help
.\NIPAT.exe dnp-call --help
.\NIPAT.exe wizard
```

`NIPAT.exe` senza argomenti apre il menu; accetta anche gli argomenti CLI.
`nipat.cmd` offre gli stessi comandi per l'uso nei terminali e negli script.
Su Linux, dopo l'installazione da sorgenti, usare `nipat` al posto di
`.\NIPAT.exe` e la sintassi dei percorsi del sistema.

Le opzioni globali precedono il sottocomando. Esempio di simulazione:

```powershell
.\NIPAT.exe --runs-dir "..\risultati-prova" --dry-run contamination `
  --input "..\campioni\sample.txt" --panel "..\pannelli\DNPpanel.txt"
```

`--dry-run` controlla gli input e prepara la richiesta senza eseguire il
motore scientifico. Registra uno stato `planned`, non produce risultati
scientifici e non sostituisce una verifica del runtime. La prova reale richiede
un nuovo nome di run. Per simulare il menu usare `NIPAT.exe --dry-run wizard`;
per effettuare analisi reali aprire normalmente NIPAT.

Per verificare strumenti e casi di prova:

```powershell
.\NIPAT.exe doctor --runtime
.\NIPAT.exe self-test
```

`doctor --runtime` verifica il motore incorporato e le sue interfacce, R,
samtools e le dipendenze richieste. `self-test` esegue l'esempio SNPcall,
i casi sintetici CPI e Contamination e le verifiche delle modalità di input
esterno. Queste ultime comprendono SNPcall da pileup, Contamination da cartella
e CPI con più cutoff oppure tutti i siti. Non includono una prova numerica
DNPcall da BAM. Il risultato dell'autotest è il suo esito finale, successivo
al completamento dei singoli run.

## Risultati e analisi in sequenza

| Contenuto del run | Utilizzo |
| --- | --- |
| `output` | Tabelle e grafici prodotti dall'analisi. |
| `work` | Richiesta al motore e intermedi conservati. |
| `run.json` | Input, parametri, identità del motore e stato dell'esecuzione. |
| `execution.log` | Comandi, messaggi e dettagli degli errori. |

Consultare questi file dalla schermata finale o dal file system.
**6 — Ultima esecuzione** richiama il run più recente della sessione;
le esecuzioni precedenti rimangono nelle rispettive cartelle.
La [guida alle esecuzioni](ESECUZIONI.md) descrive gli intermedi effettivamente
conservati e il significato degli stati.

Per una sequenza **DNPcall → Contamination**:

1. Completare DNPcall e verificare stato, campioni e risultati.
2. Scegliere **3 — Contamination**.
3. Selezionare le tabelle richieste in `output\individual_outputs` del run
   DNPcall, oppure quella sottocartella come input. La radice del run contiene
   anche file non compatibili con Contamination.
4. Indicare il pannello appropriato e avviare un nuovo run.

Conservare entrambi i run. Per preparare input modificati utilizzare copie
separate. Un run `succeeded` attesta il completamento tecnico, non la validità
scientifica del risultato; `NA` può essere previsto in assenza di siti informativi.
Una cartella di output parziale non dimostra il completamento del workflow.

## Problemi e segnalazioni

| Problema | Verifica da effettuare |
| --- | --- |
| Setup Windows incompleto | Conservare `setup.log` e `state.json` in `%LOCALAPPDATA%\Programs\NIPAT-0.5-Preview\.runtime\installer`; risolvere l'errore e usare il collegamento di completamento della preparazione. |
| File non accessibile | Controllare percorso, permessi e disponibilità del disco; su Windows usare un disco locale fisso. |
| Indice FASTA assente | Fornire il `.fai` del riferimento selezionato e, per BGZF, il `.gzi`. |
| Nome di run già presente | Scegliere un nome nuovo o lasciare il nome automatico. |
| Analisi interrotta o fallita | Conservare l'intera cartella del run e consultare `execution.log`. |
| Risultato inatteso | Confrontare input e parametri con il caso di riferimento e compilare la [scheda di validazione](VALIDAZIONE.md). |

Ctrl+C tenta di interrompere anche il container corrente. Una chiusura forzata
o uno spegnimento possono lasciare lo stato `preparing` o `running`: non sono
esiti positivi. Una nuova prova deve usare una nuova cartella.

Nomi e percorsi dei campioni sono presenti nei metadati e non vengono
anonimizzati automaticamente. Prima di allegare log o file a una segnalazione,
verificarne il contenuto e scegliere un canale adatto ai dati condivisi.

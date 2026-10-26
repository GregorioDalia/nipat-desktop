# Guida per l'utilizzo di NIPAT

Questa guida descrive **NIPAT Desktop 0.7.0a1, in sviluppo**,
con interfaccia testuale guidata e CLI diretta per Windows e Ubuntu.
Consultare la pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases) per le
versioni pubblicate e gli installatori disponibili. I pacchetti ottenuti dagli
artefatti GitHub Actions sono destinati alla revisione tecnica.

La release ufficiale disponibile è la 0.6.0. La versione documentata offre
**W — Workflow automatici** per eseguire DNPcall seguito da Contamination,
CPI oppure entrambe le analisi, con SNPcall facoltativo sugli stessi BAM.
La stessa voce offre SNPcall su più BAM o pileup. Un'unica configurazione
e conferma avvia i passaggi selezionati; le quattro analisi singole rimangono
disponibili.
**Guida e informazioni → Catalogo scientifico** e `nipat parameters`
descrivono in italiano e inglese opzioni configurabili, regole interne e
preparazione degli input. Il [riferimento del catalogo](CATALOGO_SCIENTIFICO.md)
e il [contratto dei piani](WORKFLOW_CONTRACT.md) documentano queste interfacce.

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

Nella pagina [Releases](https://github.com/GregorioDalia/nipat-desktop/releases),
aprire la versione desiderata e scaricare **NIPAT-Setup.exe** dagli asset.
Si utilizza un solo file eseguibile, senza archivi da estrarre. I file
**Source code** sono destinati allo sviluppo e non sono installatori.

Installare e avviare NIPAT:

1. Eseguire l'EXE con doppio clic dal proprio account Windows, senza usare
   «Esegui come amministratore».
2. Scegliere la cartella dell'applicazione e le quattro cartelle per ambiente
   WSL, cache, dati e risultati, oppure mantenere i valori proposti. Il setup
   indica **Installazione** oppure **Aggiornamento e riparazione** quando
   riconosce un’installazione NIPAT Desktop esistente. Se richiesta, autorizzare l'attivazione
   di WSL e completare il riavvio.
3. Attendere il completamento della preparazione e degli autotest, indicato
   da **`NIPAT: ready`**.
4. Selezionare **Avvia NIPAT Desktop** nella schermata finale del setup,
   oppure aprire il collegamento dal menu Start o dal desktop. L'opzione
   di avvio immediato è disponibile quando la preparazione è completata
   e non è richiesto un riavvio.

Il collegamento apre il menu guidato. Per gli utilizzi successivi è sufficiente
aprire la stessa icona: non occorre rieseguire il setup, organizzare archivi,
spostare componenti o aprire PowerShell. L'ambiente WSL dedicato
viene avviato automaticamente quando serve.

Se la preparazione si interrompe, conservare il messaggio e il log, risolvere
la causa indicata e aprire **NIPAT Desktop - completa preparazione** dal
menu Start. L'applicazione non avvia analisi finché il setup non è completato.
I dettagli dell'installazione e dei suoi limiti sono in
[DISTRIBUZIONE.md](DISTRIBUZIONE.md).

Il pacchetto Windows non è firmato da NIPAT. Se Windows o il browser ne impediscono
l'uso, conservare il messaggio completo e il nome del file bloccato e comunicarli
al responsabile tecnico insieme alla versione del pacchetto. Le indicazioni
per la diagnosi sono nella [guida Windows](INSTALLATORE_WINDOWS.md#controlli-di-sicurezza-di-windows-e-del-browser).

## Requisiti e avvio su Ubuntu

Il pacchetto `.deb` richiede **Ubuntu 24.04 LTS x86_64**, Python 3.12,
Docker Engine locale e Compose v2. L’installazione con APT scarica e installa
queste dipendenze se mancano. Prima di avviare NIPAT, Docker deve essere
avviato e accessibile al proprio account, con daemon di sistema senza
rimappatura degli UID.
L’installazione e l’autorizzazione a usare Docker sono descritte nella
[guida dell’installatore Linux](INSTALLATORE_LINUX.md).

Dopo l’installazione, aprire **NIPAT Desktop** dal menu delle applicazioni,
oppure eseguire `nipat` nel terminale. Il primo avvio importa
l’immagine inclusa e completa diagnostica e autotest; il menu appare solo
dopo la riuscita della preparazione. NIPAT non va eseguito con `sudo`.

Per riprendere una preparazione interrotta, risolvere la causa segnalata e
riaprire NIPAT oppure eseguire `nipat --setup`. Il launcher
conserva stato e log in `${XDG_STATE_HOME:-~/.local/state}/nipat-desktop`.

## Menu guidato

Il banner riporta la versione e il menu mostra le analisi disponibili.
Nei terminali interattivi supportati si usano frecce e Invio oppure il tasto
indicato accanto alla voce. Negli altri terminali si digita la scelta in testo
semplice: un numero oppure `W` per i workflow automatici.

| Scelta | Funzione |
| --- | --- |
| 1 | DNPcall: dinucleotidi da uno o più BAM. |
| 2 | SNPcall: SNP da BAM o pileup esistente. |
| 3 | Contamination: stime da tabelle compatibili. |
| 4 | CPI: frazione fetale e indice di paternità. |
| 5 | Configura: cartelle e impostazioni predefinite del menu, conservate fra gli avvii. |
| 6 | Risultati e log dell'ultima esecuzione della sessione. |
| 7 | Guida e informazioni: istruzioni, versione e riferimenti. |
| 8 | Verifica ambiente: controllo del runtime e degli strumenti di analisi. |
| 9 | Verifica aggiornamenti: ricerca, download verificato e avvio dell'installatore dopo conferma. |
| W | Workflow automatici: composizioni DNPcall con Contamination/CPI e SNPcall facoltativo; SNPcall su più campioni. |
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
**1 — Avvia analisi**. La scelta predefinita è **0 — Annulla**: il solo Invio
non avvia il calcolo. La conferma esplicita esegue il motore scientifico,
inclusi gli script R e samtools quando il workflow lo richiede.

La schermata finale consente di aprire risultati, cartella del run e log,
o di visualizzare il riepilogo dell'esecuzione. Il riepilogo descrive file
e metadati; non interpreta il significato scientifico dei risultati.
Il richiamo dell'ultima esecuzione vale per la sessione corrente. I run
precedenti restano sul disco; non è presente una cronologia tra sessioni.
Ogni workflow automatico conserva i risultati separati dei passaggi selezionati
all'interno di un solo run.

**7 — Guida e informazioni** è dedicata alla consultazione. **8 — Verifica
ambiente** controlla il motore e gli strumenti senza elaborare campioni.
Aprire la guida non avvia questo controllo né modifica la configurazione.

## Configurazione del menu

**5 — Configura** conserva le impostazioni utilizzate come valori proposti
nelle analisi guidate. Scegliere una categoria e poi il campo da modificare;
le indicazioni spiegano il valore richiesto. **9 — Salva modifiche** registra
la categoria, mentre **0 — Annulla modifiche** la chiude senza salvare.
Invio mantiene il valore mostrato durante la modifica di un campo; nel menu
della categoria equivale ad annullare senza salvare.

| Categoria | Impostazioni |
| --- | --- |
| Cartelle dati e risultati | Cartella proposta per organizzare i dati e destinazione predefinita dei run. |
| DNPcall | Modalità di selezione dei BAM, FASTA, pannello e modalità seriale/parallela. |
| SNPcall | Modalità BAM o pileup, FASTA e pannello SNP. |
| Contamination | Modalità singoli file o cartella e pannello. |
| CPI | Prefissi materno/paterno, frequenze di popolazione, modalità di selezione dei siti e relativi pannelli o mappe, costante d'errore. |
| Riepilogo impostazioni | Consultazione dei valori salvati. |
| Ripristina impostazioni | Ritorno ai valori iniziali del menu dopo conferma esplicita; non elimina campioni o risultati. |
| Aggiornamenti | Canale `testing` o `stable` e verifica facoltativa all'avvio. |

I valori salvati vengono riproposti anche dopo aver chiuso NIPAT. Si possono
modificare durante la compilazione di una singola analisi senza cambiare le
preferenze salvate. Campioni, coppie CPI e nome del run devono essere indicati
ogni volta: non vengono memorizzati come valori predefiniti. Verificare sempre
riferimenti, pannelli, parametri e destinazione nel riepilogo prima dell'avvio.

Le preferenze del menu sono conservate in:

| Sistema | File |
| --- | --- |
| Windows | `%LOCALAPPDATA%\NIPAT-Desktop\preferences.json` |
| Ubuntu | `${XDG_CONFIG_HOME:-~/.config}/nipat-desktop/preferences.json` |

Questa configurazione riguarda esclusivamente il menu guidato. I comandi CLI
diretti usano le proprie opzioni esplicite e i normali valori predefiniti,
indipendentemente da `preferences.json`. Se il menu viene avviato con
`--data-dir` o `--runs-dir`, quei percorsi prevalgono nella sessione; le
cartelle salvate saranno utilizzate alla riapertura senza le opzioni esplicite.

Se il file delle preferenze non è leggibile o valido, NIPAT lo segnala, non
lo sovrascrive e blocca le analisi guidate fino alla correzione o al ripristino.
Usare **Configura → Ripristina impostazioni** solo dopo aver verificato il
messaggio: il ripristino elimina le preferenze, non i dati o i risultati. Un riferimento salvato che non esiste più può essere corretto nei
campi dell'analisi; la presenza nelle preferenze non ne attesta la validità.

Per cambiare la posizione dell'applicazione, dell'ambiente WSL o della cache,
usare l'installatore. **Configura** non trasferisce questi componenti e non
sposta i dati già presenti. La gestione delle cartelle è descritta di seguito.

## Aggiornamenti

**9 — Verifica aggiornamenti** consulta le release pubblicate del repository
ufficiale. Sono proposte soltanto versioni successive, compatibili con la
piattaforma e accompagnate dalle evidenze di pubblicazione e accettazione
richieste. Le build di revisione di GitHub Actions e le bozze non sono aggiornamenti.
L'assenza di una versione proposta non attesta una nuova pubblicazione.

In **5 — Configura → 8 — Aggiornamenti** sono disponibili:

| Impostazione | Comportamento |
| --- | --- |
| Canale `testing`, predefinito | Considera pre-release e release stabili approvate. |
| Canale `stable` | Considera soltanto release stabili approvate. |
| Verifica all'avvio, inizialmente disattivata | Se attivata, consulta le release e mostra un breve avviso; non scarica né installa automaticamente. |

Quando è disponibile una versione:

1. Controllare versione e dimensione dell'installatore e consultare il
   collegamento alle note della release mostrato dal menu.
2. Selezionare **1 — Scarica aggiornamento** oppure **0 — Più tardi**,
   la scelta predefinita. Viene scaricato l'installatore completo della propria
   piattaforma; NIPAT ne verifica dimensione e checksum prima dell'utilizzo.
3. Al termine, scegliere esplicitamente **1 — Installa l'aggiornamento** o
   rimandare. Il download da solo non cambia l'applicazione installata.
4. Confermando l'installazione, il menu si chiude per consentire la sostituzione
   dei componenti. Su Windows seguire il setup; su Ubuntu l'installazione del
   `.deb` richiede autorizzazione amministrativa tramite APT.
5. Riaprire NIPAT quando la preparazione del pacchetto è completata. L'avvio
   delle analisi resta subordinato alla configurazione verificata del runtime.

La verifica automatica è soltanto informativa e non interrompe le analisi.
È possibile annullare o rimandare; una connessione assente o un errore di
verifica non impediscono di usare l'installazione già pronta. La ricerca e
il download richiedono Internet, mentre i calcoli continuano a usare il motore
locale. In modalità `--dry-run` la voce aggiornamenti non esegue connessioni,
download o installazioni.

L'installatore dello stesso prodotto conserva percorsi configurati, preferenze,
dati e risultati. Un aggiornamento non modifica i record delle analisi già
eseguite: i nuovi run registrano la versione dell'applicazione e il motore
utilizzati. Il backup di riparazione non costituisce un rollback completo
automatico. In caso di errore conservare messaggi e log, quindi seguire la
[guida Windows](INSTALLATORE_WINDOWS.md#aggiornamento-e-riparazione) o la
[guida Ubuntu](INSTALLATORE_LINUX.md#aggiornamento-e-rimozione).

## Percorsi e cartelle

Gli input possono restare nelle cartelle originali. Non occorre copiare BAM
e FASTA dentro NIPAT. La cartella dati configurata non modifica la base dei
percorsi relativi: questi restano riferiti alla cartella corrente mostrata
dal programma. Su Windows sono supportati dischi locali fissi;
condivisioni UNC, unità di rete e unità rimovibili non sono supportate dal
backend WSL. Su Linux i file devono essere accessibili al motore Docker locale.

Si possono incollare percorsi completi, anche tra virgolette, oppure percorsi
relativi alla cartella corrente mostrata dal programma. In Windows, **Copia
come percorso** di Esplora file produce un valore utilizzabile. Le voci relative
in un file BAM list partono invece dalla cartella della lista.

Il setup Windows permette di scegliere separatamente queste destinazioni:

| Contenuto | Percorso predefinito Windows |
| --- | --- |
| Applicazione e documentazione | `%LOCALAPPDATA%\Programs\NIPAT-Desktop` |
| Ambiente WSL e strumenti scientifici | `%LOCALAPPDATA%\NIPAT-Desktop\wsl` |
| Cache degli archivi di installazione | `%LOCALAPPDATA%\NIPAT-Desktop\cache` |
| Cartella dati di riferimento | `%LOCALAPPDATA%\NIPAT-Desktop\data` |
| Risultati | `%LOCALAPPDATA%\NIPAT-Desktop\runs` |

Si possono usare dischi locali fissi diversi. Le cinque cartelle devono essere
scrivibili, distinte e non contenersi tra loro; il setup controlla le
destinazioni prima di installare. Non sono accettate cartelle di sistema,
cartelle delle altre installazioni NIPAT o percorsi che attraversano collegamenti.
Per l'applicazione scegliere una cartella vuota o della stessa installazione NIPAT Desktop.
Se una cartella non vuota non viene riconosciuta, il setup può proporre una
sottocartella vuota: accettarla cambia la destinazione senza spostare o
cancellare il contenuto della cartella iniziale. In alternativa, scegliere
un'altra cartella vuota. Le cartelle dati e risultati possono già contenere
file, che vengono conservati.
Il collegamento **Cartella NIPAT Desktop** nel menu Start apre la cartella applicativa.

Le scelte vengono riproposte alla reinstallazione. Per aggiornare o riparare
un’installazione NIPAT Desktop riconosciuta, usare la stessa cartella applicativa, anche se
contiene residui di una disinstallazione. Il setup sostituisce i propri
componenti e conserva i file estranei; prima di sovrascrivere file differenti,
ne salva una copia. Il backup è selettivo e non ripristina automaticamente
l'intera installazione in caso di errore. I dettagli sono nella
[guida dell'installatore Windows](INSTALLATORE_WINDOWS.md#aggiornamento-e-riparazione).

Cambiare dati o risultati nel setup non sposta i file già presenti: i run
precedenti rimangono nella vecchia destinazione e si consultano con Esplora file. Cambiare la cartella
dell'ambiente WSL prepara un ambiente dedicato nella nuova posizione e
conserva quello precedente.

Su Ubuntu installato dal pacchetto, l’applicazione si trova in
`/opt/nipat-desktop`; dati e risultati predefiniti sono nelle sottocartelle
`data` e `runs` di `${XDG_DATA_HOME:-~/.local/share}/nipat-desktop`.
Le variabili XDG, se definite, devono indicare percorsi assoluti.

Per il checkout da sorgenti, `data` e `runs` si trovano accanto alla cartella
del progetto. `data` è una cartella di comodità e non limita la selezione
degli input. La cartella dei risultati deve essere scrivibile e separata
dalla cartella applicativa e da `data`, senza annidamenti tra queste tre radici.

**5 — Configura → Cartelle dati e risultati** salva le destinazioni proposte
per il menu. Cambiare percorso non trasferisce i file esistenti. Ogni analisi
genera una propria sottocartella dei risultati; un nome di run già esistente
viene rifiutato. È possibile lasciare vuoto il nome per ottenere quello automatico.

Nella CLI, `--data-dir` e `--runs-dir` impostano esplicitamente i percorsi.
Il checkout da sorgenti accetta anche `NIPAT_DATA_DIR` e `NIPAT_RUNS_DIR`.
I launcher dei pacchetti installati utilizzano la propria configurazione e
ignorano eventuali variabili NIPAT ereditate per questi percorsi. Le preferenze
del menu si applicano soltanto all'uso guidato; per cambiare una destinazione
in un comando diretto usare le opzioni CLI.

## Disinstallazione su Windows

Da **Impostazioni → App → App installate**, disinstallare **NIPAT Desktop**.
Dati e risultati vengono sempre conservati. La rimozione dell'ambiente WSL e
della cache NIPAT è facoltativa e non è selezionata per impostazione predefinita.
Se richiesta, riguarda soltanto le risorse verificate di NIPAT Desktop nelle
cartelle registrate; non elimina Docker Desktop, altre distribuzioni WSL o
altre installazioni NIPAT.

Le preferenze dei percorsi restano disponibili per una reinstallazione.
Conservando ambiente e cache si possono riutilizzare i componenti compatibili;
eliminandoli, il setup deve prepararli nuovamente. Un errore nella rimozione
va conservato insieme al log: non implica che tutte le risorse siano state
eliminate. La procedura e i registri sono descritti nella
[guida dell'installatore Windows](INSTALLATORE_WINDOWS.md).

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

Il valore iniziale dell'esecuzione è seriale; il menu e `--parallel`
consentono quella parallela. Il menu propone il valore salvato in **Configura**,
se presente. I BAM ricevono alias `sample_0001`, ecc.; la
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
iniziale distribuito è `0.0000892303778101497`; è richiesto un numero finito non negativo,
con il punto come separatore decimale. I parametri configurabili sono quelli
esposti nel menu e in `cpi --help`; le costanti interne degli algoritmi R
sono parte del motore scientifico distribuito.

## Comandi diretti

Su Windows, aprire PowerShell nella cartella applicativa:

```powershell
# Esempio per la cartella predefinita; usare quella scelta nel setup.
Set-Location (Join-Path $env:LOCALAPPDATA "Programs\NIPAT-Desktop")
.\nipat.cmd --help
.\nipat.cmd dnp-call --help
.\nipat.cmd wizard
```

`nipat.cmd wizard` apre il menu; `nipat.cmd` senza argomenti mostra la guida
dei comandi. Per l'uso ordinario è sufficiente l'icona NIPAT.
Su Ubuntu installato dal pacchetto, usare `nipat` al posto di
`.\nipat.cmd` e la sintassi dei percorsi Linux. Nel checkout da sorgenti
il comando è `nipat`. Per esempio:

```bash
nipat --help
nipat dnp-call --help
nipat --runs-dir "$HOME/risultati-nipat" contamination \
  --input "$HOME/campioni/sample.txt" --panel "$HOME/pannelli/DNPpanel.txt"
```

Il launcher Ubuntu permette `--help` e `--version` anche senza Docker
disponibile. `--setup` ripete la verifica dell’archivio, la diagnostica e
gli autotest senza aprire il menu.

Le opzioni globali precedono il sottocomando. Esempio di simulazione:

```powershell
.\nipat.cmd --runs-dir "..\risultati-prova" --dry-run contamination `
  --input "..\campioni\sample.txt" --panel "..\pannelli\DNPpanel.txt"
```

`--dry-run` controlla gli input e prepara la richiesta senza eseguire il
motore scientifico. Registra uno stato `planned`, non produce risultati
scientifici e non sostituisce una verifica del runtime. La prova reale richiede
un nuovo nome di run. Per simulare il menu usare `nipat.cmd --dry-run wizard`;
per effettuare analisi reali aprire normalmente NIPAT. Nel pacchetto Ubuntu,
`--dry-run` non importa l’immagine e non avvia la preparazione o gli autotest;
non attesta quindi che l’ambiente scientifico sia disponibile.

Per verificare strumenti e casi di prova:

```powershell
.\nipat.cmd doctor --runtime
.\nipat.cmd self-test
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

Le quattro analisi non sono quattro passaggi obbligatori della stessa catena:

| Composizione | Uso degli input |
| --- | --- |
| DNPcall → Contamination | Le tabelle in `output/individual_outputs` forniscono i conteggi necessari; scegliere un pannello coerente. |
| DNPcall → CPI | Le tabelle individuali dei campioni appropriati forniscono i conteggi; occorre assegnare esplicitamente i ruoli cfDNA materno/paterno e fornire coppie e frequenze di popolazione. Nei workflow automatici il motore prepara i nomi interni. |
| Contamination e CPI dopo DNPcall | Possono utilizzare le stesse tabelle DNPcall per analisi distinte; nessuna delle due richiede il risultato dell'altra. |
| SNPcall sullo stesso BAM | È un'attività indipendente, aggiungibile al workflow con un pannello SNP esplicito. Il suo output non è compatibile con gli schemi DNP di Contamination e CPI. |

Contamination produce stime e filtra i siti secondo il proprio metodo: non
modifica i conteggi DNPcall e non genera tabelle «decontaminate» da inviare a CPI.
L'opzione parallela di DNPcall riguarda i campioni all'interno di quel passaggio;
Contamination e CPI vengono avviati successivamente, uno per volta.

### Scelta del workflow automatico

Aprire **W — Workflow automatici** e selezionare:

| Scelta | Workflow | Passaggi |
| --- | --- | --- |
| 1 | DNPcall → Contamination | Conteggi DNP e stima della contaminazione. |
| 2 | DNPcall → CPI | Conteggi DNP, frazione fetale e indice di paternità per le coppie dichiarate. |
| 3 | DNPcall → Contamination e CPI | Conteggi DNP una sola volta, poi Contamination e CPI sugli stessi conteggi. |
| 4 | SNPcall su più campioni | Un passaggio SNPcall per ogni BAM o pileup, con risultati separati. |
| 0 | Indietro | Ritorno al menu principale senza avviare analisi. |

Le prime tre scelte permettono di aggiungere SNPcall sugli stessi BAM con
un pannello SNP selezionato esplicitamente. Il FASTA è quello del passaggio
DNPcall; ogni BAM distinto viene analizzato una volta da SNPcall, anche
quando compare in più coppie CPI. La scelta iniziale è di non aggiungerlo.

Nel workflow combinato Contamination viene eseguito prima di CPI, ma i suoi
risultati non diventano input CPI. Se Contamination fallisce, il piano si
arresta e CPI non parte. Il completamento tecnico di Contamination, qualunque
sia la stima prodotta, non aggiunge un filtro sui campioni destinati a CPI.

### DNPcall → Contamination

1. Scegliere **DNPcall → Contamination** dal menu dei workflow automatici.
2. Indicare uno o più BAM, oppure una lista di BAM, il FASTA indicizzato e
   il pannello DNP. Scegliere l'esecuzione DNPcall seriale o parallela.
3. Per Contamination, mantenere il pannello DNP oppure selezionare un diverso
   pannello di coordinate coerente con i conteggi da analizzare.
4. Scegliere se includere SNPcall sugli stessi BAM e, in caso affermativo,
   indicare il pannello SNP. Controllare passaggi, file e destinazione nel riepilogo, quindi
   scegliere **Avvia analisi**. È richiesta una sola conferma.
5. Attendere il completamento. Il motore verifica le tabelle prodotte da DNPcall
   e le prepara automaticamente come input di Contamination.

Il menu ripropone le impostazioni DNPcall salvate in **Configura**. La scelta
di un pannello diverso per Contamination vale per quella esecuzione e non
modifica le preferenze salvate.

Non occorre copiare file o indicare percorsi di risultati che ancora non esistono.
I nomi interni identificano i campioni senza dipendere dai nomi originali dei BAM;
`run.json` conserva l'associazione con gli input selezionati.

La stessa esecuzione può essere avviata dalla CLI:

```powershell
.\nipat.cmd --runs-dir "..\risultati" workflow dnp-contamination `
  --bam "..\campioni\campione-a.bam" --bam "..\campioni\campione-b.bam" `
  --reference "..\riferimenti\genome.fa" --panel "..\pannelli\DNP_list.txt" `
  --run-name "dnp-contamination-01"
```

In alternativa a `--bam`, utilizzare `--bamlist "..\campioni\bamlist.txt"`.
`--contamination-panel` seleziona un pannello diverso per il secondo passaggio;
se omesso, viene utilizzato quello di `--panel`. `--parallel` abilita il
parallelismo interno a DNPcall. Su Ubuntu usare `nipat` e percorsi Linux.
`nipat workflow dnp-contamination --help` elenca tutte le opzioni.

### DNPcall → CPI e DNPcall → Contamination e CPI

1. Scegliere il workflow desiderato dal menu **W**.
2. Inserire per ogni coppia un ID univoco, il BAM **cfDNA materno** e il BAM
   **paterno**. Il ruolo materno richiede il campione cfDNA previsto dal metodo,
   non viene dedotto dal nome del file o dai genotipi.
3. Indicare il FASTA indicizzato, il pannello DNPcall e la modalità seriale
   o parallela. Nel workflow combinato, scegliere anche il pannello
   Contamination oppure mantenere quello DNPcall.
4. Selezionare le frequenze di popolazione, la costante d'errore CPI e i siti
   da analizzare: tutti quelli disponibili, un pannello o pannelli etichettati.
5. Scegliere se includere SNPcall sugli stessi BAM e indicare il suo pannello.
   Controllare coppie, ruoli, passaggi e parametri nel riepilogo, poi confermare
   **Avvia analisi**. Il motore elabora i campioni e prepara automaticamente
   le tabelle per CPI, senza copie o rinomine manuali.

Il menu propone le impostazioni DNPcall e CPI salvate in **Configura**,
comprese frequenze, modalità di cutoff e costante d'errore. I prefissi CPI
salvati per l'analisi singola non si applicano ai workflow automatici:
la selezione dei campioni usa i ruoli espliciti. Coppie e nome del run vengono
inseriti per ogni esecuzione e non sono salvati come preferenze.

Gli ID delle coppie iniziano con una lettera e contengono fino a 64 caratteri
ASCII: lettere, cifre, trattino e underscore. Non sono ammessi duplicati o ID
che differiscono soltanto per maiuscole. Una stessa coppia di campioni non può
essere ripetuta con un altro ID. Un campione può appartenere a più coppie nello
stesso ruolo; viene elaborato da DNPcall una sola volta. L'uso dello stesso BAM
in entrambi i ruoli viene rifiutato. Questi controlli verificano la coerenza
formale, non l'identità biologica dei campioni.

Esempio dalla CLI, con un campione paterno condiviso:

```powershell
.\nipat.cmd --runs-dir "..\risultati" workflow dnp-cpi `
  --pair coppia_a "..\campioni\cfdna-a.bam" "..\campioni\padre.bam" `
  --pair coppia_b "..\campioni\cfdna-b.bam" "..\campioni\padre.bam" `
  --reference "..\riferimenti\genome.fa" --panel "..\pannelli\DNP_list.txt" `
  --popfreq "..\pannelli\pop_allFreq.txt" --run-name "dnp-cpi-01"
```

Per includere Contamination, sostituire `dnp-cpi` con
`dnp-contamination-cpi`. Il workflow combinato applica Contamination a tutti
i campioni distinti presenti nelle coppie; `--contamination-panel` può
selezionare un pannello diverso da quello DNPcall.

| Opzione dei workflow con CPI | Significato |
| --- | --- |
| `--pair ID MATERNAL_BAM PATERNAL_BAM` | Coppia e assegnazione esplicita dei due BAM; opzione ripetibile. |
| `--panel PATH` | Pannello usato da DNPcall per produrre i conteggi. |
| `--popfreq PATH` | Frequenze di popolazione richieste da CPI. |
| Nessuna opzione di cutoff | CPI usa tutti i siti disponibili nelle tabelle DNPcall, modalità ALL. |
| `--cpi-panel PATH` | Un pannello di coordinate per CPI, distinto dalla selezione DNPcall. |
| `--cutoff LABEL PATH` | Pannello CPI etichettato; opzione ripetibile. |
| `--cutoff-map "LABEL=PATH,LABEL2=PATH2"` | Mappa di pannelli CPI; alternativa alle due opzioni precedenti. |
| `--err-const NUMERO` | Costante d'errore CPI; valore iniziale `0.0000892303778101497`. |
| `--parallel` | Parallelismo interno DNPcall, senza esecuzione simultanea dei passaggi. |
| `--snp-panel PATH` | Aggiunge SNPcall per ogni BAM distinto usando questo pannello SNP e il FASTA del workflow. |

Le tre forme di cutoff sono alternative. Un pannello CPI seleziona i loci
fra quelli presenti nelle tabelle: non aggiunge conteggi per loci esclusi
dal pannello DNPcall. Il pannello DNPcall non viene applicato implicitamente
come cutoff CPI. I prefissi materno/paterno dei file sono gestiti dal motore;
i ruoli sono quelli dichiarati con `--pair`, non nomi da interpretare.

### SNPcall nei workflow DNPcall

Per aggiungere SNPcall a uno dei tre workflow DNPcall, rispondere alla relativa
scelta nel menu e selezionare un pannello SNP. Dalla CLI aggiungere
`--snp-panel PATH`, per esempio:

```powershell
.\nipat.cmd workflow dnp-contamination `
  --bam "..\campioni\campione-a.bam" --bam "..\campioni\campione-b.bam" `
  --reference "..\riferimenti\genome.fa" --panel "..\pannelli\DNP_list.txt" `
  --snp-panel "..\pannelli\SNPlist.txt"
```

Il pannello DNP non viene riutilizzato implicitamente come pannello SNP.
SNPcall legge gli stessi BAM originali e lo stesso FASTA, preparando un proprio
pileup per ciascun campione. Le sue tabelle rimangono risultati indipendenti;
non sostituiscono gli input di Contamination o CPI. Nei preset i passaggi SNP
seguono le analisi DNP, Contamination e CPI selezionate. Il piano è sequenziale:
se un passaggio fallisce, quelli non ancora avviati vengono bloccati anche
quando non ne dipendono scientificamente.

### SNPcall su più campioni

Scegliere **W → 4 — SNPcall su più campioni** e indicare la modalità:

- **BAM:** selezionare più BAM, oppure un file elenco, un FASTA indicizzato
  e un pannello SNP comune. Il motore prepara un pileup distinto per ogni BAM.
- **Pileup:** selezionare più pileup con QNAME e un pannello SNP comune.
  Non viene richiesto un FASTA e samtools non viene eseguito.

Controllare file, modalità, pannello e destinazione nel riepilogo, quindi
confermare una sola volta. Ogni file riceve un passaggio e una tabella di
risultati propri, anche quando gli originali in cartelle diverse hanno lo
stesso nome. Lo stesso file non può essere elencato più volte. Le modalità
BAM e pileup non possono essere mescolate nello stesso run del menu o comando.
Per il significato delle colonne e i requisiti degli input consultare
[SNPcall](#snpcall).

```powershell
.\nipat.cmd --runs-dir "..\risultati" workflow snp-batch `
  --bam "..\campioni\campione-a.bam" --bam "..\campioni\campione-b.bam" `
  --reference "..\riferimenti\genome.fa" --panel "..\pannelli\SNPlist.txt" `
  --run-name "snp-batch-01"

.\nipat.cmd workflow snp-batch `
  --pileup "..\campioni\campione-a.pileup" --pileup "..\campioni\campione-b.pileup" `
  --panel "..\pannelli\SNPlist.txt" --run-name "snp-pileup-01"
```

`--bamlist PATH` è un'alternativa a `--bam` ripetuto; i percorsi relativi
nell'elenco si risolvono rispetto alla cartella del file elenco. `--reference`
è obbligatorio per BAM e non è ammesso per pileup.
`nipat workflow snp-batch --help` elenca le opzioni; su Ubuntu usare `nipat`
e percorsi Linux.

### Risultati dei workflow automatici

| Percorso nel run automatico | Contenuto |
| --- | --- |
| `work/engine-plan.json` | Piano inviato al motore, con campioni e collegamento fra i passaggi. |
| `output/workflow/workflow-state.json` | Stato complessivo e stato di ciascun passaggio. |
| `output/workflow/steps/dnp/output` | Tabelle, riepiloghi e grafici DNPcall. |
| `output/workflow/steps/contamination/output` | Stime per sito e riepilogo Contamination, quando selezionato. |
| `output/workflow/steps/cpi/output` | Riepilogo CSV e grafici PDF CPI, quando selezionato. |
| `output/workflow/steps/snp_0001/output/SNPcall_output.txt` | Risultato del primo campione SNPcall; i successivi usano `snp_0002`, ecc. |
| `output/workflow/steps/<id>/request.json` | Richiesta concreta del passaggio. |
| `output/workflow/steps/<id>/command.log` | Messaggi R del passaggio; per DNPcall comprende anche i messaggi interni allo script. |
| `output/workflow/steps/snp_0001/preparation.log` | Messaggi samtools del primo campione SNPcall da BAM; il comando è registrato nello stato. |
| `output/workflow/steps/<id>/work` | Pannelli, liste e tabelle preparati per il passaggio. |

Un errore o un'interruzione impediscono l'avvio dei passaggi successivi; risultati
parziali e log rimangono disponibili. Controllare lo stato complessivo e quello
dei singoli passaggi, senza dedurre il successo dalla sola presenza di file.
Non è prevista la ripresa automatica: correggere la causa e avviare un nuovo run.
La simulazione `--dry-run` prepara il piano e i mount, ma non esegue nessun
passaggio e non produce risultati scientifici.

Ogni passaggio SNPcall da BAM conserva `work/snp_regions.bed` e
`work/pileup.txt`; in modalità pileup questi file non vengono rigenerati.
La mappa dei campioni in `run.json` collega i nomi interni agli input originali;
`artifacts.snp-tables` nello stato del passaggio collega la tabella al campione.
Non attribuire le tabelle ai campioni usando soltanto il nome fisso
`SNPcall_output.txt`: considerare il passaggio e la mappa registrata.

Per usare **tabelle DNPcall già disponibili**, avviare invece **3 — Contamination**
e selezionare i file richiesti in `output/individual_outputs` del run DNPcall,
oppure quella sottocartella come input. Nel workflow automatico le tabelle
si trovano in `output/workflow/steps/dnp/output/individual_outputs`.
La radice del run contiene anche file non compatibili con Contamination.

CPI produce `Summary_FetalFraction_CPI.csv` e, nella sottocartella `plots`,
un PDF per coppia e `All_CPIplots.pdf`. Non produce tabelle di dettaglio per sito o per iterazione.
La colonna `Pair` e i nomi dei PDF usano identificatori nativi assegnati dal
motore, per esempio `Mothers0001-Fathers0002_DNPs`. Per risalire all'ID
inserito dall'utente, consultare `cpi-pairs` nel record del passaggio CPI
in `workflow-state.json`; `run.json` collega le coppie ai BAM originali.
La mappa indica anche le righe del riepilogo associate a ciascuna coppia e cutoff.
I CSV e i PDF originali non vengono riscritti.

### Utilizzo di tabelle già disponibili

Per avviare **CPI da un run DNPcall già completato**, scegliere l'analisi singola
**4 — CPI**. Verificare prima la corrispondenza fra
alias DNPcall e campioni originali in `run.json`. Preparare una cartella con
copie delle tabelle selezionate, nominando per esempio `MotherA1.txt` la tabella
cfDNA materna e `FatherA1.txt` quella del presunto padre; indicare poi `A1:A1`
in CPI e fornire le frequenze di popolazione. La scelta dei ruoli non è dedotta
dai genotipi o dagli alias. Conservare la corrispondenza fra copie e run sorgente.

Conservare entrambi i run. Per preparare input modificati utilizzare copie
separate. Un run `succeeded` attesta il completamento tecnico, non la validità
scientifica del risultato; `NA` può essere previsto in assenza di siti informativi.
Una cartella di output parziale non dimostra il completamento del workflow.

## Problemi e segnalazioni

| Problema | Verifica da effettuare |
| --- | --- |
| Setup Windows incompleto | Aprire **Cartella NIPAT Desktop** dal menu Start e conservare `setup.log` e `state.json` nella sottocartella `.runtime\installer`; risolvere l'errore e usare il collegamento di completamento della preparazione. |
| Preparazione Ubuntu incompleta | Conservare `setup.log` e `state.json` nella cartella di stato XDG; verificare servizio e accesso a Docker, quindi ripetere `nipat --setup`. Consultare [Installatore Linux](INSTALLATORE_LINUX.md). |
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

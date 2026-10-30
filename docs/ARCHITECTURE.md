# Architettura di NIPAT

NIPAT Experimental08 è un'applicazione locale con interfaccia a riga di comando e menu
guidato. Il client Python gestisce l'interazione, i percorsi, la configurazione
e i registri delle esecuzioni. Un'immagine Linux autosufficiente contiene R,
samtools, le dipendenze, gli script scientifici e il codice necessario alla
preparazione delle quattro analisi e all'esecuzione dei piani composti.
Non sono presenti un server web o un servizio
di analisi remoto.

## Componenti

| Componente | Responsabilità |
| --- | --- |
| `src/nipat/cli.py` e `wizard.py` | Comandi, menu, raccolta degli input e conferma dell'analisi. |
| `src/nipat/execution/workflows.py` | Selezione e convalida preliminare degli input, richiesta del workflow e creazione del run. |
| `src/nipat/execution/runner.py` | Identificazione del motore, isolamento del container, esecuzione, interruzione e diagnostica. |
| `src/nipat/execution/transport.py` | Accesso al Docker Engine locale su Linux, al motore WSL2 su Windows o alla VM Lima su macOS. |
| `src/nipat/storage.py` | Regole condivise per separare dati e risultati dalle cartelle applicative e dalle destinazioni riservate. |
| `engine/main.py` | Contratto del motore, verifica dei sorgenti scientifici e avvio dei workflow nell'immagine. |
| `src/nipat_scientific/` | Validatori, catalogo e preparazione dei file, condivisi dal client e dal motore. |
| `src/nipat_scientific/plan.py` ed `executor.py` | Contratto dei piani e orchestrazione scientifica eseguita nell'immagine. |
| `scientific/vendor/` | Sorgenti R e risorse dei progetti scientifici integrati. |

Il client e il motore includono la stessa libreria di preparazione, ma non
condividono file montati dall'applicazione. Gli algoritmi scientifici risiedono
negli script R; gli adattatori Python preparano le loro interfacce di file.
La validazione semantica dei dati è nel modulo condiviso: conteggi, frequenze,
loci e alleli sono controllati prima di R. Le normalizzazioni scrivono copie
di lavoro e i casi che richiedono interpretazione scientifica generano avvisi
tracciabili. Analisi singole e piani riutilizzano anche i controlli degli output.
Il comando `execute` avvia una singola analisi; `execute-plan` riceve un piano
con riferimenti espliciti fra campioni, passaggi e risultati. Il client offre
DNPcall → Contamination, DNPcall → CPI e DNPcall → Contamination e CPI
come workflow automatici, con SNPcall facoltativo sugli stessi BAM, e un
workflow SNPcall su più BAM o pileup. Restano disponibili i quattro comandi
singoli. Questo documento descrive la versione sperimentale 0.8.0a1.

### Confini dei workflow automatici

Il client raccoglie e conferma il piano, prepara l'accesso ai file e avvia
un solo container. Il motore incorporato nell'immagine determina l'ordine dei
passaggi, prepara i loro parametri e associa output e input successivi.
Non dipende dalla presenza della CLI o di una GUI dentro il container.
Il contratto usa percorsi Linux assegnati dai mount e può essere utilizzato
su Windows tramite WSL2, su macOS tramite Lima, su Linux nativo e da un futuro servizio.

Il validatore e l'esecutore supportano le quattro analisi e controllano i
collegamenti tipizzati. SNPcall può condividere un BAM con DNPcall, ma non
produce output utilizzabili da Contamination o CPI. Ogni campione SNPcall
ha un passaggio distinto; da BAM, samtools prepara il pileup prima di R.
I passaggi sono sequenziali; il parallelismo interno DNPcall rimane
un'opzione distinta. Un errore interrompe
il piano e blocca tutti i passaggi non ancora avviati. Non è prevista la ripresa.

Interazione, preferenze locali, traduzione dei testi, avvio del runtime,
installazione e aggiornamenti restano responsabilità del client e dei pacchetti
di piattaforma. Gli identificatori del contratto sono indipendenti dalla
lingua dell'interfaccia. Il [contratto dei piani](WORKFLOW_CONTRACT.md)
descrive schema, stati e limiti; il [piano di sviluppo](ROADMAP.md) riporta
gli obiettivi di qualificazione, distribuzione e localizzazione.

## Ambienti di esecuzione

Su Windows, Python e gli script di avvio operano nell'account dell'utente.
Il client esegue `wsl.exe` nella distribuzione dedicata indicata dalla propria
configurazione. Il comando `nipat-engine ensure` avvia il Docker Engine interno
quando necessario. Le operazioni di controllo, analisi e interruzione usano
sempre questo stesso motore; non viene selezionato il contesto Docker dell'utente.
Il trasporto Docker nativo non è ammesso sul client Windows.

Su macOS, il client e la CLI operano nel sistema host. Il trasporto seleziona
una VM Lima dedicata e il suo Docker Engine; la VM espone al container gli input
selezionati e il singolo run. Python e Lima sono incorporati nell'applicazione.
Su Intel il guest e il container sono AMD64. Su Apple Silicon il guest è ARM64
e Rosetta esegue la stessa immagine scientifica Linux AMD64. La verifica del
motore precede le analisi: non è ammesso un ripiego silenzioso su un'immagine
con diversa architettura o contratto.

Su Linux, il client usa Docker Engine e Compose del sistema con un container
`linux/amd64`. La piattaforma Linux di riferimento è Ubuntu 24.04 LTS x86_64.
Il pacchetto `.deb` usa il socket locale `unix:///var/run/docker.sock`
senza modificare il contesto Docker dell’utente. Richiede un daemon di sistema
senza `rootless` o rimappatura `userns`: il container usa UID e GID
dell’utente Linux per i risultati. Il trasporto WSL
usa UID e GID 0 nell'ambiente dedicato; l'accesso ai file Windows dipende dai
permessi dell'account che ha avviato WSL.

## Contratto tra client e motore

Ogni analisi produce una richiesta JSON con versione di schema 1 e una delle
interfacce `dnp-call-v1`, `snp-call-v1`, `contamination-v1` o `cpi-v1`.
La richiesta contiene percorsi interni al container, parametri e destinazioni.
Il motore valida nuovamente i file e prepara gli input prima di avviare R.
I piani usano uno schema distinto, identificato da `schema_version: 1`,
e l'interfaccia di esecuzione `workflow-plan-execution-v1`. Il runner ne
verifica la presenza e il sottoinsieme di analisi supportato prima dell'avvio.
Il contratto completo è descritto nel [riferimento del motore](../engine/README.md).

Prima dell'analisi, il runner risolve l'immagine in un ID immutabile e verifica
la descrizione fornita dall'immagine. Un'interfaccia mancante o incompatibile
interrompe l'esecuzione: non è previsto un ripiego sugli script R presenti
nel filesystem del client. `doctor --runtime` verifica il motore e i contratti
dei quattro workflow senza richiedere una copia locale dei sorgenti R.

Le sonde diagnostiche e le analisi non scaricano dipendenze. Le sonde non
montano dati o cartelle applicative. Ogni analisi usa esclusivamente il proprio
`work/engine-compose.json`, con:

- file di input selezionati montati in sola lettura;
- cartella del singolo run montata in lettura e scrittura;
- filesystem dell'immagine in sola lettura e directory temporanea dedicata;
- rete disabilitata.

Le quote CPU, memoria e processi sono facoltative e registrate con l'esecuzione.
Non modificano i parametri scientifici o il numero di worker deciso da R.

Le altre analisi, la cartella dei dati predefiniti e il progetto non vengono
montati. I bind mount dei singoli file evitano di copiare BAM e FASTA di grandi
dimensioni e non espongono automaticamente le loro cartelle parenti.

## Percorsi e identità dei campioni

Input, applicazione e risultati possono avere radici distinte. Le opzioni globali
`--data-dir` e `--runs-dir` selezionano le cartelle richieste dall'utente.
I percorsi relativi dei comandi sono risolti rispetto alla directory corrente;
le voci di una lista BAM sono relative alla directory della lista.
La voce **Configura** del menu conserva cartelle e valori predefiniti del
workflow fra gli avvii; un'opzione CLI esplicita di percorso ha precedenza
nella sessione guidata.

Il client Windows accetta file su dischi locali fissi; condivisioni UNC, unità
di rete e dispositivi rimovibili non sono supportati dal trasporto WSL.
I percorsi Windows vengono tradotti separatamente dagli argomenti scientifici.
Le chiamate sono costruite come liste di argomenti, senza concatenare comandi
shell a partire dagli input dell'utente.
Il controllo delle destinazioni riservate è comune a menu e CLI diretta:
una cartella risultati non può occupare runtime o cache gestiti dall'installatore.

DNPcall riceve alias numerati come `sample_0001.bam`, compatibili con le chiamate
interne dello script. `run.json` conserva l'associazione con i BAM originali.
Nelle analisi singole, Contamination e CPI mantengono i nomi dei campioni
nelle copie preparate; collisioni di nome, incluse quelle che differiscono
soltanto per maiuscole, vengono rifiutate prima della scrittura.
Nel piano automatico, Contamination usa alias `table_0001`, ecc.; lo stato
del motore conserva l'associazione con il campione e il passaggio produttore,
indipendentemente dall'ordine dei file o dai loro nomi originali.
CPI assegna alias stabili alle tabelle selezionate e riutilizza i genitori
condivisi senza duplicarne l'elaborazione. L'identificatore di ogni coppia,
i riferimenti materno/paterno e il nome nativo prodotto da R rimangono
associati nello stato del piano; i CSV scientifici non vengono riscritti.

## Preferenze del menu guidato

Le preferenze dell'utente sono separate dal backend installato e dai record
delle analisi. Su Windows risiedono in
`%LOCALAPPDATA%\NIPAT-Experimental08\preferences.json`; su macOS in
`~/Library/Application Support/NIPAT-Experimental08/preferences.json`. Comprendono
cartelle dati e risultati, modalità, riferimenti e parametri proposti per i
workflow. Non comprendono campioni, coppie CPI o nomi dei run.
Comprendono anche modalità dei checksum e limiti facoltativi del container.

Il menu carica questi valori e li sottopone alla convalida degli input prima
dell'esecuzione. Le modifiche effettuate per una singola analisi non aggiornano
le preferenze; **Configura** richiede un salvataggio esplicito. I comandi diretti
non leggono questi valori e mantengono il proprio contratto di argomenti,
ambiente e valori iniziali. La configurazione di installazione resta responsabile
della posizione dell'applicazione, della cache e dell'ambiente WSL.

## Esecuzioni, risultati e tracciabilità

Ogni run usa una cartella nuova. `run.json` registra parametri, input, mappatura
dei percorsi, stato, comandi e identità dell'immagine. `runtime.engine` contiene
il manifest R verificato e gli hash del codice di preparazione effettivamente
usato nell'immagine; le informazioni sui sorgenti del client sono distinte.
`execution.log` conserva i messaggi del client e del motore. Nel piano,
`output/workflow/workflow-state.json` registra stato, comandi e riferimenti
agli output di ogni passaggio; i messaggi scientifici sono nei rispettivi
`steps/<id>/command.log`. La struttura dei risultati è illustrata in
[Esecuzioni e risultati](ESECUZIONI.md).

Il motore conserva le richieste e i file preparati nel run; ogni passaggio
di un piano ha una propria sottocartella `work`. SNPcall da BAM conserva
BED e pileup, e ogni modalità SNP conserva il pannello normalizzato;
DNPcall conserva pannello e lista BAM, mentre lo script R elimina
i propri file temporanei BED e pileup al termine. CPI e Contamination conservano
le tabelle preparate e i pannelli normalizzati. Gli originali non vengono modificati.

L'interruzione termina il processo attivo e richiede la rimozione del container
del run. I risultati parziali rimangono disponibili per la diagnosi. Una prova
`--dry-run` registra input, richiesta e comando previsto senza eseguire R e senza
attestare la disponibilità dell'immagine.

La modalità di provenienza `full` calcola i checksum di tutti gli input prima
e dopo il calcolo; `auto` limita gli hash ai file piccoli e dichiara gli input
identificati soltanto dai metadati. La riconciliazione delle esecuzioni incomplete
confronta il record con il container osservato, senza riscrivere la storia o
riprendere il piano. Un arresto esplicito richiede la corrispondenza dell'identità
del container e conserva un rapporto separato.

## Verifica degli aggiornamenti

Il profilo sperimentale `experimental08` esclude la verifica e l'installazione
degli aggiornamenti del canale stabile. Una nuova build viene scaricata
esplicitamente. Il numero di versione maggiore non autorizza il client stabile
a proporre una migrazione al profilo sperimentale; analogamente, l'esperimento
non sostituisce la propria installazione con un pacchetto `desktop`.

I manifest identificano versione, commit, archivi e identità del prodotto.
I checksum degli archivi verificano il contenuto, non sono firme digitali.
I record delle analisi restano associati al client e all'immagine realmente
utilizzati, indipendentemente dalla disponibilità di build successive.

## Installazione Windows

Il profilo `experimental08` identifica applicazione, collegamenti e stato di
configurazione. Il setup gestisce cinque radici configurabili per applicazione,
ambiente WSL, cache, dati e risultati. Le radici devono essere locali, fisse,
scrivibili e indipendenti, senza sovrapposizioni o collegamenti nel percorso.
Le preferenze dell'account e i registri centrali delle destinazioni appartengono
al canale e vengono conservati dopo la disinstallazione.

L'aggiornamento e la riparazione agiscono nella cartella applicativa riconosciuta.
L'inventario identifica i file del pacchetto; prima delle sostituzioni viene
creato un backup selettivo dei componenti differenti, dei metadati di recupero
e del Python generato. File estranei vengono conservati; i componenti obsoleti
si rimuovono soltanto se corrispondono all'hash nell'inventario precedente.
Gli obsoleti modificati vengono conservati in posizione e copiati nel backup.
Non sono previsti una pulizia indiscriminata o un rollback completo automatico.

L'identità della distribuzione WSL dipende dal filesystem Linux e dalla
posizione scelta. Il riutilizzo richiede una registrazione posseduta dal
canale nella destinazione prevista. Una distribuzione posseduta ma rimossa
dall'elenco WSL può essere ricreata soltanto in una destinazione vuota,
conservando la ricevuta precedente nello storico. Cambiare filesystem o posizione
prepara un ambiente affiancato senza copiare o cancellare quello precedente;
cambiare cartelle dati e risultati non trasferisce i file esistenti.

La provenienza del componente WSL è indipendente dal commit dell'interfaccia:
comprende sorgenti del componente, base, versioni dei pacchetti risolti e motore.
Il manifest della release associa applicazione, immagine scientifica e archivio
WSL. Il builder può riutilizzare i byte pubblicati di un archivio WSL soltanto
quando descrittore, contenuto e checksum corrispondono al componente richiesto.
Un cambiamento del solo client non impone quindi un'identità diversa del
componente; una differenza nelle dipendenze risolte impedisce il riutilizzo.

Il launcher usa esclusivamente il proprio manifest e backend verificati.
La configurazione è attivata dopo la riuscita di diagnostica e autotest;
uno stato incompleto impedisce l'avvio dell'analisi. La disinstallazione
conserva sempre dati e risultati; l'eventuale rimozione aggiuntiva riguarda
solo distribuzioni WSL possedute e archivi verificati della cache, nelle
destinazioni attuali e precedenti registrate. Identità, verifiche e recupero
sono descritti nel [riferimento dell'installatore](INSTALLATORE_WINDOWS.md).

La manutenzione Windows usa un inventario verificato di ambienti, cache e
registri di backup. Il client può soltanto selezionare elementi dichiarati
rimovibili o richiedere la ripresa dell'installazione corrente. Il worker
PowerShell attende l'uscita del client, acquisisce il blocco esclusivo e
ripete le verifiche prima di modificare componenti. L'esito è un rapporto
separato; i dati dell'utente restano fuori dalla pulizia. I backup selettivi
non realizzano un rollback completo della versione applicativa.

## Installazione macOS

I due pacchetti `.pkg` contengono il client, Python portabile e Lima nativi
per l'architettura host, insieme allo stesso archivio scientifico AMD64 usato
su Windows. L'applicazione è `/Applications/NIPAT Experimental08.app`.
La configurazione per utente vive in
`~/Library/Application Support/NIPAT-Experimental08`; `LIMA_HOME` è
`~/.nipat08/lima`, un percorso breve dedicato alla VM.
L'installer non riutilizza automaticamente le VM Lima dell'utente.

Il primo avvio prepara il guest e il motore e verifica l'archivio incorporato
prima di abilitarne l'utilizzo. Il provisioning può richiedere la rete; le
analisi si svolgono in container senza rete dopo la preparazione. La CLI
viene aperta nel Terminale dal launcher dell'applicazione. Dettagli e limiti
sono nella [guida macOS](INSTALLATORE_MACOS.md).

## Utilizzo Linux

La 0.8 conserva il trasporto Docker Engine locale e i controlli scientifici
Ubuntu, ma non produce un nuovo pacchetto `.deb`. La distribuzione Ubuntu
stabile mantiene la propria identità e il proprio ciclo di pubblicazione.
Il checkout sperimentale è utilizzabile da sorgenti in un ambiente separato,
secondo la [guida di distribuzione](DISTRIBUZIONE.md#ubuntu-installazione-da-sorgenti).
Non sono richieste modifiche agli script R per selezionare il trasporto.

## Limiti tecnici

DNPcall invoca samtools internamente, ne sopprime lo stderr e non controlla
esplicitamente il codice di uscita. Il runner conserva lo stato restituito da R,
ma non può attribuirgli una verifica completa di ogni sottoprocesso interno.
Il completamento di un processo deve quindi essere distinto dalla verifica
della completezza e correttezza scientifica dei risultati.

Gli hash identificano i file e rilevano alterazioni rispetto al manifest;
non costituiscono una validazione scientifica. Le prove del motore, le prove
dell'installatore e la validazione di dominio sono evidenze separate.

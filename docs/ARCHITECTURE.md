# Architettura di NIPAT

NIPAT Desktop è un'applicazione locale con interfaccia a riga di comando e menu
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
| `src/nipat/execution/transport.py` | Accesso al Docker Engine nativo su Linux o al motore gestito nella distribuzione WSL2 su Windows. |
| `engine/main.py` | Contratto del motore, verifica dei sorgenti scientifici e avvio dei workflow nell'immagine. |
| `src/nipat_scientific/` | Validatori, catalogo e preparazione dei file, condivisi dal client e dal motore. |
| `src/nipat_scientific/plan.py` ed `executor.py` | Contratto dei piani e orchestrazione scientifica eseguita nell'immagine. |
| `scientific/vendor/` | Sorgenti R e risorse dei progetti scientifici integrati. |

Il client e il motore includono la stessa libreria di preparazione, ma non
condividono file montati dall'applicazione. Gli algoritmi scientifici risiedono
negli script R; gli adattatori Python preparano le loro interfacce di file.
Il comando `execute` avvia una singola analisi; `execute-plan` riceve un piano
con riferimenti espliciti fra campioni, passaggi e risultati. Il client offre
DNPcall → Contamination, DNPcall → CPI e DNPcall → Contamination e CPI
come workflow automatici, con SNPcall facoltativo sugli stessi BAM, e un
workflow SNPcall su più BAM o pileup. Restano disponibili i quattro comandi
singoli. La versione descritta è la 0.7.0a1 di sviluppo; la release ufficiale
rimane la 0.6.0.

### Confini dei workflow automatici

Il client raccoglie e conferma il piano, prepara l'accesso ai file e avvia
un solo container. Il motore incorporato nell'immagine determina l'ordine dei
passaggi, prepara i loro parametri e associa output e input successivi.
Non dipende dalla presenza della CLI o di una GUI dentro il container.
Il contratto usa percorsi Linux assegnati dai mount e può essere utilizzato
su Windows tramite WSL2, su Linux nativo e da un futuro servizio.

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
`%LOCALAPPDATA%\NIPAT-Desktop\preferences.json`; su Linux in
`${XDG_CONFIG_HOME:-~/.config}/nipat-desktop/preferences.json`. Comprendono
cartelle dati e risultati, modalità, riferimenti e parametri proposti per i
workflow. Non comprendono campioni, coppie CPI o nomi dei run.

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
BED e pileup; DNPcall conserva pannello e lista BAM, mentre lo script R elimina
i propri file temporanei BED e pileup al termine. CPI e Contamination conservano
le tabelle preparate e i pannelli normalizzati. Gli originali non vengono modificati.

L'interruzione termina il processo attivo e richiede la rimozione del container
del run. I risultati parziali rimangono disponibili per la diagnosi. Una prova
`--dry-run` registra input, richiesta e comando previsto senza eseguire R e senza
attestare la disponibilità dell'immagine.

## Verifica degli aggiornamenti

Il client consulta le release pubblicate del repository ufficiale e il relativo
`update-manifest.json`. Verifica prodotto, versione, canale, piattaforma,
commit del tag e URL degli asset previsti. Il manifest associa i due installatori
completi a dimensione e SHA-256; è generato dopo l'accettazione della coppia
Windows/Ubuntu. Il download viene verificato prima del passaggio all'installatore.
La fiducia deriva da HTTPS e dal controllo del repository ufficiale; il manifest
non è una firma digitale del pacchetto.

Le preferenze distinguono `testing`, che comprende pre-release e stabili,
da `stable`, limitato alle release stabili. La verifica facoltativa all'avvio
è disattivata inizialmente e produce soltanto un avviso. La sessione guidata
richiede conferme separate per download e installazione e viene chiusa prima
della sostituzione dei componenti. Non vengono sostituiti client o motore
durante un'analisi; i controlli dell'installazione regolano la riapertura.
Un errore di rete non modifica il backend pronto o i record esistenti.

## Installazione Windows

Il profilo `desktop` identifica applicazione, collegamenti e stato di
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

Il launcher usa esclusivamente il proprio manifest e backend verificati.
La configurazione è attivata dopo la riuscita di diagnostica e autotest;
uno stato incompleto impedisce l'avvio dell'analisi. La disinstallazione
conserva sempre dati e risultati; l'eventuale rimozione aggiuntiva riguarda
solo distribuzioni WSL possedute e archivi verificati della cache, nelle
destinazioni attuali e precedenti registrate. Identità, verifiche e recupero
sono descritti nel [riferimento dell'installatore](INSTALLATORE_WINDOWS.md).

## Installazione Ubuntu

Il pacchetto `nipat-desktop` installa i file applicativi in
`/opt/nipat-desktop`. Il launcher usa Python 3.12 del sistema in modalità
isolata e seleziona l’applicazione installata, il backend locale e le cartelle
XDG dell’utente. Le variabili ereditate non possono sostituire il backend,
il progetto o l’immagine verificata; le opzioni CLI restano disponibili
per selezionare dati e risultati.

La preparazione è eseguita dall’utente normale, sotto un lock esclusivo.
Verifica dimensione e SHA-256 dell’archivio scientifico incluso, importa
l’immagine e verifica l’identificativo restituito dal daemon locale.
La configurazione pronta viene scritta atomicamente dopo diagnostica e
autotest riusciti. Il record collega commit, manifest, archivio e ID locale;
un aggiornamento o un’immagine rimossa richiedono una nuova preparazione.

Lo stesso archivio scientifico viene incorporato nei pacchetti Windows
e Ubuntu senza nuove esportazioni. L’ID locale dell’immagine può dipendere
dal motore Docker; l’identità condivisa di distribuzione è il checksum
dell’archivio. Il pacchetto non gestisce il daemon di sistema, i gruppi utenti
o la cancellazione delle immagini. Requisiti e ciclo di vita sono descritti
nell’[installatore Linux](INSTALLATORE_LINUX.md).

## Limiti tecnici

DNPcall invoca samtools internamente, ne sopprime lo stderr e non controlla
esplicitamente il codice di uscita. Il runner conserva lo stato restituito da R,
ma non può attribuirgli una verifica completa di ogni sottoprocesso interno.
Il completamento di un processo deve quindi essere distinto dalla verifica
della completezza e correttezza scientifica dei risultati.

Gli hash identificano i file e rilevano alterazioni rispetto al manifest;
non costituiscono una validazione scientifica. Le prove del motore, le prove
dell'installatore e la validazione di dominio sono evidenze separate.

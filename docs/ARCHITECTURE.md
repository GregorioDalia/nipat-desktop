# Architettura di NIPAT

NIPAT 0.5 è un'applicazione locale con interfaccia a riga di comando e menu
guidato. Il client Python gestisce l'interazione, i percorsi, la configurazione
e i registri delle esecuzioni. Un'immagine Linux autosufficiente contiene R,
samtools, le dipendenze, gli script scientifici e il codice necessario alla
preparazione dei quattro workflow. Non sono presenti un server web o un servizio
di analisi remoto.

## Componenti

| Componente | Responsabilità |
| --- | --- |
| `src/nipat/cli.py` e `wizard.py` | Comandi, menu, raccolta degli input e conferma dell'analisi. |
| `src/nipat/execution/workflows.py` | Selezione e convalida preliminare degli input, richiesta del workflow e creazione del run. |
| `src/nipat/execution/runner.py` | Identificazione del motore, isolamento del container, esecuzione, interruzione e diagnostica. |
| `src/nipat/execution/transport.py` | Accesso al Docker Engine nativo su Linux o al motore gestito nella distribuzione WSL2 su Windows. |
| `engine/main.py` | Contratto del motore, verifica dei sorgenti scientifici e avvio dei workflow nell'immagine. |
| `src/nipat_scientific/` | Validatori e preparazione dei file, condivisi dal client e dal motore. |
| `scientific/vendor/` | Sorgenti R e risorse dei progetti scientifici integrati. |

Il client e il motore includono la stessa libreria di preparazione, ma non
condividono file montati dall'applicazione. Gli algoritmi scientifici risiedono
negli script R; gli adattatori Python preparano le loro interfacce di file.

## Ambienti di esecuzione

Su Windows, Python e il launcher `NIPAT.exe` operano nell'account dell'utente.
Il client esegue `wsl.exe` nella distribuzione dedicata indicata dalla propria
configurazione. Il comando `nipat-engine ensure` avvia il Docker Engine interno
quando necessario. Le operazioni di controllo, analisi e interruzione usano
sempre questo stesso motore; non viene selezionato il contesto Docker dell'utente.
Il trasporto Docker nativo non è ammesso sul client Windows.

Su Linux, il client usa Docker Engine e Compose del sistema con un container
`linux/amd64`. La piattaforma Linux di riferimento è Ubuntu 24.04 LTS x86_64.
L'esecuzione da sorgenti è disponibile; l'installer Linux non è ancora disponibile.
Il container usa UID e GID dell'utente Linux per i risultati. Il trasporto WSL
usa UID e GID 0 nell'ambiente dedicato; l'accesso ai file Windows dipende dai
permessi dell'account che ha avviato WSL.

## Contratto tra client e motore

Ogni analisi produce una richiesta JSON con versione di schema 1 e una delle
interfacce `dnp-call-v1`, `snp-call-v1`, `contamination-v1` o `cpi-v1`.
La richiesta contiene percorsi interni al container, parametri e destinazioni.
Il motore valida nuovamente i file e prepara gli input prima di avviare R.
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
L'opzione 5 del menu cambia la cartella dei risultati per la sessione corrente.

Il client Windows accetta file su dischi locali fissi; condivisioni UNC, unità
di rete e dispositivi rimovibili non sono supportati dal trasporto WSL.
I percorsi Windows vengono tradotti separatamente dagli argomenti scientifici.
Le chiamate sono costruite come liste di argomenti, senza concatenare comandi
shell a partire dagli input dell'utente.

DNPcall riceve alias numerati come `sample_0001.bam`, compatibili con le chiamate
interne dello script. `run.json` conserva l'associazione con i BAM originali.
Contamination e CPI mantengono i nomi dei campioni nelle copie preparate;
collisioni di nome, incluse quelle che differiscono soltanto per maiuscole,
vengono rifiutate prima della scrittura.

## Esecuzioni, risultati e tracciabilità

Ogni run usa una cartella nuova. `run.json` registra parametri, input, mappatura
dei percorsi, stato, comandi e identità dell'immagine. `runtime.engine` contiene
il manifest R verificato e gli hash del codice di preparazione effettivamente
usato nell'immagine; le informazioni sui sorgenti del client sono distinte.
`execution.log` conserva l'output dei processi. La struttura dei risultati è
illustrata in [Esecuzioni e risultati](ESECUZIONI.md).

Il motore conserva richieste e file preparati in `work`. SNPcall da BAM conserva
BED e pileup; DNPcall conserva pannello e lista BAM, mentre lo script R elimina
i propri file temporanei BED e pileup al termine. CPI e Contamination conservano
le tabelle preparate e i pannelli normalizzati. Gli originali non vengono modificati.

L'interruzione termina il processo attivo e richiede la rimozione del container
del run. I risultati parziali rimangono disponibili per la diagnosi. Una prova
`--dry-run` registra input, richiesta e comando previsto senza eseguire R e senza
attestare la disponibilità dell'immagine.

## Installazione Windows

Il profilo `preview-0.5` identifica applicazione, cartelle, distribuzione WSL,
collegamenti e stato di configurazione. Il launcher usa esclusivamente il
proprio manifest e backend verificati. La configurazione è attivata dopo
la riuscita di diagnostica e autotest; uno stato incompleto impedisce l'avvio
dell'analisi. Identità, aggiornamento e recupero sono descritti nel
[riferimento dell'installatore](INSTALLATORE_WINDOWS.md).

## Limiti tecnici

DNPcall invoca samtools internamente, ne sopprime lo stderr e non controlla
esplicitamente il codice di uscita. Il runner conserva lo stato restituito da R,
ma non può attribuirgli una verifica completa di ogni sottoprocesso interno.
Il completamento di un processo deve quindi essere distinto dalla verifica
della completezza e correttezza scientifica dei risultati.

Gli hash identificano i file e rilevano alterazioni rispetto al manifest;
non costituiscono una validazione scientifica. Le prove del motore, le prove
dell'installatore e la validazione di dominio sono evidenze separate.

# NIPAT Desktop 0.7.0a1 — candidata di verifica

NIPAT Desktop 0.7.0a1 introduce workflow automatici e un catalogo scientifico
consultabile dal menu. L'interfaccia rimane testuale: questa versione non
include una GUI grafica. Gli algoritmi dei quattro script R e i relativi
adattatori scientifici restano invariati.

Queste note descrivono la candidata destinata alla verifica degli installatori.
Una build GitHub Actions completata non equivale alla pubblicazione di una
release né alla validazione di dominio. La pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases) identifica
le versioni effettivamente pubblicate; la costruzione della candidata non
sostituisce la release ufficiale 0.6.0.

## Funzionalità

La voce **W — Workflow automatici** offre:

| Selezione | Comportamento |
| --- | --- |
| **1 — DNPcall → Contamination** | Produce le tabelle DNP e le passa automaticamente a Contamination. |
| **2 — DNPcall → CPI** | Elabora i BAM delle coppie dichiarate e passa le tabelle a CPI. |
| **3 — DNPcall → Contamination e CPI** | Esegue le due analisi sulle tabelle originali DNP, senza usare la stima di contaminazione per filtrare CPI. |
| **4 — SNPcall su più campioni** | Esegue SNPcall separatamente per ciascun BAM o pileup selezionato, nello stesso run. |

I primi tre workflow possono includere SNPcall sugli stessi BAM, con un
pannello SNP scelto esplicitamente. SNPcall è indipendente: i suoi risultati
non diventano input di Contamination o CPI. Un solo riepilogo e una sola
conferma avviano i passaggi selezionati. L'esecuzione è sequenziale; un errore
o un'interruzione impediscono l'avvio dei passaggi rimanenti. Non è prevista
la ripresa automatica di un run interrotto.

Per CPI si assegnano esplicitamente un ID a ogni coppia, il BAM del cfDNA
materno e quello del campione paterno. Un campione condiviso tra coppie viene
elaborato una sola volta e conserva il ruolo dichiarato. Le modalità ALL,
pannello singolo e pannelli con etichetta, insieme alla costante di errore,
restano selezionabili. I comandi delle quattro analisi singole rimangono
disponibili.

**Guida e informazioni → Catalogo scientifico** e `nipat parameters`
descrivono le opzioni pubbliche degli script, le regole interne e la
preparazione degli input. Il catalogo è disponibile in italiano e inglese;
la traduzione completa dell'applicazione e della documentazione è ancora
pianificata. La consultazione del catalogo non modifica i parametri e non
avvia analisi.

La navigazione permette il ritorno diretto al menu principale con
`:annulla` nei campi e nei menu testuali, oppure con Ctrl+C anche durante
un'analisi. Il calcolo viene interrotto conservando log e risultati già
prodotti; i passaggi successivi di un workflow automatico non vengono
avviati. Le modifiche di configurazione non ancora salvate vengono scartate,
mentre quelle già salvate restano attive. Esc e `:indietro` mantengono la
navigazione al passaggio precedente; **0 — Esci** chiude NIPAT dal menu
principale.

## Pacchetti e requisiti

| Piattaforma | File da eseguire | Requisiti principali |
| --- | --- | --- |
| Windows 11 x64 | `NIPAT-Setup.exe` | Virtualizzazione disponibile e WSL2; l'attivazione può richiedere autorizzazione amministrativa, Internet e riavvio. |
| Ubuntu 24.04 LTS x86_64 | `nipat-desktop_0.7.0~a1_amd64.deb` | Python 3.12, Docker Engine locale e Compose v2; APT installa le dipendenze mancanti, mentre l'accesso dell'account a Docker richiede autorizzazione amministrativa distinta. |

Entrambi i pacchetti incorporano lo stesso archivio scientifico, contenente
R, samtools, dipendenze, preparazione degli input ed esecuzione dei piani.
Windows include anche Python portabile e l'ambiente WSL dedicato; non
richiede Docker Desktop o strumenti scientifici installati separatamente.
La normale installazione usa soltanto l'EXE o il `.deb` della piattaforma.

Per una build di revisione, aprire il workflow
[Installers (review build)](https://github.com/GregorioDalia/nipat-desktop/actions/workflows/windows-installer.yml)
riuscito sul commit scelto e controllare l'esito `installer-required`.
Per Windows, scaricare l'artefatto **NIPAT-Setup.exe**, disponibile anche dal
riepilogo della build: il download è direttamente eseguibile. Per Ubuntu,
scaricare direttamente **nipat-desktop_0.7.0~a1_amd64.deb** dal medesimo
riepilogo. Entrambi i download contengono il solo installatore, senza ZIP
da estrarre. Gli archivi runtime separati non servono all'installazione
ordinaria. Conservare il manifest, i checksum e l'ID della stessa build per
identificare la prova. Gli artefatti **nipat-windows-setup** e
**nipat-linux-setup** conservano le evidenze e copie identiche dei pacchetti;
non occorre scaricarli per installare l'applicazione.

Le build Actions non sono proposte da **Verifica aggiornamenti**. Tale voce
considera soltanto release pubblicate e approvate con il relativo manifest.
Le istruzioni complete di installazione sono nelle guide
[Windows](INSTALLATORE_WINDOWS.md) e [Ubuntu](INSTALLATORE_LINUX.md).

La candidata utilizza la stessa identità **NIPAT Desktop** della 0.6:
sul computer scelto il setup aggiorna l'applicazione esistente, non crea
una seconda edizione affiancata. Chiudere le sessioni NIPAT prima di
installare e verificare le destinazioni riproposte dal setup. Dati,
risultati e preferenze vengono conservati; per il collaudo scegliere una
nuova cartella risultati. La conservazione dei file non costituisce un
rollback automatico della versione applicativa.

## Prima prova del pacchetto

Registrare versione, commit e checksum del pacchetto effettivamente scaricato,
sistema operativo e stato iniziale di WSL o Docker. Conservare gli esiti
nella [scheda di validazione](VALIDAZIONE.md).

1. Installare il pacchetto e completare la preparazione dell'ambiente.
   Su Windows attendere `NIPAT: ready`; su Ubuntu avviare NIPAT dal proprio
   account e attendere preparazione, diagnostica e autotest.
2. Aprire **NIPAT Desktop** dal collegamento, controllare la versione e
   selezionare una cartella risultati dedicata in **Configura**.
3. Eseguire **8 — Verifica ambiente** e consultare il catalogo scientifico.
   Conservare separatamente l'esito degli autotest e quello della diagnostica.
4. In **W**, scegliere una composizione per cui siano disponibili input
   appropriati e risultati di riferimento. Per il piano completo selezionare
   **3**, dichiarare le coppie e aggiungere SNPcall con un pannello SNP
   esplicito. Non dedurre il ruolo biologico dal nome del file.
5. Controllare il riepilogo, avviare una sola volta e verificare stati,
   associazioni dei campioni, conteggi e risultati di ogni passaggio.
   Confrontare anche le analisi separate sugli stessi input e con gli stessi
   parametri; un riferimento numerico indipendente rimane necessario per
   valutare l'accuratezza scientifica.
6. Provare **W → 4** con più BAM; riutilizzare poi i pileup conservati,
   selezionando la modalità pileup, e confrontare i risultati per campione.
7. Riaprire NIPAT e verificare preferenze e accessibilità dei risultati.
   Registrare eventuali difficoltà, errori o avvisi con il testo completo.

Questa è una sequenza iniziale di collaudo, non la dichiarazione che tutti
gli scenari siano già superati. La disponibilità di dati materni e paterni,
pannelli e frequenze di popolazione appropriati determina quali prove CPI
siano scientificamente valutabili. Quando mancano, registrare il caso come
non eseguito senza sostituirlo con un'associazione arbitraria di campioni.

## Risultati e tracciabilità

Ogni run conserva `run.json`, `execution.log` e il piano inviato al motore.
In `output/workflow`, `workflow-state.json` registra lo stato complessivo e
quello delle singole attività. Le sottocartelle `steps/dnp`,
`steps/contamination`, `steps/cpi` e `steps/snp_0001`, `steps/snp_0002`, ecc.
contengono risultati e log separati per i passaggi effettivamente selezionati.

I record conservano gli input, i parametri, l'identità del motore e le
associazioni fra campioni, coppie e risultati. SNPcall da BAM mantiene BED,
pileup e log della preparazione samtools; la modalità pileup non li rigenera.
Un run fallito conserva le evidenze già prodotte e non viene riutilizzato:
la ripetizione richiede una nuova destinazione. I dettagli sono in
[Esecuzioni e registri](ESECUZIONI.md).

## Ambito delle verifiche

Le regressioni del motore coprono i workflow automatici, risultati numerici
noti, parità con le analisi separate, identità dei campioni e gestione
degli errori. Le prove dei pacchetti aggiungono verifiche riferite agli
artefatti costruiti. Nessuno di questi livelli attesta da solo l'installazione
su ogni PC o la validità scientifica per qualsiasi campione.

| Prova automatica del pacchetto | Ambito | Limite |
| --- | --- | --- |
| Windows, `windows-client-check.json` | Client del pacchetto con Python incorporato, catalogo, menu e piani in simulazione, da una cartella con spazi e caratteri Unicode. | Non esegue Inno Setup, WSL o calcolo scientifico sul runner Windows. |
| Ubuntu, `linux-installation-check.json` | Pacchetto installato, analisi singole e piano completo su BAM sintetici da un account non root; conservazione di input, risultati e preferenze. | Usa un runner già configurato; non prova un desktop pulito né l'aggiornamento da 0.6 a 0.7. |

Per ciascuna build consultare gli esiti e i registri Actions effettivi.
Le prove sul computer destinatario e la valutazione delle esperte di dominio
rimangono evidenze distinte, da riferire alla versione e ai dati utilizzati.
La [procedura di distribuzione](../.github/RELEASE.md) mantiene separate
costruzione, accettazione e pubblicazione.

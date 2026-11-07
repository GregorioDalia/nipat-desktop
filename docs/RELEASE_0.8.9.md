# NIPAT Desktop 0.8.9

NIPAT Desktop 0.8.9 è la release ufficiale per Windows, macOS e Ubuntu.
Riduce allocazioni e calcoli ripetuti nei quattro programmi R e rende più
chiara la configurazione delle risorse. Mantiene l'impianto dell'applicazione,
i parametri scientifici e i formati dei risultati. La diagnostica delle
prestazioni rimane facoltativa e disattivata per impostazione predefinita.

## Modifiche

- **DNPcall:** preparazione diretta delle osservazioni del pileup, conversione
  delle qualità tramite tabella, riuso delle estrazioni ripetute e degli indici
  per locus, riduzione dei raggruppamenti e dei conteggi duplicati.
- **SNPcall:** lettura delle colonne necessarie e aggregazione delle caratteristiche
  delle letture, conservando il raggruppamento globale per QNAME e il trattamento
  compatibile delle osservazioni non standard.
- **CPI:** riuso dei campioni condivisi fra coppie consecutive e dei risultati
  fra soglie che selezionano gli stessi loci, con ricostruzione di tutte le righe
  e conservazione dell'ordine dei prodotti.
- **Contamination:** raccolta delle righe e assemblaggio finale unico dei riepiloghi.
- **Risorse:** distinzione fra configurazione salvata, risorse effettive,
  suggerimenti e nuovi valori. **Invio conserva il valore corrente**, anche
  quando automatico; `:suggerito` applica esplicitamente il suggerimento.

Le formule, le soglie e i filtri non vengono modificati per ridurre il lavoro.
DNPcall continua a preparare il pileup tramite scansione sequenziale del BAM
con `samtools mpileup -l`. Il parallelismo DNPcall riguarda i campioni; non
suddivide un singolo BAM tra worker. Il
[contratto di equivalenza](OPTIMIZATION_0.8.9.md) descrive gli interventi e i
criteri di confronto con la 0.8.5.

## Download e aggiornamento

Scaricare un solo installer dalla
[release 0.8.9](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.9):

| Sistema | Download |
| --- | --- |
| Windows 10 22H2 x64 / Windows 11 x64 | [NIPAT-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.9/NIPAT-Setup.exe) |
| macOS 14 o successivo, Apple Silicon | [NIPAT-0.8.9-macos-arm64.pkg](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.9/NIPAT-0.8.9-macos-arm64.pkg) |
| macOS 14 o successivo, Intel | [NIPAT-0.8.9-macos-x86_64.pkg](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.9/NIPAT-0.8.9-macos-x86_64.pkg) |
| Ubuntu 24.04 LTS x86_64 | [nipat-desktop_0.8.9_amd64.deb](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.9/nipat-desktop_0.8.9_amd64.deb) |

Chi usa la 0.8.5 può scegliere **9 — Verifica aggiornamenti** e seguire la
procedura del proprio sistema oppure scaricare il pacchetto manualmente.
L'installer aggiorna NIPAT Desktop; i risultati precedenti conservano i
propri metadati e non vengono ricalcolati. Chiudere le analisi prima di aggiornare.
Le guide [Windows](INSTALLATORE_WINDOWS.md), [macOS](INSTALLATORE_MACOS.md) e
[Ubuntu](INSTALLATORE_LINUX.md) descrivono requisiti, aggiornamento e rimozione.

Windows usa WSL2 con Docker Engine gestito da NIPAT; macOS usa Lima e, su
Apple Silicon, Rosetta per il container AMD64; Ubuntu usa Docker Engine locale.
Docker Desktop non è un prerequisito. I pacchetti non hanno una firma NIPAT
riconosciuta dai sistemi; macOS non dispone di notarizzazione Apple.
Le guide descrivono le procedure applicabili senza disattivare le protezioni.

## Verifiche e limiti

I confronti differenziali eseguono il riferimento R congelato della 0.8.5 e
il candidato nello stesso runtime. Controllano i byte delle tabelle,
le quantità intermedie non arrotondate e il rendering dei PDF nei casi coperti.
I test mirati verificano inoltre le trasformazioni DNPcall e SNPcall e il
calcolo CPI. L'equivalenza osservata riguarda i casi eseguiti e non dimostra
validità scientifica per ogni input possibile.

La CI e la build degli installer verificano client, contratti, regressioni
scientifiche, integrità dell'immagine e corrispondenza con i pacchetti.
I rapporti della release identificano commit, immagine, build, installer e
risultati dei controlli. Il record di accettazione della 0.8.9 è distinto da
quello della 0.8.5 e include i sorgenti R revisionati e le relative evidenze.

Le verifiche automatiche dei client e dei pacchetti Mac non costituiscono
una prova completa con VM Lima/Rosetta: la qualificazione dedicata sulle due
architetture non è stata eseguita. Le prove su dispositivi finali e la
validazione di dominio restano evidenze separate dai test automatici.

I microbenchmark misurano singole operazioni su dati sintetici, escludendo
alcuni costi del workflow. Non stabiliscono il guadagno su un BAM reale o
il picco di memoria del container. La [guida alle prestazioni](PERFORMANCE.md)
distingue durata complessiva, tempo R, memoria del container e rilevazioni
parziali del processo R. Le prestazioni dipendono da dati, hardware e ambiente.

## Versionamento

I candidati precedenti alla pubblicazione sono identificati da commit,
build e checksum. La release pubblicata rimane immutabile; ogni successivo
pacchetto ufficiale ha una versione superiore. L'aggiornatore confronta il
numero di versione, non il commit: una build diversa denominata ancora
0.8.9 non viene proposta a chi usa già la 0.8.9.

La 0.8.10 sarà un unico prototipo integrato per le prove di sviluppo e non
sostituirà automaticamente questa release nel canale stabile.

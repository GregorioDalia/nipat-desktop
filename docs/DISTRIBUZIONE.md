# Distribuzione e requisiti

NIPAT Desktop distribuisce la stessa CLI e lo stesso motore scientifico
su Windows, macOS e Ubuntu. Ogni pacchetto contiene l'immagine scientifica:
non occorre scaricarla separatamente o importarla manualmente.

I [download per piattaforma](../README.md#download) sono disponibili nel README.
La pagina [Releases](https://github.com/GregorioDalia/nipat-desktop/releases)
conserva tutte le versioni. La 0.8.2 è il canale stabile; la prerelease 0.8.5
aggiunge la [diagnostica facoltativa delle prestazioni](PERFORMANCE.md).
Scegliere l'installatore nella sezione Assets. Gli archivi **Source code**
non sono installatori. Gli artefatti GitHub Actions sono build per revisione,
identificate da commit e checksum, e non sostituiscono una release pubblicata.

## Piattaforme

| Sistema | Ambiente scientifico | Pacchetto |
| --- | --- | --- |
| Windows 10 22H2 x64, build 19045, o Windows 11 x64 | WSL2 con Docker Engine gestito da NIPAT | `NIPAT-Setup.exe` |
| macOS 14 o successivo, Intel | VM Lima AMD64 con Docker Engine | `.pkg` x86_64 |
| macOS 14 o successivo, Apple Silicon | VM Lima ARM64, Rosetta e Docker Engine | `.pkg` arm64 |
| Ubuntu 24.04 LTS x86_64 | Docker Engine locale | `nipat-desktop_VERSIONE_amd64.deb` |

Tutti i pacchetti incorporano lo stesso archivio scientifico Linux AMD64.
L'immagine contiene gli script R, samtools, dipendenze, validazione degli
input e orchestrazione. Ogni analisi usa un container con rete disabilitata,
input selezionati in sola lettura e cartella del run scrivibile.

## Pacchetto Windows

Avviare `NIPAT-Setup.exe` dal proprio account. Il setup include Python,
filesystem WSL e archivio scientifico, verifica il sistema e prepara i
componenti WSL mancanti. Non occorre installare Docker Desktop, R o samtools.
L'attivazione o l'aggiornamento di WSL può richiedere Internet, autorizzazione
amministrativa e riavvio. Windows ARM, Server e 32 bit non sono supportati.

L'installatore permette di scegliere cartelle di applicazione, ambiente WSL,
cache, dati e risultati. Conserva i percorsi delle installazioni NIPAT Desktop
riconosciute e non svuota cartelle estranee. Attendere **NIPAT: ready**, poi
avviare **NIPAT Desktop** dal menu Start o dal collegamento sul desktop.
La [guida Windows](INSTALLATORE_WINDOWS.md) descrive aggiornamento, riparazione,
rimozione e gestione degli avvisi di sicurezza.

## Pacchetto macOS

Scegliere il `.pkg` della propria architettura, completare l'installazione e
aprire **NIPAT Desktop** da Applicazioni. Il menu CLI si apre nel Terminale.
Python e Lima sono inclusi; il primo avvio prepara la VM e richiede Internet.
Homebrew e Docker Desktop non sono prerequisiti. Su Apple Silicon l'immagine
scientifica AMD64 viene eseguita tramite Rosetta nel guest ARM64.

I pacchetti non hanno firma Developer ID o notarizzazione Apple. Per il
messaggio di software non verificato, la [guida macOS](INSTALLATORE_MACOS.md)
spiega l'autorizzazione specifica da Privacy e sicurezza. Le policy di un
Mac gestito possono richiedere l'intervento dell'amministratore.

L'applicazione è in `/Applications/NIPAT Desktop.app`; dati e risultati sono
nell'area utente `~/Library/Application Support/NIPAT-Desktop`.
Il runtime Lima dedicato non adotta le altre VM dell'utente.
Le installazioni sperimentali hanno identità separata e non vengono rimosse.

## Pacchetto Ubuntu

Installare il `.deb` con il gestore pacchetti oppure, nella cartella del download:

```bash
sudo apt install ./nipat-desktop_0.8.2_amd64.deb
```

APT installa le dipendenze mancanti dai repository configurati, inclusi Python,
Docker Engine e Compose. L'accesso dell'utente al daemon deve essere autorizzato
secondo la configurazione del sistema. Il pacchetto non concede automaticamente
questi privilegi. Consultare la [guida Ubuntu](INSTALLATORE_LINUX.md).

## Ubuntu: installazione da sorgenti

Per sviluppo servono Python 3.12 con `venv`, Docker Engine locale e Compose v2.
Dalla radice del checkout:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
nipat build-runtime
nipat doctor --runtime
nipat self-test
nipat wizard
```

La build richiede Internet. Usare directory di sviluppo distinte dall'applicazione
installata. `--data-dir` e `--runs-dir`, prima del sottocomando, selezionano i percorsi.

## Risorse e risultati

Il menu **Configura** permette di consultare risorse disponibili e limiti
applicati. La memoria fisica, quella della VM e il limite del container sono
valori distinti. Le [istruzioni sulle risorse](RISORSE.md) spiegano il loro
significato e le modifiche che richiedono un riavvio.

Ogni analisi conserva una mappa dei campioni e un resoconto leggibile.
Le esportazioni per la consultazione riportano i nomi originali; i risultati
scientifici e i loro metadati conservano gli identificativi necessari a collegare
le fasi. Consultare [Risultati e registrazione](ESECUZIONI.md).

## Aggiornamenti dall'applicazione

**Verifica aggiornamenti** consulta le release compatibili con il sistema.
Il download viene verificato prima dell'installazione. L'aggiornamento dell'app
è distinto dall'aggiornamento dei componenti del sistema, come WSL.
Chiudere le analisi prima di aggiornare; dati e risultati restano nelle loro
cartelle. La guida del proprio sistema descrive il passaggio all'installatore.

## Integrità e verifiche

Versione, commit, manifest e checksum identificano i pacchetti esatti.
I checksum rilevano differenze di contenuto ma non costituiscono una firma
riconosciuta da Windows o Apple. Il setup non disattiva le protezioni del sistema.

Le note della release riportano le prove effettivamente svolte. La CI controlla
client, pacchetti e regressioni scientifiche; i runner macOS ospitati non
qualificano automaticamente l'avvio di una VM Lima reale. Le prove Windows 10,
le installazioni desktop e la valutazione di dominio restano evidenze distinte,
come descritto in [CI/CD](CI_CD.md) e nella [scheda di validazione](VALIDAZIONE.md).

Il codice originale NIPAT usa la licenza [GPL-3.0-or-later](../LICENSE).
Le attribuzioni sono in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

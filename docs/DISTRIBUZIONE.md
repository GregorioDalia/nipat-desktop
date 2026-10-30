# Distribuzione e requisiti

**NIPAT Experimental08 0.8.0a1** è una distribuzione sperimentale con identità
propria, destinata alle prove di portabilità Windows 10 e macOS. Non sostituisce
[NIPAT Desktop 0.7.2](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.7.2),
che rimane la versione stabile. CLI, workflow e core scientifico R sono
conservati; la sperimentazione riguarda installazione e ambiente di esecuzione.

I pacchetti si ottengono dalla build **Installers (review build)** del branch
`experiment/0.8-portability` o da una pre-release esplicitamente sperimentale.
Controllare versione, commit e checksum associati al pacchetto. Le build
Actions non sono automaticamente release e non dimostrano il completamento
delle prove sui computer dei ricercatori. Gli archivi **Source code** di
GitHub non sono installatori.

## Piattaforme

| Sistema | Esecuzione scientifica | Installatore |
| --- | --- | --- |
| Windows 10 22H2 x64, build 19045, o Windows 11 x64 | WSL2 dedicato, Docker Engine interno, immagine Linux AMD64 | `NIPAT-Setup.exe`. |
| macOS 14 o successivo, Intel | VM Lima con Docker Engine, immagine Linux AMD64 | `NIPAT-Experimental-0.8.0a1-macos-x86_64.pkg`. |
| macOS 14 o successivo, Apple Silicon | VM Lima ARM64 con Rosetta, immagine Linux AMD64 | `NIPAT-Experimental-0.8.0a1-macos-arm64.pkg`. |

Il client Python gestisce l'interazione e l'accesso ai file. L'immagine
scientifica include R, samtools, dipendenze, script scientifici, preparazione
degli input e orchestrazione dei workflow. Le analisi singole e i workflow
composti usano lo stesso motore; non viene creata un'immagine per ogni codice R.
Il container di analisi non accede alla rete e legge gli input selezionati
senza modificarli.

## Pacchetto Windows

Aprire `NIPAT-Setup.exe` con doppio clic dal proprio account, senza selezionare
«Esegui come amministratore». Il setup include Python portabile, filesystem
WSL e archivio scientifico. Non occorre estrarre archivi runtime separati né
installare R, samtools o Docker Desktop.

Il setup verifica edizione, build e architettura, rileva WSL e prepara i
componenti mancanti. Windows Server, ARM e 32 bit non sono supportati. La
virtualizzazione deve essere disponibile; l'attivazione o l'aggiornamento
di WSL può richiedere Internet, autorizzazione amministrativa e riavvio.
Le policy del dispositivo possono impedire questa operazione.

L'identità **NIPAT Experimental08**, canale `experimental08`, dispone di
collegamenti, configurazione e cartelle propri:

| Contenuto | Percorso predefinito |
| --- | --- |
| Applicazione | `%LOCALAPPDATA%\Programs\NIPAT-Experimental08` |
| Ambiente WSL | `%LOCALAPPDATA%\NIPAT-Experimental08\wsl` |
| Cache | `%LOCALAPPDATA%\NIPAT-Experimental08\cache` |
| Dati | `%LOCALAPPDATA%\NIPAT-Experimental08\data` |
| Risultati | `%LOCALAPPDATA%\NIPAT-Experimental08\runs` |

Le cinque cartelle sono configurabili, su dischi locali fissi, scrivibili e
non sovrapposte. Il setup conserva file estranei e non adotta installazioni
di altri canali. Un'installazione dello stesso profilo può essere riparata;
una cartella non vuota estranea non viene svuotata.

Attendere `NIPAT: ready`, poi aprire **NIPAT Experimental08** dal menu Start
oppure dal collegamento scelto nel setup. La preparazione incompleta impedisce
l'analisi; il collegamento di completamento consente di riprenderla.
La disinstallazione conserva dati e risultati. L'eventuale pulizia aggiuntiva
riguarda soltanto runtime e cache verificati del profilo sperimentale.
Procedure e diagnostica: [installatore Windows](INSTALLATORE_WINDOWS.md).

## Pacchetto macOS

Scaricare il `.pkg` corrispondente all'architettura del Mac. Il pacchetto
installa **NIPAT Experimental08.app** in `/Applications`, con Python e Lima
inclusi. Aprire l'applicazione per avviare il menu CLI nel Terminale; il primo
avvio prepara la VM, Docker Engine e l'immagine scientifica.
Homebrew e Docker Desktop non sono richiesti.

Il primo avvio richiede una connessione Internet per i componenti del sistema
ospite. L'archivio scientifico è incluso nel pacchetto e verificato prima
dell'importazione. Su Apple Silicon è richiesta l'esecuzione AMD64 tramite
Rosetta: la presenza di un Mac ARM non trasforma l'immagine scientifica in ARM.

Dati, risultati e ambiente Lima appartengono all'account dell'utente, sotto
`~/Library/Application Support/NIPAT-Experimental08`. La VM e le preferenze
non condividono l'identità del canale stabile. Il supporto di percorsi e mount
è descritto nella [guida macOS](INSTALLATORE_MACOS.md).

I pacchetti non dispongono di firma Developer ID o notarizzazione Apple.
Gatekeeper o le policy di un dispositivo gestito possono impedirne l'avvio;
la build non disattiva queste protezioni. La disponibilità di un `.pkg` non
costituisce una prova di installazione su un Mac reale.

## Ubuntu: installazione da sorgenti

La sperimentazione 0.8 non produce un nuovo `.deb`. Il pacchetto Ubuntu della
serie stabile rimane 0.7.2 ed è descritto nella [guida Linux](INSTALLATORE_LINUX.md).
Ubuntu 24.04 LTS x86_64 resta il riferimento per sviluppo e regressioni
scientifiche con Docker Engine locale e Compose v2.

Servono Python 3.12 con supporto `venv`, Docker Engine locale, Compose v2 e
permessi per usare il daemon con il proprio account. Dalla radice di un
checkout separato del branch sperimentale:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
nipat build-runtime
nipat doctor --runtime
nipat self-test
nipat wizard
```

La build dell'immagine richiede Internet. Usare cartelle dati e risultati
dedicate, selezionabili con `--data-dir` e `--runs-dir` prima del sottocomando.
Il checkout da sorgenti non è un installatore autonomo e non va sovrapposto
al pacchetto stabile installato.

## Aggiornamenti dall'applicazione

La verifica degli aggiornamenti è disabilitata nel profilo `experimental08`.
Una nuova build sperimentale richiede un download esplicito. Le release
stabili e le loro preferenze `stable`/`testing` non distribuiscono questa
edizione; l'esperimento non installa una release stabile al proprio posto.
Gli aggiornamenti dei componenti del sistema operativo restano distinti
dagli aggiornamenti dell'applicazione.

## Integrità e verifiche

Ogni pacchetto associa versione, commit, manifest e checksum degli archivi.
Lo stesso archivio scientifico AMD64 viene usato per Windows e i due pacchetti
Mac. Un checksum rileva differenze di contenuto; non è una firma digitale
e non garantisce l'autorizzazione del sistema a eseguire il programma.

La CI verifica sorgenti, contratti, pacchetti e regressioni scientifiche.
I runner macOS ospitati verificano il client e il confezionamento; una prova
con VM Lima reale richiede capacità di virtualizzazione appropriate.
I test Windows simulano anche le condizioni Windows 10: non sono una prova
di attivazione WSL, riavvio e avvio del menu su un PC Windows 10 pulito.
La [documentazione CI/CD](CI_CD.md) distingue questi livelli.

Registrare installazione, avvio e analisi effettivamente osservati nella
[scheda di validazione](VALIDAZIONE.md), indicando cosa rimane da verificare.
La distribuzione sperimentale può precedere la qualificazione desktop completa;
non deve presentare i casi non eseguiti come superati. La validazione scientifica
con dati rappresentativi è separata dalle prove di portabilità.

Il codice originale NIPAT è distribuito con licenza
[GPL-3.0-or-later](../LICENSE). Le attribuzioni dei componenti sono in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

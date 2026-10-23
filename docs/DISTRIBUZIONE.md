# Distribuzione e requisiti

Questo documento descrive **NIPAT 0.5.0a1**. La versione non è pubblicata e
non dispone di installer scaricabili dalla pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
Gli artefatti generati dai controlli automatici servono alla verifica tecnica;
non attestano una distribuzione pronta per l'utilizzo generale.

## Piattaforme

| Sistema | Esecuzione scientifica | Modalità disponibile |
| --- | --- | --- |
| Windows 11 x64 | Distribuzione WSL2 dedicata, Docker Engine interno, immagine NIPAT autonoma | Pacchetto `NIPAT-Setup.exe` predisposto; verifica completa sul sistema e pubblicazione non concluse. |
| Ubuntu 24.04 LTS x86_64 | Docker Engine locale con Compose v2 e immagine NIPAT autonoma | Pacchetto `.deb` predisposto; verifica su Ubuntu Desktop pulito e pubblicazione non concluse. |

L'immagine scientifica contiene gli script R, samtools, le dipendenze e i
moduli di preparazione degli input. Le analisi non richiedono un'installazione
R sul sistema dell'utente. Il client e l'immagine devono appartenere a una
combinazione compatibile: NIPAT controlla le interfacce dei workflow e
l'integrità del motore prima dell'esecuzione.

## Pacchetto Windows

`NIPAT-Setup.exe` incorpora applicazione, launcher `NIPAT.exe`, Python
portabile, ambiente Linux e archivio dell'immagine scientifica. Il setup
verifica gli archivi, prepara la distribuzione WSL, importa l'immagine ed
esegue i controlli dell'ambiente e gli autotest. Non sono necessari download
separati dei componenti NIPAT né spostamenti manuali degli archivi.

Sono richiesti Windows 11 x64, disponibilità della virtualizzazione e WSL2.
L'attivazione dei componenti Windows può richiedere Internet, consenso
amministrativo e riavvio. Il setup deve essere eseguito normalmente dal
proprio account: richiede l'elevazione soltanto per le operazioni di sistema
che la necessitano. Le policy amministrative del computer possono impedire
l'attivazione di WSL. L'installazione completa su un sistema privo di WSL e
la ripresa dopo riavvio devono essere verificate separatamente dai test
automatici del codice.

La configurazione ha identità **NIPAT 0.5 Preview**:

| Elemento | Posizione o identificativo |
| --- | --- |
| Applicazione | `%LOCALAPPDATA%\Programs\NIPAT-0.5-Preview` |
| Dati predefiniti | `%LOCALAPPDATA%\NIPAT-0.5-Preview\data` |
| Risultati predefiniti | `%LOCALAPPDATA%\NIPAT-0.5-Preview\runs` |
| Cache dei componenti | `%LOCALAPPDATA%\NIPAT-0.5-Preview\cache` |
| Distribuzione WSL | Nome con prefisso `NIPAT-05-Preview-`, derivato dall'archivio Linux. |
| Avvio | Collegamento **NIPAT 0.5 Preview** nel menu Start o sul desktop. |

Applicazione, configurazione, cache e distribuzione appartengono a questo
canale. Il setup rifiuta cartelle applicative diverse da quella prevista;
i dati di analisi e la destinazione dei risultati si selezionano invece
nell'applicazione. La cartella dati non limita la posizione degli input:
sono ammessi file su dischi locali fissi.

L'esito finale della configurazione è `NIPAT: ready`. Se si interrompe,
la nuova applicazione resta bloccata per le analisi. Il collegamento
**NIPAT 0.5 Preview - completa preparazione** riprende il setup utilizzando
i componenti conservati. Stato e log si trovano nella sottocartella
`.runtime\installer` dell'applicazione.

### Aggiornamento e rimozione

Un aggiornamento dello stesso canale conserva le cartelle dati e risultati
configurate. Se cambia l'archivio dell'ambiente Linux, il setup prepara una
distribuzione dedicata al nuovo archivio e attiva la configurazione dopo i
controlli. La distribuzione precedente viene conservata. Un'interruzione
non attiva una configurazione incompleta; i file applicativi già installati
non vengono però ripristinati automaticamente.

La gestione di questa distribuzione NIPAT è distinta dalla manutenzione del
componente WSL di Windows. L'applicazione non costituisce un sistema di
aggiornamento automatico generale di Windows o WSL.

La disinstallazione rimuove i file applicativi e i collegamenti. Dati,
risultati e ambiente WSL vengono conservati: la disinstallazione non deve
essere interpretata come cancellazione completa dei dati di ricerca.
I dettagli tecnici e le prove richieste sono in
[INSTALLATORE_WINDOWS.md](INSTALLATORE_WINDOWS.md).

## Pacchetto Ubuntu

Il file `.deb` installa **NIPAT 0.5 Preview**, la documentazione e l’archivio
scientifico già verificato dalla build. Windows e Ubuntu incorporano gli
stessi byte di questo archivio, identificati da dimensione e SHA-256 nel
manifest comune. Ubuntu non include né richiede il filesystem WSL.

Il pacchetto dichiara Python 3.12, Docker Engine e Compose v2 come dipendenze.
APT risolve i pacchetti mancanti dai repository configurati; non è necessario
installare R o samtools sul sistema. Docker Engine deve essere avviato e
accessibile al proprio account tramite il socket locale. Sono supportati
il daemon di sistema e i container senza rimappatura degli UID; Docker
rootless, `userns-remap` e daemon remoti non fanno parte di questo contratto.

Il primo avvio verifica e importa l’archivio incluso, controlla il motore ed
esegue gli autotest prima di consentire le analisi. L’applicazione non cambia
i gruppi dell’utente, i permessi del socket o la configurazione Docker.
L’accesso al gruppo `docker` deve essere autorizzato dall’amministratore,
poiché concede privilegi equivalenti a root.

| Elemento | Posizione o identificativo |
| --- | --- |
| Pacchetto | `nipat-05-preview` |
| Applicazione | `/opt/nipat-05-preview` |
| Avvio | Collegamento **NIPAT 0.5 Preview** o `nipat-05-preview` |
| Dati predefiniti | `${XDG_DATA_HOME:-~/.local/share}/nipat-05-preview/data` |
| Risultati predefiniti | `${XDG_DATA_HOME:-~/.local/share}/nipat-05-preview/runs` |
| Stato e log della preparazione | `${XDG_STATE_HOME:-~/.local/state}/nipat-05-preview` |

Un aggiornamento del pacchetto conserva i dati dell’utente e richiede la
verifica della nuova combinazione di applicazione e immagine. La rimozione
del pacchetto conserva dati, risultati, stato e immagini Docker. I comandi
di installazione, diagnosi e rimozione sono nella
[guida dell’installatore Linux](INSTALLATORE_LINUX.md).

## Ubuntu: installazione da sorgenti

Servono Python 3.12 con supporto `venv`, Docker Engine locale, Compose v2 e
permessi per utilizzare il motore con il proprio account. La compilazione
dell'immagine richiede Internet. Il repository completo contiene i file di
build e i dati sintetici degli autotest.

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

L'applicazione utilizza `data` e `runs` accanto al progetto. Si possono
scegliere altre destinazioni con `--data-dir` e `--runs-dir`, prima del
sottocomando, oppure con `NIPAT_DATA_DIR` e `NIPAT_RUNS_DIR`. I file selezionati
come input vengono montati in sola lettura; la cartella del run corrente è
scrivibile dal container.

L'installazione Python non include l'immagine scientifica. Un archivio
**Source code** di GitHub è un checkout da preparare secondo questa procedura,
non un installatore autonomo. L'esecuzione da sorgenti richiede competenze
nell'amministrazione di Python e Docker.

## Integrità e verifica del pacchetto

Una distribuzione deve associare versione, commit, manifest degli asset e
checksum dei file. Gli asset di una release pubblicata costituiscono un
insieme versionato: un aggiornamento richiede una nuova versione.
La [procedura di pubblicazione](../.github/RELEASE.md) descrive i controlli
per i manutentori; [CI_CD.md](CI_CD.md) descrive la copertura automatica.

La verifica di un pacchetto comprende installazione, avvio, diagnostica,
autotest e analisi con dati appropriati sul sistema dichiarato. L'esito della
CI non sostituisce una prova dell'installer sul computer destinatario né la
validazione di dominio. La [scheda dedicata](VALIDAZIONE.md) consente di
registrare separatamente questi risultati.

Il codice originale NIPAT è distribuito con licenza
[GPL-3.0-or-later](../LICENSE). Le attribuzioni e le licenze delle dipendenze
sono conservate in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

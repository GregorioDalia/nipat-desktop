# Installazione di NIPAT su Ubuntu

Il pacchetto Linux di **NIPAT 0.5.0a1** è un unico file
`nipat-05-preview_0.5.0~a1_amd64.deb`. Contiene applicazione, documentazione
e immagine scientifica con R, samtools, dipendenze e preparazione dei workflow.
Il motore è lo stesso archivio verificato incluso nel pacchetto Windows.
Non è necessario scaricare o spostare separatamente l'immagine.

La versione è una Preview non pubblicata. Il pacchetto viene prodotto come
artefatto per revisione e non è ancora disponibile nella pagina Releases.
Le istruzioni si riferiscono a un pacchetto della build identificata;
un archivio **Source code** di GitHub non è un installatore.

## Requisiti

| Componente | Requisito |
| --- | --- |
| Sistema | Ubuntu 24.04 LTS, architettura x86_64/amd64. |
| Client | Python 3.12 del sistema, installato da APT se mancante. |
| Runtime | Docker Engine locale e Compose v2, installati da APT se mancanti. |
| Accesso | Account non root autorizzato a usare il socket `/var/run/docker.sock`. |
| Configurazione Docker | Daemon di sistema, container Linux amd64, senza modalità rootless o `userns-remap`. |
| Archiviazione | Spazio per il pacchetto installato, l'immagine Docker decompressa, input, intermedi e risultati. |

Il `.deb` dichiara le dipendenze `python3.12`, `docker.io | docker-ce` e
`docker-compose-v2 | docker-compose-plugin`. Installando il `.deb` con APT,
le dipendenze mancanti vengono scaricate e installate dai repository
configurati: non occorre installare prima Docker manualmente. Servono una
connessione Internet e autorizzazione amministrativa. Su Ubuntu con i
repository ordinari disponibili, la dipendenza Docker è soddisfatta da
`docker.io` e `docker-compose-v2`. Un’installazione Docker già presente deve
soddisfare questi requisiti. Il pacchetto NIPAT non aggiunge repository,
non sostituisce configurazioni del daemon e non abilita automaticamente
l’accesso degli utenti.

Docker Engine deve essere avviato prima della preparazione. L'autorizzazione
all'uso del gruppo `docker` è una scelta amministrativa: concede privilegi
equivalenti a root. L'amministratore deve configurarla esplicitamente secondo
le [istruzioni Docker per Linux](https://docs.docker.com/engine/install/linux-postinstall/).
Dopo una modifica ai gruppi può essere necessario uscire e rientrare nella
sessione. Non eseguire NIPAT con `sudo` e non rendere il socket scrivibile da tutti.

Il launcher usa esclusivamente il socket Docker locale e non cambia il
contesto globale dell'utente. Docker rootless, daemon remoti e rimappatura
UID non sono supportati da questo pacchetto. Il loro rifiuto evita di avviare
analisi con percorsi o proprietari dei risultati differenti da quelli attesi.

## Installazione e primo avvio

Dalla cartella che contiene il file ricevuto da una build verificata:

```bash
sudo apt install ./nipat-05-preview_0.5.0~a1_amd64.deb
```

APT mostra anche le dipendenze da scaricare e installare. Esaminare il
riepilogo prima di confermare. `dpkg -i` da solo non risolve né scarica le
dipendenze mancanti. L’apertura del `.deb` con doppio clic richiede un
gestore grafico che installi pacchetti locali e ne risolva le dipendenze;
questa funzione dipende dal desktop configurato. Il comando APT costituisce
la procedura di riferimento.

L’installazione dei pacchetti e l’autorizzazione dell’account sono due
operazioni distinte. Dopo l’installazione, verificare che Docker sia avviato
e completare con l’amministratore l’accesso al socket. Il setup NIPAT
non aggiunge automaticamente l’utente al gruppo `docker`.

Dopo l'installazione:

1. Aprire **NIPAT 0.5 Preview** dal menu delle applicazioni, oppure eseguire
   `nipat-05-preview` nel terminale.
2. Attendere la verifica dell'archivio incluso e l'importazione dell'immagine.
3. Attendere la diagnostica del motore e gli autotest.
4. Nel menu, scegliere il workflow e compilare gli input. Confermare
   **Avvia analisi** nel riepilogo per eseguire il calcolo scientifico.

Il collegamento apre la CLI in un terminale e mantiene visibili i messaggi
finali fino alla conferma di chiusura. Non è una GUI grafica.
Gli avvii successivi controllano lo stato e l’immagine locale e riutilizzano
la configurazione verificata, senza rileggere l’intero archivio o ripetere
gli autotest. Il primo avvio
può richiedere diversi minuti; l'immagine scientifica non viene scaricata
nuovamente da Internet.

Per eseguire o ripetere esplicitamente la verifica dell’archivio,
la diagnostica e gli autotest, senza aprire il menu:

```bash
nipat-05-preview --setup
```

Se la preparazione fallisce, le analisi restano bloccate. Risolvere la causa
indicata e ripetere il comando: i dati e i risultati già presenti sono conservati.

## Comandi e percorsi

```bash
nipat-05-preview --version
nipat-05-preview --help
nipat-05-preview dnp-call --help
nipat-05-preview doctor --runtime
nipat-05-preview self-test
nipat-05-preview
```

`--help` e `--version` sono disponibili anche se Docker non è accessibile.
Le simulazioni `--dry-run` preparano il run senza importare l’immagine,
avviare gli autotest o eseguire calcoli scientifici; non verificano
la disponibilità del runtime.
`doctor --runtime` controlla il motore e i contratti dei quattro workflow;
`self-test` esegue i casi distribuiti e ne verifica i risultati. Nessuno dei
due costituisce una validazione scientifica generale. Input, parametri e
risultati sono descritti nella [guida per l'utilizzo](GUIDA_UTILIZZO.md).

| Contenuto | Posizione predefinita |
| --- | --- |
| Applicazione e archivio scientifico | `/opt/nipat-05-preview` |
| Comando | `/usr/bin/nipat-05-preview` |
| Dati | `~/.local/share/nipat-05-preview/data` |
| Risultati | `~/.local/share/nipat-05-preview/runs` |
| Stato della preparazione | `~/.local/state/nipat-05-preview/state.json` |
| Log della preparazione | `~/.local/state/nipat-05-preview/setup.log` |

Se `XDG_DATA_HOME` o `XDG_STATE_HOME` sono definiti, sostituiscono
rispettivamente `~/.local/share` e `~/.local/state`; devono essere percorsi
assoluti. I dati appartengono all'utente e restano separati dall'applicazione.
Non usare la directory `/opt/nipat-05-preview` per campioni o risultati.

Gli input possono trovarsi in altre cartelle locali accessibili. Per scegliere
una destinazione dei risultati usare l'opzione 5 del menu oppure `--runs-dir`
prima del sottocomando:

```bash
nipat-05-preview --runs-dir "$HOME/risultati-nipat" contamination \
  --input "$HOME/campioni/sample.txt" --panel "$HOME/pannelli/DNPpanel.txt"
```

## Aggiornamento e rimozione

Installare un nuovo `.deb` dello stesso canale con `sudo apt install ./<file.deb>`.
APT sostituisce i file applicativi e conserva i dati dell'utente. Al primo
avvio, NIPAT verifica la combinazione aggiornata di applicazione, manifest e
immagine. Una configurazione incompleta non viene attivata. I file applicativi
installati da APT non vengono ripristinati automaticamente se la preparazione
successiva fallisce.

Per rimuovere l'applicazione:

```bash
sudo apt remove nipat-05-preview
```

La rimozione elimina applicazione e collegamento. Conserva dati, risultati,
stato e immagini Docker. Non rimuove il daemon, non cambia i gruppi utenti
e non elimina altre immagini o container. L'eventuale cancellazione dei dati
è un'operazione separata da pianificare dopo averne verificato la conservazione.

## Diagnostica

| Problema | Intervento |
| --- | --- |
| Docker non raggiungibile | Verificare con l'amministratore che il servizio sia avviato e il socket accessibile dall'account corrente. |
| Permesso negato sul socket | Completare la configurazione amministrativa dell'accesso; dopo una modifica ai gruppi, rientrare nella sessione. |
| Rootless, rimappatura UID o piattaforma non supportata | Usare un sistema e un daemon conformi ai requisiti dichiarati. |
| Archivio non integro | Conservare il log e reinstallare il pacchetto verificato della stessa build. |
| Preparazione già in corso | Attendere il completamento dell'altro avvio. |
| Autotest fallito | Conservare log, stato e run generati; non considerare la preparazione completata. |
| Immagine rimossa da Docker | Avviare nuovamente NIPAT per ripristinarla dall'archivio incluso. |

Per una segnalazione, registrare versione del sistema, versione NIPAT,
provenienza del `.deb`, messaggio completo e log della preparazione.
I log dei run possono contenere nomi e percorsi dei campioni: verificarne
il contenuto prima di condividerli.

## Verifiche del pacchetto

La build usa il manifest comune di Windows e Ubuntu e verifica che il `.deb`
incorpori l'archivio scientifico previsto. I controlli automatici comprendono
installazione, preparazione con utente non root, autotest SNPcall, CPI
e Contamination, DNPcall su BAM sintetico, input privati e percorsi con
spazi e caratteri non ASCII. Verificano inoltre proprietà dei risultati,
reinstallazione dello stesso pacchetto e rimozione con conservazione
dei dati, dello stato e delle risorse Docker estranee. Le prove usano
un runner Ubuntu 24.04 con Docker già configurato; la reinstallazione
non copre un aggiornamento fra versioni differenti.

Una prova separata installa il `.deb` in un container Ubuntu 24.04
inizialmente privo delle dipendenze, verifica che APT installi Python 3.12,
Docker Engine e Compose v2 e controlla i comandi informativi del pacchetto.
Questa prova non avvia un daemon Docker nel container e non verifica
l’autorizzazione di un account desktop.

Le due prove automatiche non attestano l’esperienza completa su un Ubuntu
Desktop pulito, la risoluzione di ogni configurazione APT o l’interazione
con ogni gestore grafico dei pacchetti. Prima della distribuzione,
completare il [protocollo di accettazione](ACCETTAZIONE_INSTALLATORI.md)
sul pacchetto effettivo. La [scheda di validazione](VALIDAZIONE.md)
consente di registrare anche le analisi di dominio.
Evidenze, artefatti e confini della pipeline sono descritti in [CI/CD](CI_CD.md).

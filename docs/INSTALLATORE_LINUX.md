# Installazione di NIPAT su Ubuntu

Il pacchetto Linux di **NIPAT Desktop 0.6.0** è un unico file
`nipat-desktop_0.6.0_amd64.deb`. Contiene applicazione, documentazione
e immagine scientifica con R, samtools, dipendenze e preparazione dei workflow.
Il motore è lo stesso archivio verificato incluso nel pacchetto Windows.
Non è necessario scaricare o spostare separatamente l'immagine.

La versione appartiene al canale desktop. Le versioni pubblicate e i
relativi pacchetti sono elencati nella pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
I pacchetti degli artefatti GitHub Actions servono alla revisione tecnica.
Le istruzioni si riferiscono a una build identificata; un archivio
**Source code** di GitHub non è un installatore.

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

Scaricare il pacchetto `.deb` della versione scelta dagli asset della pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
Dalla cartella che contiene il pacchetto:

```bash
sudo apt install ./nipat-desktop_0.6.0_amd64.deb
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

1. Aprire **NIPAT Desktop** dal menu delle applicazioni, oppure eseguire
   `nipat` nel terminale.
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
nipat --setup
```

Se la preparazione fallisce, le analisi restano bloccate. Risolvere la causa
indicata e ripetere il comando: i dati e i risultati già presenti sono conservati.

## Comandi e percorsi

```bash
nipat --version
nipat --help
nipat dnp-call --help
nipat doctor --runtime
nipat self-test
nipat
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
| Applicazione e archivio scientifico | `/opt/nipat-desktop` |
| Comando | `/usr/bin/nipat` |
| Dati | `~/.local/share/nipat-desktop/data` |
| Risultati | `~/.local/share/nipat-desktop/runs` |
| Stato della preparazione | `~/.local/state/nipat-desktop/state.json` |
| Log della preparazione | `~/.local/state/nipat-desktop/setup.log` |
| Preferenze del menu | `~/.config/nipat-desktop/preferences.json` |

Se `XDG_DATA_HOME` o `XDG_STATE_HOME` sono definiti, sostituiscono
rispettivamente `~/.local/share` e `~/.local/state`; devono essere percorsi
assoluti. `XDG_CONFIG_HOME`, se definito, sostituisce `~/.config` per le
preferenze del menu. I dati appartengono all'utente e restano separati dall'applicazione.
Non usare la directory `/opt/nipat-desktop` per campioni o risultati.

Gli input possono trovarsi in altre cartelle locali accessibili. Per scegliere
una destinazione dei risultati usare **5 — Configura → Cartelle dati e
risultati** nel menu oppure `--runs-dir` prima del sottocomando. Le preferenze
salvate si applicano soltanto al menu; i comandi diretti rimangono espliciti:


```bash
nipat --runs-dir "$HOME/risultati-nipat" contamination \
  --input "$HOME/campioni/sample.txt" --panel "$HOME/pannelli/DNPpanel.txt"
```

## Aggiornamento e rimozione

**9 — Verifica aggiornamenti** scarica e verifica il `.deb` completo di una
release approvata. Dopo la conferma esplicita di installazione, la sessione
corrente si chiude e viene aperto un terminale di sistema. L'installazione
tramite APT richiede autorizzazione amministrativa attraverso Polkit.
Al termine il launcher normale verifica o prepara il runtime prima del menu.
Se terminale o Polkit non sono disponibili, il pacchetto verificato rimane
sul disco e NIPAT mostra il comando APT completo da eseguire con l'amministratore.

Si può anche installare il pacchetto con `sudo apt install ./<file.deb>`.
APT sostituisce i file applicativi e conserva i dati dell'utente. Al primo
avvio, NIPAT verifica la combinazione aggiornata di applicazione, manifest e
immagine. Una configurazione incompleta non viene attivata. I file applicativi
installati da APT non vengono ripristinati automaticamente se la preparazione
successiva fallisce. Le preferenze e i percorsi dell'utente vengono conservati.
Le sessioni NIPAT ancora attive impediscono la modifica del pacchetto; non
vengono terminate per consentire l'aggiornamento. Se APT o dpkg si interrompono,
completare la configurazione del pacchetto con l'amministratore prima di riaprire
NIPAT. Non è previsto un rollback automatico completo.

Per rimuovere l'applicazione:

```bash
sudo apt remove nipat-desktop
```

La rimozione elimina applicazione e collegamento. Conserva dati, risultati,
stato, preferenze del menu e immagini Docker. Non rimuove il daemon, non cambia i gruppi utenti
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
| Aggiornamento interrotto | Conservare `${XDG_CACHE_HOME:-~/.cache}/nipat-desktop/updates/handoff-*/state.json` e i messaggi del terminale APT; se la transazione non è completa, riprendere la configurazione del pacchetto con l'amministratore. La preparazione del runtime usa il consueto `setup.log` nella cartella di stato XDG. |

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

# Distribuzione e requisiti

Questo documento descrive l'installazione di **NIPAT Desktop 0.7.2**. Consultare la pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases) per le
versioni pubblicate, i pacchetti disponibili e le relative evidenze.
Gli artefatti GitHub Actions servono alla verifica tecnica e sono distinti
dalle release; la loro costruzione non autorizza da sola la pubblicazione.
Le [note della versione 0.7.2](RELEASE_0.7.2.md) descrivono funzionalità e
ambito delle verifiche. L'installazione su un PC con NIPAT Desktop aggiorna
quell'applicazione, senza creare un'edizione affiancata.

## Piattaforme

| Sistema | Esecuzione scientifica | Installatore |
| --- | --- | --- |
| Windows 11 x64 | Distribuzione WSL2 dedicata, Docker Engine interno, immagine NIPAT autonoma | Unico file `NIPAT-Setup.exe`. |
| Ubuntu 24.04 LTS x86_64 | Docker Engine locale con Compose v2 e immagine NIPAT autonoma | Unico pacchetto `.deb`. |

L'immagine scientifica contiene gli script R, samtools, le dipendenze e i
moduli di preparazione degli input. Le analisi non richiedono un'installazione
R sul sistema dell'utente. Il client e l'immagine devono appartenere a una
combinazione compatibile: NIPAT controlla le interfacce dei workflow e
l'integrità del motore prima dell'esecuzione.

## Pacchetto Windows

Scaricare `NIPAT-Setup.exe` dagli asset della versione scelta nella pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
È sufficiente un solo file eseguibile: non occorre estrarre uno ZIP.
Le build tecniche prima della pubblicazione seguono la procedura di
[accettazione degli installatori](ACCETTAZIONE_INSTALLATORI.md).

`NIPAT-Setup.exe` incorpora applicazione, componenti di avvio, Python
portabile, ambiente Linux e archivio dell'immagine scientifica. Il setup
verifica gli archivi, prepara la distribuzione WSL, importa l'immagine ed
esegue i controlli dell'ambiente e gli autotest. Non sono necessari download
separati dei componenti NIPAT né spostamenti manuali degli archivi.
Il setup crea il collegamento **NIPAT Desktop** nel menu Start e, se
selezionato, sul desktop. Il collegamento apre il menu guidato tramite
`2_AVVIA.cmd`; per la CLI diretta è disponibile `nipat.cmd`. Entrambi
controllano la configurazione installata prima di avviare il client Python.
La schermata finale del setup propone anche l'avvio immediato, quando la
preparazione è completata e non richiede un riavvio.

Sono richiesti Windows 11 x64, disponibilità della virtualizzazione e WSL2.
L'attivazione dei componenti Windows può richiedere Internet, consenso
amministrativo e riavvio. Il setup deve essere eseguito normalmente dal
proprio account: richiede l'elevazione soltanto per le operazioni di sistema
che la necessitano. Le policy amministrative del computer possono impedire
l'attivazione di WSL. L'installazione completa su un sistema privo di WSL e
la ripresa dopo riavvio devono essere verificate separatamente dai test
automatici del codice. Il pacchetto non è firmato da NIPAT: la compatibilità
con le protezioni del computer va verificata per ciascun dispositivo del
collaudo. Il setup non modifica le policy di sicurezza per autorizzarsi
all'esecuzione.

La configurazione ha identità **NIPAT Desktop**, indipendente dal numero di
versione. Il setup propone cinque cartelle modificabili separatamente:

| Contenuto | Percorso predefinito |
| --- | --- |
| Applicazione | `%LOCALAPPDATA%\Programs\NIPAT-Desktop` |
| Ambiente WSL e immagine scientifica | `%LOCALAPPDATA%\NIPAT-Desktop\wsl` |
| Cache degli archivi di installazione | `%LOCALAPPDATA%\NIPAT-Desktop\cache` |
| Dati di riferimento | `%LOCALAPPDATA%\NIPAT-Desktop\data` |
| Risultati | `%LOCALAPPDATA%\NIPAT-Desktop\runs` |

Le cartelle devono essere scrivibili dall'account e trovarsi su dischi locali
fissi. Possono essere su dischi diversi, ma devono essere distinte e nessuna
può contenerne un'altra. Il setup rifiuta cartelle di sistema, destinazioni
delle altre installazioni NIPAT, percorsi UNC, unità di rete, supporti rimovibili e
percorsi che attraversano junction o collegamenti. La cartella applicativa
deve essere vuota o appartenere alla stessa installazione NIPAT Desktop; dati già presenti nelle
cartelle dati e risultati vengono conservati. La cartella dati non limita
la posizione degli input selezionati per le analisi.

Le preferenze di **Configura** sono separate dall'installazione e risiedono
in `%LOCALAPPDATA%\NIPAT-Desktop\preferences.json`. Modificano i valori
proposti nel menu, senza trasferire applicazione, ambiente WSL o cache.
Le opzioni esplicite della CLI conservano il loro comportamento; i comandi
diretti non usano queste preferenze.

Il menu Start include **Cartella NIPAT Desktop**, che apre la destinazione applicativa.
Le preferenze dei percorsi sono associate al canale e vengono riproposte nelle
reinstallazioni, anche dopo la disinstallazione. La modalità **Aggiornamento
e riparazione** riutilizza la stessa cartella di un’installazione NIPAT Desktop riconosciuta,
anche quando contiene residui di disinstallazione. Una cartella estranea non
vuota non viene svuotata: il setup propone, quando disponibile, una
sottocartella vuota oppure richiede un'altra destinazione.

L'esito finale della configurazione è `NIPAT: ready`. Se si interrompe,
la nuova applicazione resta bloccata per le analisi. Il collegamento
**NIPAT Desktop - completa preparazione** riprende il setup utilizzando
i componenti conservati. Stato e log si trovano nella sottocartella
`.runtime\installer` dell'applicazione.

### Aggiornamento e rimozione

Prima di sostituire file applicativi differenti, il setup li salva insieme
ai metadati di recupero e al Python portabile generato in un backup selettivo
nel profilo dell'utente. I file estranei ai componenti distribuiti restano
nella loro posizione; una collisione con un file da installare viene salvata
prima della sovrascrittura. I componenti non più distribuiti vengono rimossi
soltanto se coincidono con l'inventario precedente verificato; quelli
modificati rimangono in posizione e vengono anche salvati nel backup. Il backup non
è una copia completa dell'installazione e non prevede un rollback automatico.

Un aggiornamento dello stesso canale ripropone i percorsi configurati. Se
cambia l'archivio Linux o la destinazione dell'ambiente WSL, il setup prepara
una distribuzione dedicata e attiva la configurazione dopo i controlli.
Il componente WSL ha un'identità distinta dall'applicazione: quando sorgenti,
dipendenze e contenuto verificato restano gli stessi, la build può riutilizzare
l'archivio pubblicato senza legarlo a una modifica del solo menu.
L'ambiente precedente viene conservato, senza copiarlo o eliminarlo
automaticamente. Cambiare le cartelle dati o risultati non trasferisce i file:
i risultati precedenti restano consultabili nella destinazione originaria.
Un'interruzione non attiva una configurazione incompleta; i file applicativi
già installati non vengono però ripristinati automaticamente.

La gestione di questa distribuzione NIPAT è distinta dalla manutenzione del
componente WSL di Windows. L'applicazione non costituisce un sistema di
aggiornamento automatico generale di Windows o WSL.

La disinstallazione rimuove i file applicativi e i collegamenti e conserva
sempre dati e risultati. Per impostazione predefinita conserva anche ambiente
WSL e cache; l'opzione di rimozione aggiuntiva elimina soltanto le distribuzioni
verificate di NIPAT Desktop e gli archivi verificati della sua cache, nelle
destinazioni attuali e precedenti registrate. Non interviene su Docker
Desktop, sulle altre installazioni NIPAT o su altre distribuzioni WSL. Le preferenze
e i piccoli registri dei percorsi restano disponibili per una reinstallazione.
I dettagli tecnici e le prove richieste sono in
[INSTALLATORE_WINDOWS.md](INSTALLATORE_WINDOWS.md).

La voce **Guida e informazioni → Installazione e spazio** consente di
consultare le risorse Windows, eliminare singoli componenti precedenti
verificati e riprendere la preparazione della versione installata. Mantiene
protetti ambiente attivo e precedente più recente e conserva dati e risultati.
Ogni modifica richiede conferma e viene eseguita da un processo separato dopo
la chiusura del client. Questa funzione non ripristina una versione precedente;
ambito e rapporti sono descritti nella
[manutenzione Windows](INSTALLATORE_WINDOWS.md#manutenzione-dei-componenti-installati).

## Pacchetto Ubuntu

Il file `.deb` installa **NIPAT Desktop**, la documentazione e l’archivio
scientifico già verificato dalla build. Windows e Ubuntu incorporano gli
stessi byte di questo archivio, identificati da dimensione e SHA-256 nel
manifest comune. Ubuntu non include né richiede il filesystem WSL.

Il pacchetto dichiara Python 3.12, Docker Engine e Compose v2 come dipendenze.
L’installazione con `sudo apt install ./<file.deb>` scarica e installa
automaticamente i pacchetti mancanti dai repository configurati, inclusi
Docker e Compose. Richiede autorizzazione amministrativa e una connessione
per i download. Un Docker compatibile già installato soddisfa le dipendenze;
NIPAT non aggiunge repository o sostituisce configurazioni del daemon.
Non è necessario installare R o samtools sul sistema. Docker Engine deve essere avviato e
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
| Pacchetto | `nipat-desktop` |
| Applicazione | `/opt/nipat-desktop` |
| Avvio | Collegamento **NIPAT Desktop** o `nipat` |
| Dati predefiniti | `${XDG_DATA_HOME:-~/.local/share}/nipat-desktop/data` |
| Risultati predefiniti | `${XDG_DATA_HOME:-~/.local/share}/nipat-desktop/runs` |
| Stato e log della preparazione | `${XDG_STATE_HOME:-~/.local/state}/nipat-desktop` |
| Preferenze del menu | `${XDG_CONFIG_HOME:-~/.config}/nipat-desktop/preferences.json` |

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

## Aggiornamenti dall'applicazione

Il menu **Verifica aggiornamenti** usa esclusivamente le release pubblicate
del repository ufficiale, con manifest di aggiornamento coerente con il
prodotto, la versione, il commit e la piattaforma. Il manifest viene prodotto
dalla procedura di pubblicazione soltanto dopo la verifica della coppia di
installatori e del record di accettazione. Le build Actions e le bozze non
sono distribuite attraverso questo canale.

`testing`, predefinito, comprende pre-release e release stabili approvate;
`stable` comprende soltanto le stabili. Il numero della versione non sostituisce
la scelta esplicita del canale. La verifica all'avvio è facoltativa, disattivata
inizialmente e solo informativa. Download e installazione sono operazioni
separate, ciascuna confermata dall'utente, e riguardano l'installatore completo.

Il download controlla dimensione e SHA-256 prima dell'utilizzo. Queste verifiche
si basano su HTTPS e sulle risorse del repository ufficiale; non costituiscono
una firma digitale del software. L'aggiornamento riusa le procedure documentate
di installazione, preserva percorsi, preferenze e dati e richiede la verifica
del runtime prima di nuove analisi. Non è un aggiornamento automatico di Windows,
WSL o Docker Engine di sistema. Le analisi già registrate conservano la versione
utilizzata e l'installazione pronta resta utilizzabile senza connessione.

## Integrità e verifica del pacchetto

Una distribuzione deve associare versione, commit, manifest degli asset e
checksum dei file. Gli asset di una release pubblicata costituiscono un
insieme versionato: un aggiornamento richiede una nuova versione.
La [procedura di pubblicazione](../.github/RELEASE.md) descrive i controlli
per i manutentori; [CI_CD.md](CI_CD.md) descrive la copertura automatica.

La verifica di un pacchetto comprende installazione, avvio, diagnostica,
autotest e analisi con dati appropriati sul sistema dichiarato. L'esito della
CI non sostituisce una prova dell’installer sul computer destinatario né la
validazione di dominio. Il [protocollo degli installatori](ACCETTAZIONE_INSTALLATORI.md)
distingue l'accettazione per ricerca pre-1.0, basata su prove manuali
circoscritte, verifiche automatiche e revisione delle modifiche, dalla
qualificazione desktop completa. La decisione documenta le evidenze disponibili
e i casi ancora da verificare; la scelta del canale `stable` non estende la
copertura dichiarata. La versione 0.7.2 è destinata alla campagna di valutazione
con le esperte di dominio. La
[scheda di validazione](VALIDAZIONE.md) consente di registrare separatamente
i risultati scientifici.

Il codice originale NIPAT è distribuito con licenza
[GPL-3.0-or-later](../LICENSE). Le attribuzioni e le licenze delle dipendenze
sono conservate in [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

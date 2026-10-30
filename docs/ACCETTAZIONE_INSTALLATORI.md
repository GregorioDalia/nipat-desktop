# Accettazione degli installatori

## Esperimento 0.8

NIPAT Experimental08 0.8.0a1 esplora Windows 10 22H2 x64 e macOS 14 o
successivo, Intel e Apple Silicon, mantenendo Windows 11 x64. È separato
dalla distribuzione stabile: non usa il relativo manifest di aggiornamento
e non costituisce una promozione a `Latest`.

Le prove della candidata devono identificare versione, commit, checksum e
architettura. Registrare distintamente:

- test automatici del client e dei contratti;
- decisioni Windows simulate e build effettiva degli installer;
- regressioni scientifiche Linux AMD64;
- confezionamento Mac su runner ospitati;
- eventuale esecuzione Lima reale per ciascuna architettura;
- installazioni e analisi effettivamente osservate sui dispositivi.

Una distribuzione sperimentale può avvenire prima del completamento del
collaudo desktop esteso. Le note riportano i casi non eseguiti; test simulati
e osservazioni su un'altra piattaforma non vengono attribuiti al dispositivo
ancora da provare. La [scheda di validazione](VALIDAZIONE.md) raccoglie i
risultati. Questa sperimentazione non modifica i criteri o le evidenze della
0.7.2 già distribuita.

## Protocollo del canale stabile


Questo documento definisce i criteri di distribuzione e il piano di collaudo
progressivo di **NIPAT Desktop** su Windows 11 x64 con WSL2 e Ubuntu 24.04 LTS
x86_64. Ogni decisione identifica gli installatori tramite commit, build
GitHub Actions e checksum e distingue prove osservate, controlli automatici
e scenari ancora da verificare.

La serie **0.7** prevede una distribuzione per ricerca pre-1.0, basata su
prove manuali documentate, una build completa riuscita e una decisione
esplicita del manutentore. La **0.7.2** è destinata alla campagna di valutazione
con le esperte di dominio. La qualificazione desktop completa rimane un
percorso distinto: il suo catalogo di casi non blocca automaticamente ogni
release pre-1.0.

L’accettazione tecnica riguarda installazione, avvio, conservazione dei dati
e funzionamento dei workflow. La validazione scientifica sui dati e sugli
scenari d’uso è documentata separatamente in [VALIDAZIONE.md](VALIDAZIONE.md).
La pubblicazione nel canale `stable` identifica una versione ufficiale
per gli aggiornamenti; non attesta una validazione scientifica generale.

## Criteri di distribuzione pre-1.0

L'accettazione per ricerca richiede:

1. CI applicabile e build completa degli installatori riuscite, incluse le
   regressioni dei quattro workflow e le prove automatiche dei pacchetti.
2. Identità verificata di commit, manifest, archivio scientifico comune e
   installatori Windows/Ubuntu. Pacchetti diversi richiedono una nuova decisione.
3. Evidenza manuale di installazione pronta e di almeno una esecuzione
   scientifica riuscita, tramite autotest o analisi DNPcall, con il commit
   realmente osservato. Registrare anche la diagnostica quando disponibile.
4. Revisione esplicita della distribuzione per ricerca, con responsabile,
   data, riferimenti alle evidenze e indicazione degli scenari rinviati.

Una prova su una build precedente può essere conservata con uno dei seguenti
ambiti verificati automaticamente:

- **Schema 2, serie 0.6:** equivalenza dei sorgenti operativi distribuiti,
  con le sole esclusioni esplicitamente definite dal validatore.
- **Schema 3, fino alla 0.7.1:** equivalenza dei sorgenti scientifici e del runtime;
  revisione esplicita di ogni differenza nei sorgenti distribuiti del client,
  degli installatori e dei loro test, con hash precedenti e nuovi.
- **Schema 4, dalla 0.7.2:** evidenza storica di installazione e funzionamento
  sulla piattaforma osservata. Le differenze operative, inclusi adattatori e
  runtime, sono revisionate con hash precedenti e nuovi; i sorgenti R e il
  loro manifest devono restare invariati. Il confronto non dichiara equivalenza
  operativa con la build precedente. Sono richiesti anche la prova reale di
  aggiornamento Ubuntu e il rapporto permanente delle verifiche della candidata.

Il confronto considera l'inventario versionato dei file distribuiti. Per lo
schema 3, modifiche ai percorsi `scientific/`, `engine/`,
`src/nipat_scientific/`, `docker/`, `installer/runtime/` o al file `compose.yaml` impediscono il
riutilizzo di questo riferimento: non possono essere autorizzate come semplici
correzioni del client. Le differenze ammesse devono coincidere esattamente
con quelle dichiarate e revisionate. Documentazione e strumenti `.github`
di CI/pubblicazione non sono sorgenti operativi dell'applicazione; restano
soggetti alla revisione e ai controlli della pipeline.

L'equivalenza riguarda i sorgenti, non i byte degli installatori o l'ambiente
completo. Le evidenze non attribuiscono una prova manuale al nuovo EXE se non
è stato installato. L'accettazione per ricerca non trasforma i sei scenari
desktop rinviati in prove superate e non abilita automaticamente la
qualificazione della versione 1.0.

Nello schema 4 la prova precedente mantiene soltanto il ruolo
`historical-platform-evidence`. La candidata viene valutata sulle proprie
regressioni scientifiche, sul client Windows preparato, sul pacchetto Ubuntu
installato e sul suo aggiornamento effettivo dalla 0.7.1. Nessuna di queste
evidenze viene presentata come una nuova installazione manuale Windows.

I test automatici vengono estesi quando un difetto, un nuovo comportamento
o una condizione di confine possono essere riprodotti. Rimangono separati
la copertura automatica, l'esperienza su dispositivi reali e il giudizio
scientifico delle esperte di dominio.

## Pacchetti da provare

Usare una build **Installers (review build)** completata con successo sul
commit revisionato destinato alla distribuzione. La build deve provenire
da questo repository, essere avviata manualmente e avere superato il
controllo `installer-required`. Può essere eseguita sul branch di sviluppo
prima dell’integrazione: ciò consente di provare e accettare gli installatori
senza modificare `main`. I controlli automatici delle pull request non
producono un'autorizzazione alla distribuzione.

Le [note della versione 0.7.2](RELEASE_0.7.2.md) descrivono le funzionalità
e il riferimento manuale utilizzato per la valutazione. Costruire e provare
una candidata non richiede di dichiarare superati scenari non eseguiti o di
pubblicare una release. Ogni distribuzione richiede una propria decisione
associata ai pacchetti esatti.

La sequenza prevista è:

1. Avviare manualmente la build sul commit revisionato del branch di sviluppo.
2. Raccogliere le prove richieste dalla modalità scelta e compilare il record
   di accettazione, indicando esplicitamente i casi rinviati.
3. Dopo approvazione, integrare sorgenti e record in `main`, conservando
   il commit compilato nella sua storia.
4. Avviare **Prepare or publish verified release** da `main` con operazione
   `prepare` per creare una bozza completa degli stessi pacchetti.
5. Esaminare la bozza e avviare separatamente `publish`, indicando ID della
   bozza e commit di preparazione. Questa operazione ricontrolla le evidenze
   senza ricompilare o sostituire i file.

Una riscrittura dei commit durante l’integrazione può rendere il commit
compilato estraneo alla storia di `main`: in quel caso la pubblicazione
viene rifiutata. L’integrazione non equivale a pubblicazione automatica.

Conservare questi elementi della medesima build:

- `NIPAT-Setup.exe` da `nipat-windows-setup`;
- il `.deb` da `nipat-linux-setup`;
- `installer-manifest.json` e i checksum;
- `installer-set-check.json` da `nipat-installer-set-evidence`;
- `linux-upgrade-check.json` e il rapporto permanente di qualificazione
  richiesti dallo schema 4;
- ID e URL della build, commit completo e registri delle prove.

Verificare gli SHA-256 prima di installare. Non sostituire gli archivi
incorporati, ricompilare gli eseguibili o combinare artefatti di build diverse.
Se i pacchetti cambiano, l’accettazione precedente non si applica.
Gli artefatti Actions hanno scadenza: completare la revisione entro la loro
conservazione, oppure ripetere build e accettazione sui nuovi artefatti.
L’eventuale uso di una prova manuale precedente segue l'ambito dichiarato
dallo schema scelto, senza estenderne le osservazioni alla nuova candidata.

## Registrazione di ciascuna prova

La tabella seguente costituisce il catalogo della qualificazione desktop
completa. Nello schema 1 tutti i sei scenari devono essere superati;
negli schemi 2 e 3 per ricerca sono dichiarati esplicitamente come rinviati.
Le singole evidenze automatiche o manuali restano utilizzabili con il loro
ambito effettivo, senza attribuire loro la copertura dell’intero scenario.

Registrare sistema operativo e build, architettura, account utilizzato,
stato iniziale di WSL o Docker, versione NIPAT, commit, checksum del
pacchetto, data UTC, responsabile della prova e sequenza eseguita.
Conservare log di installazione, stato del runtime e run delle analisi.
Utilizzare dati sintetici o autorizzati alla condivisione; i nomi e i percorsi
nei log possono identificare i campioni.

Una prova è superata soltanto se sono soddisfatti tutti i criteri della
relativa riga. Un’interruzione, un passaggio non eseguito o un esito incerto
restano da verificare; non vanno registrati come `passed`.

| Chiave della prova | Ambiente e operazioni | Criteri di accettazione |
| --- | --- | --- |
| `windows_clean_wsl` | Windows 11 x64 senza NIPAT, Docker Desktop, Python o strumenti scientifici; WSL inizialmente non configurato. Eseguire l’EXE con doppio clic, autorizzare i componenti richiesti, completare l’eventuale riavvio e riaprire NIPAT dall’icona. Eseguire diagnostica, autotest e i quattro workflow con casi noti. Riavviare Windows e ripetere l’avvio. | La preparazione arriva a `ready` senza spostare file; il menu e i calcoli funzionano dal normale account; risultati e log sono accessibili; dopo il riavvio non servono comandi manuali per avviare il runtime. |
| `windows_stable_coexistence` | Windows 11 x64 con installazioni NIPAT 0.4 e 0.5 e dati di controllo, affiancate a NIPAT Desktop. Registrare prima e dopo percorsi, versioni, stato e inventario delle distribuzioni WSL. Avviare tutte le applicazioni. | NIPAT Desktop usa nome, cartelle, collegamenti e distribuzione propri. Applicazione, configurazione, dati e runtime delle altre installazioni NIPAT restano utilizzabili e non vengono adottati o sostituiti da NIPAT Desktop. |
| `windows_reinstall_removal` | Sull’installazione NIPAT Desktop preparata, eseguire i casi sotto riportati per percorsi personalizzati, reinstallazione, cambio di destinazione e rimozione. Provare entrambe le scelte di conservazione dell'ambiente, l'annullamento e un errore parziale. | Le preferenze vengono riproposte, i file esistenti restano nelle loro destinazioni e le analisi funzionano. La rimozione elimina applicazione e collegamenti; l'opzione aggiuntiva riguarda soltanto risorse verificate di NIPAT Desktop. Dati, risultati e risorse estranee rimangono invariati. |
| `ubuntu_clean_dependencies` | Ubuntu Desktop 24.04 x86_64 senza Docker Engine o Compose. Installare il `.deb` con APT, registrare le dipendenze installate e configurare l’accesso Docker tramite l’amministratore. Accedere nuovamente all’account se richiesto. Avviare dal menu applicazioni, eseguire preparazione, diagnostica, autotest e i quattro workflow; riavviare il sistema e ripetere l’avvio. | APT installa le dipendenze; l’account non riceve accesso Docker senza autorizzazione; il servizio e l’accesso funzionano dopo la configurazione e il riavvio. Menu e analisi sono eseguiti senza `sudo`; risultati e log appartengono all’utente. |
| `ubuntu_existing_docker` | Ubuntu Desktop 24.04 con Docker di sistema già configurato e risorse Docker estranee a NIPAT. Registrare versioni, endpoint e configurazione prima e dopo installazione, preparazione e analisi. | Il Docker compatibile viene riutilizzato; non vengono sostituiti repository, contesto globale, configurazione del daemon, immagini o container estranei. NIPAT usa il socket locale dichiarato. |
| `ubuntu_reinstall_removal` | Sull’installazione NIPAT Desktop preparata, conservare un run e un file di controllo; reinstallare lo stesso `.deb`, ripetere avvio e diagnostica, poi rimuovere `nipat-desktop` con APT. | Reinstallazione e avvio riescono; la rimozione elimina applicazione e collegamento, conservando dati, risultati, stato e immagini Docker. Le risorse Docker estranee non cambiano. |

Le prove possono essere ripartite tra più sistemi, registrando le condizioni
di ciascuno. Non è necessario modificare la configurazione di un computer
che contiene dati di ricerca per ottenere un ambiente iniziale pulito.

## Percorsi e rimozione su Windows

Associare a `windows_reinstall_removal` evidenze per tutti i casi seguenti.
Registrare le cinque destinazioni selezionate, l'inventario delle distribuzioni
WSL e i checksum dei file di controllo prima e dopo ciascuna operazione.

| Caso | Operazioni e criteri |
| --- | --- |
| Destinazioni personalizzate | Installare con cartelle applicazione, WSL, cache, dati e risultati separate, includendo un secondo disco locale fisso, spazi e caratteri non ASCII. Usare dati già presenti e verificare che restino invariati. Avviare menu, diagnostica e analisi; verificare risultati nella destinazione scelta e collegamento **Cartella NIPAT Desktop**. |
| Destinazioni non ammesse | Provare radici coincidenti o annidate, cartelle non scrivibili, cartella applicativa estranea non vuota, percorsi UNC, rete, supporti rimovibili, junction, cartelle di sistema e destinazioni stabili. Il setup deve rifiutarle senza modificare il contenuto protetto. |
| Reinstallazione e preferenze | Reinstallare lo stesso EXE nella cartella applicativa esistente; controllare la modalità **Aggiornamento e riparazione**, le cinque scelte riproposte, l'avvio e i run conservati. Ripetere dopo la disinstallazione, aggiungendo un file estraneo accanto ai residui riconoscibili di NIPAT Desktop: la riparazione deve riuscire senza eliminarlo. Le preferenze devono restare disponibili anche se ambiente e cache sono stati rimossi. |
| Backup e inventario | Preparare componenti modificati, un file estraneo che collide con il nome di un componente in arrivo e altri file estranei. Verificare la copia dei file da sovrascrivere, dei metadati e del Python generato nel backup selettivo prima delle sostituzioni; gli altri file devono rimanere invariati. Con un inventario precedente valido, verificare rimozione dei soli componenti obsoleti immutati; quelli modificati devono restare in posizione ed essere copiati nel backup. I file estranei non coinvolti nelle sostituzioni devono restare invariati senza essere inclusi nel backup. Un inventario del nuovo pacchetto non valido deve interrompere l'operazione; un inventario precedente danneggiato deve essere salvato senza autorizzare rimozioni di componenti obsoleti. |
| Inventario da manifest | Su un’installazione NIPAT Desktop priva di `.distribution/application-files.json`, verificare l'uso della mappa `source_sha256` di un manifest precedente valido. Provare schema, profilo, commit o mappa non validi: nessuna rimozione di file obsoleti deve essere autorizzata. Se `application-files.json` esiste ma è danneggiato, il manifest non deve sostituirlo per autorizzare rimozioni. |
| Cartella estranea | Selezionare una cartella non vuota non appartenente a NIPAT. Verificare la proposta di una sottocartella vuota e la conferma esplicita: il contenuto iniziale resta invariato. Rifiutare la proposta deve mantenere la selezione; una sottocartella già non vuota non deve essere svuotata né generare annidamenti ripetuti. |
| Distribuzione rimossa manualmente | Con dati sintetici, rimuovere da WSL una distribuzione posseduta da NIPAT Desktop mantenendone i registri. Il setup deve ricrearla soltanto nella destinazione vuota e archiviare la ricevuta precedente. Ripetere con un file di controllo nella destinazione: la preparazione deve arrestarsi senza cancellarlo. Verificare anche il riutilizzo della distribuzione ancora registrata e coerente. |
| Cambio di destinazione | Cambiare cartella WSL mantenendo lo stesso EXE: deve essere preparato un ambiente distinto e quello precedente deve restare intatto. Cambiare dati e risultati: nessun file preesistente deve essere spostato, cancellato o sovrascritto. Verificare nuovi run nella destinazione attiva e accesso ai precedenti. |
| Rimozione predefinita | Conservare ambiente e cache. Applicazione e collegamenti devono essere rimossi, mentre dati, risultati e risorse WSL/cache restano disponibili. Reinstallare e verificare il riutilizzo compatibile. |
| Rimozione facoltativa | Selezionare la rimozione di ambiente e cache dopo avere usato più destinazioni. Controllare che vengano rimosse soltanto distribuzioni possedute da NIPAT Desktop e archivi verificati delle destinazioni registrate, inclusi quelli conservati in precedenza. Dati e risultati di tutte le destinazioni, file estranei, Docker Desktop, altre installazioni NIPAT e altre distribuzioni devono restare invariati. |
| Annullamento e fallimenti | Annullare la disinstallazione prima della rimozione e verificare assenza di effetti. In un ambiente di prova controllato, simulare proprietà o cache non verificabili e un errore dopo una rimozione parziale; verificare arresto, messaggio, registri e risorse rimaste, quindi ripresa senza rimuovere dati o risorse estranee. |

Questi casi definiscono il collaudo completo dello scenario, non risultati
già acquisiti né un obbligo per ogni distribuzione pre-1.0. Non registrare
`windows_reinstall_removal` come superato se uno dei casi richiesti non è
stato eseguito o non dispone di evidenze.

## Configurazione e interazione

Includere nelle prove Windows e Ubuntu i seguenti controlli, conservando
il file delle preferenze e i record dei run quando condivisibili:

1. Salvare cartelle e valori predefiniti di ciascun workflow in **Configura**;
   chiudere e riaprire NIPAT e verificarne la persistenza.
2. Modificare un valore per la singola analisi: il riepilogo e `run.json`
   devono registrarlo, mentre le preferenze salvate devono restare invariate.
3. Verificare che campioni, coppie CPI e nomi dei run vengano richiesti ogni
   volta e non siano riproposti dalle preferenze.
4. Provare annullamento, ripristino esplicito, preferenze non valide e riferimenti
   mancanti. Le preferenze non valide devono impedire le analisi guidate fino
   alla correzione; il solo Invio nel riepilogo non deve avviare un'analisi.
   Dati e risultati devono essere conservati.
5. Avviare il menu con percorsi CLI espliciti e verificare che prevalgano nella
   sessione. Un comando diretto con argomenti invariati deve restare indipendente
   dalle preferenze del menu.
6. Aprire **Guida e informazioni** senza attivare controlli; eseguire quindi
   **Verifica ambiente** e verificare l'esito separato.

Queste verifiche integrano i sei scenari della qualificazione completa.
Registrare i casi svolti e mantenere distinti quelli non ancora eseguiti.

## Verifiche durante le analisi

Su Windows registrare anche lo stato di Smart App Control e gli eventuali
avvisi di Chrome, SmartScreen o antivirus. Provare download, setup, avvio,
abilitazione dei prerequisiti e disinstallazione con le protezioni attive.
Un blocco richiede il nome del componente e il testo dell'avviso; un'installazione
completata dopo un aggiramento non soddisfa questo controllo. Il pacchetto
non è firmato digitalmente da NIPAT: l'esito sul dispositivo deve essere
registrato senza attribuire al checksum il valore di una firma del distributore.

Per entrambi i sistemi includere input fuori dalla cartella dell’applicazione,
percorsi con spazi e caratteri non ASCII e una destinazione dei risultati
scelta dall’utente. Su Ubuntu includere input privati leggibili dal solo account.
Su Windows usare dischi locali fissi, coerentemente con i requisiti dichiarati.

Verificare almeno una sequenza DNPcall → Contamination usando l’output del
primo run come input del secondo. Eseguire SNPcall e CPI con i rispettivi
input e valori attesi. `self-test` non comprende una prova DNPcall da BAM:
questa analisi richiede un caso esplicito, completo di FASTA indicizzato.
Controllare conteggi e risultati pertinenti, non soltanto la presenza dei file.

Verificare che gli input originali non cambino, ogni analisi produca un run
separato, i metadati identifichino il runtime e un nome di run già esistente
non venga sovrascritto. Provare un input non valido e l’annullamento dal menu;
correggere il caso e avviare una nuova analisi. Conservare anche l’esito
negativo per documentare il messaggio e il recupero osservati.

Una reinstallazione della stessa build non verifica un aggiornamento fra
versioni differenti. Quest'ultimo richiede due pacchetti identificati dello
stesso canale e prove aggiuntive di sostituzione dei componenti, gestione
dell'inventario, conservazione dei dati, migrazione del runtime, interruzione
e ripresa. Le prove con inventari controllati verificano le regole di gestione
dei file, ma non sostituiscono questo collaudo dei pacchetti effettivi.

## Verifiche degli aggiornamenti

Registrare piattaforma, versione installata, canale scelto, release proposta,
checksum del pacchetto scaricato e risultato di ciascun passaggio. Le prove
con risposte GitHub simulate verificano i controlli del client; una prova
completa di aggiornamento richiede due pacchetti identificati dello stesso
prodotto e le rispettive evidenze di pubblicazione.

| Controllo | Criterio |
| --- | --- |
| Canali | `testing` considera pre-release e stabili approvate; `stable` esclude le pre-release. Bozze, build Actions, versioni non successive e manifest non coerenti non sono proposti. |
| Avviso all'avvio | Disattivato inizialmente; se attivato mostra soltanto un avviso e non avvia download, installazioni o interruzioni. |
| Assenza di rete | La ricerca segnala il problema e l'installazione già pronta continua a funzionare con il runtime locale. |
| Download | Nome, versione, piattaforma, dimensione e SHA-256 corrispondono alla release approvata; un file incompleto o alterato non può essere avviato come installatore. |
| Conferme e rinvio | Invio mantiene la scelta di rimandare. Download e installazione richiedono conferme distinte; annullamento o rinvio non modificano i componenti installati. |
| Installazione | La sessione corrente si chiude prima della sostituzione; un'analisi in altra sessione non viene terminata per consentire l'aggiornamento. Su Ubuntu verificare autorizzazione APT e comportamento senza terminale o Polkit. |
| Conservazione e riapertura | Percorsi, preferenze, dati e run esistenti restano disponibili. Il nuovo client avvia analisi soltanto dopo la preparazione verificata; un errore non viene presentato come aggiornamento completato. |
| Tracciabilità | Il run precedente conserva versione e runtime originari; il run successivo identifica la versione installata e il motore effettivamente utilizzati. |

Conservare separatamente l'esito dei controlli simulati e quello dei pacchetti
installati. Non attribuire a una reinstallazione della stessa build la verifica
di un aggiornamento fra versioni, né trasformare una candidata di revisione
in una release approvata per completare una prova.

## Record di accettazione

Dalla radice del repository, generare una scheda associata alle evidenze
della build:

```bash
python .github/scripts/release_acceptance.py \
  --installer-set /percorso/installer-set-check.json \
  --run-id ID_BUILD \
  --output /percorso/accettazione-da-compilare.json
```

Il comando genera il modello dello **schema 1**: riporta commit, versione
e checksum e inizializza la decisione e le prove come `pending`. Non esegue
le prove e non autorizza la pubblicazione. Compilare il record soltanto con
risultati realmente osservati.

### Schema 1: qualificazione desktop completa

Il record schema 1 contiene:

| Campo | Contenuto |
| --- | --- |
| `version`, `source_commit`, `build_run_id` | Versione, commit completo e ID numerico della build provata. |
| `installer_manifest_sha256` | SHA-256 del manifest comune. |
| `scientific_archive_sha256` | SHA-256 dell’archivio scientifico condiviso. |
| `windows_installer_sha256`, `linux_installer_sha256` | SHA-256 degli installatori effettivamente provati. |
| `decision` | `accepted` soltanto dopo il completamento di tutte le prove. |
| `tests` | Le sei chiavi della tabella; ciascuna con `result`, `tester`, `tested_at` ed `evidence`. |

Ogni prova accettata richiede `result: "passed"`, un responsabile identificato,
data UTC nel formato `YYYY-MM-DDTHH:MM:SSZ` e almeno un collegamento HTTPS alle
evidenze consultabili dai revisori. I riferimenti possono rimandare a rapporti
e registri appropriati al contenuto dei dati; non pubblicare dati sensibili
nei log o negli allegati del repository. Il controllo automatico verifica
struttura, completezza e coerenza del record; la valutazione dei rapporti
e degli esiti dichiarati resta responsabilità della revisione.

### Schema 2: accettazione per ricerca della serie 0.6

Lo schema 2 conserva i campi di identità e i quattro digest dello schema 1,
ma sostituisce la dichiarazione di qualificazione completa con una decisione
circoscritta:

| Campo | Contenuto |
| --- | --- |
| `schema_version` | `2`. |
| `decision`, `scope` | `accepted-for-research` e `pre-1.0-research`. |
| `review` | Responsabile, data UTC e riferimenti HTTPS della decisione. |
| `observed_baseline` | Commit effettivamente osservato, riferimenti alle evidenze e osservazioni ricevute. Sono obbligatori `installation_ready` e almeno uno fra `scientific_self_tests` e `dnp_sample_analysis`; `runtime_diagnostics` può completare la registrazione. |
| `observed_baseline.source_equivalence_scope` | `distributed-operative-sources-v1`; la procedura esegue il confronto dei sorgenti, non si limita alla dichiarazione nel record. |
| `deferred_desktop_scenarios` | Tutte le sei chiavi del catalogo desktop, esplicitamente rinviate. |
| `domain_validation` | `planned-for-0.7`. |

Non inserire `passed` per le prove rinviate o un checksum dell'installatore
precedente non disponibile. L'identità della candidata da pubblicare resta
completa e distinta da quella del riferimento manuale. Il confronto dei
sorgenti viene ripetuto prima della preparazione e della pubblicazione;
una differenza fuori dall'ambito ammesso interrompe la procedura.

### Schema 3: distribuzione per ricerca fino alla 0.7.1

Lo schema 3 conserva l'identità della build e i digest dei pacchetti e distingue
la prova manuale di riferimento dalle verifiche della nuova distribuzione:

| Campo | Contenuto |
| --- | --- |
| `schema_version` | `3`. |
| `decision`, `scope` | `accepted-for-research` e `pre-1.0-research`. |
| `review` | Responsabile, data UTC e riferimenti HTTPS della decisione. |
| `observed_baseline` | Commit effettivamente provato, riferimenti alle evidenze e osservazioni ricevute; descrive soltanto le prove realmente eseguite. |
| `observed_baseline.source_equivalence_scope` | `scientific-runtime-equivalence-with-reviewed-client-changes-v1`. |
| `reviewed_source_changes` | Elenco ordinato delle differenze operative ammesse: `path`, `before_sha256`, `after_sha256`; aggiunte e rimozioni hanno un lato `null`. |
| `deferred_desktop_scenarios` | Tutte le sei chiavi del catalogo desktop, esplicitamente rinviate. |
| `domain_validation` | `pending-domain-researchers`. |

La procedura confronta i file con Git: non si limita ad accettare gli hash
scritti nel record. Una differenza non dichiarata, un digest errato o una
modifica scientifica o del runtime interrompono la pubblicazione. I nuovi
pacchetti devono comunque superare la build completa e le prove automatiche
applicabili: client Windows preparato e pacchetto Ubuntu installato.

La prova Windows di riferimento della 0.7.1 riguarda il commit
`1b601081a4aff9efe1806c921fd7ac963feea7b7` e il workflow DNPcall → Contamination.
Il confronto numerico osservato comprende 11 siti DNP e 10 siti mantenuti da
Contamination, concordanti con le esecuzioni separate. Non equivale a un
collaudo manuale del nuovo EXE, dei casi CPI o di tutti i desktop destinatari.

### Schema 4: distribuzione per ricerca dalla 0.7.2

Lo schema 4 conserva identità della build, checksum dei pacchetti, decisione
`accepted-for-research`, revisione e scenari rinviati. Richiede inoltre:

| Campo | Contenuto |
| --- | --- |
| `schema_version` | `4`. |
| `qualification_evidence_sha256` | SHA-256 del rapporto permanente di qualificazione della candidata. |
| `linux_upgrade_check_sha256` | SHA-256 della prova di aggiornamento del pacchetto Ubuntu. |
| `observed_baseline.role` | `historical-platform-evidence`: descrive soltanto l'esperienza effettivamente osservata sulla piattaforma. |
| `observed_baseline.source_comparison_scope` | `reviewed-operative-changes-with-unchanged-r-v1`. |
| `reviewed_source_changes` | Differenze operative complete, con percorso e hash prima/dopo; include gli adattatori Python e il runtime quando cambiano. |
| `domain_validation` | `pending-domain-researchers`. |

La procedura confronta i byte effettivi dei sorgenti e rifiuta modifiche R,
differenze non dichiarate o hash non corrispondenti. Il resoconto del confronto
dichiara che non attesta equivalenza operativa né installazione manuale del
candidato Windows. Le verifiche richieste sono associate alla build esatta:
regressioni scientifiche, client Windows preparato, pacchetto Ubuntu installato,
aggiornamento reale dalla 0.7.1 e rapporto permanente delle evidenze.

Il rapporto dell'aggiornamento distingue il pacchetto precedente dalla candidata
e verifica la conservazione di dati e preferenze. Una reinstallazione dello
stesso pacchetto non soddisfa questo requisito. Gli hash dei rapporti sono
controllati insieme a quelli degli installatori prima della pubblicazione.

### Revisione e pubblicazione

Sottoporre il record a revisione in
`.github/release-acceptance/v0.7.2.json`, separatamente dal commit della
build da distribuire. Il record può essere preparato sul branch di sviluppo;
prima della pubblicazione, integrare in `main` sia il commit compilato sia
il record approvato. Quest’ultimo non è incorporato negli installatori.
Il publisher legge il file dal commit della procedura su `main`,
verifica i requisiti dello schema selezionato e confronta i checksum con gli
artefatti della build richiesta. Un record mancante, incompleto o riferito ad
altri file interrompe la pubblicazione prima della modifica di una release.

La [procedura di pubblicazione](../.github/RELEASE.md) descrive controlli,
caricamento degli asset e gestione delle bozze. L’accettazione tecnica non
abilita una pubblicazione automatica: il workflow di pubblicazione rimane
un’operazione manuale su `main`.

# Accettazione degli installatori

NIPAT Desktop 0.8.9 distribuisce Windows 10/11 x64, Ubuntu 24.04 x86_64 e
macOS 14 o successivo Intel/Apple Silicon. La decisione di distribuzione
identifica commit, build e checksum; distingue prove automatiche,
osservazioni sui dispositivi e validazione scientifica di dominio.

## Criteri di distribuzione pre-1.0

La distribuzione per ricerca richiede CI e build applicabili riuscite,
identità dei quattro pacchetti e dell'archivio scientifico comune verificata,
revisione delle modifiche e descrizione fedele delle prove svolte. I collaudi
desktop estesi possono essere rinviati. Una prova storica non diventa una
prova dell'installatore candidato; un test simulato non diventa una prova
sul computer del ricercatore. Il canale `stable` indica la versione ufficiale,
non una validazione scientifica generale.

Il record schema 6 per gli script R revisionati comprende tutti i campi
dello schema 5 e un riferimento aggiuntivo alle evidenze scientifiche:

| Campo | Contenuto |
| --- | --- |
| `version`, `source_commit`, `build_run_id` | Identità completa della build candidata. |
| `installer_manifest_sha256`, `scientific_archive_sha256` | Identità del manifest e dell'archivio comune. |
| `windows_installer_sha256`, `linux_installer_sha256` | Identità dei pacchetti Windows e Ubuntu. |
| `macos_arm64_installer_sha256`, `macos_x86_64_installer_sha256` | Identità dei due pacchetti Mac. |
| `decision`, `scope` | `accepted-for-research`, `pre-1.0-research`, dopo revisione. |
| `review` | Responsabile, data UTC e riferimenti HTTPS della decisione. |
| `observed_baseline` | Commit effettivamente osservato, prove ricevute, ruolo `historical-platform-evidence`. |
| `observed_baseline.source_comparison_scope` | `reviewed-operative-changes-with-tested-r-equivalence-v1` nello schema 6. |
| `reviewed_source_changes` | Elenco ordinato di percorso e hash prima/dopo; `null` per aggiunte o rimozioni. |
| `qualification_evidence_sha256`, `linux_upgrade_check_sha256` | Rapporti permanenti della candidata e aggiornamento reale Ubuntu dalla 0.7.2. |
| `macos_validation` | Stato separato `arm64`/`x86_64`: `passed` con evidenze HTTPS oppure `not-performed` con elenco vuoto. |
| `deferred_desktop_scenarios` | Scenari desktop estesi ancora da svolgere. |
| `scientific_equivalence` | Commit della baseline 0.8.5, percorso e SHA-256 del rapporto nel bundle di qualificazione e ID immutabile dell’immagine scientifica. |
| `domain_validation` | `pending-domain-researchers`. |

Lo schema 5 continua a richiedere script R vendorizzati invariati. Dalla
0.8.9 lo schema 6 permette la revisione dei quattro script R identificati e
del relativo manifest, mantenendo immutabile il riferimento 0.8.5. Il publisher
verifica i byte Git prima/dopo, il rapporto conservato nel bundle della build,
l’identità dell’immagine distribuita e gli hash dei sorgenti sottoposti ai test.
Richiede i confronti completi per tutti i quattro moduli: tabelle esatte, valori
R non arrotondati identici e rendering PDF esatto, oltre ai controlli mirati.
Il risultato è conservato in `scientific-equivalence-check.json`.
Il publisher confronta file e hash effettivi dei commit;
una differenza non dichiarata o un rapporto riferito ad altri pacchetti
interrompe la procedura. Le prove Mac non eseguite non impediscono di per sé
una distribuzione pre-1.0, ma devono rimanere dichiarate come tali.

## Pacchetti da provare

Usare una build manuale **Installers (review build)** completata sul commit
revisionato, con `installer-required` riuscito. Conservare EXE, DEB, entrambi
i PKG, manifest, checksum, rapporti e ID della build. Non combinare file
di build diverse. Le [note 0.8.9](RELEASE_0.8.9.md) descrivono le funzionalità;
i risultati di qualificazione devono riferirsi ai pacchetti esatti.

La sequenza è: costruire, raccogliere evidenze, revisionare il record,
integrare sorgenti e record in `main` conservando il commit compilato,
preparare la bozza, quindi pubblicarla con un secondo avvio esplicito.
La [procedura di pubblicazione](../.github/RELEASE.md) specifica i parametri.

## Registrazione di ciascuna prova

La tabella seguente costituisce il catalogo della qualificazione desktop
completa. Nello schema 1 tutti i sei scenari devono essere superati;
negli schemi 5 e 6 per ricerca sono dichiarati esplicitamente come rinviati.
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

Su tutte le piattaforme includere input fuori dalla cartella dell’applicazione,
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
| Conferme e rinvio | Invio mantiene la scelta di rimandare. Su Windows/Linux download e installazione richiedono conferme distinte; su Mac si conferma il download, si chiude NIPAT e si apre manualmente il PKG; annullamento o rinvio non modificano i componenti installati. |
| Installazione | La sessione corrente si chiude prima della sostituzione; un'analisi in altra sessione non viene terminata per consentire l'aggiornamento. Su Ubuntu verificare autorizzazione APT e comportamento senza terminale o Polkit. |
| Conservazione e riapertura | Percorsi, preferenze, dati e run esistenti restano disponibili. Il nuovo client avvia analisi soltanto dopo la preparazione verificata; un errore non viene presentato come aggiornamento completato. |
| Tracciabilità | Il run precedente conserva versione e runtime originari; il run successivo identifica la versione installata e il motore effettivamente utilizzati. |

Conservare separatamente l'esito dei controlli simulati e quello dei pacchetti
installati. Non attribuire a una reinstallazione della stessa build la verifica
di un aggiornamento fra versioni, né trasformare una candidata di revisione
in una release approvata per completare una prova.

## Prove macOS e risorse

Su Intel e Apple Silicon registrare separatamente versione macOS, hardware,
RAM, Lima, Rosetta quando applicabile e identità del PKG. Provare installazione,
avvio da Finder, preparazione, analisi, riapertura, reinstallazione e rimozione.
Segnalare gli avvisi Gatekeeper e le eventuali autorizzazioni richieste.
Una build nativa del pacchetto non sostituisce queste osservazioni.

Su tutte le piattaforme controllare nomi originali nelle tabelle e nei PDF,
`sample-map.tsv`, `run-report.html`, conservazione degli output canonici e
numeri invariati. Includere spazi, caratteri non ASCII e nomi uguali in cartelle
diverse, oltre a campioni e coppie dei workflow automatici.

Per WSL/Lima provare anteprima, annullamento, backup, conservazione delle
impostazioni estranee, modifiche concorrenti e rifiuto durante un'analisi.
Il riavvio globale WSL richiede una conferma separata. Su Ubuntu verificare
che NIPAT applichi soltanto limiti ai propri container. Distinguere un OOM
confermato da una terminazione con causa non accertata.

## Record di accettazione

Generare il modello dalla stessa build:

```bash
python .github/scripts/release_acceptance.py \
  --installer-set /percorso/installer-set-check.json \
  --run-id ID_BUILD \
  --output /percorso/accettazione-da-compilare.json
```

Per la 0.8.5 il comando genera lo schema 5 in stato `pending`; non esegue
prove né autorizza pubblicazioni. Compilare soltanto con evidenze disponibili
e revisionare `.github/release-acceptance/v0.8.5.json`. Il record è separato
dal commit e dai byte dell'installatore, e viene letto da `main` dal publisher.

Gli schemi precedenti rimangono disponibili per le relative release storiche.
La [scheda di validazione](VALIDAZIONE.md) raccoglie i casi di dominio;
l'accettazione tecnica non sostituisce la valutazione scientifica di dominio.

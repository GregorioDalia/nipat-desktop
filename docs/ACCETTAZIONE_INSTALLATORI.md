# Accettazione degli installatori

Questo protocollo verifica i pacchetti **NIPAT 0.5 Preview** su Windows 11 x64
con WSL2 e Ubuntu 24.04 LTS x86_64. Si applica agli installatori effettivi
che si intende pubblicare, identificati da commit, build GitHub Actions e
checksum. La riuscita della CI e gli autotest non sostituiscono queste prove.
La pubblicazione richiede un record di accettazione revisionato e coerente
con i pacchetti verificati; questo documento non ne attesta il completamento.

L’accettazione tecnica riguarda installazione, avvio, conservazione dei dati
e funzionamento dei workflow. La validazione scientifica sui dati e sugli
scenari d’uso è documentata separatamente in [VALIDAZIONE.md](VALIDAZIONE.md).
Una pre-release destinata alla valutazione di dominio non equivale a una
versione scientificamente validata per ogni impiego.

## Pacchetti da provare

Usare una build **Installers (review build)** completata con successo sul
commit revisionato destinato alla distribuzione. La build deve provenire
da questo repository, essere avviata manualmente e avere superato il
controllo `installer-required`. Può essere eseguita sul branch di sviluppo
prima dell’integrazione: ciò consente di provare e accettare gli installatori
senza modificare `main`. Le build automatiche di pull request servono alla
revisione e non sono pubblicabili.

La sequenza prevista è:

1. Avviare manualmente la build sul commit revisionato del branch di sviluppo.
2. Completare le prove e compilare l’accettazione dei file prodotti.
3. Dopo approvazione, integrare sorgenti e record in `main`, conservando
   il commit compilato nella sua storia.
4. Avviare il publisher da `main` per distribuire gli stessi file, senza
   una nuova build.

Una riscrittura dei commit durante l’integrazione può rendere il commit
compilato estraneo alla storia di `main`: in quel caso la pubblicazione
viene rifiutata. L’integrazione non equivale a pubblicazione automatica.

Conservare questi elementi della medesima build:

- `NIPAT-Setup.exe` da `nipat-windows-setup`;
- il `.deb` da `nipat-linux-setup`;
- `installer-manifest.json` e i checksum;
- `installer-set-check.json` da `nipat-installer-set-evidence`;
- ID e URL della build, commit completo e registri delle prove.

Verificare gli SHA-256 prima di installare. Non sostituire gli archivi
incorporati, ricompilare gli eseguibili o combinare artefatti di build diverse.
Se i pacchetti cambiano, l’accettazione precedente non si applica.
Gli artefatti Actions hanno scadenza: completare le prove entro la loro
conservazione, oppure ripetere build e accettazione sui nuovi artefatti.

## Registrazione di ciascuna prova

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
| `windows_stable_coexistence` | Windows 11 x64 con installazione NIPAT stabile e dati di controllo, affiancato alla Preview. Registrare prima e dopo percorsi, versioni, stato e inventario delle distribuzioni WSL. Avviare entrambe le applicazioni. | La Preview usa nome, cartelle, collegamenti e distribuzione propri. Applicazione, configurazione, dati e runtime della versione stabile restano utilizzabili e non vengono adottati o sostituiti dalla Preview. |
| `windows_reinstall_removal` | Sulla Preview preparata, eseguire i casi sotto riportati per percorsi personalizzati, reinstallazione, cambio di destinazione e rimozione. Provare entrambe le scelte di conservazione dell'ambiente, l'annullamento e un errore parziale. | Le preferenze vengono riproposte, i file esistenti restano nelle loro destinazioni e le analisi funzionano. La rimozione elimina applicazione e collegamenti; l'opzione aggiuntiva riguarda soltanto risorse verificate della Preview. Dati, risultati e risorse estranee rimangono invariati. |
| `ubuntu_clean_dependencies` | Ubuntu Desktop 24.04 x86_64 senza Docker Engine o Compose. Installare il `.deb` con APT, registrare le dipendenze installate e configurare l’accesso Docker tramite l’amministratore. Accedere nuovamente all’account se richiesto. Avviare dal menu applicazioni, eseguire preparazione, diagnostica, autotest e i quattro workflow; riavviare il sistema e ripetere l’avvio. | APT installa le dipendenze; l’account non riceve accesso Docker senza autorizzazione; il servizio e l’accesso funzionano dopo la configurazione e il riavvio. Menu e analisi sono eseguiti senza `sudo`; risultati e log appartengono all’utente. |
| `ubuntu_existing_docker` | Ubuntu Desktop 24.04 con Docker di sistema già configurato e risorse Docker estranee a NIPAT. Registrare versioni, endpoint e configurazione prima e dopo installazione, preparazione e analisi. | Il Docker compatibile viene riutilizzato; non vengono sostituiti repository, contesto globale, configurazione del daemon, immagini o container estranei. NIPAT usa il socket locale dichiarato. |
| `ubuntu_reinstall_removal` | Sulla Preview preparata, conservare un run e un file di controllo; reinstallare lo stesso `.deb`, ripetere avvio e diagnostica, poi rimuovere `nipat-05-preview` con APT. | Reinstallazione e avvio riescono; la rimozione elimina applicazione e collegamento, conservando dati, risultati, stato e immagini Docker. Le risorse Docker estranee non cambiano. |

Le prove possono essere ripartite tra più sistemi, registrando le condizioni
di ciascuno. Non è necessario modificare la configurazione di un computer
che contiene dati di ricerca per ottenere un ambiente iniziale pulito.

## Percorsi e rimozione su Windows

Associare a `windows_reinstall_removal` evidenze per tutti i casi seguenti.
Registrare le cinque destinazioni selezionate, l'inventario delle distribuzioni
WSL e i checksum dei file di controllo prima e dopo ciascuna operazione.

| Caso | Operazioni e criteri |
| --- | --- |
| Destinazioni personalizzate | Installare con cartelle applicazione, WSL, cache, dati e risultati separate, includendo un secondo disco locale fisso, spazi e caratteri non ASCII. Usare dati già presenti e verificare che restino invariati. Avviare menu, diagnostica e analisi; verificare risultati nella destinazione scelta e collegamento **Cartella NIPAT 0.5 Preview**. |
| Destinazioni non ammesse | Provare radici coincidenti o annidate, cartelle non scrivibili, cartella applicativa estranea non vuota, percorsi UNC, rete, supporti rimovibili, junction, cartelle di sistema e destinazioni stabili. Il setup deve rifiutarle senza modificare il contenuto protetto. |
| Reinstallazione e preferenze | Reinstallare lo stesso EXE nella cartella applicativa esistente; controllare la modalità **Aggiornamento e riparazione**, le cinque scelte riproposte, l'avvio e i run conservati. Ripetere dopo la disinstallazione, aggiungendo un file estraneo accanto ai residui riconoscibili della Preview: la riparazione deve riuscire senza eliminarlo. Le preferenze devono restare disponibili anche se ambiente e cache sono stati rimossi. |
| Backup e inventario | Preparare componenti modificati, un file estraneo che collide con il nome di un componente in arrivo e altri file estranei. Verificare la copia dei file da sovrascrivere, dei metadati e del Python generato nel backup selettivo prima delle sostituzioni; gli altri file devono rimanere invariati. Con un inventario precedente valido, verificare rimozione dei soli componenti obsoleti immutati; quelli modificati devono restare in posizione ed essere copiati nel backup. I file estranei non coinvolti nelle sostituzioni devono restare invariati senza essere inclusi nel backup. Un inventario del nuovo pacchetto non valido deve interrompere l'operazione; un inventario precedente danneggiato deve essere salvato senza autorizzare rimozioni di componenti obsoleti. |
| Inventario da manifest | Su una Preview priva di `.distribution/application-files.json`, verificare l'uso della mappa `source_sha256` di un manifest precedente valido. Provare schema, profilo, commit o mappa non validi: nessuna rimozione di file obsoleti deve essere autorizzata. Se `application-files.json` esiste ma è danneggiato, il manifest non deve sostituirlo per autorizzare rimozioni. |
| Cartella estranea | Selezionare una cartella non vuota non appartenente a NIPAT. Verificare la proposta di una sottocartella vuota e la conferma esplicita: il contenuto iniziale resta invariato. Rifiutare la proposta deve mantenere la selezione; una sottocartella già non vuota non deve essere svuotata né generare annidamenti ripetuti. |
| Distribuzione rimossa manualmente | Con dati sintetici, rimuovere da WSL una distribuzione posseduta dalla Preview mantenendone i registri. Il setup deve ricrearla soltanto nella destinazione vuota e archiviare la ricevuta precedente. Ripetere con un file di controllo nella destinazione: la preparazione deve arrestarsi senza cancellarlo. Verificare anche il riutilizzo della distribuzione ancora registrata e coerente. |
| Cambio di destinazione | Cambiare cartella WSL mantenendo lo stesso EXE: deve essere preparato un ambiente distinto e quello precedente deve restare intatto. Cambiare dati e risultati: nessun file preesistente deve essere spostato, cancellato o sovrascritto. Verificare nuovi run nella destinazione attiva e accesso ai precedenti. |
| Rimozione predefinita | Conservare ambiente e cache. Applicazione e collegamenti devono essere rimossi, mentre dati, risultati e risorse WSL/cache restano disponibili. Reinstallare e verificare il riutilizzo compatibile. |
| Rimozione facoltativa | Selezionare la rimozione di ambiente e cache dopo avere usato più destinazioni. Controllare che vengano rimosse soltanto distribuzioni possedute dalla Preview e archivi verificati delle destinazioni registrate, inclusi quelli conservati in precedenza. Dati e risultati di tutte le destinazioni, file estranei, Docker Desktop, NIPAT stabile e altre distribuzioni devono restare invariati. |
| Annullamento e fallimenti | Annullare la disinstallazione prima della rimozione e verificare assenza di effetti. In un ambiente di prova controllato, simulare proprietà o cache non verificabili e un errore dopo una rimozione parziale; verificare arresto, messaggio, registri e risorse rimaste, quindi ripresa senza rimuovere dati o risorse estranee. |

Questi casi sono requisiti di collaudo, non risultati già acquisiti.
Non registrare `windows_reinstall_removal` come superato se uno dei casi
richiesti non è stato eseguito o non dispone di evidenze.

## Verifiche durante le analisi

Su Windows registrare anche lo stato di Smart App Control e gli eventuali
avvisi di Chrome, SmartScreen o antivirus. Provare download, setup, avvio,
abilitazione dei prerequisiti e disinstallazione con le protezioni attive.
Un blocco richiede il nome del componente e il testo dell'avviso; un'installazione
completata dopo un aggiramento non soddisfa questo controllo. La verifica delle
firme deve riguardare i file finali: una firma applicata dopo il collaudo modifica
i digest e richiede una nuova candidata. Consultare la
[copertura della firma Windows](FIRMA_WINDOWS.md).

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

## Record di accettazione

Dalla radice del repository, generare una scheda associata alle evidenze
della build:

```bash
python .github/scripts/release_acceptance.py \
  --installer-set /percorso/installer-set-check.json \
  --run-id ID_BUILD \
  --output /percorso/accettazione-da-compilare.json
```

Il comando riporta commit, versione e checksum e inizializza la decisione
e le prove come `pending`. Non esegue le prove e non autorizza la pubblicazione.
Compilare il record soltanto con risultati realmente osservati.

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

Sottoporre il record a revisione in
`.github/release-acceptance/v0.5.0a1.json`, separatamente dal commit della
build provata. Il record può essere preparato sul branch di sviluppo;
prima della pubblicazione, integrare in `main` sia il commit compilato sia
il record approvato. Quest’ultimo non è incorporato negli installatori.
Il publisher legge il file dal commit della procedura su `main`,
verifica tutti i risultati e confronta i checksum con gli
artefatti della build richiesta. Un record mancante, incompleto o riferito ad
altri file interrompe la pubblicazione prima della modifica di una release.

La [procedura di pubblicazione](../.github/RELEASE.md) descrive controlli,
caricamento degli asset e gestione delle bozze. L’accettazione tecnica non
abilita una pubblicazione automatica: il workflow di pubblicazione rimane
un’operazione manuale su `main`.

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
| `windows_reinstall_removal` | Sulla Preview preparata, conservare un run e un file di controllo; reinstallare lo stesso EXE, ripetere avvio e diagnostica, poi disinstallare dal sistema. | Reinstallazione e avvio riescono senza alterare dati e risultati. La rimozione elimina applicazione e collegamenti della Preview e conserva dati e ambienti WSL previsti, senza modificare l’installazione stabile. |
| `ubuntu_clean_dependencies` | Ubuntu Desktop 24.04 x86_64 senza Docker Engine o Compose. Installare il `.deb` con APT, registrare le dipendenze installate e configurare l’accesso Docker tramite l’amministratore. Accedere nuovamente all’account se richiesto. Avviare dal menu applicazioni, eseguire preparazione, diagnostica, autotest e i quattro workflow; riavviare il sistema e ripetere l’avvio. | APT installa le dipendenze; l’account non riceve accesso Docker senza autorizzazione; il servizio e l’accesso funzionano dopo la configurazione e il riavvio. Menu e analisi sono eseguiti senza `sudo`; risultati e log appartengono all’utente. |
| `ubuntu_existing_docker` | Ubuntu Desktop 24.04 con Docker di sistema già configurato e risorse Docker estranee a NIPAT. Registrare versioni, endpoint e configurazione prima e dopo installazione, preparazione e analisi. | Il Docker compatibile viene riutilizzato; non vengono sostituiti repository, contesto globale, configurazione del daemon, immagini o container estranei. NIPAT usa il socket locale dichiarato. |
| `ubuntu_reinstall_removal` | Sulla Preview preparata, conservare un run e un file di controllo; reinstallare lo stesso `.deb`, ripetere avvio e diagnostica, poi rimuovere `nipat-05-preview` con APT. | Reinstallazione e avvio riescono; la rimozione elimina applicazione e collegamento, conservando dati, risultati, stato e immagini Docker. Le risorse Docker estranee non cambiano. |

Le prove possono essere ripartite tra più sistemi, registrando le condizioni
di ciascuno. Non è necessario modificare la configurazione di un computer
che contiene dati di ricerca per ottenere un ambiente iniziale pulito.

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
versioni differenti. Quest’ultimo richiede due pacchetti identificati dello
stesso canale e un protocollo aggiuntivo di conservazione dei dati, migrazione
del runtime, interruzione e ripresa. Non attribuire questo risultato alle
prove di reinstallazione richieste qui.

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

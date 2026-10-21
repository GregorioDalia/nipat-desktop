# Installatore Windows: compilazione e verifica

La pre-release **0.4.1** fornisce `NIPAT-Setup.exe` per **Windows 11 x64**:
un unico file con i componenti NIPAT incorporati, il launcher `NIPAT.exe` e
l'ambiente scientifico. L'alternativa `NIPAT-DockerDesktop-Setup.exe` installa
la stessa applicazione per l'uso con Docker Desktop già disponibile. Questo documento distingue costruzione e verifica tecnica
dei pacchetti dalla validazione scientifica; il rilascio è destinato al testing
di dominio, non ne dichiara il completamento.

**Perimetro della prima consegna per le prove di dominio (21 ottobre 2026):**
Windows 11 x64 con WSL2 già funzionante. Il percorso di attivazione iniziale
di WSL, UAC e ripresa dopo riavvio resta da verificare separatamente e non
blocca questa consegna. Su ogni PC il setup deve comunque completare gli
autotest e riportare `NIPAT: ready` prima delle analisi.

## Flusso previsto per l’utilizzo

1. Scaricare il solo [NIPAT-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-Setup.exe)
   dalla [pre-release v0.4.1](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.4.1).
2. Avviare il file dal proprio account Windows, senza “Esegui come amministratore”.
3. Il setup prepara l’applicazione e i componenti incorporati. Se WSL non è
   disponibile, richiede l’autorizzazione amministrativa per abilitarne i prerequisiti.
4. Se serve riavviare Windows, la configurazione riprende al successivo accesso
   allo stesso account. Il collegamento per la configurazione consente anche
   una ripresa manuale dopo un errore.
5. Il setup prepara l’ambiente Linux interno di NIPAT e lancia gli autotest.
   Attendere `NIPAT: ready`, poi aprire l'icona **NIPAT** sul desktop o nel
   menu Start. Il collegamento richiama `NIPAT.exe`, senza richiedere
   un terminale già aperto.

Il setup non richiede download separati dei componenti NIPAT né cartelle
di archivi da preparare. WSL permette di eseguire l'ambiente Linux interno su
Windows: la sua eventuale attivazione può richiedere Internet. Le analisi si
svolgono localmente.
Virtualizzazione disabilitata o restrizioni dell’ente possono impedire WSL e
richiedere intervento IT. L’installatore non modifica tali policy.

## Installatore per Docker Desktop

Scaricare [NIPAT-DockerDesktop-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-DockerDesktop-Setup.exe),
avviare Docker Desktop con container Linux e installare con doppio clic.
Il setup avvia automaticamente la preparazione degli strumenti, `doctor`
e gli autotest. Aprire **NIPAT (Docker Desktop)** per usare il menu: se la
preparazione non è terminata, l'icona la riprende automaticamente.
Dopo un errore si riprova dalla stessa icona. La normale procedura non
richiede estrazione di ZIP o avvio di `1_SETUP.cmd`.

La copia Docker Desktop usa `%LOCALAPPDATA%\Programs\NIPAT-DockerDesktop`
per l'applicazione e `%LOCALAPPDATA%\NIPAT-DockerDesktop\data` e `runs`
per dati e risultati predefiniti. Nella cartella applicativa,
`.runtime\setup.log` riepiloga la preparazione e `.runtime\setup-checks.log`
contiene i dettagli di `doctor` e degli autotest; conservarli entrambi. Queste cartelle sono separate
da quelle WSL. La [procedura di prova](VALIDAZIONE.md#prima-prova-con-docker-desktop)
registra preparazione e analisi sul pacchetto effettivamente usato.

## Componenti e confini del percorso WSL

- Applicazione per utente: `%LOCALAPPDATA%\Programs\NIPAT`.
- Dati e risultati predefiniti: `%LOCALAPPDATA%\NIPAT\data` e `runs`.
- Distribuzione WSL2 dedicata: per i nuovi ambienti,
  `NIPAT-Runtime-<prime 40 cifre dello SHA-256 del rootfs>`; il nome effettivo
  è registrato in `.runtime\backend.json`. La distribuzione delle versioni
  precedenti può chiamarsi `NIPAT-Runtime`.
- Python portabile 3.12.10, senza modificare il PATH del sistema.
- Docker Engine e Compose nel solo ambiente dedicato; Docker Desktop non serve.
- Runtime scientifico precompilato: archivio verificato con SHA-256 e immagine
  fissata all'ID restituito dal motore locale durante il caricamento.

Gli input rimangono nelle cartelle scelte dall’utente e vengono montati in
sola lettura. Il backend WSL inizialmente supporta percorsi su dischi locali fissi
Windows; condivisioni UNC e unità di rete non sono incluse. La GUI non fa parte
di questa revisione. Non vengono modificati gli algoritmi R.

La disinstallazione rimuove i file applicativi e la ripresa automatica, ma
conserva dati, risultati, cache e distribuzioni WSL. Il setup aggiorna
l'ambiente scientifico affiancandone uno nuovo quando cambia il rootfs, anche
se la modifica applicativa riguarda soltanto l'interfaccia.

### Aggiornamento dell'ambiente interno e ripresa

L'aggiornamento descritto riguarda l'ambiente Linux usato da NIPAT per le
analisi. È gestito dal setup dell'applicazione; non richiede di seguire una
procedura manuale di manutenzione di Windows o WSL.

Il nome del nuovo ambiente deriva dal digest del rootfs. Il setup registra la
proprietà di ciascun target in
`%LOCALAPPDATA%\NIPAT\wsl\registrations\<nome-distribuzione>.json`.
La precedente distribuzione e il vecchio `wsl\ownership.json` vengono
conservati. Un ambiente legacy può essere riutilizzato solo se corrisponde
allo stesso hash completo e supera i controlli di registrazione, prodotto e
proprietà. Un nome occupato da un ambiente non riconosciuto causa l'arresto
della preparazione, senza sostituzioni automatiche.

Prima di modificare lo stato del setup, viene salvata una sola copia delle
informazioni precedenti per il target in
`.runtime\installer\recovery\<commit>-<prime 16 cifre dello SHA-256 del rootfs>.json`.
La ripetizione della preparazione per lo stesso target conserva questa copia.
Si tratta di evidenze di configurazione, non di un backup dell'applicazione.
Le cartelle dati e risultati della configurazione precedente valida vengono
mantenute; gli input e i risultati non vengono trasferiti nel nuovo rootfs.

La preparazione carica l'immagine nell'ambiente candidato e vi esegue
`doctor --runtime` e `self-test`. Solo dopo il loro successo pubblica la nuova
configurazione del backend; lo stato `ready` è scritto per ultimo. La
configurazione e lo stato finale registrano il nome WSL e lo SHA-256 del rootfs.
Una ripetizione del setup riconosce il proprio target e riprende la preparazione.

In caso di errore, conservare `setup.log` e `state.json` e riaprire
**NIPAT - completa preparazione** oppure `1_SETUP.cmd` nell'installazione.
La distribuzione precedente, gli input e i risultati restano presenti.
L'applicazione appena installata rimane bloccata finché la configurazione
non termina: Inno Setup ha già sostituito i file applicativi prima di avviare
la preparazione, quindi non si tratta di un ripristino completo della versione
precedente. I file di recupero documentano lo stato precedente e non devono
essere copiati alla cieca sopra la configurazione corrente.

Non vengono eliminate automaticamente le vecchie distribuzioni. L'applicazione
è per utente: avviare il setup dal proprio account Windows, senza cambiare
account amministratore. Il comportamento descritto deve essere verificato sul
pacchetto finale con una prima installazione, un aggiornamento e una ripresa
reali su Windows; i test automatici della logica di migrazione sono evidenze
separate.

## Costruzione su GitHub

Il workflow `.github/workflows/windows-installer.yml`:

1. Su Windows esegue la suite Python e i controlli PowerShell 5.1, inclusi
   quelli della migrazione, poi compila e verifica `NIPAT.exe`. Conserva
   questo stesso eseguibile per i due pacchetti.
2. Solo dopo questi controlli costruisce l’immagine scientifica Linux ed
   esegue `doctor --runtime` e `self-test`. Esporta l’immagine verificata e
   costruisce l’archivio dell’ambiente WSL.
3. Registra commit, versioni dei pacchetti, dimensioni, ID immagine e SHA-256
   nel materiale di distribuzione. Ogni asset deve rientrare nel limite
   imposto dal builder per GitHub Releases.
   Carica inoltre l'archivio esportato in un motore nuovo del rootfs distribuito,
   esegue R e samtools e ripete il caricamento per verificare la ripresa del setup.
4. Prepara solo i sorgenti presenti in `distribution-files.txt`, il Python
   verificato e il manifest dell’installatore.
5. Su Windows recupera l'eseguibile già verificato, compila l'helper per WSL
   e l'installatore Inno Setup. Quest'ultimo incorpora anche i due archivi
   verificati dell'ambiente Linux e del runtime scientifico.
6. Prepara il pacchetto Docker Desktop con lo stesso launcher, gli stessi
   sorgenti e l'archivio scientifico già esportato, poi lo incorpora
   nell'installatore Docker Desktop. Lo ZIP viene conservato come artefatto
   di costruzione e verifica; per l'utilizzo si distribuisce il relativo EXE.

Il manifest fidato e i due archivi sono incorporati nell’EXE. Il setup estrae
automaticamente gli archivi nella cache dell'utente
`%LOCALAPPDATA%\NIPAT\cache`, con nomi che includono il relativo SHA-256.
La cache viene conservata per riprendere la preparazione dopo un'interruzione
o un riavvio; non occorre affiancare una cartella `assets` all'EXE.
Il setup verifica gli hash prima dell’importazione. Dopo `docker load`
acquisisce l'unico ID immutabile riportato per quell'archivio, verifica Linux
amd64 e lo usa per
le esecuzioni. L'ID della build viene conservato separatamente: il motore
classico identifica la configurazione dell'immagine, mentre containerd usa il
manifest/index. I due ID non sono quindi necessariamente uguali.
Non scarica un manifest sostitutivo dalla rete.

Il setup registra ID della build, ID locale e SHA-256 dell'archivio nello stato
e nella configurazione. Il launcher ne verifica la corrispondenza con la release.
Ogni ripresa del setup riverifica e ricarica l'archivio; l'avvio ordinario usa
direttamente l'ID locale registrato. Gli archivi esportati devono contenere una
sola immagine senza tag: risposte assenti, ambigue o con errori vengono rifiutate.

Il workflow **non pubblica automaticamente** una release. Conservare il log
e gli artefatti della compilazione utilizzata per le prove. Non ricostruire
un runtime diverso fra verifica e distribuzione.

## Prova prima della pubblicazione

Per la verifica tecnica prima di una futura pubblicazione usare gli artefatti
GitHub Actions di una sola build riuscita del workflow **Windows installer
(review build)**, identificata dal commit da verificare. Per provare `0.4.1`
già confezionato, utilizzare direttamente il pacchetto della
[release](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.4.1).

Per aggiornare una copia NIPAT WSL già installata:

1. Terminare le analisi e chiudere NIPAT. Annotare il nome della distribuzione,
   le cartelle dati/risultati e lo stato della versione installata leggendo
   `.runtime\backend.json` e `.runtime\installer\state.json`. Conservare una
   copia di questi piccoli file come evidenza della prova, senza modificarli.
2. Dalla stessa esecuzione GitHub scaricare **`nipat-windows-setup`** ed estrarre
   l'archivio fornito da GitHub Actions per ottenere **`NIPAT-Setup.exe`**.
   Questo solo EXE contiene tutto il necessario a NIPAT; non scaricare o
   sistemare gli archivi runtime separatamente. L'eventuale `NIPAT.exe`
   separato è un'evidenza della compilazione e non è l'installatore.
3. Fare doppio clic su `NIPAT-Setup.exe` dal proprio account Windows. Il setup
   estrae e verifica automaticamente i componenti incorporati.
   Se l'ambiente Linux interno cambia, ne prepara uno affiancato; non occorre
   disinstallare la versione precedente o modificare
   manualmente la configurazione. La presenza del vecchio ambiente e del nuovo
   richiede spazio per entrambi durante questa prova.
4. Attendere `NIPAT: ready`, poi aprire **NIPAT** dal menu Start. Verificare il
   banner, la presenza dell'interfaccia attesa e le cartelle dati/risultati.
   Confrontare nome della distribuzione e percorsi con quelli annotati prima:
   il nome può cambiare, mentre le radici configurate devono restare le stesse.
5. Controllare che i risultati precedenti siano ancora consultabili. Verificare
   il riavvio autonomo del nuovo ambiente e completare un'analisi reale con un
   caso noto. Registrare gli esiti nella scheda di validazione.

Per una prima installazione si usa lo stesso EXE, senza una configurazione
precedente da confrontare. Se la preparazione fallisce, registrare
l'errore e riprenderla con il collegamento di completamento; non modificare
`backend.json`, `ownership.json` o le registrazioni WSL per forzarne l'esito.
L'EXE dell'applicazione viene collocato dal setup nella cartella installata e
si avvia da lì, con tutti i suoi file di supporto.

Per la sola verifica tecnica del riavvio autonomo, leggere il nome dalla
configurazione della copia installata. Nei nuovi pacchetti non è necessariamente
`NIPAT-Runtime`:

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $nipatApp = Join-Path $env:LOCALAPPDATA 'Programs\NIPAT'
    $nipatConfig = Get-Content -LiteralPath (Join-Path $nipatApp '.runtime\backend.json') -Raw |
        ConvertFrom-Json
    if ($nipatConfig.backend -ne 'wsl' -or
        $nipatConfig.wsl_distro -cnotmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$') {
        throw 'Configurazione WSL NIPAT non valida: interrompere la prova.'
    }
    & "$env:WINDIR\System32\wsl.exe" --terminate $nipatConfig.wsl_distro
    if ($LASTEXITCODE -ne 0) { throw 'Arresto del runtime non riuscito.' }
    & (Join-Path $nipatApp 'NIPAT.exe') doctor --runtime
    if ($LASTEXITCODE -ne 0) { throw 'Riavvio autonomo del runtime non riuscito.' }
}
```

Questo controllo va eseguito senza analisi in corso. I comandi con il nome
fisso `NIPAT-Runtime` nella sezione storica sottostante descrivono soltanto il
candidato precedente. Per Docker Desktop usare il relativo installatore
della stessa build e seguire la preparazione descritta nella [guida](GUIDA_UTILIZZO.md).

Registrare versione di Windows, versione WSL, commit, ID del workflow e ID
immagine insieme agli esiti. La matrice completa di verifica dell'installatore
comprende i casi seguenti; i casi senza WSL funzionante rimangono fuori dal
perimetro della prima consegna per le prove di dominio:

| Caso | Esito da osservare |
| --- | --- |
| PC Windows senza WSL e senza Docker Desktop | Prerequisiti, eventuale riavvio, ripresa, importazione e autotest completi. |
| PC con WSL già disponibile | Ambiente NIPAT separato; distribuzioni preesistenti utilizzabili. |
| Riavvio successivo all’installazione | Il collegamento NIPAT avvia il motore senza operazioni manuali. |
| Configurazione fallita o interrotta | Errore leggibile, log e componenti incorporati conservati, ripresa senza preparare archivi manualmente. |
| Archivio alterato | Rifiuto prima dell’importazione. |
| Nome distribuzione già occupato da ambiente non NIPAT | Arresto con messaggio, nessuna sostituzione automatica. |
| Input su più unità locali, spazi e caratteri speciali | Tutti i workflow operativi, originali invariati, risultati nella cartella scelta. |
| Interruzione di un’analisi | Stato del run registrato e container dell’analisi fermato. |
| Aggiornamento da una versione NIPAT WSL precedente | Nuovo ambiente validato prima dell'attivazione; distribuzione precedente e cartelle dati/risultati conservate. |
| Interruzione o errore nell'aggiornamento | Applicazione bloccata senza falso `ready`; evidenze conservate e ripresa sullo stesso target. |
| Riesecuzione del setup e disinstallazione | Nessuna perdita di dati o risultati; indicazioni esplicite per gli ambienti conservati. |

La compilazione su GitHub non copre l’avvio di WSL e l’interazione con UAC
su un PC fisico. Gli autotest numerici non coprono tutti i casi DNPcall da BAM:
proseguire con la [scheda di validazione](VALIDAZIONE.md).

### Correzione e prova locale del setup (21 ottobre 2026)

Il candidato compilato dal commit `19507bb3991d636fef3e594b9636c5ae2ee656e4`
ha superato l'importazione WSL e il caricamento dell'archivio su un PC Windows.
Il controllo successivo cercava l'ID della build (`bbc352...`) mentre Docker
29.9.1 con containerd riportava `dc9773...`; il setup si arrestava correttamente
senza dichiarare l'installazione pronta. La correzione descritta sopra elimina
l'assunzione di identita' degli ID fra i due motori.

Sul PC di prova la correzione locale `image-id-v1`, applicata al candidato
di quel commit, ha poi permesso al setup di terminare con `NIPAT: ready`.
Il log fornito dall'utilizzatore documenta:

- 29 controlli dell'installer e 34 controlli dell'identita' dell'immagine
  superati da `powershell.exe` prima della sostituzione dei tre script.
- Caricamento dell'archivio verificato, risoluzione dell'ID locale `dc9773...`
  e preparazione di Python portabile 3.12.10.
- `doctor --runtime` superato nel backend `NIPAT-Runtime`, con R 4.4.2,
  pacchetti richiesti disponibili e samtools 1.21.
- Regressioni SNPcall (9 righe), CPI (valori CSV e tre PDF) e Contamination
  (riepilogo e valori per sito) superate.
- Quattro prove su input esterni superate: SNPcall da pileup, Contamination
  da directory ricorsiva, CPI con due pannelli e CPI ALL. I percorsi di prova
  includono spazi e caratteri speciali; gli input sono rimasti invariati.
- Avvio ordinario verificato dopo `wsl --terminate NIPAT-Runtime`:
  `nipat.cmd doctor --runtime` ha riavviato il motore dedicato, verificato
  l'immagine locale e le dipendenze; `2_AVVIA.cmd` ha aperto il menu CLI
  e si e' chiuso regolarmente con l'opzione 0.
- DNPcall da BAM reale nel run `ionxpress_008_wsl_20261021-121741-605`:
  11 siti corrispondenti al precedente run Docker Desktop. Il confronto ha
  incluso `chr`, `pos1`, `pos2`, `REF`, `ALT`, `N_REF`, `N_ALT`, `N_Other`,
  `GT`, `total_count` e `reads_discarded_for_indels` (11 colonne).

Questa evidenza riguarda il candidato con tre script corretti localmente,
non l'installazione completa di un nuovo EXE compilato dalla revisione corretta.
Il confronto BAM riguarda un solo campione e un risultato precedente dello
stesso programma: non è un riferimento scientifico indipendente. Restano da
verificare la prima installazione del nuovo EXE su un altro PC e il percorso
su Windows pulito, inclusi abilitazione WSL e riavvio Windows.

La prima esecuzione di questo nuovo controllo (`39580501326`) ha rilevato
un errore di estrazione dei whiteout nel container Linux del test. Il motore
annidato usava il filesystem overlay del container esterno come archivio.
Il test ora assegna volumi anonimi separati a `/var/lib/docker` e
`/var/lib/containerd`, registra il filesystem e rimuove quei volumi alla fine.
Questo adeguamento riguarda l'ambiente CI; il setup WSL continua a usare
il disco della propria distribuzione. Il controllo sugli errori di caricamento
rimane attivo, cosi' come l'esecuzione e il secondo caricamento dell'immagine.

La successiva [compilazione 39581854492](https://github.com/GregorioDalia/nipat-desktop/actions/runs/39581854492),
dal commit `0595c47179f93cf4426f66162875ae1e1035f5c8`, è terminata con successo:
suite Python su Linux e Windows (129 test ciascuna), 63 controlli PowerShell
su Windows PowerShell 5.1, regressioni scientifiche, caricamento/esecuzione/
ricaricamento dell'archivio nel motore Docker 29.9.2 con containerd distribuito
e compilazione dell'EXE. È evidenza di build e integrazione del runtime,
distinta dalle prove sul PC descritte sopra. Una modifica dei sorgenti inclusi,
anche della documentazione, richiede una nuova build coerente di EXE e asset.

## Pubblicazione della versione verificata

Dopo la revisione dei pacchetti, seguire
[.github/RELEASE.md](../.github/RELEASE.md) per pubblicare una **pre-release**
dal commit esatto compilato e integrato. La procedura trasferisce gli asset di
una build ammessa e riuscita, controllando manifest, sorgenti e checksum; una
build di pull request non è direttamente pubblicabile. Per la
doppia distribuzione vengono verificati anche il contenuto Docker incorporato
nell'EXE, il launcher comune e l'identità dell'archivio scientifico. Lo ZIP
resta un artefatto intermedio di verifica. Il file `SHA256SUMS`
della release comprende tutti gli asset pubblicati.

Riportare nelle note della release i controlli effettivamente superati e le
prove ancora aperte. Condividere il link alla versione con l'interfaccia
verificata. Il percorso principale richiede soltanto `NIPAT-Setup.exe`, con
gli archivi già incorporati; chi dispone di Docker Desktop può scaricare
`NIPAT-DockerDesktop-Setup.exe`.
`NIPAT.exe` è contenuto in entrambi i pacchetti e richiede i relativi file di
supporto: non distribuirlo isolatamente.

Verificare la firma del codice se disponibile; gli eseguibili compilati senza
certificato sono privi di firma e Windows può mostrare l'avviso per autore non
riconosciuto. Non sostituire gli asset di una versione già consegnata: usare
una nuova versione. Il codice originale NIPAT è GPL-3.0-or-later; conservare
[licenze e attribuzioni](../THIRD_PARTY_NOTICES.md) dei componenti inclusi e
rendere disponibili i materiali richiesti dalle rispettive licenze.

## Riferimenti tecnici

- [Installazione WSL](https://learn.microsoft.com/en-us/windows/wsl/install).
- [Importazione e comandi WSL](https://learn.microsoft.com/en-us/windows/wsl/basic-commands).
- [Docker Engine su Debian](https://docs.docker.com/engine/install/debian/).
- [Identificativi delle immagini con graphdriver e containerd](https://github.com/moby/moby/issues/51934).
- [Inno Setup: privilegi](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm).

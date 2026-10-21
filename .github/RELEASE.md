# Pubblicazione dei pacchetti verificati

Il workflow **Publish verified Windows pre-release** trasferisce gli asset da
una build riuscita a GitHub Releases senza ricompilarli o scaricarli sul PC
del manutentore. Si avvia manualmente da Actions sul branch `main`, indicando
l'ID della build **Windows installer (review build)** e il suo commit completo.
Il commit deve essere già integrato in `main`.

La [CI del ramo di sviluppo](../docs/CI_CD.md) esegue i controlli sulle pull
request e su `main`, con esito aggregato `required`. Il suo successo non
produce installatori pubblicabili. **Windows installer (review build)** resta
separato: si avvia manualmente oppure sulle pull request che modificano i
percorsi di installazione, runtime o packaging definiti nel workflow.
**Publish verified Windows pre-release** resta esclusivamente manuale.
Questa organizzazione e i nuovi vincoli delle dipendenze riguardano le build
successive; non modificano versione, tag o asset già pubblicati di `0.4.1`.

La versione `0.4.1` usa il tag `v0.4.1`, ma viene pubblicata con lo stato
GitHub **Pre-release** per la validazione di dominio. Il suffisso della
versione non determina questo stato: la procedura imposta e verifica sempre
`prerelease: true` e non contrassegna la pubblicazione come `Latest`.

La build esegue prima i controlli rapidi `windows-checks`, comprese le prove
di ripresa dell'aggiornamento WSL e del launcher compilato. Solo dopo il loro
successo costruisce ed esporta il runtime Linux. Il job finale scarica lo stesso
`NIPAT.exe` già verificato dall'artifact intermedio `nipat-tested-launcher` e lo
include in entrambi i pacchetti.

Il download standard per WSL e' **solo `NIPAT-Setup.exe`**. L'EXE include
Python, l'applicazione, il launcher e i due archivi runtime; l'utente non deve
creare una cartella `assets` o disporre altri file accanto all'installatore.
Dopo il setup avvia NIPAT dal collegamento creato. L'abilitazione di WSL resta
una funzione di Windows e puo' richiedere Internet o un riavvio.

Dalla versione `0.4.1`, anche Docker Desktop dispone di un singolo
installatore, **`NIPAT-DockerDesktop-Setup.exe`**. Include Python,
l'applicazione, il launcher e l'archivio scientifico; richiede Docker Desktop
già installato e avviato in modalità Linux. Al termine si apre il collegamento
**NIPAT (Docker Desktop)**. Non richiede immagini preesistenti: la preparazione
verifica e importa automaticamente l'archivio incluso, anche con Docker
Desktop vuoto, senza pull o build manuali né download separati del runtime.
Lo ZIP usato dalla build rimane un'evidenza interna
e non viene caricato fra i download della release.

La procedura verifica build, manifest, sorgenti, archivi e checksum, crea una
bozza sul commit compilato e carica l'installatore WSL, i due archivi runtime,
il manifest, l'installatore Docker Desktop e `SHA256SUMS` combinato.
Gli archivi runtime separati sono asset di recupero e verifica, non download richiesti
per l'installazione WSL standard. Sono conservati per mantenere validi i
collegamenti del manifest e il recupero automatico previsto dal setup.
Pubblica come pre-release solo dopo aver verificato dimensioni e
digest degli asset caricati. Non modifica release già pubblicate né tag di
altri commit; una bozza parziale può essere ripresa solo con gli stessi
contenuti verificati. Un errore lascia la bozza non pubblicata.
Per riprendere una bozza già creata si può indicare il suo ID nel campo
facoltativo `draft_release_id`; commit, note e asset vengono comunque verificati.

Per i nuovi candidati la stessa build deve conservare tre artifact:

- `nipat-windows-setup`: `NIPAT-Setup.exe`, `installer-manifest.json`,
  `SHA256SUMS` dell'installatore, `installer-build.json` e `NIPAT.exe` come
  evidenza del launcher compilato.
- `nipat-runtime-assets`: i due archivi, il manifest e i relativi checksum.
- `nipat-docker-desktop`: `NIPAT-DockerDesktop-<versione>-windows-x64.zip`
  e `package-build.json` con schema 1, versione, commit, nome, dimensione e
  SHA-256 dello ZIP e SHA-256 del launcher; dalla `0.4.1` include anche
  `NIPAT-DockerDesktop-Setup.exe` e `docker-installer-build.json`.

Per i nuovi candidati, `installer-build.json` deve riportare schema 1,
distribuzione `self-contained-wsl`, versione, commit, nome, dimensione e
SHA-256 dell'EXE, SHA-256 del manifest e del launcher, e nome/dimensione/SHA-256
di entrambi gli asset incorporati. Il publisher confronta questi dati con i
file e il manifest verificati e rifiuta un EXE di dimensione pari o superiore
a 2 GiB. Prima della compilazione, la build verifica gli archivi e l'include
Inno Setup generato; le voci `Source` degli archivi specificano il loro `Hash`,
che il compilatore controlla durante l'inclusione. I metadati collegano l'EXE
a questa build riuscita e ai suoi input; non sono una prova separata ottenuta
estraendo o installando l'EXE finale.

`docker-installer-build.json` usa schema 1 e distribuzione
`self-contained-docker-desktop`. Collega nome, dimensione e SHA-256 dell'EXE
a versione, commit, manifest, launcher, nome/dimensione/SHA-256 dello ZIP
interno e dimensione/SHA-256 dell'archivio scientifico. Il campo
`staged_files_sha256` contiene esattamente i file dello ZIP verificato,
con percorsi relativi all'applicazione, più il marcatore
`.distribution/docker-desktop.json` previsto dall'installatore. Il publisher
ricostruisce questi hash dai byte verificati: file mancanti, modificati o
aggiuntivi impediscono la pubblicazione. Il builder controlla lo stage prima
e dopo la compilazione e ogni voce Inno Setup specifica il proprio `Hash`.
Anche l'EXE Docker deve essere inferiore a 2 GiB e non avere archivi `.bin`
separati. Questi controlli vincolano l'EXE alla build riuscita e ai suoi input;
non costituiscono un'estrazione indipendente del suo contenuto.

Il publisher verifica anche il contenuto dello ZIP: esattamente i sorgenti
approvati e i componenti previsti, stesso commit e versione, stesso launcher
dell'installatore WSL, Python portabile fissato e identico archivio scientifico
verificato. File aggiuntivi, dati locali, sorgenti modificati o pacchetti di
build diverse impediscono la pubblicazione. Il solo `NIPAT.exe` non viene
pubblicato come download autonomo: richiede gli altri file del pacchetto.
La vecchia `0.3.0a1` mantiene il protocollo WSL originale senza ZIP Docker
e senza `installer-build.json`. La `0.4.0` conserva il download ZIP Docker;
dalla `0.4.1` il publisher richiede e pubblica l'EXE Docker, conservando lo ZIP
soltanto nell'artifact della build. Le evidenze dell'installatore WSL
autosufficiente rimangono obbligatorie per tutte le versioni successive
alla `0.3.0a1`.

Le build attivate da pull request rimangono destinate alla revisione e vengono
rifiutate dal publisher. Dopo l'integrazione in `main`, avviare manualmente
**Windows installer (review build)** sul commit da distribuire; usare poi
l'ID di questa build riuscita nella procedura di pubblicazione. La pubblicazione
riutilizza gli asset verificati, senza ricostruirli.

Le note provengono da `docs/RELEASE_<versione>.md` del commit compilato.
I file di questa procedura sono strumenti del manutentore: non fanno parte
dei sorgenti applicativi inclusi nell'EXE e non richiedono di ricostruire un
runtime già verificato. Le prove su Windows e di dominio rimangono distinte
dai controlli di pubblicazione.

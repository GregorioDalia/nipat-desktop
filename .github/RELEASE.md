# Pubblicazione dei pacchetti verificati

Il workflow **Publish verified Windows pre-release** trasferisce gli asset da
una build riuscita a GitHub Releases senza ricompilarli o scaricarli sul PC
del manutentore. Si avvia manualmente da Actions sul branch `main`, indicando
l'ID della build **Windows installer (review build)** e il suo commit completo.
Il commit deve essere già integrato in `main`.

La versione `0.4.0` usa il tag `v0.4.0`, ma viene pubblicata con lo stato
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

La procedura verifica build, manifest, sorgenti, archivi e checksum, crea una
bozza sul commit compilato e carica l'installatore WSL, i due archivi runtime,
il manifest, il pacchetto Docker Desktop e `SHA256SUMS` combinato.
Lo ZIP Docker Desktop e' un'alternativa per chi usa quel motore; gli archivi
runtime separati sono asset di recupero e verifica, non download richiesti
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
  SHA-256 dello ZIP e SHA-256 del launcher.

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

Il publisher verifica anche il contenuto dello ZIP: esattamente i sorgenti
approvati e i componenti previsti, stesso commit e versione, stesso launcher
dell'installatore WSL, Python portabile fissato e identico archivio scientifico
verificato. File aggiuntivi, dati locali, sorgenti modificati o pacchetti di
build diverse impediscono la pubblicazione. Il solo `NIPAT.exe` non viene
pubblicato come download autonomo: richiede gli altri file del pacchetto.
La vecchia `0.3.0a1` mantiene il protocollo WSL originale senza ZIP Docker
e senza `installer-build.json`; il pacchetto Docker e le evidenze
dell'installatore autosufficiente sono obbligatori per le altre pre-release.

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

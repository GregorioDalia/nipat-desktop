# Pubblicazione dei pacchetti verificati

Il workflow **Publish verified Windows pre-release** trasferisce gli asset da
una build riuscita a GitHub Releases senza ricompilarli o scaricarli sul PC
del manutentore. Si avvia manualmente da Actions sul branch `main`, indicando
l'ID della build **Windows installer (review build)** e il suo commit completo.
Il commit deve essere già integrato in `main`.

La procedura verifica build, manifest, sorgenti, archivi e checksum, crea una
bozza sul commit compilato e carica l'installatore WSL, i due archivi runtime,
il manifest, il pacchetto Docker Desktop e `SHA256SUMS` combinato.
Pubblica come pre-release solo dopo aver verificato dimensioni e
digest degli asset caricati. Non modifica release già pubblicate né tag di
altri commit; una bozza parziale può essere ripresa solo con gli stessi
contenuti verificati. Un errore lascia la bozza non pubblicata.
Per riprendere una bozza già creata si può indicare il suo ID nel campo
facoltativo `draft_release_id`; commit, note e asset vengono comunque verificati.

Per i nuovi candidati la stessa build deve conservare tre artifact:

- `nipat-windows-setup`: `NIPAT-Setup.exe`, `installer-manifest.json`,
  `SHA256SUMS` dell'installatore e `NIPAT.exe` come evidenza del launcher compilato.
- `nipat-runtime-assets`: i due archivi, il manifest e i relativi checksum.
- `nipat-docker-desktop`: `NIPAT-DockerDesktop-<versione>-windows-x64.zip`
  e `package-build.json` con schema 1, versione, commit, nome, dimensione e
  SHA-256 dello ZIP e SHA-256 del launcher.

Il publisher verifica anche il contenuto dello ZIP: esattamente i sorgenti
approvati e i componenti previsti, stesso commit e versione, stesso launcher
dell'installatore WSL, Python portabile fissato e identico archivio scientifico
verificato. File aggiuntivi, dati locali, sorgenti modificati o pacchetti di
build diverse impediscono la pubblicazione. Il solo `NIPAT.exe` non viene
pubblicato come download autonomo: richiede gli altri file del pacchetto.
La vecchia `0.3.0a1` mantiene il protocollo WSL originale senza ZIP Docker;
il pacchetto Docker è obbligatorio per le altre pre-release.

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

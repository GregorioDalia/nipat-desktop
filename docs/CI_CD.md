# Integrazione continua e distribuzione

NIPAT separa i controlli sui sorgenti, la costruzione degli installatori e la
pubblicazione. La versione 0.5.0a1 appartiene al canale Preview. La pipeline
produce installatori Windows WSL e Ubuntu per revisione. La pubblicazione
richiede una coppia di pacchetti verificata e un record di accettazione
revisionato, riferito agli stessi file. Il publisher verifica il record
prima di modificare una release.

## Workflow GitHub Actions

| Workflow | Attivazione | Risultato |
| --- | --- | --- |
| [CI](../.github/workflows/ci.yml) | Pull request, push su `main`, avvio manuale. | Test Linux/Windows, verifiche scientifiche quando richieste e controllo aggregato `required`. |
| [Installers (review build)](../.github/workflows/windows-installer.yml) | Pull request sui percorsi di packaging/runtime indicati nel file, oppure avvio manuale. | Installatore WSL e pacchetto Ubuntu con lo stesso archivio scientifico, prove ed evidenze di costruzione. |
| [Publish verified pre-release](../.github/workflows/publish-windows-release.yml) | Avvio manuale su `main`. | Verifica la coppia Windows/Ubuntu e l’accettazione dei file esatti, quindi pubblica una pre-release senza ricostruire gli asset. |

Una build di pull request serve alla revisione ed è rifiutata dal publisher.
Per la 0.5, una build destinata alla pubblicazione deve essere avviata
manualmente su un commit revisionato di questo repository; può provenire
dal branch di sviluppo prima dell’integrazione. I pacchetti vengono provati
e accettati su quel commit. Prima della pubblicazione, sorgenti e record di
accettazione devono essere integrati in `main`, conservando il commit
compilato nella sua storia. Il publisher opera da `main` e riusa gli stessi
artefatti verificati senza ricostruirli; non modifica release già pubblicate.

## Controlli sui sorgenti

I job `linux-checks` e `windows-checks` eseguono la suite Python su entrambi
i sistemi. Il primo comprende i test della selezione CI, del publisher e la
verifica sintattica dell'helper del motore. Il secondo comprende parsing con
PowerShell 5.1, protezioni del bootstrap, identità delle immagini, configurazione
WSL riprendibile e compilazione/prova del launcher.

Il job `scientific` costruisce il motore e avvia:

- `scripts/verify_engine_package.py`: quattro workflow nell'immagine, senza
  sorgenti applicativi montati, con aspettative numeriche e casi non validi;
- `python -m nipat doctor --runtime`: compatibilità e identità del motore;
- `python -m nipat self-test`: regressioni distribuite e modalità di input.

Le prove DNPcall includono BAM sintetici, campioni singoli e multipli, liste,
parità sequenziale/parallela e confronto con l'invocazione R. Le prove CPI
comprendono modalità dei pannelli, assenza di siti informativi e variazione
della costante d'errore. Le fixture dichiarano dati, valori attesi e tolleranze.

La selezione delle verifiche scientifiche è definita in
[`ci_changes.py`](../.github/scripts/ci_changes.py). Modifiche al motore, ai
sorgenti scientifici, all'esecuzione, alle fixture e alla configurazione
pertinente le rendono obbligatorie. Un avvio manuale le richiede sempre.
Se il confronto Git non riesce, vengono richieste per precauzione.
Le modifiche esclusivamente documentali possono evitare la ricostruzione
scientifica, mantenendo i controlli rapidi.

Il controllo conclusivo `required` viene valutato anche dopo un fallimento.
Riesce soltanto se i controlli rapidi e la selezione hanno avuto successo e
le prove scientifiche richieste sono riuscite. Un controllo obbligatorio
fallito, annullato o saltato impedisce un esito positivo.

Per un repository di distribuzione, configurare la protezione di `main` con
pull request obbligatoria, controllo `required`, branch aggiornato e divieto
di force push e cancellazione. Queste regole sono impostazioni di GitHub,
non vengono applicate automaticamente copiando i file del repository.

## Costruzione degli installatori

La build esegue i controlli Windows prima delle operazioni più costose.
Il medesimo `NIPAT.exe` compilato e verificato viene incorporato nell'installatore.
Successivamente costruisce e verifica il motore scientifico e il filesystem
WSL, esporta gli archivi e genera il manifest con commit, dimensioni e SHA-256.

Il test di importazione usa un motore isolato del filesystem WSL distribuito,
inizialmente privo dell'immagine. Carica l'archivio esportato, avvia R e samtools
e ripete il caricamento per verificare la ripresa. La compilazione Inno Setup
usa gli stessi archivi verificati, il profilo di installazione e il launcher.
La verifica finale Windows confronta manifest, sorgenti, EXE ed evidenze
di costruzione.

Il job `linux-installer` riceve il medesimo archivio esportato, senza
ricostruirlo, e prepara il pacchetto `nipat-05-preview` per Ubuntu 24.04 amd64.
Il builder verifica versione, commit, sorgenti e checksum, quindi produce
il `.deb`, il manifest e le evidenze. La prova installa il pacchetto con APT
su un runner con Docker configurato e avvia preparazione e analisi da
un account non root. Oltre agli autotest SNPcall, CPI e Contamination,
esegue DNPcall su BAM sintetico con confronto dei conteggi e dei genotipi
attesi. Usa input privati e percorsi con spazi e caratteri non ASCII;
verifica proprietà e accessibilità dei risultati, ripetizione dell’avvio,
reinstallazione dello stesso pacchetto e rimozione con conservazione dei
dati, dello stato e delle risorse Docker estranee. La reinstallazione
non equivale a una prova di aggiornamento fra versioni differenti.

Una prova separata usa un container Ubuntu 24.04 identificato da digest,
inizialmente privo delle dipendenze. Installa il `.deb` tramite APT e
verifica l’installazione di Python 3.12, `docker.io` e `docker-compose-v2`,
l’avvio di `--help` e `--version` da un account non root e l’assenza di
modifiche ai repository e di autorizzazioni Docker automatiche per l’utente.
Conserva versioni ed esiti in `linux-dependency-check.json`. Non avvia
un daemon nel container e non prova l’interfaccia Ubuntu Desktop.

Il job conclusivo `installer-required` richiede il successo dei pacchetti
Windows e Ubuntu e confronta commit, manifest e archivio scientifico nelle
evidenze dei due installatori. Richiede anche le prove Linux del ciclo
di installazione e delle dipendenze. Conserva l’esito in
`installer-set-check.json`, con `publication_authorized: false`: la verifica
automatica non costituisce accettazione sui sistemi destinatari.

| Artefatto Actions | Contenuto |
| --- | --- |
| `nipat-tested-launcher` | Launcher compilato e verificato. |
| `nipat-runtime-assets` | Archivio scientifico, filesystem WSL, manifest e checksum. |
| `nipat-installer-inputs` | Applicazione preparata e manifest destinati al compilatore. |
| `nipat-scientific-check-logs` | Registri e metadati delle regressioni conservati dalla build. |
| `nipat-windows-setup` | `NIPAT-Setup.exe`, manifest, checksum ed evidenze dell'installatore e del launcher. |
| `nipat-linux-setup` | Pacchetto `.deb`, manifest comune, checksum, evidenze di costruzione, installazione e risoluzione delle dipendenze. |
| `nipat-installer-set-evidence` | `installer-set-check.json`, esito della verifica congiunta Windows/Ubuntu. |

Gli artefatti Actions hanno una durata limitata indicata nel workflow.
Non equivalgono a una release pubblica. La versione 0.5 non produce un
installatore Docker Desktop.

## Dipendenze e riproducibilità

| Componente | Vincolo |
| --- | --- |
| Base scientifica | `rocker/r-ver:4.4.2` con digest nel Dockerfile. |
| Pacchetti R | Snapshot CRAN del 27 febbraio 2025 e versioni attese in [`r-packages.tsv`](../docker/scientific-runtime/r-packages.tsv), verificate durante la build. |
| samtools | Versione 1.21 e SHA-256 dell'archivio sorgente. |
| Filesystem WSL | Base Debian identificata da digest e versioni esplicite di Docker Engine/CLI, containerd, Buildx e Compose. |
| Python Windows | Archivio portabile 3.12.10 identificato e verificato dal builder. |
| Python Ubuntu | Pacchetto di sistema 3.12.x dichiarato nelle dipendenze del `.deb`. |
| Docker Ubuntu | Engine e Compose v2 del sistema, con accesso utente al socket locale; il launcher verifica la configurazione supportata. |
| Azioni GitHub | Riferimenti a commit espliciti nei workflow. |

L'immagine scientifica conserva gli inventari R e APT in
`/usr/share/nipat/r-versions.tsv` e `/usr/share/nipat/apt-versions.tsv`.
Il filesystem WSL conserva l'inventario APT e i metadati dei pacchetti Docker.
Le dipendenze di sistema risolte dai repository APT firmati non garantiscono
una ricostruzione identica byte per byte. L'unità di distribuzione è quindi
l'archivio esportato e verificato dalla build identificata.

La cache BuildKit accelera la compilazione, con ambiti distinti per le due
immagini `linux/amd64`. Non sostituisce test o verifiche degli asset.
Un errore nell'esportazione della cache non invalida una build che abbia
superato tutti i controlli di correttezza.

## Evidenze richieste per una distribuzione

Il successo della CI non dimostra l’installazione completa sui sistemi
destinatari. Le prove PowerShell simulano i confini Windows/WSL; il test
del motore interno usa Linux. La risoluzione APT in un container Ubuntu
non verifica riavvio, autorizzazione dell’account o apertura del collegamento
in un desktop reale.

Il [protocollo di accettazione](ACCETTAZIONE_INSTALLATORI.md) richiede prove
degli installatori effettivi su Windows e Ubuntu Desktop: prima installazione,
riavvio e analisi, coesistenza della Preview con NIPAT stabile su Windows,
Docker già presente su Ubuntu, reinstallazione dello stesso pacchetto e
rimozione con conservazione dei dati. Gli aggiornamenti fra versioni
differenti richiedono prove aggiuntive.

Il record di accettazione è sottoposto a revisione su `main` e identifica
build, commit, manifest, archivio scientifico e checksum dei due installatori.
Il publisher richiede tutte le prove completate e verifica nuovamente gli
artefatti prima di creare o modificare una bozza. Un record assente, ancora
`pending` o incoerente interrompe la pubblicazione. Gli artefatti accettati
non vengono ricostruiti; una nuova build con file differenti richiede una
nuova accettazione associata ai nuovi checksum.

Le prove di dominio utilizzano input e attese indipendenti dalle fixture di
regressione. Esiti, versioni e limiti sono registrati nella
[scheda di validazione](VALIDAZIONE.md). La procedura tecnica di pubblicazione
è descritta in [Pubblicazione](../.github/RELEASE.md).

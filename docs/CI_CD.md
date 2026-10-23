# Integrazione continua e distribuzione

NIPAT separa i controlli sui sorgenti, la costruzione degli installatori e la
pubblicazione. La versione 0.5.0a1 è una Preview non pubblicata. La pipeline
produce un installatore Windows WSL per revisione; la pubblicazione 0.5 è
bloccata finché il contratto di distribuzione Windows/Linux non è completo.

## Workflow GitHub Actions

| Workflow | Attivazione | Risultato |
| --- | --- | --- |
| [CI](../.github/workflows/ci.yml) | Pull request, push su `main`, avvio manuale. | Test Linux/Windows, verifiche scientifiche quando richieste e controllo aggregato `required`. |
| [Windows installer (review build)](../.github/workflows/windows-installer.yml) | Pull request sui percorsi di packaging/runtime indicati nel file, oppure avvio manuale. | Installatore WSL autosufficiente e relative evidenze di costruzione. |
| [Publish verified Windows pre-release](../.github/workflows/publish-windows-release.yml) | Avvio manuale su `main`. | Verifica e pubblicazione degli artefatti ammessi; rifiuta le versioni 0.5 finché il loro contratto di distribuzione è incompleto. |

Una build di pull request serve alla revisione ed è rifiutata dal publisher.
Una build destinata alla pubblicazione deve essere avviata manualmente sul
commit già integrato in `main`. La pubblicazione riusa gli artefatti verificati
senza ricostruirli; non modifica release già pubblicate.

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

## Costruzione dell'installatore Windows

La build esegue i controlli Windows prima delle operazioni più costose.
Il medesimo `NIPAT.exe` compilato e verificato viene incorporato nell'installatore.
Successivamente costruisce e verifica il motore scientifico e il filesystem
WSL, esporta gli archivi e genera il manifest con commit, dimensioni e SHA-256.

Il test di importazione usa un motore isolato del filesystem WSL distribuito,
inizialmente privo dell'immagine. Carica l'archivio esportato, avvia R e samtools
e ripete il caricamento per verificare la ripresa. La compilazione Inno Setup
usa gli stessi archivi verificati, il profilo di installazione e il launcher.
La verifica finale confronta manifest, sorgenti, EXE ed evidenze di costruzione.

| Artefatto Actions | Contenuto |
| --- | --- |
| `nipat-tested-launcher` | Launcher compilato e verificato. |
| `nipat-runtime-assets` | Archivio scientifico, filesystem WSL, manifest e checksum. |
| `nipat-installer-inputs` | Applicazione preparata e manifest destinati al compilatore. |
| `nipat-scientific-check-logs` | Registri e metadati delle regressioni conservati dalla build. |
| `nipat-windows-setup` | `NIPAT-Setup.exe`, manifest, checksum ed evidenze dell'installatore e del launcher. |

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

Il successo della CI non dimostra un'installazione reale. Le prove PowerShell
simulano i confini Windows/WSL; il test del motore interno usa Linux.
Prima di autorizzare una distribuzione occorrono prove del pacchetto effettivo
su Windows, inclusi prima installazione, riavvio, aggiornamento, ripresa dopo
errore e conservazione dei risultati. L'installer Linux richiede prove separate
sulla piattaforma dichiarata.

Le prove di dominio utilizzano input e attese indipendenti dalle fixture di
regressione. Esiti, versioni e limiti devono essere registrati nella
[scheda di validazione](VALIDAZIONE.md). La procedura tecnica di pubblicazione
è descritta in [Pubblicazione](../.github/RELEASE.md).

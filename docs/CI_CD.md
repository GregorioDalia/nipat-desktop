# Controlli automatici e pubblicazione

Questa procedura descrive i controlli introdotti nel ramo di sviluppo dopo
la pubblicazione di `0.4.1`. Si applica alle build successive e non modifica
il tag, gli installatori o gli altri asset già distribuiti. Gli esiti delle
esecuzioni GitHub Actions e delle prove reali su Windows vanno registrati
separatamente: la presenza di un workflow non attesta che la build sia riuscita.

## Tre procedure distinte

| Workflow | Attivazione | Scopo |
| --- | --- | --- |
| **CI** | Ogni pull request, ogni push su `main`, oppure avvio manuale. | Controlli rapidi Linux/Windows, regressioni scientifiche quando previste e controllo conclusivo `required`. Non produce installatori per la release. |
| **Windows installer (review build)** | Avvio manuale oppure pull request che modificano i percorsi di installazione, runtime o packaging elencati nel workflow. | Costruire e verificare entrambi gli installatori e i relativi artefatti. |
| **Publish verified Windows pre-release** | Solo avvio manuale su `main`, con ID della build e commit completo. | Verificare gli artefatti di una build ammessa e pubblicarli senza ricostruirli. |

La build completa degli installatori non parte per ogni modifica della CLI
o della documentazione. I filtri sono definiti in
[`windows-installer.yml`](../.github/workflows/windows-installer.yml);
comprendono installatore, Dockerfile, ingresso e moduli condivisi del motore,
script Windows e di packaging, elenco dei file distribuiti, configurazione del
pacchetto e relativi controlli.
Una build di pull request serve alla revisione e non è ammessa dal publisher.
Per distribuire un nuovo candidato occorre avviare la build completa sul
commit già integrato in `main`, quindi seguire
la [procedura di pubblicazione](../.github/RELEASE.md).

## Controllo CI richiesto

Il workflow [`CI`](../.github/workflows/ci.yml) esegue sempre:

- `linux-checks`: suite Python, controlli della selezione CI e della pubblicazione,
  sintassi del comando che avvia il motore interno;
- `windows-checks`: suite Python, sintassi PowerShell 5.1, controlli di setup,
  importazione del runtime, ripresa WSL e compilazione/prova del launcher.

Il job `scientific` costruisce il runtime, esegue `verify_engine_package.py`,
`doctor --runtime` e `self-test`. Il primo verifica tutti e quattro i workflow
completi senza mount dei sorgenti dell'applicazione, con input in lettura,
run in scrittura, rete disabilitata e filesystem dell'immagine in sola lettura.
Comprende valori numerici attesi, modalità di input, metadati del motore e casi
non validi; per DNPcall confronta anche esecuzione sequenziale/parallela, per CPI
l'effetto della costante d'errore con incompatibilità paterne sintetiche.
È richiesto per modifiche a `src/`, `scientific/`, `docker/`, `engine/`,
`tests/fixtures/`, agli script `verify_*` e `check_runtime_*`, alla configurazione
di esecuzione o ai file CI indicati in
[`ci_changes.py`](../.github/scripts/ci_changes.py). Un avvio manuale lo esegue
sempre. Se il confronto Git è indisponibile o fallisce, la verifica scientifica
viene richiesta comunque. Le modifiche esclusivamente documentali mantengono
i controlli rapidi e possono saltare la ricostruzione scientifica.

Il job conclusivo **`required`** viene valutato anche quando uno dei controlli
fallisce. Riesce solo se la selezione e tutti i controlli rapidi sono riusciti
e il job scientifico è riuscito, oppure è stato saltato perché non previsto.
Un controllo richiesto fallito, annullato o saltato non produce un esito verde.
Questo nome stabile permette di usare lo stesso controllo anche per le pull
request che modificano soltanto la documentazione.

La protezione di `main` richiede una pull request, il controllo `required`
riuscito e il branch aggiornato rispetto alla base. Non richiede un secondo
revisore: il manutentore può integrare la propria pull request dopo i controlli.
La regola impedisce anche force push e cancellazione di `main`, senza eccezioni
di bypass. È un'impostazione del repository GitHub, separata dai file del
workflow; quando si configura un fork occorre impostarla esplicitamente.
La build completa degli EXE rimane un requisito separato della procedura di
pubblicazione.

## Dipendenze e cache

Le nuove build rendono espliciti gli input usati per il runtime `0.4.1`:

| Componente | Vincolo e verifica |
| --- | --- |
| Base scientifica | `rocker/r-ver:4.4.2` con digest SHA-256 nel Dockerfile. |
| Pacchetti R | Snapshot CRAN del 27 febbraio 2025; le 13 versioni attese in [`r-packages.tsv`](../docker/scientific-runtime/r-packages.tsv) vengono verificate durante la build. Una differenza interrompe la costruzione. |
| samtools | Versione `1.21` e SHA-256 dell'archivio sorgente verificati prima della compilazione. |
| Ambiente WSL | Base Debian identificata da digest e versioni esplicite di Docker Engine/CLI, containerd, Buildx e Compose nel Dockerfile. |

Il runtime scientifico conserva gli inventari completi R e APT in
`/usr/share/nipat/r-versions.tsv` e `/usr/share/nipat/apt-versions.tsv`.
L'ambiente WSL conserva l'inventario APT e i metadati dei pacchetti Docker.
Le altre dipendenze di sistema vengono ancora risolte tramite i repository
APT firmati: non si garantisce una ricostruzione identica byte per byte.
Gli archivi esportati e verificati di una release restano gli artefatti da
distribuire; non vanno ricostruiti per sostituire quelli già pubblicati.

BuildKit usa la cache GitHub Actions con ambiti separati per il runtime
scientifico e l'ambiente WSL, entrambi `linux/amd64`. La cache riduce il lavoro
di compilazione, ma non salta `doctor`, gli autotest scientifici o i controlli
sugli asset previsti dal workflow. L'esportazione della cache può fallire senza
invalidare una build altrimenti riuscita: non è un controllo di correttezza.

## Docker Desktop inizialmente vuoto

Questo comportamento è già previsto dall'EXE pubblicato `0.4.1`:
`NIPAT-DockerDesktop-Setup.exe` include Python e l'archivio scientifico.
Con Docker Desktop installato e avviato in modalità Linux, la preparazione
verifica l'archivio incluso e lo importa automaticamente, anche in assenza
di immagini preesistenti. Non servono pull, build manuali o altri download dei
componenti NIPAT. Il percorso da soli sorgenti ha requisiti diversi, descritti
nella [guida per l'utilizzo](GUIDA_UTILIZZO.md).

I test PowerShell simulano anche un motore privo dell'immagine, controllando
che l'importazione preceda l'ispezione e che non vengano richiesti pull o build.
La build completa prova inoltre la funzione di importazione dell'applicazione
con un vero motore Linux isolato, inizialmente senza immagini, e avvia il runtime
importato. Queste prove non equivalgono a installare l'EXE finale su un PC con
Docker Desktop vuoto. Tale prova, gli aggiornamenti e la validazione scientifica con
input indipendenti si registrano nella [scheda di validazione](VALIDAZIONE.md).

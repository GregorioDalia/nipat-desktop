# Verifica e pubblicazione dei pacchetti

NIPAT distribuisce installatori costruiti e verificati da GitHub Actions.
La pubblicazione riutilizza gli stessi file, senza ricompilare applicazione
o runtime. Le versioni Desktop 0.8.2 e successive comprendono Windows 10/11 x64, Ubuntu 24.04 x86_64
e macOS Intel/Apple Silicon, con un archivio scientifico comune.

La distribuzione per ricerca pre-1.0 distingue controlli automatici, prove
osservate sui dispositivi e valutazione di dominio. Le prove desktop estese
possono essere rinviate esplicitamente. La scelta del canale `stable` identifica
la versione ufficiale, non una validazione scientifica generale.

## Documentazione pubblica

README, guide e note di versione devono essere autonomi e professionali:
descrivere funzionalità, requisiti, utilizzo e limiti tecnici pertinenti,
con esempi generici. Non includere riferimenti a conversazioni private,
collaboratori specifici o accordi di consegna estranei al funzionamento.
Conservare le attribuzioni e i riferimenti necessari alla provenienza e
alle verifiche. I record storici di accettazione mantengono identità,
ambito ed esiti originali; non attestano prove su versioni successive.

## Build identificata

Avviare manualmente **Installers (review build)** su un commit revisionato
di `main` oppure del branch `release/VERSIONE` o `release/VERSIONE-...`
corrispondente alla versione del pacchetto.
Il branch di sviluppo permette di costruire e verificare la candidata prima
dell'integrazione in `main`. Conservare il commit completo, non soltanto il
nome del branch o il numero di versione.

La build verifica il client, costruisce l'immagine scientifica, esegue le
regressioni, esporta l'archivio comune e confeziona i quattro installatori.
Il builder include soltanto i file ammessi da `distribution-files.txt` e i
componenti identificati dai manifest. Il controllo `installer-required`
confronta i pacchetti e le loro evidenze. Una build di pull request non è una
build di pubblicazione.

| Artefatto | Contenuto principale |
| --- | --- |
| `nipat-windows-setup` | `NIPAT-Setup.exe`, manifest, checksum, `installer-build.json`, `windows-client-check.json`. |
| `nipat-runtime-assets` | Archivio scientifico, filesystem WSL, manifest e checksum. |
| `nipat-linux-setup` | DEB, manifest, rapporti di confezionamento, installazione, dipendenze e aggiornamento. |
| `nipat-macos-setup-arm64` | PKG Apple Silicon e rapporto del pacchetto nativo. |
| `nipat-macos-setup-x86_64` | PKG Intel e rapporto del pacchetto nativo. |
| `nipat-scientific-check-logs` | Metadati e registri delle regressioni scientifiche. |
| `nipat-installer-set-evidence` | `installer-set-check.json`, identità congiunta dei quattro pacchetti. |

Il manifest collega versione, commit, architettura, archivio scientifico e
profilo `desktop`. La versione deve coincidere con il `pyproject.toml` del
commit compilato. Un archivio ricostruito, anche dallo stesso commit, richiede
verifica dei nuovi byte e un'accettazione corrispondente.

## Verifiche dei pacchetti

### Windows

`installer-build.json` collega EXE, manifest, launcher e archivi incorporati
tramite dimensioni e SHA-256. Il pacchetto è un unico `NIPAT-Setup.exe`, senza
file `.bin` separati; il solo launcher non costituisce un'installazione.

`windows-client-check.json` verifica il payload con il Python incorporato in
una destinazione isolata, incluse pianificazione e richieste con percorsi
complessi. Lo scenario `staged-embedded-python-client` non esegue il setup
Inno, la preparazione WSL o una prova su Windows 10 reale. Tali osservazioni
vanno registrate separatamente.

Dalla 0.8.20, `windows-installer-fixture-check.json` registra anche installazione,
aggiornamento e rimozione di una fixture compilata dalla definizione Inno
della candidata. Il rapporto identifica la definizione per SHA-256 e dichiara
che setup di produzione, WSL e Smart App Control non sono stati eseguiti.
`windows-trust-check.json` collega setup e inventario applicativo agli stati
Authenticode osservati, includendo i componenti del Python incorporato.
La verifica del publisher richiede questi rapporti e rifiuta identità
differenti o dichiarazioni improprie di collaudo Smart App Control.

### Ubuntu

Il DEB incorpora lo stesso archivio scientifico. Le verifiche eseguono APT,
preparazione, diagnostica e analisi da utente non root, reinstallazione e
rimozione conservando dati e preferenze. Una prova separata verifica le
dipendenze in un ambiente inizialmente privo dei pacchetti richiesti, senza
concedere automaticamente accesso Docker.

`linux-upgrade-check.json` identifica il precedente pacchetto 0.7.2 e la
candidata, verifica l'aggiornamento effettivo e la conservazione dei dati.
Reinstallare la stessa versione non soddisfa questo controllo. Il runner
configurato non viene presentato come un Ubuntu Desktop pulito.

### macOS

Ogni PKG incorpora Python e Lima nativi per l'architettura host e l'archivio
scientifico AMD64 comune. I rapporti verificano identità, contenuti e launcher
su runner Mac. Le prove Lima reali sono attivabili con
`qualify_macos_runtime` su runner dedicati; se non eseguite, il record indica
`not-performed` per l'architettura interessata.

La costruzione riuscita di un PKG non prova l'avvio della VM o l'accettazione
Gatekeeper sul computer destinatario. I checksum identificano gli artefatti,
non sostituiscono una firma del distributore o la notarizzazione Apple.

## Accettazione dei pacchetti

Il record della candidata è `.github/release-acceptance/vVERSIONE.json`.
Viene revisionato dopo la build e integrato in `main` insieme ai sorgenti,
conservando il commit compilato nella storia. Non fa parte del pacchetto.
La generazione del modello non equivale ad accettazione:

```bash
python .github/scripts/release_acceptance.py \
  --installer-set /percorso/installer-set-check.json \
  --run-id ID_BUILD \
  --output /percorso/accettazione-da-compilare.json
```

Per Desktop 0.8.2–0.8.8 il modello usa lo **schema 5**; dalla 0.8.9 usa lo
**schema 6** per i sorgenti R revisionati. La decisione iniziale è `pending`.
Una distribuzione per ricerca richiede:

- versione, commit, build e checksum dei quattro installatori, del manifest
  e dell'archivio scientifico;
- decisione `accepted-for-research`, responsabile, data UTC e riferimenti;
- prova storica identificata come `historical-platform-evidence`, senza
  attribuirla all'installazione della candidata;
- elenco completo delle modifiche operative con hash prima/dopo, secondo
  `reviewed-operative-changes-with-tested-r-equivalence-v1` nello schema 6
  (`reviewed-operative-changes-with-unchanged-vendored-r-v1` nello schema 5);
- R vendorizzato invariato nello schema 5; nello schema 6, revisione esplicita
  dei quattro script e confronto con i riferimenti congelati applicabili:
  dalla 0.8.30, SNPcall 2.0 per SNP e NIPAT 0.8.5 per gli altri tre moduli;
  regressioni della candidata e rapporto permanente
  di qualificazione, con prova dell'aggiornamento Ubuntu;
- `macos_validation` distinto per `arm64` e `x86_64`: `passed` con evidenze
  HTTPS oppure `not-performed` con elenco vuoto;
- scenari desktop rinviati e `domain_validation: pending-domain-researchers`.

Lo schema 5 permette la revisione degli adattatori di presentazione,
preservando gli script R vendorizzati. Lo schema 6 consente le modifiche
revisionate ai quattro script noti e a `scientific/SHA256SUMS`, richiedendo
`scientific_equivalence` con `reference_source_commit`, `report_path`,
`report_sha256` e `runtime_image`. Dalla 0.8.30 è inoltre rivedibile il solo
`scientific/vendor/NEWPAT/SNPcall/examples/output.txt`, aggiornato alle
17 colonne di SNPcall 2.0: deve comparire nel delta con gli hash esatti
prima/dopo. Gli input di esempio e gli altri asset scientifici restano protetti.
Il rapporto deve appartenere al bundle
`qualification-evidence.zip` della build accettata e confrontare sorgenti R
esattamente corrispondenti al commit e all’immagine distribuiti. Il publisher
verifica la baseline congelata contro il commit 0.8.5 e, dalla 0.8.30, anche
i byte del sorgente SNPcall 2.0 identificato nel rapporto. Il campo
`reference_source_commit` continua a identificare la baseline NIPAT 0.8.5;
il riferimento SNP distinto è conservato in `snp_reference` nel rapporto.
Tabelle e valori R non arrotondati devono coincidere con il riferimento
scientifico pertinente. Dalla 0.8.30 i PDF aggiornati richiedono verifiche
di contenuto e dimensioni, i controlli mirati degli istogrammi e rendering
identici tra le modalità seriale e parallele della candidata. Le release
precedenti mantengono il confronto dei rendering con la propria baseline.
L’esito è conservato in `scientific-equivalence-check.json`. Il confronto
verifica i byte Git, non si limita a leggere gli hash dichiarati. Gli schemi
precedenti rimangono utilizzati per le rispettive release storiche. Il
[protocollo di accettazione](../docs/ACCETTAZIONE_INSTALLATORI.md) descrive
prove e registrazione senza trasformare i casi non svolti in esiti positivi.

## Protezioni della pubblicazione

**Prepare or publish verified release** è manuale e opera su `main`.
Richiede la build completa riuscita, il commit presente nella storia di
`main`, il record approvato e i file corrispondenti. `testing` è predefinito;
`stable` accetta una versione numerica `MAJOR.MINOR.PATCH` e diventa `Latest`.
Non esiste pubblicazione automatica al push di un branch o tag.

### 1. Preparare la bozza

Avviare il workflow con `operation: prepare`, `run_id`, `source_commit`
completo e `channel`. Lasciare `preparation_commit` vuoto. La procedura:

1. verifica build, commit, versione e accettazione;
2. scarica e ricontrolla i quattro pacchetti e l'archivio comune;
3. confronta checksum, rapporti e revisione dei sorgenti;
4. usa le note `docs/RELEASE_VERSIONE.md` del commit di preparazione;
5. crea una bozza, carica i file e verifica dimensioni e digest restituiti;
6. riporta ID della bozza e commit della preparazione nel riepilogo Actions.

Esaminare note, canale, commit, nomi e contenuti. La bozza non è proposta
dall'aggiornatore. Una preparazione interrotta può riprendere sullo stesso
`draft_release_id` soltanto se i contenuti esistenti coincidono.

### 2. Pubblicare la bozza verificata

Avviare `operation: publish` con gli stessi build, commit e canale, più
`draft_release_id` e `preparation_commit` restituiti dalla preparazione.
Il commit della preparazione e quello del pacchetto hanno ruoli diversi.

La procedura ricontrolla evidenze e contenuti esatti della bozza, richiede
accettazione invariata e conserva le note della preparazione. Non crea bozze
mancanti, non carica file e non corregge asset alterati. Dopo la verifica,
`stable` diventa una release ufficiale `Latest`; `testing` una pre-release.

## Asset pubblicati e aggiornamenti

La release conserva quattro installatori, manifest, archivi del runtime,
checksum, rapporti di piattaforma, `desktop-acceptance.json`,
`baseline-source-check.json`, `release-provenance.json`,
`linux-upgrade-check.json` e `qualification-evidence.json`/`.zip`.
L'archivio delle evidenze contiene prove sintetiche e rapporti verificati;
non devono essere inclusi dati privati dei ricercatori.

`release-provenance.json` distingue commit del pacchetto, della procedura e
delle note. I due indici di aggiornamento sono:

| File | Destinatari |
| --- | --- |
| `update-manifest.json` | Windows e Linux; formato compatibile con i client 0.7.2. |
| `update-manifest-macos.json` | macOS ARM64 e Intel. |

Ogni indice identifica versione, tag, commit, canale e file della stessa
release, con piattaforma, dimensione e SHA-256. Il client verifica questi
campi e i byte scaricati. Su Mac il download verificato è seguito dalla
chiusura di NIPAT e dall'apertura manuale del PKG. Gli indici non firmano
i pacchetti: la fiducia nel download dipende da HTTPS e repository ufficiale.

Per installare, il ricercatore scarica soltanto il file della propria
piattaforma. Gli altri asset servono alla verifica o al recupero.

## Immutabilità degli artefatti pubblicati

Non sovrascrivere release o tag già pubblicati. Completare e verificare la
bozza prima della pubblicazione; una correzione richiede una nuova versione.
Un artefatto Actions scaduto non può essere sostituito da una ricostruzione
senza rivedere checksum e accettazione. Consultare [CI/CD](../docs/CI_CD.md)
per i livelli di test e i limiti delle prove automatiche.

# Verifica e pubblicazione dei pacchetti

NIPAT distribuisce installatori costruiti e verificati da GitHub Actions.
La pubblicazione riutilizza gli stessi file, senza ricompilare applicazione
o runtime. La versione 0.8.2 comprende Windows 10/11 x64, Ubuntu 24.04 x86_64
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
di `main`, `release/0.8.2` o `release/0.8.2-...`.
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

Il record della candidata è `.github/release-acceptance/v0.8.2.json`.
Viene revisionato dopo la build e integrato in `main` insieme ai sorgenti,
conservando il commit compilato nella storia. Non fa parte del pacchetto.
La generazione del modello non equivale ad accettazione:

```bash
python .github/scripts/release_acceptance.py \
  --installer-set /percorso/installer-set-check.json \
  --run-id ID_BUILD \
  --output /percorso/accettazione-da-compilare.json
```

Per la 0.8.2 il modello usa lo **schema 5**, con decisione iniziale `pending`.
Una distribuzione per ricerca richiede:

- versione, commit, build e checksum dei quattro installatori, del manifest
  e dell'archivio scientifico;
- decisione `accepted-for-research`, responsabile, data UTC e riferimenti;
- prova storica identificata come `historical-platform-evidence`, senza
  attribuirla all'installazione della candidata;
- elenco completo delle modifiche operative con hash prima/dopo, secondo
  `reviewed-operative-changes-with-unchanged-vendored-r-v1`;
- R vendorizzato invariato, regressioni della candidata e rapporto permanente
  di qualificazione, con prova dell'aggiornamento Ubuntu;
- `macos_validation` distinto per `arm64` e `x86_64`: `passed` con evidenze
  HTTPS oppure `not-performed` con elenco vuoto;
- scenari desktop rinviati e `domain_validation: pending-domain-researchers`.

Gli adattatori di presentazione sono revisionabili; questa regola non
permette modifiche ai metodi R vendorizzati. Il confronto verifica i byte Git,
non si limita a leggere gli hash dichiarati. Gli schemi precedenti rimangono
utilizzati per le rispettive release storiche. Il
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
4. usa le note `docs/RELEASE_0.8.2.md` del commit di preparazione;
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

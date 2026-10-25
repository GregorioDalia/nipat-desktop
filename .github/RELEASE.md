# Verifica e pubblicazione dei pacchetti

NIPAT distribuisce artefatti costruiti e verificati da GitHub Actions. La
pubblicazione non ricompila applicazione o runtime e non richiede al manutentore
di trasferire manualmente gli archivi dal proprio computer.

La versione 0.6 richiede installatori Windows e Ubuntu dello stesso commit
e con lo stesso archivio scientifico. La procedura verifica entrambi i
pacchetti e richiede una decisione di distribuzione riferita ai file esatti.
Per la 0.6 è ammessa l'accettazione per ricerca pre-1.0: integra una prova
manuale documentata di installazione e funzionamento con i controlli automatici,
rendendo espliciti i collaudi estesi ancora da svolgere. Le versioni
pubblicate e le relative evidenze sono disponibili nella pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
Un record assente o incompleto interrompe la pubblicazione prima della
creazione o modifica di una release.

Questo documento descrive le evidenze di build e le protezioni della procedura.
La riuscita dei controlli automatici non autorizza da sola una distribuzione:
le prove del pacchetto reale e la validazione di dominio sono registrate
separatamente nella [scheda di validazione](../docs/VALIDAZIONE.md).

## Build identificata

Il workflow **Installers (review build)** compila `NIPAT.exe`, ne esegue
le prove e conserva quello stesso file per il confezionamento. Costruisce
l'immagine scientifica, verifica i quattro workflow, esporta l'archivio e
costruisce il filesystem WSL. Verifica inoltre il caricamento, l'esecuzione
e il ricaricamento dell'archivio nel motore interno distribuito.
Si avvia manualmente dal branch e dal commit scelti per la distribuzione.
La CI automatica continua a verificare ogni aggiornamento dei sorgenti, ma
non produce installatori completi a ogni push.

Il builder prepara soltanto i file ammessi da `distribution-files.txt`, Python
portabile verificato e i componenti previsti. La compilazione Inno Setup usa
il manifest fidato, il profilo del canale e i due archivi verificati.
Il risultato Windows è un unico **`NIPAT-Setup.exe`**, contenente tutti i
componenti NIPAT necessari. Il solo `NIPAT.exe` non è un pacchetto autonomo.

Il pacchetto Ubuntu è un unico `.deb`: contiene i sorgenti ammessi e lo stesso
archivio scientifico, senza il filesystem WSL. La build verifica il contenuto,
esegue installazione e preparazione su un runner Ubuntu 24.04 e conserva
evidenze separate da quelle Windows.

Gli artefatti da conservare per la verifica dei pacchetti sono:

| Artefatto | Evidenze |
| --- | --- |
| `nipat-windows-setup` | `NIPAT-Setup.exe`, `installer-manifest.json`, `SHA256SUMS`, `installer-build.json` e launcher verificato. |
| `nipat-runtime-assets` | Archivio scientifico, filesystem WSL, manifest e relativi checksum. |
| `nipat-linux-setup` | `.deb`, manifest comune, checksum, `linux-installer-build.json`, `linux-installation-check.json` e `linux-dependency-check.json`. |
| `nipat-scientific-check-logs` | Metadati e registri delle regressioni conservati dalla build. |
| `nipat-installer-set-evidence` | `installer-set-check.json`, verifica congiunta di sorgenti e archivio scientifico Windows/Ubuntu. |

Il manifest identifica versione, tag previsto, commit, piattaforma, archivio
scientifico, filesystem WSL e profilo di installazione. Il profilo deve
corrispondere al sorgente del commit e al canale `desktop`.
La versione del manifest deve coincidere con quella del `pyproject.toml`
committato: un manifest non può scegliere un protocollo di distribuzione diverso.
Usare il commit completo indicato dal manifest e dal riepilogo della build.
Un eventuale artefatto storico di pull request può provenire da un merge
temporaneo, diverso dalla testa del branch: quell'evento non è ammesso alla
pubblicazione. Il confronto della sola versione non identifica gli stessi byte.

## Verifica dell'installatore Windows

`installer-build.json` usa schema 1 e distribuzione `self-contained-wsl`.
Collega versione e commit ai seguenti elementi:

- nome, dimensione e SHA-256 dell'EXE;
- SHA-256 del manifest e del launcher;
- nome, dimensione e SHA-256 dei due archivi incorporati;
- profilo di installazione previsto dal canale.

La verifica confronta le evidenze con i file effettivi e i sorgenti del commit.
Prima della compilazione, il builder verifica il profilo e gli include Inno
Setup generati; le voci degli archivi specificano l'hash che il compilatore
controlla durante l'inclusione. L'installatore deve essere inferiore a 2 GiB
e non richiedere archivi `.bin` separati.

La funzione `prepare_assets` del publisher verifica i pacchetti Windows
anche durante la build, indipendentemente dall’accettazione richiesta per
pubblicarli. Rifiuta evidenze mancanti, file provenienti da build diverse,
un profilo incoerente e
artefatti Docker Desktop. Questi controlli legano l'EXE alla build e ai suoi
input; non costituiscono una verifica ottenuta installando o estraendo
indipendentemente l'eseguibile finale.

Gli archivi runtime separati servono a recupero e verifica. La normale
installazione Windows usa soltanto l'EXE; non richiede che l'utente disponga
gli archivi accanto all'installatore.

## Verifica del pacchetto Ubuntu

`linux-installer-build.json` usa schema 1 e distribuzione `native-linux-deb`.
Collega pacchetto, versione, commit, dimensione e SHA-256 del `.deb` al
manifest comune e all’archivio scientifico incorporato. Il builder richiede
sorgenti coerenti con il commit e verifica i byte prima del confezionamento;
l’archivio non viene esportato o compresso nuovamente.

`linux-installation-check.json` documenta le prove del pacchetto effettivo
su un runner Ubuntu 24.04 con Docker configurato. L’installazione e la
rimozione usano APT; preparazione, diagnostica e analisi sono eseguite da
un utente non root. I controlli comprendono i casi distribuiti di SNPcall, CPI
e Contamination e un caso DNPcall sintetico, proprietà dei risultati e
conservazione dei dati dopo reinstallazione dello stesso pacchetto e
rimozione. Non attestano un aggiornamento fra versioni differenti.

Una prova distinta installa il `.deb` in un container Ubuntu 24.04
inizialmente privo delle dipendenze. `linux-dependency-check.json` identifica
il pacchetto e registra l’installazione APT di Python, Docker Engine e
Compose v2 dai repository configurati. Controlla inoltre i comandi
informativi da un utente non root, senza avviare un daemon o concedere
automaticamente accesso Docker. Non è una prova su Ubuntu Desktop.

Il controllo `installer-required` confronta commit, manifest comune e
checksum scientifico dei due pacchetti, verifica entrambe le evidenze
Linux e conserva `installer-set-check.json`.
Questa corrispondenza lega gli installatori alla stessa esportazione.
Le evidenze di build non sostituiscono le prove su Windows e Ubuntu Desktop puliti. I dettagli
operativi del pacchetto sono nell’[installatore Linux](../docs/INSTALLATORE_LINUX.md).

## Accettazione dei pacchetti

Il pacchetto Windows non è firmato digitalmente da NIPAT. La verifica dei
checksum identifica i file approvati ma non autentica un distributore per
Windows. Registrare l'esito con le protezioni dei dispositivi destinatari
attive, inclusi eventuali blocchi del browser, di Smart App Control o antivirus.

Il [protocollo di accettazione](../docs/ACCETTAZIONE_INSTALLATORI.md) definisce
le prove sui sistemi destinatari. Una scheda generata con
`release_acceptance.py` parte da `pending` e non costituisce un’autorizzazione.
Il record distingue due modalità:

- **Schema 1, qualificazione completa:** richiede tutti i sei scenari desktop
  superati sugli installatori esatti della build.
- **Schema 2, distribuzione per ricerca pre-1.0:** richiede una decisione
  esplicita del manutentore, una prova manuale osservata di installazione e
  funzionamento, le evidenze automatiche e l'elenco delle prove rinviate.
  La 0.6 usa questa modalità; la valutazione con le esperte di dominio è
  pianificata sulla 0.7. Il numero di versione o il canale `stable` non
  trasformano questa accettazione in una validazione scientifica.

Quando la prova manuale riguarda una build precedente, il record ne conserva
il commit effettivo. La procedura confronta i sorgenti operativi di quella
build con quelli della candidata secondo l'ambito definito nel validatore.
Un confronto riuscito permette di riutilizzare la prova come riferimento,
ma non attesta che il nuovo EXE sia stato installato né che i due pacchetti
siano identici. Il confronto e i limiti sono parte delle evidenze della release.

Il record viene sottoposto a revisione in
`.github/release-acceptance/v0.6.0.json` e integrato in `main` prima della
pubblicazione, insieme al sorgente accettato. Può essere preparato e
revisionato sul branch di sviluppo dopo le prove. È separato dai file
incorporati negli installatori e dal commit della build provata. Collega versione,
commit, ID della build, manifest comune, archivio scientifico e checksum
di entrambi gli installatori alla decisione, alle prove osservate e ai limiti
dichiarati, con responsabile, data e collegamenti alle evidenze. Il successo
della build non compila o approva automaticamente questo record.

Il publisher legge l’accettazione dal commit della procedura su `main`.
Un record mancante o non accettato interrompe l’operazione; dopo il download,
i checksum devono coincidere con quelli dei pacchetti effettivi. Se gli
artefatti scadono o vengono ricostruiti, non riutilizzare l’accettazione
per file con digest differenti. La data di scadenza è quella indicata
dalla conservazione degli artefatti Actions.

## Protezioni della pubblicazione

Il workflow **Prepare or publish verified release** è esclusivamente manuale e
opera su `main`. Richiede l'ID della build, il suo commit completo e il canale
`testing` o `stable`. `testing` è predefinito e pubblica una pre-release;
`stable` pubblica una release stabile e accetta soltanto versioni numeriche
`MAJOR.MINOR.PATCH`. La scelta del canale non modifica i requisiti della
modalità di accettazione selezionata. Lo schema pre-1.0 attuale è limitato
alla serie 0.6; i criteri delle versioni successive richiedono una revisione
esplicita. Per la 0.6, avviare manualmente **Installers (review build)** su un commit
revisionato di questo repository: può essere il branch di sviluppo, così
che le prove e l’accettazione precedano l’integrazione in `main`.

Dopo l’approvazione, integrare sorgenti e record di accettazione conservando
il commit compilato nella storia di `main`. Il publisher verifica esito
della build, corrispondenza del commit e sua appartenenza alla storia di
`main` al momento della pubblicazione. Riutilizza gli artefatti accettati
della build manuale, senza ricostruirli dopo l’integrazione. Le build di
pull request vengono rifiutate. Il successo del solo workflow CI non
sostituisce una build completa degli installatori.

La distribuzione richiede due avvii separati dello stesso workflow.

### 1. Preparare la bozza

Selezionare `operation: prepare`, il `run_id` della build accettata,
il suo `source_commit` completo e il canale scelto. Lasciare
`preparation_commit` vuoto. La procedura:

1. verifica commit, versione, build e accettazione richiesta;
2. scarica gli artefatti di quella build e ripete la verifica della coppia
   Windows/Ubuntu sui file effettivi;
3. confronta pacchetti, manifest e archivio scientifico con il record di
   accettazione e prepara un elenco combinato dei checksum;
4. usa le note `docs/RELEASE_<versione>.md` del commit compilato per lo
   schema 1; nello schema 2 usa quelle del commit di preparazione, che
   descrivono la decisione di ricerca e i limiti correnti;
5. crea una bozza sul commit verificato e carica gli asset;
6. verifica dimensioni e digest restituiti da GitHub;
7. conserva la release come **bozza**, senza pubblicarla, e riporta l'ID
   della bozza e il commit di preparazione nel riepilogo Actions.

Controllare nella bozza note, versione, commit sorgente, canale e nomi degli
installatori. In questa fase l'aggiornatore NIPAT non propone il pacchetto.

### 2. Pubblicare la bozza verificata

Avviare nuovamente il workflow su `main` con `operation: publish`, gli stessi
`run_id`, `source_commit` e `channel`, il `draft_release_id` restituito e
il `preparation_commit` completo del primo avvio. Non utilizzare il commit
del pacchetto al posto di quello della preparazione: identificano due ruoli
diversi.

La procedura ripete le verifiche del set, richiede che il record di accettazione
sia invariato rispetto alla preparazione e controlla che la bozza contenga
esattamente gli asset approvati. Per lo schema 2 mantiene le note del commit
di preparazione, anche se `main` avanza. Non crea una bozza mancante, non carica asset
e non corregge contenuti alterati. Un avanzamento di `main` è ammesso soltanto
se le condizioni verificate rimangono soddisfatte.

Dopo i controlli, `stable` pubblica una release stabile e la imposta come
**Latest**; `testing` pubblica una pre-release senza impostarla come Latest.
La pubblicazione della stabile viene verificata anche tramite il riferimento
GitHub alla release Latest. Non sono previste pubblicazioni automatiche al push
di un branch o di un tag.

La verifica comprende il contenuto del `.deb`, l’evidenza di compilazione
dell’EXE, gli archivi incorporati e le prove Linux. Non ricompila
applicazione o immagine. La release conserva i due installatori, il manifest
comune, gli archivi runtime, le evidenze di costruzione e prova,
`desktop-acceptance.json`, `release-provenance.json`, `update-manifest.json`
e `SHA256SUMS`. Lo schema 2 include anche `baseline-source-check.json`,
che registra l'esito e l'ambito del confronto con il riferimento manuale.
`release-provenance.json` identifica separatamente il commit del pacchetto,
quello della procedura e quello delle note tramite `release_notes_commit`.
I collegamenti delle note puntano alla revisione documentale corrispondente;
la documentazione aggiornata non comporta una ricompilazione dei pacchetti.
Per l’installazione ordinaria l’utente scarica soltanto l’EXE o il `.deb`
della propria piattaforma; gli altri file servono alla verifica e al recupero.

### Manifest per l'aggiornatore

`update-manifest.json` viene generato soltanto dopo la verifica degli installatori
e dell'accettazione. Lo schema 1 identifica `product: nipat-desktop`, versione,
tag, commit sorgente, canale e `minimum_updater_version: 1`. Contiene esattamente
l'EXE Windows e il `.deb` Linux della coppia approvata, ciascuno con nome atteso,
piattaforma, dimensione, SHA-256 e URL ufficiale della stessa release.
Il suo digest viene incluso in `SHA256SUMS`.

Il client confronta manifest, release e commit del tag prima di proporre il
download, quindi verifica i byte scaricati. I canali dell'applicazione selezionano
le sole release pubblicate: `testing` include pre-release e stabili, `stable`
include soltanto le stabili. Bozze e artefatti Actions non vengono proposti.
Questa procedura non firma i pacchetti: la fiducia nelle informazioni pubblicate
si basa su HTTPS e sul repository ufficiale, distinta da Authenticode.

L’esito automatico del set, con
`publication_authorized: false`, resta distinto dall’accettazione umana;
il publisher richiede entrambi.

Una preparazione interrotta può essere ripresa con `operation: prepare` e
`draft_release_id`, soltanto se commit, note e contenuti già presenti
coincidono con quelli verificati. `publish` richiede invece una bozza completa
e non la modifica per recuperare errori di preparazione. Release già pubblicate e tag associati
ad altri commit non vengono modificati. Non ricostruire un runtime per
sostituire un archivio già verificato o pubblicato.

Per l’organizzazione dei workflow e i confini dei test consultare
[CI/CD](../docs/CI_CD.md); per i pacchetti consultare
[Installatore Windows](../docs/INSTALLATORE_WINDOWS.md) e
[Installatore Linux](../docs/INSTALLATORE_LINUX.md).

# Verifica e pubblicazione dei pacchetti

NIPAT distribuisce artefatti costruiti e verificati da GitHub Actions. La
pubblicazione non ricompila applicazione o runtime e non richiede al manutentore
di trasferire manualmente gli archivi dal proprio computer.

La versione 0.6 richiede installatori Windows e Ubuntu dello stesso commit
e con lo stesso archivio scientifico. La procedura verifica entrambi i
pacchetti e richiede un’accettazione revisionata dei file esatti. Le versioni
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

La verifica dei checksum e il successo dei test non attestano la firma
Authenticode. La candidata Windows deve essere valutata anche con Smart App
Control attivo e senza aggirare i blocchi del browser o dell'antivirus.
La [procedura di firma Windows](../docs/FIRMA_WINDOWS.md) definisce l'ordine
di firma, la copertura e il legame con i digest finali. Il verificatore delle
firme è uno strumento preparatorio: il servizio di firma e il relativo
controllo obbligatorio di pubblicazione devono essere attivati prima di
distribuire una release dichiarata firmata.

Il [protocollo di accettazione](../docs/ACCETTAZIONE_INSTALLATORI.md) definisce
le prove sui sistemi destinatari. Una scheda generata con
`release_acceptance.py` parte da `pending` e non costituisce un’autorizzazione.
I risultati devono essere osservati sugli stessi EXE e `.deb` della build
che si intende pubblicare.

Il record viene sottoposto a revisione in
`.github/release-acceptance/v0.6.0.json` e integrato in `main` prima della
pubblicazione, insieme al sorgente accettato. Può essere preparato e
revisionato sul branch di sviluppo dopo le prove. È separato dai file
incorporati negli installatori e dal commit della build provata. Collega versione,
commit, ID della build, manifest comune, archivio scientifico e checksum
di entrambi gli installatori alle prove completate, con responsabile,
data UTC e collegamenti alle evidenze. Il successo della build non
compila o approva automaticamente questo record.

Il publisher legge l’accettazione dal commit della procedura su `main`.
Un record mancante o non accettato interrompe l’operazione; dopo il download,
i checksum devono coincidere con quelli dei pacchetti effettivi. Se gli
artefatti scadono o vengono ricostruiti, non riutilizzare l’accettazione
per file con digest differenti. La data di scadenza è quella indicata
dalla conservazione degli artefatti Actions.

## Protezioni della pubblicazione

Il workflow **Publish verified pre-release** è esclusivamente manuale e
opera su `main`. Richiede l’ID della build e il suo commit completo. Per la
0.6, avviare manualmente **Installers (review build)** su un commit
revisionato di questo repository: può essere il branch di sviluppo, così
che le prove e l’accettazione precedano l’integrazione in `main`.

Dopo l’approvazione, integrare sorgenti e record di accettazione conservando
il commit compilato nella storia di `main`. Il publisher verifica esito
della build, corrispondenza del commit e sua appartenenza alla storia di
`main` al momento della pubblicazione. Riutilizza gli artefatti accettati
della build manuale, senza ricostruirli dopo l’integrazione. Le build di
pull request vengono rifiutate. Il successo del solo workflow CI non
sostituisce una build completa degli installatori.

La procedura:

1. verifica commit, versione, build e accettazione richiesta;
2. scarica gli artefatti di quella build e ripete la verifica della coppia
   Windows/Ubuntu sui file effettivi;
3. confronta pacchetti, manifest e archivio scientifico con il record di
   accettazione e prepara un elenco combinato dei checksum;
4. usa le note `docs/RELEASE_<versione>.md` del commit compilato;
5. crea una bozza sul commit verificato e carica gli asset;
6. verifica dimensioni e digest restituiti da GitHub;
7. pubblica soltanto come **Pre-release**, senza indicare **Latest**.

La verifica comprende il contenuto del `.deb`, l’evidenza di compilazione
dell’EXE, gli archivi incorporati e le prove Linux. Non ricompila
applicazione o immagine. La release conserva i due installatori, il manifest
comune, gli archivi runtime, le evidenze di costruzione e prova,
`desktop-acceptance.json`, `release-provenance.json` e `SHA256SUMS`.
Per l’installazione ordinaria l’utente scarica soltanto l’EXE o il `.deb`
della propria piattaforma; gli altri file servono alla verifica e al recupero.

L’esito automatico del set, con
`publication_authorized: false`, resta distinto dall’accettazione umana;
il publisher richiede entrambi.

Un errore lascia la bozza non pubblicata. Una bozza parziale può essere
ripresa con `draft_release_id` soltanto se commit, note e contenuti
coincidono con quelli verificati. Release già pubblicate e tag associati
ad altri commit non vengono modificati. Non ricostruire un runtime per
sostituire un archivio già verificato o pubblicato.

Per l’organizzazione dei workflow e i confini dei test consultare
[CI/CD](../docs/CI_CD.md); per i pacchetti consultare
[Installatore Windows](../docs/INSTALLATORE_WINDOWS.md) e
[Installatore Linux](../docs/INSTALLATORE_LINUX.md).

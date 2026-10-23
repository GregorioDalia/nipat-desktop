# Verifica e pubblicazione dei pacchetti

NIPAT distribuisce artefatti costruiti e verificati da GitHub Actions. La
pubblicazione non ricompila applicazione o runtime e non richiede al manutentore
di trasferire manualmente gli archivi dal proprio computer.

**La pubblicazione 0.5 è bloccata.** Il contratto di questa versione richiede
installatori Windows e Linux coerenti con lo stesso commit e archivio scientifico.
Il workflow produce entrambi i pacchetti per revisione. Il publisher mantiene
il blocco della 0.5: la procedura di pubblicazione e le prove di accettazione
dei sistemi destinatari devono essere completate prima della distribuzione.
Il blocco precede qualsiasi creazione o modifica di una release.

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
| `nipat-linux-setup` | `.deb`, manifest comune, checksum, `linux-installer-build.json` e `linux-installation-check.json`. |
| `nipat-scientific-check-logs` | Metadati e registri delle regressioni conservati dalla build. |
| `nipat-installer-set-evidence` | `installer-set-check.json`, verifica congiunta di sorgenti e archivio scientifico Windows/Ubuntu. |

Il manifest identifica versione, tag previsto, commit, piattaforma, archivio
scientifico, filesystem WSL e profilo di installazione. Il profilo deve
corrispondere al sorgente del commit e al canale `preview-0.5`.
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

La funzione `prepare_assets` del publisher verifica anche i pacchetti Windows
0.5 durante la build, indipendentemente dal blocco di pubblicazione. Rifiuta
evidenze mancanti, file provenienti da build diverse, un profilo incoerente e
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

Il controllo `installer-required` confronta commit, manifest comune e
checksum scientifico dei due pacchetti e conserva `installer-set-check.json`.
Questa corrispondenza lega gli installatori alla stessa esportazione.
Le evidenze di build non
sostituiscono le prove su Windows e Ubuntu Desktop puliti. I dettagli
operativi del pacchetto sono nell’[installatore Linux](../docs/INSTALLATORE_LINUX.md).

## Protezioni della pubblicazione

Il workflow **Publish verified Windows pre-release** è esclusivamente manuale
e opera su `main`. Richiede l'ID della build e il suo commit completo. Per il pacchetto da
distribuire, avviare manualmente la build dell'installatore su `main`.
Il publisher verifica l'esito riuscito, la corrispondenza del commit e la sua
appartenenza alla storia di `main`; le build di pull request vengono rifiutate.
Il successo del solo workflow CI non sostituisce una build dell'installatore.

Per le versioni ammesse dal publisher, la procedura:

1. verifica commit, versione, build e contratto dei pacchetti;
2. prepara gli asset verificati e un elenco combinato dei checksum;
3. usa le note `docs/RELEASE_<versione>.md` del commit compilato;
4. crea una bozza sul commit verificato e carica gli asset;
5. verifica dimensioni e digest restituiti da GitHub;
6. pubblica soltanto come **Pre-release**, senza indicare **Latest**.

Un errore lascia la bozza non pubblicata. Una bozza parziale può essere ripresa
con `draft_release_id` soltanto se commit, note e contenuti coincidono con
quelli verificati. Release già pubblicate e tag associati ad altri commit
non vengono modificati. Non ricostruire un runtime per sostituire l'archivio
già verificato o pubblicato.

La rimozione del blocco 0.5 richiede una procedura di pubblicazione che
verifichi entrambi gli installatori, le relative prove e il manifest della
medesima build, oltre all’accettazione dei pacchetti sui sistemi dichiarati.
Non è sufficiente modificare la stringa di versione o disattivare il
controllo del publisher.
Per l'organizzazione dei workflow e i confini dei test consultare
[CI/CD](../docs/CI_CD.md); per il pacchetto Windows consultare
[Installatore Windows](../docs/INSTALLATORE_WINDOWS.md).

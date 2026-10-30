# Integrazione continua e distribuzione

NIPAT separa test sui sorgenti, costruzione dei pacchetti, prove degli ambienti
reali e pubblicazione. **NIPAT Experimental08 0.8.0a1** usa il branch
`experiment/0.8-portability`, installatori Windows/macOS e un'identità distinta
dal canale stabile. La distribuzione stabile Windows/Ubuntu 0.7.2 e il suo
publisher non vengono promossi o sostituiti dalla riuscita dell'esperimento.

## Workflow GitHub Actions

| Workflow | Attivazione | Risultato |
| --- | --- | --- |
| [CI](../.github/workflows/ci.yml) | Push, aggiornamenti delle pull request e avvio manuale. | Test del client e dei contratti, documentazione, componenti di piattaforma e regressioni scientifiche applicabili. |
| [Installers (review build)](../.github/workflows/windows-installer.yml) | Avvio manuale sul commit sperimentale scelto. | Installer Windows e due pacchetti macOS, con manifest, checksum e rapporti. Non pubblica una release. |
| [Prepare or publish verified release](../.github/workflows/publish-windows-release.yml) | Avvio manuale secondo il protocollo del canale stabile. | Publisher della distribuzione desktop Windows/Ubuntu; non costituisce il publisher della 0.8 sperimentale. |
| [Published runtime security report](../.github/workflows/security-monitoring.yml) | Pianificazione e avvio manuale. | Inventari e segnalazioni candidate sulle immagini pubblicate, da esaminare separatamente. |

La CI seleziona i controlli in base ai file modificati. Contratti, runtime,
installer e file della pipeline attivano i livelli corrispondenti; se il
confronto Git non è disponibile, la selezione non considera automaticamente
la modifica come sola documentazione. Il controllo aggregato `required`
verifica l'esito dei job richiesti. I test automatici non costruiscono tutti
gli installatori a ogni aggiornamento.

I controlli di una pull request restano attivi anche quando il corrispondente
push viene deduplicato. Gli avvii manuali e i pacchetti conservano il commit
esatto: il nome di un branch e il numero di versione non bastano a identificare
una build.

## Copertura della sperimentazione

| Livello | Ambiente | Cosa verifica | Cosa non dimostra |
| --- | --- | --- | --- |
| Python e contratti | Linux, Windows, macOS ARM e Intel | CLI/menu, configurazione, input, piani, registri, errori e interruzioni. | Installazione su un desktop nuovo o correttezza scientifica su ogni campione. |
| Windows e WSL | Runner Windows e simulazioni controllate | Build ed edizione Windows, architettura, stato WSL, decisioni del bootstrap, percorsi, riparazione, rimozione e isolamento dei profili. | Installazione reale su Windows 10, attivazione della virtualizzazione o ripresa dopo riavvio. |
| macOS e Lima | Runner macOS ospitati | Contratto del trasporto, percorsi, comandi, manifest, launcher e confezionamento per le due architetture. | Avvio di una VM Lima reale se il runner non espone la virtualizzazione. |
| Motore scientifico | Container Linux AMD64 | Quattro analisi, workflow composti, BAM sintetici, confronti numerici, input non validi e conservazione degli originali. | Prestazioni o correttezza del trasporto Rosetta su un Mac reale. |
| Runtime Mac reale | Runner dedicati abilitati esplicitamente | Preparazione e uso della VM Lima, diagnostica, autotest e comportamento del motore sul relativo host. | Interazione Finder, policy Gatekeeper o tutte le configurazioni desktop. |
| Documentazione | Controllo offline | File, immagini, link relativi e sezioni Markdown. | Disponibilità dei siti esterni o validità scientifica della prosa. |

I runner Windows ospitati non sono Windows 10. Le simulazioni dei prerequisiti
rendono riproducibili le decisioni del codice, ma l'avvio WSL su Windows 10
resta una prova da registrare su quel sistema. Analogamente, costruire un
`.pkg` su macOS non prova che il pacchetto possa avviare una VM, né che le
protezioni di tutti i Mac ne autorizzino l'esecuzione.

Gli esiti devono specificare **eseguito**, **fallito**, **saltato** o **non
eseguito** con il relativo motivo. Un job di runtime facoltativo saltato
non va presentato come una prova Lima superata.

## Test scientifici e regressioni

L'immagine contiene R, samtools, i sorgenti scientifici e l'orchestrazione.
Il client non monta gli script R dalla cartella applicativa. I controlli
verificano i contratti del motore prima delle analisi e usano input sintetici
con risultati attesi.

Le regressioni coprono DNPcall, SNPcall, Contamination e CPI; i workflow
composti sono confrontati con le analisi singole equivalenti. I test del
client e della libreria condivisa verificano alleli e pannelli, conteggi,
frequenze, avvisi, associazioni fra campioni e coppie, dipendenze, arresto al
fallimento e mancata sovrascrittura dei run. Il catalogo scientifico rimane
legato ai sorgenti R identificati da hash.

L'esperimento usa una sola immagine **Linux AMD64** anche su Apple Silicon.
Lima esegue un guest nativo ARM64 e Rosetta abilita i processi AMD64 del
container. Per questa combinazione servono evidenze ottenute sul runtime
reale: la riuscita delle stesse analisi su Ubuntu AMD64 non le sostituisce.
I risultati scientifici attesi non cambiano con la piattaforma host.

## Build degli installatori

Avviare **Installers (review build)** sul commit sperimentale da verificare.
La build costruisce e verifica il motore scientifico, produce gli archivi e
confeziona i client. I due pacchetti Mac incorporano Python e Lima nativi per
l'host; l'archivio scientifico AMD64 è comune a Windows e macOS.

| Artefatto Actions | Contenuto principale |
| --- | --- |
| `nipat-windows-setup` | `NIPAT-Setup.exe` e prove del pacchetto Windows sperimentale. |
| `nipat-macos-setup-arm64` | `NIPAT-Experimental-0.8.0a1-macos-arm64.pkg` e rapporto del pacchetto Apple Silicon. |
| `nipat-macos-setup-x86_64` | `NIPAT-Experimental-0.8.0a1-macos-x86_64.pkg` e rapporto del pacchetto Intel. |
| `nipat-experimental-installer-evidence` | Identità dei pacchetti e dell'archivio scientifico comune, con verifiche aggregate. |

Il download di un artefatto Actions può presentarsi come archivio contenitore;
il file da installare al suo interno è l'EXE o il `.pkg`. Un'eventuale
pre-release espone questi file direttamente. I pacchetti **Source code**
non contengono un ambiente pronto all'uso.

La build sperimentale non produce un `.deb` 0.8 con l'identità stabile e non
aggiorna `Latest`, tag o asset della 0.7.2. Una pubblicazione sperimentale è
un'operazione distinta e deve rendere espliciti commit, checksum e stato
sperimentale; non genera il manifest di aggiornamento del canale desktop.

## Verifiche Lima su runner dedicati

Il parametro manuale `qualify_macos_runtime` abilita le prove di VM reali.
Servono runner dedicati con etichette `self-hosted`, `macOS`, `nipat-runtime`
e architettura `ARM64` oppure `X64`, secondo il job. Devono esporre la
virtualizzazione e le condizioni richieste dal pacchetto sperimentale.
Non eseguire codice di pull request non fidate su questi runner.

La prova deve identificare hardware, versione macOS, architettura, versione
Lima e modalità Rosetta, insieme a commit e checksum del pacchetto. I log
conservano diagnostica e risultati delle analisi; eventuali scenari non
provati rimangono elencati. Il completamento di un solo job non qualifica
l'altra architettura.

## Distribuzione e controllo delle evidenze

I pacchetti sperimentali usano il profilo `experimental08`, distinto da
`desktop`. Gli aggiornamenti automatici del canale stabile non propongono
l'esperimento; il client sperimentale non migra al canale stabile.
Le prove non modificano installazioni o risultati delle ricercatrici.

Per distribuire un esperimento non occorre dichiarare completato ogni
scenario desktop. Occorre descrivere fedelmente quali verifiche sono state
eseguite e quali rimangono aperte. La [scheda di validazione](VALIDAZIONE.md)
registra le osservazioni su Windows 10/11 e Mac Intel/Apple Silicon; il
[protocollo dei pacchetti](../.github/RELEASE.md) distingue distribuzione
sperimentale e pubblicazione stabile.

Ogni difetto riproducibile dovrebbe diventare una regressione del livello
appropriato. Il numero di test non rappresenta da solo la copertura:
restano distinti comportamento del codice, calcolo scientifico, installazione
del pacchetto e valutazione di dominio.

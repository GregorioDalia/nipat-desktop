# Integrazione continua e distribuzione

NIPAT separa i controlli sui sorgenti, la costruzione degli installatori e la
pubblicazione. La versione 0.6.0 appartiene al canale desktop. La pipeline
produce installatori Windows WSL e Ubuntu per revisione. La pubblicazione
richiede una coppia di pacchetti verificata e un record di accettazione
revisionato, riferito agli stessi file. La serie 0.6 ammette un'accettazione
per ricerca pre-1.0 con prova manuale documentata e scenari estesi dichiarati
come rinviati. Il publisher verifica il record prima di modificare una release.

## Workflow GitHub Actions

| Workflow | Attivazione | Risultato |
| --- | --- | --- |
| [CI](../.github/workflows/ci.yml) | Push sui branch, aggiornamenti delle pull request, incluse le bozze, e avvio manuale. | Test Linux/Windows, documentazione e verifiche scientifiche quando richieste; controllo aggregato `required` su pull request e `main`. |
| [Installers (review build)](../.github/workflows/windows-installer.yml) | Avvio manuale su un commit scelto. | Installatore WSL e pacchetto Ubuntu con lo stesso archivio scientifico, prove ed evidenze di costruzione. |
| [Prepare or publish verified release](../.github/workflows/publish-windows-release.yml) | Due avvii manuali distinti da `main`: `prepare`, poi `publish`. | Prepara una bozza completa verificata; dopo la revisione, ricontrolla e pubblica gli stessi file nel canale scelto. |

La CI controlla ogni aggiornamento senza ricostruire gli installatori completi.
Quando un push riguarda una pull request aperta dello stesso repository e
dello stesso commit, e risulta avviata una CI della pull request corrispondente,
i controlli sono assegnati alla pull request per evitare
una seconda esecuzione equivalente. Il controllo delle pull request è sempre
attivo; se GitHub non consente di confermare questa corrispondenza, vengono
eseguiti anche i controlli del push. Una pull request con conflitti o priva di
una CI confermata non sopprime quindi le verifiche del branch.
Le esecuzioni manuali rimangono indipendenti
e non vengono annullate da nuovi push.

Una build destinata alla pubblicazione deve essere avviata
manualmente su un commit revisionato di questo repository; può provenire
dal branch di sviluppo prima dell’integrazione. La decisione di distribuzione
identifica esattamente i pacchetti prodotti; le prove manuali riportano il
commit realmente osservato e il loro ambito. Prima della pubblicazione,
sorgenti e record di accettazione devono essere integrati in `main`, conservando il commit
compilato nella sua storia. Il publisher opera da `main` e riusa gli stessi
artefatti verificati senza ricostruirli; non modifica release già pubblicate.
Un artefatto prodotto da un evento `pull_request` non è pubblicabile.
Il commit effettivamente compilato è quello riportato nel manifest e nel
riepilogo di build: un checkout di pull request può identificare un merge
temporaneo, diverso dalla testa del branch. Nome del branch e sola versione
del programma non bastano a identificare un installatore.

## Copertura e livelli di prova

| Livello | Esecuzione | Verifiche principali | Limite |
| --- | --- | --- | --- |
| Client e contratti | CI su Linux e Windows a ogni aggiornamento applicabile. | Tutta la suite Python, CLI/menu, preferenze, percorsi, errori, interruzioni, aggiornamenti e registrazione dei run. | Processi esterni simulati dove occorre; non prova l'installazione su un PC nuovo. |
| Documentazione | CI Linux a ogni aggiornamento applicabile. | Link a file locali, asset e sezioni Markdown, inclusi README e guide. | Non verifica disponibilità di siti esterni né correttezza scientifica della prosa. |
| Motore scientifico reale | CI selettiva; sempre nella CI manuale e nella build installatori. | Container autonomo, quattro workflow, BAM sintetici, risultati numerici, casi non validi e isolamento degli input. | Casi sintetici e regressioni non equivalgono a validazione di dominio. |
| Componenti Windows | CI e build installatori. | PowerShell, percorsi, migrazione, riparazione, rimozione, blocchi attività, aggiornamento, launcher e compilazione Inno Setup. | Le simulazioni WSL e il passaggio a un installatore di prova non sono una prima installazione o un aggiornamento reale fra versioni. |
| Pacchetti completi | Build installatori manuale. | Archivio comune, importazione nel motore distribuito, confezionamento Windows/Ubuntu e ciclo APT reale sul runner. | Il runner predisposto e il container delle dipendenze non sono un desktop utente pulito. |
| Accettazione per ricerca 0.6 | Prova manuale documentata e revisione esplicita, integrate con la build verificata. | Installazione pronta ed esecuzione scientifica; equivalenza dei sorgenti se si riutilizza un riferimento precedente. | Non attesta una prova manuale di ogni nuovo installer o il completamento dei sei scenari desktop. |
| Qualificazione desktop completa | Prove registrate sui due installatori esatti. | Sei scenari Windows/Ubuntu, avvio, riavvio, conservazione dei dati e rimozione. | Percorso progressivo distinto dalla distribuzione pre-1.0; la valutazione scientifica rimane separata. |

I nomi e il numero dei test possono evolvere; la copertura viene valutata
rispetto ai comportamenti e ai rischi verificati, non al solo conteggio.

Il catalogo scientifico è verificato rispetto ai sorgenti R identificati da
SHA-256, al numero di righe e alla copertura delle sezioni esaminate. I test
del contratto dei piani verificano struttura, riferimenti tipizzati,
dipendenze e ordine deterministico. La suite dell'esecutore verifica inoltre
stati dei passaggi, errori, interruzioni, output mancanti e rifiuto di una
destinazione già utilizzata. Il confronto scientifico reale del workflow
DNPcall → Contamination, dei piani con CPI e delle attività SNPcall è
distinto da questi test unitari: viene eseguito nell'immagine con R e samtools. Nessuno di questi controlli attesta da solo
la validità biologica degli input.

## Controlli sui sorgenti

I job `linux-checks` e `windows-checks` eseguono la suite Python su entrambi
i sistemi. Il primo comprende i test della selezione CI, del publisher e la
verifica sintattica dell'helper del motore. I test del menu e delle preferenze
controllano persistenza, annullamento e ripristino, priorità dei percorsi e
separazione dai comandi diretti. Il secondo comprende parsing con
PowerShell 5.1, protezioni del bootstrap, identità delle immagini, configurazione
WSL riprendibile e compilazione/prova del launcher. I controlli di riparazione
e inventario verificano il backup selettivo, la gestione dei componenti
sostituiti o obsoleti e la conservazione dei file estranei. I controlli relativi
ai percorsi e alla rimozione devono verificare separazione delle destinazioni,
identità delle risorse possedute e conservazione dei dati; non sostituiscono
la prova dell'interfaccia del setup su Windows. I controlli dell'aggiornatore
comprendono selezione del canale, rifiuto dei metadati non coerenti, integrità
del download, conferme esplicite e comportamento senza rete; le prove simulate
non attestano l'installazione completa di una versione successiva.
Il verificatore [`check_docs.py`](../.github/scripts/check_docs.py) controlla
la documentazione mantenuta nel repository senza richieste di rete; i documenti
importati in `scientific/vendor` restano esclusi dalla scansione dei sorgenti.

Il job `scientific` costruisce il motore e avvia:

- `scripts/verify_engine_package.py`: quattro workflow nell'immagine, senza
  sorgenti applicativi montati, con aspettative numeriche e casi non validi;
  controlla inoltre il catalogo incorporato, la validazione dei piani e
  i workflow automatici DNPcall → Contamination, DNPcall → CPI e DNPcall →
  Contamination e CPI tramite `scripts/verify_workflow_execution.py`, oltre
  ai piani SNPcall tramite `scripts/verify_snp_workflow.py`;
- `python -m nipat doctor --runtime`: compatibilità e identità del motore;
- `python -m nipat self-test`: regressioni distribuite e modalità di input.

Le prove DNPcall includono BAM sintetici, campioni singoli e multipli, liste,
parità sequenziale/parallela e confronto con l'invocazione R. Le prove CPI
comprendono modalità dei pannelli, assenza di siti informativi e variazione
della costante d'errore. Le fixture dichiarano dati, valori attesi e tolleranze.

La regressione del workflow automatico usa due BAM sintetici ed esegue
DNPcall → Contamination in un solo container, senza sorgenti del client montati.
Confronta conteggi, genotipi, verosimiglianze e grafici DNPcall con il caso
atteso, poi confronta le tabelle con le analisi separate. Per Contamination
controlla due siti per campione, media e deviazione standard attese pari a zero.
Verifica anche l'associazione fra identità dei campioni e risultati, stato e
manifest, conservazione degli input, rifiuto del riutilizzo della destinazione
e arresto della catena su input non valido. I casi negativi non equivalgono
alla validazione scientifica su campioni reali.

Le regressioni CPI dei piani comprendono due livelli distinti:

- **Tabelle importate:** casi informativi e senza siti, più coppie con un
  campione materno condiviso, modalità ALL, pannello singolo e pannelli
  etichettati, oltre a una costante d'errore non predefinita. Valori attesi
  indipendenti e confronto con l'analisi separata verificano il CSV; nomi,
  intestazioni PDF e mappa delle coppie verificano l'identità degli output.
- **BAM e workflow completi:** il percorso DNPcall → CPI verifica il caso
  senza siti informativi. Il percorso DNPcall → Contamination e CPI usa BAM
  sintetici con tre loci, 96 letture REF e 4 ALT per il campione materno e
  50 REF/50 ALT per quello paterno. I valori attesi sono frazione fetale 8%
  e log10 CPI `0.903` sul pannello completo; un pannello con un solo locus
  produce log10 CPI `0.301`. Contamination deve restituire media `0.04` per
  il campione materno e nessun sito informativo per quello paterno.

La [fixture del workflow CPI](../tests/fixtures/workflow_cpi/README.md)
documenta come sono costruiti i BAM e come sono derivati i valori attesi.
Il caso completo verifica che CPI riceva i conteggi DNPcall originali anche
quando Contamination scarta i loci paterni; il suo risultato non viene usato
come filtro o trasformazione degli input CPI. La prova attraversa il client
senza sorgenti R locali, richiede un solo comando container e controlla stati,
parametri effettivi, checksum, campioni condivisi e conservazione degli input.
Il confronto dei PDF ne verifica presenza e formato, non l'aspetto grafico.

Le regressioni SNPcall dei piani eseguono i due percorsi BAM e pileup con
risultati numerici attesi e confronto con le analisi singole. Il percorso
BAM conserva BED, pileup e log samtools, verificando anche i checksum degli
intermedi; quello importato verifica il riuso del pileup senza rigenerarlo. Il client viene esercitato con più campioni e
nomi di file coincidenti in cartelle diverse, controllando l'associazione fra
input originali, passaggi e tabelle. L'opzione SNPcall nei workflow DNPcall
verifica la condivisione dei BAM e la separazione dei risultati delle due
analisi. Un caso negativo reale verifica che un errore samtools impedisca
l'avvio di R e blocchi il campione SNP successivo, anche se indipendente.
Queste prove avvengono senza sorgenti scientifici del client montati.
La suite dell'esecutore distingue errore samtools, pileup non valido, errore R
e annullamento, verificando l'arresto dei passaggi non ancora avviati.

La selezione delle verifiche scientifiche è definita in
[`ci_changes.py`](../.github/scripts/ci_changes.py). Modifiche al motore, ai
sorgenti scientifici, a qualsiasi file sotto `src/` o `tests/`, agli script
di verifica scientifica e alla configurazione CI pertinente le rendono
obbligatorie. Anche una modifica ai soli test può quindi eseguire il motore.
I dati JSON del catalogo, il validatore e l'esecutore dei piani appartengono
a questi percorsi: le loro modifiche richiedono le prove nell'immagine reale.
Un avvio manuale le richiede sempre.
Se il confronto Git non riesce, vengono richieste per precauzione.
Le modifiche esclusivamente documentali possono evitare la ricostruzione
scientifica, mantenendo i controlli rapidi.

Il controllo conclusivo `required` viene valutato anche dopo un fallimento.
Riesce soltanto se i controlli rapidi e la selezione hanno avuto successo e
le prove scientifiche richieste sono riuscite. Un controllo obbligatorio
fallito, annullato o saltato impedisce un esito positivo.
I push sui branch di sviluppo espongono il nome `branch-required`, così un
push delegato alla propria pull request non può soddisfare il controllo
protetto `required` al suo posto.

Nel repository ufficiale `main` è protetto da pull request obbligatoria,
controllo `required`, branch aggiornato e divieto di force push e cancellazione.
Queste sono impostazioni GitHub, non proprietà applicate automaticamente a un
fork copiando i file. Le azioni di CI e costruzione hanno permessi di sola
lettura; soltanto il job di pubblicazione dispone di `contents: write`.

## Costruzione degli installatori

La build esegue i controlli Windows prima delle operazioni più costose.
Una compilazione Inno Setup con componenti minimi di prova controlla lo script
dell'installatore prima di costruire il runtime; non esegue il setup né verifica
la sua interfaccia grafica. Il medesimo `NIPAT.exe` compilato e verificato
viene incorporato nell'installatore.
Successivamente costruisce e verifica il motore scientifico e il filesystem
WSL, esporta gli archivi e genera il manifest con commit, dimensioni e SHA-256.

Il test di importazione usa un motore isolato del filesystem WSL distribuito,
inizialmente privo dell'immagine. Carica l'archivio esportato, avvia R e samtools
e ripete il caricamento per verificare la ripresa. La compilazione Inno Setup
usa gli stessi archivi verificati, il profilo di installazione e il launcher.
La verifica finale Windows confronta manifest, sorgenti, EXE ed evidenze
di costruzione.

Il controllo `windows-client-check.json` usa il payload destinato al setup,
trasferito in una cartella isolata con spazi e caratteri Unicode. Esegue
Python incorporato, importazioni, catalogo, navigazione del menu e simulazioni
dei workflow automatici, verificando i piani e la conservazione degli input.
Le evidenze identificano EXE, manifest, launcher e inventario del medesimo
pacchetto. Lo scenario `staged-embedded-python-client` non installa Inno Setup
e non esegue WSL o il calcolo scientifico sul runner Windows.

Il job `linux-installer` riceve il medesimo archivio esportato, senza
ricostruirlo, e prepara il pacchetto `nipat-desktop` per Ubuntu 24.04 amd64.
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

La prova del pacchetto 0.7 comprende inoltre un piano DNPcall, Contamination,
CPI e SNPcall sui due BAM sintetici. Controlla i cinque passaggi nel medesimo
motore, risultati numerici, associazioni dei campioni, file intermedi e hash
degli output. I campi `automatic_workflow_plan` e `preferences_preserved`
registrano rispettivamente questo controllo e la conservazione delle
preferenze durante esecuzione, reinstallazione e rimozione.

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
| `nipat-windows-setup` | `NIPAT-Setup.exe`, manifest, checksum ed evidenze dell'installatore, del launcher e del client preparato (`windows-client-check.json`). |
| `NIPAT-Setup.exe` | Download diretto del solo installatore Windows, senza ZIP, disponibile dopo la verifica congiunta Windows/Ubuntu. |
| `nipat-linux-setup` | Pacchetto `.deb`, manifest comune, checksum, evidenze di costruzione, installazione e risoluzione delle dipendenze. |
| `nipat-desktop_<versione>_amd64.deb` | Download diretto del solo pacchetto Ubuntu, senza ZIP, disponibile dopo la verifica congiunta Windows/Ubuntu. |
| `nipat-installer-set-evidence` | `installer-set-check.json`, esito della verifica congiunta Windows/Ubuntu. |

Per il collaudo, accedere a GitHub e aprire il run riuscito indicato dal
referente. Il riepilogo offre i download diretti di **NIPAT-Setup.exe** per
Windows e del **.deb** per Ubuntu, disponibili anche nella sezione
**Artifacts**. Non richiedono estrazione o assemblaggio. I download contengono
gli stessi byte dei pacchetti conservati negli artefatti di evidenza
`nipat-windows-setup` e `nipat-linux-setup`; le prove e la procedura di
accettazione restano associate alla coppia Windows/Ubuntu.

Gli artefatti sono conservati per **14 giorni** dalla creazione e non
equivalgono a una release pubblica. Conservare il riferimento al run per
identificare la build usata nelle prove. La versione 0.6 non produce un
installatore Docker Desktop.

## Pubblicazione dei canali di aggiornamento

**Prepare or publish verified release** richiede una scelta esplicita del canale:
`testing` è il valore predefinito e pubblica una pre-release; `stable` pubblica
una release stabile e richiede una versione numerica `MAJOR.MINOR.PATCH`.
Entrambi richiedono avvio manuale da `main`, coppia verificata e decisione di
accettazione riferita ai medesimi pacchetti. Il canale non cambia lo schema
di accettazione e non certifica il metodo scientifico. Tutti i controlli
automatici e di identità dei pacchetti rimangono obbligatori.

`prepare` crea e completa una bozza senza renderla pubblica. Il riepilogo
restituisce l'ID della bozza e il commit della preparazione. Dopo averne
controllato note, pacchetti e canale, un secondo avvio con `publish` deve
indicare entrambi gli identificativi. La pubblicazione ricontrolla build,
accettazione invariata e byte della bozza; non carica file mancanti e non
ripara una bozza alterata. Una release `stable` diventa **Latest**; una
pre-release `testing` non lo diventa. Il solo push di un branch o tag non
pubblica software.

Nell'accettazione per ricerca, le note della versione provengono dal commit
di preparazione e vengono mantenute nella pubblicazione. La provenienza
identifica tale revisione separatamente dal commit del pacchetto; i collegamenti
puntano alla stessa revisione documentale. `baseline-source-check.json` conserva
il confronto dei sorgenti con la build osservata manualmente. Nessuna di queste
operazioni ricompila gli installatori.

Dopo le verifiche, il publisher genera `update-manifest.json`, lo include in
`SHA256SUMS` e lo pubblica con gli installatori. Il manifest identifica prodotto,
versione, tag, commit, canale e protocollo minimo dell'aggiornatore; elenca nome,
piattaforma, dimensione, checksum e URL ufficiale di EXE e `.deb`. Il client
propone soltanto release già pubblicate e compatibili. Una build di revisione
non diventa un aggiornamento per il solo fatto di avere superato la CI.

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

Il [protocollo di accettazione](ACCETTAZIONE_INSTALLATORI.md) distingue la
distribuzione per ricerca della 0.6 dalla qualificazione completa dei desktop.
La prima richiede una prova manuale di installazione e funzionamento e una
decisione del manutentore, conservando esplicitamente i limiti della prova e
gli scenari rinviati. Se la prova riguarda una build precedente, il publisher
confronta i sorgenti operativi distribuiti; un cambiamento fuori dall'ambito
ammesso impedisce il riutilizzo del riferimento. L'equivalenza dei sorgenti
non dichiara identici i binari né provata l'installazione della nuova candidata.

La qualificazione completa conserva i sei scenari Windows/Ubuntu: sistema
pulito, coesistenza, riavvio, percorsi personalizzati, riparazione e rimozione
con protezione dei dati. Gli aggiornamenti fra versioni differenti richiedono
casi dedicati. Questi collaudi sono organizzati progressivamente; la campagna
con le esperte di dominio è prevista sulla 0.7.

Il record revisionato su `main` identifica build, commit, manifest, archivio
scientifico e checksum dei due installatori. Il publisher verifica i requisiti
dello schema scelto e ricontrolla gli artefatti prima di creare o modificare
una bozza. Un record assente, non approvato o incoerente interrompe la
pubblicazione. Gli artefatti accettati non vengono ricostruiti; file differenti
richiedono una nuova decisione associata ai nuovi checksum.

La CI viene ampliata con casi riproducibili per i difetti osservati, i valori
di confine e i nuovi comportamenti. Per la 0.7 le priorità comprendono
propagazione dei parametri, impostazioni scientifiche fisse, equivalenza
tra analisi separate e workflow concatenati e gestione dei fallimenti tra
passaggi dipendenti. La 0.7.0a1 comprende i controlli del catalogo e la catena
DNPcall → Contamination, le composizioni CPI e i piani SNPcall descritti sopra.
Queste verifiche non vengono attribuite retroattivamente alla 0.6.

Le prove di dominio utilizzano input e attese indipendenti dalle fixture di
regressione. Esiti, versioni e limiti sono registrati nella
[scheda di validazione](VALIDAZIONE.md). La procedura tecnica di pubblicazione
è descritta in [Pubblicazione](../.github/RELEASE.md).

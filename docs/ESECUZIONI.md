# Risultati e registrazione delle esecuzioni

In NIPAT Experimental08 ogni analisi singola o workflow automatico crea un nuovo
**run** nella cartella risultati.
La destinazione predefinita Windows è
`%LOCALAPPDATA%\NIPAT-Experimental08\runs`; nel pacchetto macOS è
`~/Library/Application Support/NIPAT-Experimental08/runs`. Nel checkout
da sorgenti è `runs` accanto al progetto. Si può impostare una destinazione con `--runs-dir`
prima del sottocomando oppure, nel menu guidato, salvando la destinazione
in **5 — Configura → Cartelle dati e risultati**. La preferenza del menu
non modifica i comandi CLI diretti.
Un run esistente non viene sovrascritto.

## Contenuto del run

| File o cartella | Contenuto |
| --- | --- |
| `output` | Tabelle e grafici scientifici. |
| `work` | Richiesta al motore, configurazione dei mount e intermedi conservati. |
| `run.json` | Stato, input, parametri, software e identità del motore. |
| `execution.log` | Comandi, messaggi del client e output combinato del motore; nei piani, il dettaglio scientifico è nei log dei passaggi. |
| `work/input-validation.json` | Controlli degli input, avvisi e provenienza delle copie normalizzate dell'analisi singola. |
| `work/scientific-validation.json` | Controlli degli output e segnalazioni di qualità dell'analisi singola. |

I percorsi si possono aprire dalla schermata finale del menu oppure dal
file system. **6 — Ultima esecuzione** richiama il run più recente della
sessione, anche fallito o interrotto se la sua cartella è stata creata.
Un errore precedente alla creazione di una nuova cartella non sostituisce
il riferimento all'ultimo run. I nomi dei file scientifici sono quelli
prodotti dal workflow.

Ogni workflow automatico conserva un unico record `run.json` e i passaggi
selezionati nella sottocartella `output/workflow`:

| Percorso nel run automatico | Contenuto |
| --- | --- |
| `work/engine-plan.json` | Richiesta con campioni, parametri e dipendenze inviata al motore. |
| `output/workflow/plan.json` | Piano canonico eseguito dal motore. |
| `output/workflow/workflow-state.json` | Stato complessivo e dei passaggi, con riferimenti agli output e checksum. |
| `output/workflow/steps/dnp` | Preparazione, risultati e log DNPcall. |
| `output/workflow/steps/contamination` | Preparazione, risultati e log Contamination, quando selezionato. |
| `output/workflow/steps/cpi` | Preparazione, risultati e log CPI, quando selezionato. |
| `output/workflow/steps/snp_0001`, ecc. | Un passaggio SNPcall per ogni campione selezionato. |

Ogni cartella di passaggio contiene `request.json`, `command.log`, `work`
e `output`. `command.log` conserva l'output R. Nei passaggi SNPcall da BAM,
`preparation.log` conserva i messaggi samtools, mentre il comando è registrato
nello stato del passaggio; per DNPcall
samtools viene invece invocato internamente da R. Il log principale segnala
l'avvio dei passaggi e l'esito del piano. Le tabelle individuali DNPcall si trovano in
`steps/dnp/output/individual_outputs`; il riepilogo Contamination si trova
in `steps/contamination/output/contamination_summary.txt`.
Il riepilogo CPI è `steps/cpi/output/Summary_FetalFraction_CPI.csv`, accompagnato
dai PDF in `steps/cpi/output/plots`, incluso `All_CPIplots.pdf`.
Ogni tabella SNPcall si trova in `steps/snp_0001/output/SNPcall_output.txt`
o nel passaggio successivo corrispondente. La modalità BAM conserva
`work/snp_regions.bed` e `work/pileup.txt` nella cartella del passaggio;
la modalità pileup conserva il riferimento all'input e non lo rigenera.
Questi percorsi sono relativi a `output/workflow`.

## Stati e significato dell'esito

| Stato | Significato |
| --- | --- |
| `preparing` | Controlli e preparazione dell'esecuzione. |
| `running` | Motore avviato, senza un esito finale registrato. |
| `planned` | Simulazione con `--dry-run`; calcolo scientifico non eseguito. |
| `succeeded` | Il processo del workflow è terminato correttamente e gli output hanno superato i controlli tecnici previsti. |
| `failed` | Errore durante preparazione o esecuzione; consultare il log. |
| `interrupted` | Interruzione intercettata, per esempio Ctrl+C. |

Il successo descrive il completamento tecnico, non la correttezza scientifica
per un particolare campione. Una cartella con alcuni output può appartenere
a un'esecuzione fallita. Gli autotest confrontano i valori dopo il completamento
del workflow: anche il loro esito finale deve essere positivo.

I controlli sono condivisi dalle analisi singole e dai piani automatici.
Gli avvisi sui valori numerici restano distinti dagli errori strutturali:
consultare le segnalazioni di qualità anche quando il run termina con successo.
Gli script R e i risultati originali non vengono modificati da questi controlli.
Nelle analisi singole il resoconto è `work/scientific-validation.json`;
nei piani gli avvisi del passaggio sono in `artifacts.quality_warnings`
di `workflow-state.json`. Il resoconto degli input è invece
`work/input-validation.json` nell'analisi o nella cartella di ogni passaggio.

Per SNPcall da BAM, samtools deve terminare correttamente prima dell'avvio
R; il successo del solo pileup non conclude il workflow. DNPcall richiama
samtools internamente nello script R, nascondendone lo stderr e senza
verificarne esplicitamente il codice di uscita. Il suo stato finale può
quindi non rilevare ogni errore interno di samtools: occorre verificare
anche la completezza e i valori degli output.

Nel workflow automatico, `workflow-state.json` conserva anche gli stati
`pending`, `running`, `succeeded`, `failed`, `cancelled` dei passaggi.
Dopo un errore o un'interruzione, tutti i passaggi non ancora avviati diventano
`blocked`, compresi quelli indipendenti. `succeeded` del passaggio DNPcall
non implica il successo del successivo Contamination o dell'intero piano.
Il record del client usa `interrupted` per l'interruzione intercettata;
il motore usa `cancelled` nello stato del piano.

Nel menu guidato, Ctrl+C interrompe l'operazione corrente e riporta al menu
principale dopo la procedura di arresto. Nei campi e nei menu a inserimento
testuale è disponibile anche `:annulla`; durante il calcolo usare Ctrl+C.
Prima dell'avvio, l'annullamento scarta la compilazione senza creare un run.
Durante un'esecuzione, conserva invece i log e tutti gli output già prodotti.

Il client tenta di fermare il container corrente. Per un piano, il motore
inoltra l'interruzione al gruppo di processi scientifici e il client concede
un intervallo di arresto prima della rimozione forzata. Se l'arresto non viene
confermato, l'avviso e il log richiedono una verifica dello stato del runtime;
il ritorno al menu non costituisce una conferma di arresto in questo caso.
Una chiusura forzata del programma o uno spegnimento possono lasciare
`preparing` o `running`: questi stati non indicano successo e non provano che
il container sia ancora attivo. Conservare il run e usare un nuovo nome per
ripetere l'analisi. I comandi CLI diretti terminano dopo l'interruzione,
senza aprire il menu guidato.

## Metadati e riproducibilità

`run.json` registra workflow, parametri, input, data e ora UTC, versione
Python, sorgenti del client e informazioni Git o della release quando
disponibili. `source.role = client` distingue l'identità applicativa da
quella scientifica. `source.nipat_version` registra la versione del client
utilizzata per quel run. Un aggiornamento dell'applicazione non riscrive i
record precedenti: confrontare versione, parametri e identità del motore prima
di attribuire differenze tra analisi a un aggiornamento.

`runtime.engine` identifica script R e moduli di preparazione presenti
nell'immagine. NIPAT verifica il manifest incorporato e l'interfaccia del
workflow prima dell'analisi. L'immagine viene risolta al suo identificativo
locale, registrato e riutilizzato per il run; un cambiamento del tag non
cambia il runtime tra le fasi della stessa esecuzione. Sono raccolte anche
le versioni di R, samtools e dei pacchetti R richiesti.

La modalità predefinita `--input-hashes auto` calcola SHA-256 per gli input
fino a **16 MiB**. Per file più grandi, come BAM e FASTA, registra percorso,
dimensione e data di modifica con una nota esplicita sull'assenza dell'hash.
Dimensione e data non attestano l'identità dei contenuti.

Con `--input-hashes full`, NIPAT legge tutti gli input per calcolarne SHA-256
prima del calcolo e li verifica nuovamente dopo l'esecuzione. Questa modalità
richiede letture aggiuntive dei BAM e dei FASTA e può prolungare la preparazione
e la conclusione del run. Il calcolo dei checksum può essere annullato.
Non vengono riutilizzati hash sulla sola base di dimensione e data del file.
Conservare comunque gli originali necessari alla riproduzione.

I mount in sola lettura impediscono al container di modificare gli input;
non impediscono a un altro programma sull'host di cambiarli. Evitare modifiche
ai file durante la preparazione e l'analisi. Un controllo dell'identità
prima e dopo il calcolo rileva le differenze osservabili fra quei due momenti,
ma non rende immutabile il file sull'host.

Il workflow automatico registra inoltre il collegamento fra identità dei
campioni, alias interni e tabelle prodotte. Il campo `parameters.expected_steps` in
`run.json` descrive i passaggi previsti e, per SNPcall, campione e modalità.
La consultazione dei risultati confronta questa struttura con lo stato
del motore, evitando di presentare un piano incompleto come riuscito. I risultati collegati tra i passaggi
hanno percorso relativo e hash SHA-256 nel file `workflow-state.json`.
Contamination copia e rinomina le tabelle nello staging interno senza alterare
i conteggi DNPcall; i nomi `table_0001`, ecc. vanno interpretati attraverso
questa corrispondenza, non confrontati direttamente con i nomi dei BAM.

Per SNPcall, `artifacts.snp-tables` associa l'ID del campione alla tabella
prodotta, con percorso relativo e SHA-256. `artifacts.preparation` identifica
BED e pileup generati in modalità BAM; `preparation_artifacts` nel record
del passaggio li conserva già prima dell'avvio R, anche se questo fallisce.
I pileup importati restano input: la loro provenienza non viene ricostruita
e non viene attribuita loro la configurazione samtools di NIPAT.

Per CPI, `artifacts.cpi-pairs` nel record del passaggio associa ogni ID di
coppia ai riferimenti materno e paterno, al nome nativo R, al PDF e alle righe
del riepilogo. `summary_rows` usa numeri a partire da 1, escludendo
l'intestazione del CSV, e conserva il valore `Cutoff` quando presente.
Gli alias come `Mothers0001-Fathers0002_DNPs` non sono nomi di campioni originali;
per attribuire i risultati usare questa mappa e `run.json`. Il campo
`pair_mapping` del passaggio conserva già la corrispondenza prima dell'avvio
R ed è disponibile per interpretare eventuali output parziali dopo un errore.
I CSV e PDF generati da R mantengono il proprio contenuto originale.

La corrispondenza tra file originali e percorsi nel container è conservata
nei metadati e in `work/input-mounts.json`. I BAM e i FASTA vengono montati
in sola lettura, senza copiarli nella cartella del progetto. DNPcall usa
alias `sample_0001`, ecc.; la mappa dei campioni permette di attribuire
tabelle e grafici ai BAM originali.

`work/engine-request.json` descrive la richiesta di un'analisi singola;
`work/engine-plan.json` descrive invece il workflow automatico.
`work/engine-compose.json` configura il container con i soli input
selezionati in sola lettura e il run corrente in scrittura. Il client non
monta i propri script R per eseguire le analisi. Il record riporta
`engine_verification = verified` dopo la verifica del motore;
in simulazione vale `not_run_dry_run` e gli intermedi scientifici non
vengono generati.

Il log mostra anche i messaggi nel terminale. `run.json` viene aggiornato
con sostituzione atomica del file; non è un database di cronologia globale.

## Limiti delle risorse

Le opzioni globali `--cpus`, `--memory-mb` e `--pids-limit` permettono di
impostare rispettivamente una quota CPU, un limite di memoria in MiB e un
limite di processi per il container scientifico. Se non indicate, NIPAT non
aggiunge limiti a quelli già applicati da Docker e, su Windows, da WSL.
Il menu può conservare queste scelte in **Configura → Esecuzione e provenienza**;
la CLI diretta usa le proprie opzioni.
Queste opzioni e `--input-hashes` riguardano analisi, workflow e wizard;
diagnostica, autotest e comandi di manutenzione mantengono i propri protocolli
e rifiutano opzioni di esecuzione non applicabili.

Questi limiti riguardano il container. La quota CPU non modifica il numero
di worker scelto da `detectCores()` nello script DNPcall quando si abilita
`--parallel`. Un limite di memoria o processi insufficiente può interrompere
il calcolo: scegliere valori adeguati al numero di campioni e alla dimensione
del pannello, conservando il log in caso di errore.

### Misure delle prestazioni

Nel checkout, `scripts/benchmark_workflows.py` esegue una serie esplicita di
prove DNPcall o DNPcall → Contamination e conserva `benchmark.json`, i log
dei comandi e run distinti. Richiede BAM reali distinti; non duplica un singolo
campione per simulare un numero maggiore di input. Esempio:

```sh
python scripts/benchmark_workflows.py \
  --bamlist /dati/bamlist.txt --reference /dati/genome.fa \
  --panel /dati/DNP_list.txt --output-dir /risultati/benchmark-nuovo \
  --sample-counts 1 10 --repeats 1 --workflow dnp-contamination
```

Il resoconto misura durata complessiva e dimensione dei file prodotti;
riporta il picco RAM dichiarato da R quando disponibile, che non rappresenta
necessariamente il picco dell'intero container. Sono disponibili anche i
limiti di risorse, la modalità checksum e `--parallel`. Le misure dipendono
da hardware, dati e configurazione: questo strumento prepara prove
riproducibili, non certifica prestazioni su altri computer. Le prove sono
facoltative e distinte dai controlli rapidi della CI.

## Esecuzioni incomplete

**Guida e informazioni → Esecuzioni incomplete** consente di confrontare
lo stato registrato con quello osservabile nel runtime. Dalla CLI:

```sh
nipat runs inspect
nipat runs inspect --run /percorso/del/run --json
nipat runs stop --run /percorso/del/run
```

`inspect` è una consultazione: non modifica i record storici e non arresta
processi. La mancata disponibilità del runtime è riportata separatamente
dall'assenza di un container. `stop` richiede una conferma esplicita;
`--yes` consente la conferma nei comandi automatizzati.

L'arresto è ammesso soltanto quando il container corrisponde all'identità
registrata da NIPAT per quel run, inclusi motore e immagine. I run privi
delle informazioni necessarie possono essere consultati ma non autorizzano
la rimozione del container. Non sono eseguite pulizie generali di Docker o WSL.
L'esito della richiesta di arresto è conservato in `recovery.json`, lasciando
intatti `run.json` e gli output. La sola consultazione non crea questo file. La funzione non riprende il calcolo:
per ripeterlo occorre un nuovo run.

## Intermedi e output per workflow

| Workflow | Intermedi conservati | Output principali |
| --- | --- | --- |
| DNPcall | `work/DNP_list.txt` e `work/bamlist.txt`, con pannello normalizzato e alias dei campioni. | Tabelle in `output/individual_outputs`, riepiloghi in `output/summary` e grafici in `output/plots`. |
| SNPcall | `work/SNPpanel.tsv` normalizzato; da BAM anche `work/snp_regions.bed` e `work/pileup.txt`. Da pileup: riferimento al file selezionato. | `output/SNPcall_output.txt`. |
| Contamination | `work/DNPpanel.txt` e tabelle preparate in `work/inputs`. | `output/contamination_summary.txt` e tabelle `contamination_full_output_*.txt`. |
| CPI | Tabelle parentali richieste in `work/inputs`; eventuale `work/DNPpanel.txt` o pannelli `work/cutoff_001.tsv`, ecc. | `output/Summary_FetalFraction_CPI.csv`, un PDF per coppia in `output/plots` e `output/plots/All_CPIplots.pdf`. |

Il pileup e il BED generati internamente da DNPcall nella radice del run
vengono eliminati al termine dallo script R; non sono intermedi conservati
stabilmente. Con un solo campione, il grafico UpSet non viene prodotto.

CPI copia senza modificare i byte le sole tabelle parentali richieste.
Un campione presente in più coppie viene preparato una sola volta. La modalità
ALL non genera pannelli e non aggiunge `Cutoff` al CSV. Un pannello singolo
produce una colonna `Cutoff` con il percorso interno del pannello; i cutoff
etichettati conservano le etichette selezionate. I nomi dei PDF e la colonna
`Pair` usano `Mother<id>-Father<id>_DNPs`, anche quando i prefissi degli input
sono diversi. Nei piani gli ID nativi sono assegnati dal motore e documentati
nella mappa delle coppie. Lo script produce il riepilogo CSV e i PDF, non
tabelle di dettaglio per sito o per iterazione.

## Conservazione e uso successivo

Conservare insieme `output`, `work`, `run.json` ed `execution.log`, oltre agli
input originali necessari alla riproduzione. Nel workflow automatico,
conservare l'intera sottocartella `output/workflow`: piano, stati, richieste,
log e output dei passaggi selezionati formano un insieme collegato. Non rinominare
singoli file al suo interno se si vogliono conservare i riferimenti registrati.
Non è prevista la ripresa automatica di un piano interrotto; una nuova prova
richiede un nuovo run.

Le altre sequenze si compongono selezionando gli output compatibili del run
completato come input del successivo. Le tabelle individuali DNPcall possono
alimentare Contamination e, con ruoli materni/paterni e frequenze adeguati, CPI.
La [guida alle sequenze](GUIDA_UTILIZZO.md#risultati-e-analisi-in-sequenza)
descrive la preparazione richiesta. Per collegare run avviati separatamente,
documentare il run sorgente e l'eventuale rinomina delle copie utilizzate
come input; questi collegamenti non vengono ricostruiti automaticamente.

I metadati contengono nomi e percorsi dei campioni e non sono anonimizzati.
Prima di condividere una segnalazione o pubblicare un allegato, controllare
il contenuto dei file. La [scheda di validazione](VALIDAZIONE.md) aiuta a
registrare atteso, osservato e materiali riproducibili.

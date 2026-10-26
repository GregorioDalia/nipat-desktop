# Risultati e registrazione delle esecuzioni

In NIPAT Desktop ogni analisi singola o workflow automatico crea un nuovo
**run** nella cartella risultati.
La destinazione predefinita Windows è
`%LOCALAPPDATA%\NIPAT-Desktop\runs`; nel pacchetto Ubuntu è
`${XDG_DATA_HOME:-~/.local/share}/nipat-desktop/runs`. Nel checkout
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

I percorsi si possono aprire dalla schermata finale del menu oppure dal
file system. **6 — Ultima esecuzione** richiama il run più recente della
sessione. I nomi dei file scientifici sono quelli prodotti dal workflow.

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
| `succeeded` | Il processo del workflow è terminato senza errori segnalati. |
| `failed` | Errore durante preparazione o esecuzione; consultare il log. |
| `interrupted` | Interruzione intercettata, per esempio Ctrl+C. |

Il successo descrive il completamento tecnico, non la correttezza scientifica
per un particolare campione. Una cartella con alcuni output può appartenere
a un'esecuzione fallita. Gli autotest confrontano i valori dopo il completamento
del workflow: anche il loro esito finale deve essere positivo.

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

Ctrl+C tenta di fermare il container corrente. Per un piano, il motore inoltra
l'interruzione al gruppo di processi scientifici e il client concede un
intervallo di arresto prima della rimozione forzata. Una chiusura forzata del
programma o uno spegnimento possono lasciare `preparing` o `running`:
questi stati non indicano successo e non provano che il container sia ancora
attivo. Conservare il run e usare un nuovo nome per ripetere l'analisi.

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

Gli input fino a **16 MiB** ricevono un hash SHA-256. Per file più grandi,
come BAM e FASTA, sono registrati percorso, dimensione e data di modifica,
con una nota esplicita sull'assenza dell'hash. Dimensione e data non
attestano l'identità dei contenuti: per riprodurre un'analisi conservare
gli originali o un proprio inventario dei checksum.

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

## Intermedi e output per workflow

| Workflow | Intermedi conservati | Output principali |
| --- | --- | --- |
| DNPcall | `work/DNP_list.txt` e `work/bamlist.txt`, con pannello normalizzato e alias dei campioni. | Tabelle in `output/individual_outputs`, riepiloghi in `output/summary` e grafici in `output/plots`. |
| SNPcall | Da BAM: `work/snp_regions.bed` e `work/pileup.txt`. Da pileup: riferimento al file selezionato. | `output/SNPcall_output.txt`. |
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

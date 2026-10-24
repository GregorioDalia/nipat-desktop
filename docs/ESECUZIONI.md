# Risultati e registrazione delle esecuzioni

In NIPAT 0.5 ogni analisi crea un nuovo **run** nella cartella risultati.
La destinazione predefinita Windows è
`%LOCALAPPDATA%\NIPAT-0.5-Preview\runs`; nel pacchetto Ubuntu è
`${XDG_DATA_HOME:-~/.local/share}/nipat-05-preview/runs`. Nel checkout
da sorgenti è `runs` accanto al progetto. Si può impostare una destinazione con `--runs-dir`
prima del sottocomando o con **5 — Cartella risultati** per la sessione corrente.
Un run esistente non viene sovrascritto.

## Contenuto del run

| File o cartella | Contenuto |
| --- | --- |
| `output` | Tabelle e grafici scientifici. |
| `work` | Richiesta al motore, configurazione dei mount e intermedi conservati. |
| `run.json` | Stato, input, parametri, software e identità del motore. |
| `execution.log` | Comandi eseguiti e output combinato standard/errori. |

I percorsi si possono aprire dalla schermata finale del menu oppure dal
file system. **6 — Ultima esecuzione** richiama il run più recente della
sessione. I nomi dei file scientifici sono quelli prodotti dal workflow.

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

Ctrl+C tenta di fermare il container corrente. Una chiusura forzata del
programma o uno spegnimento possono lasciare `preparing` o `running`:
questi stati non indicano successo e non provano che il container sia ancora
attivo. Conservare il run e usare un nuovo nome per ripetere l'analisi.

## Metadati e riproducibilità

`run.json` registra workflow, parametri, input, data e ora UTC, versione
Python, sorgenti del client e informazioni Git o della release quando
disponibili. `source.role = client` distingue l'identità applicativa da
quella scientifica.

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

La corrispondenza tra file originali e percorsi nel container è conservata
nei metadati e in `work/input-mounts.json`. I BAM e i FASTA vengono montati
in sola lettura, senza copiarli nella cartella del progetto. DNPcall usa
alias `sample_0001`, ecc.; la mappa dei campioni permette di attribuire
tabelle e grafici ai BAM originali.

`work/engine-request.json` descrive la richiesta al motore.
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
| CPI | Tabelle parentali richieste in `work/inputs`; eventuale `work/DNPpanel.txt` o pannelli `work/cutoff_001.tsv`, ecc. | `output/Summary_FetalFraction_CPI.csv`, risultati per coppia e grafici. |

Il pileup e il BED generati internamente da DNPcall nella radice del run
vengono eliminati al termine dallo script R; non sono intermedi conservati
stabilmente. Con un solo campione, il grafico UpSet non viene prodotto.

CPI copia senza modificare i byte le sole tabelle parentali richieste.
Un campione presente in più coppie viene preparato una sola volta. La modalità
ALL non genera pannelli e non aggiunge `Cutoff` al CSV. Un pannello singolo
produce una colonna `Cutoff` con il percorso interno del pannello; i cutoff
etichettati conservano le etichette selezionate. I risultati per coppia usano
nomi `Mother<id>-Father<id>_DNPs`, anche quando i prefissi degli input sono diversi.

## Conservazione e uso successivo

Conservare insieme `output`, `work`, `run.json` ed `execution.log`, oltre agli
input originali necessari alla riproduzione. Per concatenare analisi,
selezionare gli output compatibili del run completato come input del
successivo; ogni passaggio mantiene una propria cartella e un proprio record.

I metadati contengono nomi e percorsi dei campioni e non sono anonimizzati.
Prima di condividere una segnalazione o pubblicare un allegato, controllare
il contenuto dei file. La [scheda di validazione](VALIDAZIONE.md) aiuta a
registrare atteso, osservato e materiali riproducibili.

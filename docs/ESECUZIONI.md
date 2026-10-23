# Registrazione delle esecuzioni

Ogni nuova analisi conserva `run.json` ed `execution.log` nella propria
cartella sotto la radice dei risultati scelta dall'utente, accanto a `work`
e `output`. La radice predefinita dell'applicazione installata è
`%LOCALAPPDATA%\NIPAT\runs`; da sorgenti è `runs` accanto al progetto. Si può cambiarla
con `--runs-dir`, `NIPAT_RUNS_DIR` o l'opzione **5 — Cartella risultati** del
menu. La scelta nel menu vale per i run successivi nella sessione corrente.
I nomi degli output scientifici
rimangono quelli prodotti dagli script, all'interno del nuovo run.

Il JSON descrive il workflow completo. Per SNPcall, il successo del comando
samtools non conclude il run: deve terminare anche lo script R. Le date sono
registrate in UTC con fuso esplicito.

| Stato | Significato |
| --- | --- |
| `preparing` | Raccolta delle informazioni e controlli prima dell'analisi. |
| `running` | Workflow avviato, senza esito finale registrato. |
| `planned` | Dry-run: comandi preparati, analisi scientifica non eseguita. |
| `succeeded` | Tutti i comandi del workflow sono terminati correttamente. |
| `failed` | Errore durante preparazione o esecuzione; consultare il log. |
| `interrupted` | Interruzione intercettata dal processo, per esempio Ctrl+C. |

Il successo riguarda l'esecuzione, non la validità scientifica del risultato.
Per SNPcall, CPI e Contamination gli script di autotest confrontano i valori dopo la
chiusura del workflow: fa fede anche l'esito finale di `nipat self-test`.

Il record comprende input e parametri, versione del Python effettivo, hash dei
sorgenti, metadati Git quando disponibili e informazioni `release.json` del
pacchetto. Viene registrato l'identificativo effettivo dell'immagine Docker;
il runner lo usa anche per l'analisi, evitando che un cambiamento del tag
fra due comandi cambi il runtime. Sono raccolte le versioni di R, samtools
e dei pacchetti R richiesti.

Gli input fino a 16 MiB ricevono un hash SHA-256. Per file più grandi, come
BAM e FASTA, vengono registrati percorso, dimensione e data di modifica,
con indicazione esplicita dell'assenza dell'hash. Questi metadati non provano
l'identità dei contenuti: conservare gli originali usati nelle prove.

Gli input possono provenire da percorsi esterni al progetto. Ogni esecuzione
registra la corrispondenza fra i file originali e i percorsi montati in sola
lettura nel container, anche in `work/input-mounts.json`. I file BAM e FASTA
non vengono copiati per spostarli dentro il progetto. Gli adattamenti di
piccole tabelle sono conservati in `work`; la conservazione degli altri intermedi
dipende dal workflow.
Per DNPcall gli alias `sample_0001.bam`, ecc. evitano le limitazioni dei nomi
nello script R: la corrispondenza dei campioni nei metadati permette di
attribuire i risultati ai BAM originali.

Il log salva i comandi e l'output combinato standard/errori, continuando
a mostrarlo nel terminale. I file JSON vengono sostituiti atomicamente dopo
ogni aggiornamento. Il manifest scientifico viene verificato prima di
eseguire i comandi dei workflow.

Nel percorso di sviluppo 0.5, Contamination, SNPcall e DNPcall usano il motore incorporato.
`work/engine-request.json` descrive la richiesta; `work/engine-compose.json`
è l'unica configurazione Compose usata per l'analisi. Espone soltanto gli input
selezionati in sola lettura e la cartella del run corrente in scrittura.
Per Contamination il motore genera `work/DNPpanel.txt` e `work/inputs`, conservando i nomi dei campioni.
Per SNPcall da BAM genera `work/snp_regions.bed` e `work/pileup.txt`, quindi avvia R
soltanto se samtools termina con successo. Nella modalità pileup usa direttamente
il file selezionato. Il risultato rimane `output/SNPcall_output.txt`.
`run.json` registra una sola invocazione del motore per l'intero workflow;
per SNPcall il log contiene anche il comando samtools eseguito nel container.

Per DNPcall il motore conserva `work/DNP_list.txt` e `work/bamlist.txt`, con gli
alias ordinati dei campioni. Lo script R genera il pileup e il BED nella radice
del run e li elimina al termine: non sono intermedi conservati stabilmente.
Il comportamento R rimane invariato, compresa una limitazione: la chiamata interna
a samtools nasconde lo stderr e non ne verifica il codice di uscita. Lo stato del
run riflette quindi quello del processo R, senza garantire il rilevamento di ogni
errore interno di samtools. I controlli numerici degli output restano necessari.

Per questi workflow, `source.role` vale `client`: gli hash locali descrivono
l'applicazione, mentre `runtime.engine` identifica gli script R e i moduli Python
di preparazione effettivamente presenti nell'immagine. Il controllo di integrità
scientifica riguarda quindi il manifest incorporato, non una copia R sul PC.
`engine_verification` vale `verified` dopo il controllo del motore; in dry-run
vale `not_run_dry_run` e non vengono creati gli intermedi scientifici.

Ctrl+C tenta di fermare anche il container della fase corrente. In caso
di chiusura forzata del processo o spegnimento del PC, il record può restare
`preparing` o `running`: non va interpretato come successo né come prova
che un container sia ancora attivo. I run precedenti non vengono modificati
o ricostruiti retroattivamente. Un nuovo tentativo crea una nuova cartella.

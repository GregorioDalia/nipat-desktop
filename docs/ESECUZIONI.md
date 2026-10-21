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
Per CPI e Contamination gli script di autotest confrontano i valori dopo la
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
piccole tabelle e i file intermedi sono conservati in `work`.
Per DNPcall gli alias `sample_0001.bam`, ecc. evitano le limitazioni dei nomi
nello script R: la corrispondenza dei campioni nei metadati permette di
attribuire i risultati ai BAM originali.

Il log salva i comandi e l'output combinato standard/errori, continuando
a mostrarlo nel terminale. I file JSON vengono sostituiti atomicamente dopo
ogni aggiornamento. Il manifest scientifico viene verificato prima di
eseguire i comandi dei workflow.

Ctrl+C tenta di fermare anche il container della fase corrente. In caso
di chiusura forzata del processo o spegnimento del PC, il record può restare
`preparing` o `running`: non va interpretato come successo né come prova
che un container sia ancora attivo. I run precedenti non vengono modificati
o ricostruiti retroattivamente. Un nuovo tentativo crea una nuova cartella.

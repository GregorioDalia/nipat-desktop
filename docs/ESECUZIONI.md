# Risultati e registrazione delle esecuzioni

Ogni analisi crea una nuova cartella, o **run**, nella destinazione dei
risultati. Se il nome è già in uso, scegliere un nome diverso.
Nel menu usare **5 — Configura → Cartelle dati e risultati** per la
destinazione predefinita. Nella CLI usare `--runs-dir` prima del comando.
La [guida d'uso](GUIDA_UTILIZZO.md#percorsi-e-cartelle) elenca i percorsi
predefiniti per piattaforma.

## Contenuto del run

| Aprire | Per trovare |
| --- | --- |
| `run-report.html` | Esito, file di input, campioni, impostazioni, fasi, risorse e avvisi, in un riepilogo per il browser. |
| `output/` | Tabelle e grafici canonici prodotti dal motore. |
| `output/presentation/` | Export leggibili con le etichette dei campioni nelle analisi singole quando disponibili. |
| `sample-map.tsv` | Associazione fra file originali e ID interni, ad esempio `sample_0001`. |
| `run.json` | Registro strutturato con stato, input, parametri, software e identità del motore. |
| `execution.log` | Comandi, messaggi e dettagli degli errori. |
| `work/` | Richiesta inviata al motore, configurazione dei mount e intermedi conservati. |

La schermata finale apre il rapporto, le cartelle o i log. **6 — Ultima
esecuzione** richiama il run più recente della sessione quando ne è stata
creata la cartella. Per i run precedenti, aprire la cartella dalla destinazione
dei risultati.

### Workflow automatici

Il workflow ha un solo `run.json` e più passaggi sotto `output/workflow/`.

| Percorso relativo a `output/workflow/` | Contenuto |
| --- | --- |
| `plan.json` | Piano canonico con campioni, ruoli, passaggi e dipendenze. |
| `workflow-state.json` | Esito complessivo e dei singoli passaggi, artefatti e checksum. |
| `steps/<id>/output/` | Risultati canonici del passaggio. |
| `steps/<id>/command.log` | Messaggi del processo R. |
| `steps/<id>/request.json` | Richiesta concreta del passaggio. |
| `steps/<id>/work/` | Tabelle, pannelli e altri intermedi specifici del passaggio. |
| `presentation/` | Export del piano organizzati per campione o famiglia. |
| `snp_summary/group_0001/`, ecc. | Genotipi aggregati, etichette, grafici e risorse dei gruppi SNP compatibili. |

I preset DNP usano identificativi come `dnp`, `contamination` e `cpi`.
`workflow analyze` distingue il ramo, per esempio `dnp_cpi` e
`snp_cpi`. I campioni SNP hanno passaggi `snp_0001`, `snp_0002`, ecc.
Seguire il piano e le mappe del run per associare un file al suo campione
o alla sua famiglia.

Un passaggio SNP da BAM conserva `work/snp_regions.bed`,
`work/pileup.txt` e `preparation.log`. Il pileup fornito come input
è registrato tra i file originali del run. In DNPcall samtools è invocato
all'interno del processo R tramite l'acquisizione DNP; per individuarne
tempi ed esito consultare [le misure DNP](PERFORMANCE.md#consultazione-dei-risultati).

## Stati e significato dell'esito

| Stato del run | Significato |
| --- | --- |
| `preparing` | Controlli e preparazione in corso. |
| `running` | Motore avviato, esito finale ancora da registrare. |
| `planned` | Simulazione con `--dry-run`. |
| `succeeded` | Esecuzione conclusa e controlli tecnici sugli output superati. |
| `failed` | Errore durante la preparazione o l'esecuzione. |
| `interrupted` | Interruzione intercettata dal client, per esempio Ctrl+C. |

Controllare stato e avvisi anche quando tabelle o grafici sono presenti.
Gli avvisi di qualità possono accompagnare un run riuscito. Nelle analisi
singole sono registrati in `work/scientific-validation.json`; nei piani
in `artifacts.quality_warnings` del passaggio. Per i controlli in ingresso
consultare `work/input-validation.json` nella cartella dell'analisi o
del passaggio. La [guida ai controlli](INPUT_VALIDATION.md) spiega come
interpretare errori e avvisi.

Nel piano i passaggi ancora da iniziare sono `pending`. Dopo un
errore o un'interruzione diventano `blocked`; il passaggio interrotto
può essere registrato come `cancelled`. Una singola fase riuscita
conferma solo l'esecuzione di quella fase. Il collaudo sintetico usa
risultati attesi per verificare alcuni casi noti; i risultati sui propri
campioni richiedono una valutazione appropriata al contesto.

## Metadati e riproducibilità

Per confrontare due esecuzioni, conservare almeno:

- **Input.** File, ordine dei campioni, mapping di coppie o terne, pannelli
  e frequenze. `--input-hashes auto` calcola SHA-256 fino a 16 MiB; per
  quelli maggiori registra i metadati, che non attestano l'identità dei
  byte. `--input-hashes full` aggiunge il calcolo e le verifiche degli
  hash anche per BAM e FASTA grandi, con letture complete aggiuntive.
- **Parametri.** `run.json` registra la richiesta. Il modulo conserva le
  impostazioni effettive in `work/effective-scientific-settings.json`
  e in `output/scientific-settings.json`. Nei piani questi file si
  trovano nella cartella di ogni passaggio.
- **Software.** `source.nipat_version` identifica il client.
  `runtime.engine` descrive il motore incorporato, gli script e le
  interfacce verificate. Il run riporta l'identità risolta dell'immagine
  e le versioni degli strumenti.
- **Collegamenti.** `workflow-state.json` collega ID interni, file e
  checksum. `artifacts.snp-tables` risale alla tabella del campione,
  `artifacts.cpi-pairs` alle coppie e alle righe CSV,
  `artifacts.cpin-trios` alle terne. Per interpretare alias come
  `table_0001` o `Mothers0001-Fathers0002_DNPs` seguire le mappe.
  `summary_rows` conta le righe dati da 1 ed esclude l'intestazione.

I file selezionati sono montati in sola lettura nel container per
limitare le scritture durante il calcolo. Tenere gli originali invariati
sull'host fino alla fine. `work/input-mounts.json` registra quali file
sono stati collegati e con quali alias. `work/engine-request.json`
oppure `work/engine-plan.json` conserva la richiesta; `work/engine-compose.json`
descrive l'ambiente di esecuzione.

I risultati in `presentation` aggiungono etichette leggibili senza
ricostruire l'identità biologica dei campioni. I passaggi successivi del
workflow usano gli artefatti canonici. Per collegare run avviati
separatamente, annotare il run sorgente e la corrispondenza di eventuali
copie o tabelle rinominate.

## Limiti delle risorse

| Opzione globale | Effetto |
| --- | --- |
| `--cpus` | Quota CPU del container, considerata al momento di scegliere il budget di calcolo. |
| `--memory-mb` | Limite memoria del container in MiB. |
| `--pids-limit` | Tetto al numero di processi nel container, inclusi i coordinatori. |
| `--execution-mode serial` | Un solo processo di calcolo alla volta. |
| `--execution-mode auto` | Scelta automatica secondo risorse disponibili e carico. |
| `--max-workers` | Massimo dei processi simultanei di calcolo, entro il budget automatico. |

Le prime tre opzioni riguardano il container. Su Windows e macOS le
risorse di WSL o Lima costituiscono un ulteriore limite. Omettere
un'opzione mantiene il limite dell'ambiente. Il tetto dei worker è una
richiesta distinta dalla quota CPU. I [controlli delle risorse](RISORSE.md)
spiegano valori rilevati, configurazione e diagnostica.

### Misure delle prestazioni

Scegliere **Avvia analisi con diagnostica prestazioni** nel menu o
usare `--performance-diagnostics` prima del comando. Il rapporto HTML e
`performance/` conservano le misure disponibili di tempi, memoria e CPU.
La [guida alle prestazioni](PERFORMANCE.md) spiega come confrontare modalità,
fasi e fonti della memoria in prove ripetute.

## Esecuzioni incomplete

Una chiusura forzata può lasciare `preparing` o `running` nel registro.
Per verificare lo stato del runtime usare **Guida e informazioni →
Esecuzioni incomplete**, oppure:

```sh
nipat runs inspect
nipat runs inspect --run "/percorso/del/run" --json
nipat runs stop --run "/percorso/del/run"
```

`inspect` consulta senza arrestare processi. `stop` richiede conferma e
agisce solo sul container riconosciuto per quel run. `--yes` è la conferma
esplicita per l'uso automatizzato. `recovery.json` conserva l'esito
dell'arresto; la sola consultazione non lo crea. Per ripetere il calcolo
correggere la causa e avviare un nuovo run.

## Intermedi e output per workflow

I percorsi seguenti partono dal run di un modulo singolo o dalla cartella
`steps/<id>/` del workflow.

| Modulo | Output principali |
| --- | --- |
| DNPcall | `output/individual_outputs/` per campione, tabella dei genotipi e grafici in `output/summary/`, altri grafici in `output/plots/`. |
| SNPcall | `output/SNPcall_output.txt`, grafici per campione e riepiloghi in `output/summary/`. |
| Contamination | `output/contamination_summary.txt` e tabelle `contamination_<campione>.txt`, con gli alias del run. |
| CPI | `output/Summary_FetalFraction_CPI.csv`, curve in `output/curves/`, PDF in `output/plots/`. |
| CPIN | `output/Summary_Postnatal_CPI.txt`, siti in `output/sites/`, curve in `output/curves/` e PDF. |

Le tabelle individuali dei caller possono alimentare una nuova analisi.
I riepiloghi e i grafici servono per la consultazione. I pileup e altri
intermedi temporanei DNPcall non sono conservati stabilmente.
I riepiloghi SNP aggregano solo campioni con pannello, riferimento e
modalità compatibili. Il grafico UpSet conta loci con genotipo assegnato.
Il file SNP `resources.tsv` riporta il tempo della fase R e osservazioni
RSS iniziale e finale; per il picco del container consultare la diagnostica.

## Conservazione e uso successivo

Conservare la cartella completa del run e gli input originali per
ricostruire l'analisi. Nei workflow, `output/workflow/` contiene percorsi
relativi tra stati, log, artefatti e richieste; mantenere la struttura
quando la si sposta. Per avviare un'altra analisi dai risultati seguire
la [guida alle tabelle esistenti](GUIDA_UTILIZZO.md#utilizzo-di-tabelle-già-disponibili).

Prima di allegare log, metadati o report a una segnalazione, controllare
nomi e percorsi dei campioni e la presenza di dati identificativi.
La [scheda di validazione](VALIDAZIONE.md) aiuta a conservare atteso,
osservato ed evidenze riproducibili.

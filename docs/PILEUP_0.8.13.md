# Pileup parallelo — candidato 0.8.13

La 0.8.13 estende il parallelismo alla **preparazione del pileup DNP**.
Il riferimento scientifico resta NIPAT 0.8.5, con gli stessi requisiti di
equivalenza dei [test differenziali](../tests/r_optimization/README.md).
Questa guida descrive il candidato e il protocollo di collaudo; non dichiara
un'accelerazione misurata sui dati reali o la validazione degli installer.

## Perché questo intervento

Un run DNP della 0.8.12 con un BAM e 845 loci ha registrato:

| Fase | Durata |
| --- | ---: |
| Acquisizione del pileup | 148,155 s |
| Scansione e indicizzazione | 16,292 s |
| Calcolo dei blocchi, con cinque processi R | 41,918 s |
| Altre operazioni comprese nel run | 9,709 s |
| Totale del run | 216,074 s |

Il precedente run 0.8.10 seriale a 32 MiB durava 298,676 s. Sono singole
osservazioni: spiegano la priorità data alla preparazione, ma non misurano
la nuova 0.8.13. I quattro file di tabelle esportate coincidevano nei byte
fra quei run; il confronto del dataset reale con 0.8.5 resta distinto e da
completare. I dati identificativi e gli archivi dei run non sono inclusi
nel repository.

## Preparazione per cromosoma

Quando tutti i BAM hanno un indice e dizionari di riferimento compatibili,
il preparatore crea attività per i cromosomi del pannello. Ogni attività
avvia **un solo processo `samtools mpileup`**, selezionando il cromosoma e
le posizioni richieste. Mantiene ordine dei campioni, opzioni scientifiche,
filtri, BAQ e limite di profondità. Le finestre DNP non vengono suddivise
fra attività.

I risultati parziali sono scritti nello scratch Linux e ricomposti
nell'ordine del dizionario `@SQ` del BAM, indipendentemente dall'ordine in
cui terminano i processi. Il file completo passa poi all'indice e al
calcolo R esistenti. L'inferenza dei tipi e i controlli globali su QNAME e
coordinate rimangono prima del calcolo dei blocchi.

La selezione per cromosoma ha un compromesso prestazionale da misurare:
`mpileup -r` può leggere e decodificare più allineamenti fuori pannello
rispetto alla preselezione multi-intervallo `view -M -L` della 0.8.12.
Il filtro BED rimane applicato prima del calcolo BAQ: il costo aggiuntivo
possibile riguarda lettura e decodifica, senza cambiare le opzioni scientifiche.
Su un BAM dell'intero genoma con un pannello molto rado, il lavoro supplementare
può compensare o superare il beneficio del parallelismo. La 0.8.13 è quindi
un candidato da collaudare per questo carico, non un'accelerazione garantita
per ogni BAM o pannello.

Indici assenti o misti, dizionari non compatibili o nomi di riferimento
ambigui per la selezione regionale richiedono il percorso seriale
`sequential-budgeted`. In questo percorso ogni BAM con indice viene prima
preselezionato da `samtools view -M -L` in un file temporaneo sul disco Linux;
i BAM senza indice vengono letti dagli originali. Dopo le preselezioni,
un solo `mpileup` elabora la lista conservando l'ordine dei campioni.
Queste operazioni avvengono in successione, con un processo samtools alla
volta. Il tempo e i byte dello staging fanno parte delle misure di acquisizione.

La motivazione del ripiego viene registrata. Un indice presente non viene
ignorato soltanto perché un altro BAM non ne possiede uno: gli errori della
preselezione o dell'elaborazione indicizzata interrompono il run.
L'interruzione arresta e attende i processi avviati dal preparatore; un run
fallito o annullato conserva la diagnostica e non presenta un pileup parziale
come risultato completato.

La selezione usa le funzionalità di
[samtools 1.21](https://www.htslib.org/doc/1.21/samtools-mpileup.html).
La qualificazione deve dimostrare l'identità del pileup rispetto al percorso
di riferimento: la disponibilità dell'opzione regionale, da sola, non è
una prova di equivalenza.

## Budget e impostazioni

Le opzioni già disponibili dalla [0.8.12](PARALLELISMO_0.8.12.md) restano:

| Impostazione | Valore iniziale | Effetto nella 0.8.13 |
| --- | --- | --- |
| `--execution-mode` | `auto` | Scelta automatica; `serial` mantiene un solo processo di calcolo per fase. |
| `--max-workers` | Nessun massimo manuale | Limita i processi di preparazione DNP e i processi R di calcolo. |
| `--dnp-block-mib` | `32` | Obiettivo di input grezzo per blocco R, non limite RAM. |
| `--dnp-block-loci` | `64` | Obiettivo di loci completi per blocco R. |

La stessa politica considera CPU disponibili, quote del container, memoria,
PID e limite manuale. La preparazione riceve il budget calcolato da R prima
dell'acquisizione e lo limita al numero di attività indipendenti disponibili.
Nella fase di preparazione ogni attività occupa un processo samtools; nella
fase successiva lo stesso massimo limita i processi R di calcolo. Le due fasi
non sono concorrenti e non aprono pool annidati.

Il numero effettivo può essere inferiore al massimo e diverso fra le fasi.
Il budget conserva almeno un processo; le stime di memoria non garantiscono
che qualsiasi dataset rientri nella RAM. Coordinatori, client e monitoraggio
non sono processi di calcolo del pool: il limite complessivo dei PID del
container (`--pids-limit`) è un controllo distinto.

Gli input originali restano in sola lettura. Lo scratch era già nel filesystem
Linux prima di questa versione: la 0.8.13 non introduce una copia automatica
integrale di BAM e FASTA. Un eventuale esperimento di località degli input
deve misurare anche il costo della copia.

## Evidenze da conservare

| File relativo al run | Significato |
| --- | --- |
| `run.json` | Versione, commit, input, opzioni richieste, risorse e stato. |
| `work/dnp-acquisition-budget.json` | Budget trasmesso alla preparazione. |
| `work/dnp-pileup.json` | Strategia, motivazione dell'eventuale ripiego, tempi e attività dei processi di acquisizione. |
| `work/dnp-blocks.json` | Blocchi R, tempi di acquisizione/indice/calcolo e processi effettivi. |
| `work/parallel/*.jsonl` | Decisioni e intervalli di attività dei processi R. |
| `performance/engine/summary.json` e `performance/engine/samples.jsonl` | Memoria del container, CPU e contatori dei processi, quando la diagnostica è attiva. |
| `output/` | Risultati scientifici da confrontare. |

Nei workflow composti, i file `work/` appartengono al passaggio sotto
`output/workflow/steps/<id>/`. Il report deve distinguere configurazione
richiesta e processi osservati: il vecchio parametro DNP `parallel=false`
non significa che la modalità automatica sia disattivata.

La dicitura R **Maximum observed R-process RSS (MiB)** descrive un massimo
osservato per processo. Per confrontare il consumo complessivo usare il
picco cgroup, quando disponibile; non sommare gli RSS, che possono contare
le stesse pagine condivise.

## Collaudo Windows

1. Conservare l'identità delle build 0.8.12 e 0.8.13 e dei medesimi BAM,
   indici, FASTA e pannello. Il numero nel nome di una vecchia cartella
   risultati non identifica la versione: fanno fede i metadati del run.
2. Mantenere fisse le risorse WSL/container, la politica dei checksum,
   **32 MiB / 64 loci** e la diagnostica. Evitare altre analisi concorrenti.
3. Confrontare le quattro condizioni seguenti. Riutilizzare un run precedente
   soltanto se input, versione, impostazioni e risultati sono verificabili;
   assegnare un nome nuovo a ogni nuova esecuzione.

| Versione | Modalità | Scopo |
| --- | --- | --- |
| 0.8.12 | Seriale | Controllo del calcolo R precedente. |
| 0.8.12 | Automatica | Riferimento con il solo parallelismo R. |
| 0.8.13 | Seriale | Controllo del nuovo percorso con una sola attività alla volta. |
| 0.8.13 | Automatica | Misura della preparazione e del calcolo paralleli. |

Nel riepilogo dell'analisi, **4 — Parallelismo e blocchi** permette di scegliere
la modalità per il solo run corrente. Avviare con diagnostica e conservare
anche fallimenti o interruzioni. Per ripetizioni sostenibili, alternare l'ordine
delle condizioni; non interpretare un solo run come una stima stabile della
velocità o dell'effetto delle cache.

4. Verificare i processi effettivi e la sovrapposizione delle attività nelle
   rispettive fasi. Un massimo richiesto o molti PID osservati in successione
   non dimostrano parallelismo.
5. Confrontare il pileup nei test di qualifica e i risultati scientifici con
   **0.8.5**, inclusi ordine delle tabelle, quantità non arrotondate e grafici.
   Ripetere almeno la condizione parallela per verificare la ripetibilità.
   Il confronto già effettuato con 0.8.10 non sostituisce questo riferimento.
6. Valutare tempi totali e delle fasi, RAM cgroup e correttezza insieme. Solo
   successivamente confrontare altre dimensioni dei blocchi o altri limiti
   dei processi.

La [qualificazione locale 0.8.13](validation/0.8.13-rootless.json) è stata
completata sui sorgenti identificati dagli hash nel rapporto: **20 casi,
64 esecuzioni scientifiche e 44 confronti con 0.8.5**, senza riutilizzare
esecuzioni precedenti. Coincidono i byte di 145 confronti di tabelle, gli
oggetti R scientifici non arrotondati e 137 pagine PDF renderizzate a 36 DPI
(metadati PDF esclusi). Sono inoltre passati nove controlli R mirati,
25 casi di acquisizione pileup e il controllo della cancellazione R.

I casi pileup comprendono alta profondità, letture accoppiate sovrapposte,
indel, QNAME ripetuti, pannelli sovrapposti/non ordinati, ordine non lessicografico
dei cromosomi, input multipli, indici mancanti/corrotti, nomi di contig ambigui
e cancellazione. Nei test di acquisizione sono stati osservati direttamente
massimi di uno, due e quattro processi samtools. Nei 24 confronti R paralleli
il budget di memoria dell'ambiente ha selezionato due worker, anche quando
il massimo richiesto era quattro; tutti hanno mostrato attività sovrapposte.

Queste verifiche usano R 4.4.2 e samtools 1.21 su Linux, con runtime R
rilocato e senza Docker o WSL: non applicano le quote del container scientifico
e non qualificano gli installer né le prestazioni sul dataset reale.
Le [evidenze locali 0.8.12](validation/0.8.12-rootless.json) restano il
riferimento storico separato della versione precedente.

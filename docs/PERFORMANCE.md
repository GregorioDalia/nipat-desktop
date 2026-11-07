# Diagnostica delle prestazioni

Guida per **NIPAT Desktop 0.8.9**. La diagnostica è disponibile dalla 0.8.5.
Installare il pacchetto del proprio sistema dalla [release 0.8.9](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.9);
il banner dell'applicazione deve riportare `NIPAT 0.8.9`.

La diagnostica raccoglie misure locali per analizzare tempi, memoria e uso delle
risorse. È facoltativa e disattivata normalmente. Non modifica i parametri
scientifici, gli input o gli script R e non invia dati a servizi esterni.
Il monitoraggio introduce un costo che deve essere misurato separatamente.

## Prima misura dal menu

Per misurare DNPcall su un singolo BAM, preparare:

- Il BAM e il relativo indice, conservato accanto al file.
- Il FASTA della stessa assembly del BAM, con indice `.fai` ed eventuale `.gzi`
  per un FASTA BGZF. Nel menu si seleziona il FASTA, non il suo indice.
- Il pannello DNP effettivamente usato nell'analisi: cinque colonne senza
  intestazione, `chr`, `pos1`, `pos2`, `REF`, `ALT`.
- Una cartella locale per i risultati, con spazio per intermedi, tabelle e grafici.

Eseguire la prima coppia di prove:

1. Aprire **NIPAT Desktop** e controllare che il banner riporti `0.8.9`.
   Eseguire **8 — Verifica ambiente** prima del benchmark.
2. In **5 — Configura**, controllare la cartella risultati e i limiti delle
   risorse. Mantenerli uguali fra le prove; non aumentare CPU o RAM durante
   il confronto. Chiudere le applicazioni che possono introdurre carichi variabili.
3. Scegliere **1 — DNPcall**, inserire un solo BAM, il FASTA e il pannello.
   Mantenere gli stessi parametri scientifici e la stessa modalità di verifica
   degli input nelle due prove. Assegnare il nome `dnp-baseline-01` e confermare
   **Avvia analisi** nel riepilogo.
4. Ripetere DNPcall con gli stessi input e parametri, usando il nome
   `dnp-diagnostica-01`. Nel riepilogo scegliere
   **Avvia analisi con diagnostica prestazioni**.
5. Conservare entrambe le cartelle dei run. In `dnp-diagnostica-01`, aprire
   `run-report.html` e controllare la sezione **Diagnostica delle prestazioni**.
   Conservare anche `run.json`, `execution.log`, la cartella `performance` e gli
   output scientifici, necessari per interpretare le misure e confrontare i risultati.

La diagnostica è inclusa nell'installer e nel motore scientifico: questa
procedura non richiede di scaricare o avviare script separati. Non usare
`--dry-run`, perché quella modalità prepara il run senza eseguire il calcolo.
Una sola coppia di prove serve a verificare il funzionamento della raccolta;
per valutare i tempi seguire il [protocollo di ripetizione](#protocollo-per-un-bam-grande).
Se un'analisi fallisce o viene interrotta, conservare comunque il run.

## Attivazione per una singola analisi

Compilare gli input nel menu guidato e scegliere **Avvia analisi con diagnostica
prestazioni** nel riepilogo. La scelta riguarda quella esecuzione: l'analisi
successiva torna alla modalità ordinaria. **Avvia analisi** esegue il calcolo
senza monitoraggio delle prestazioni.

La CLI accetta l'opzione globale prima del comando:

```sh
nipat --performance-diagnostics dnp-call \
  --bam /dati/campione.bam --reference /dati/genome.fa \
  --panel /dati/DNP_list.txt --run-name dnp-diagnostica-01
```

Sono supportati anche gli altri comandi di analisi e i workflow automatici.
`nipat --performance-diagnostics wizard` propone la diagnostica per la
prossima analisi; il riepilogo permette comunque di avviarla in modalità
ordinaria. L'opzione non viene conservata nelle preferenze.
Il motore deve dichiarare il contratto `performance-diagnostics-v1`;
un'immagine precedente non viene considerata strumentata implicitamente.

## Misure e significato

| Misura | Origine | Interpretazione |
| --- | --- | --- |
| Durata totale | Supervisore del benchmark | Comprende avvio del client, preparazione, runtime, analisi e finalizzazione. |
| Tempi delle fasi | Eventi del motore con orologio monotono | Distingue i confini disponibili di preparazione, esecuzione R, controllo degli output e presentazione. Le fasi annidate non si sommano. |
| CPU del container | Docker e contatori cgroup disponibili | Comprende i processi del container. CPU cumulativa e percentuale istantanea sono grandezze diverse. |
| Memoria Docker | Osservatore esterno al container | Valore arrotondato della CLI Docker, che su Linux sottrae la cache inattiva. |
| Memoria cgroup | Monitor interno al motore | Memoria contabilizzata dal kernel per il gruppo, inclusa la cache. Non coincide con la memoria del solo R. |
| Picco cgroup | Contatore del kernel, quando disponibile | Massimo registrato dal kernel fino alla lettura; se l'ultima lettura manca, non garantisce il picco finale. |
| Processi osservati | `/proc` nel container | RSS e contatori dei processi selezionati, per distinguere R, samtools e il supervisore. La somma degli RSS non è una misura esatta del container perché le pagine possono essere condivise. |
| I/O | Contatori disponibili nel kernel e in Docker | Letture/scritture contabilizzate. Cache, filesystem condivisi e virtualizzazione possono limitarne l'attribuzione; un valore basso non esclude attese sul disco. |
| Stato di uscita | Docker e registri del run | Il codice 137 da solo non dimostra esaurimento della RAM; la diagnosi conserva separatamente le evidenze OOM. |

Il valore **Peak RAM** stampato da R è una rilevazione parziale del processo R:
non rappresenta il picco dell'intero container. I confronti devono riportare
sempre la fonte della misura e non scambiare questi valori.

Le misure sono periodiche: il massimo dei campioni può perdere picchi tra due
letture. I tempi reali dei campioni sono registrati e possono variare con il
carico e il trasporto. Il monitor interno usa un intervallo nominale di un
secondo; le interrogazioni esterne Docker hanno durata propria.

L'esecuzione R comprende anche la preparazione interna, il calcolo e i grafici
prodotti dallo script e dal wrapper di presentazione. Non vengono dichiarati
tempi esatti delle sottofasi DNPcall sulla base dell'arrivo delle righe di log.
Per distinguere due operazioni interne allo stesso processo R può essere
necessaria una successiva sessione di profiling mirato.

WSL, Lima e Docker Engine nativo usano lo stesso contratto di raccolta. Kernel,
controller e filesystem possono fornire informazioni diverse: dati non
disponibili rimangono tali e non diventano consumi pari a zero.

## Consultazione dei risultati

Aprire `run-report.html` nella cartella del run. La sezione **Diagnostica delle
prestazioni** riporta stato della raccolta, misure di memoria, fasi completate
e collegamenti ai file:

| File relativo al run | Contenuto |
| --- | --- |
| `performance/summary.json` | Riepilogo dell'osservatore esterno. |
| `performance/container-samples.jsonl` | Campioni ottenuti tramite Docker. |
| `performance/engine/summary.json` | Riepilogo del monitor interno, limiti e disponibilità. |
| `performance/engine/samples.jsonl` | Campioni cgroup e dei processi. |
| `performance/engine/phases.jsonl` | Eventi di inizio/fine delle fasi. |

I file sono scritti progressivamente e hanno limiti di dimensione. Un limite
raggiunto o un errore di monitoraggio non trasforma un calcolo riuscito in un
fallimento scientifico. La copertura parziale è indicata nei resoconti.
Se il container viene terminato, l'osservatore esterno può conservare le
misure già raccolte; una terminazione dell'applicazione, della VM o del computer
può lasciare un riepilogo incompleto. I campioni disponibili restano consultabili.
L'assenza di campioni in un run molto breve non equivale a un consumo nullo.

La diagnostica non acquisisce il contenuto del BAM né gli argomenti completi
dei processi. I normali `run.json`, log e rapporti del benchmark possono
contenere percorsi e nomi dei campioni: verificarli prima di condividerli.

## Protocollo per un BAM grande

1. Preparare BAM, indice, pannello realmente utilizzato e FASTA con i relativi
   indici. Conservare versioni, parametri e identità dei file.
2. Usare DNPcall su un solo BAM, con input e risultati su dischi locali.
   Annotare hardware, piattaforma, memoria e CPU assegnate al runtime e al
   container. Non modificare questi limiti durante il confronto.
3. Eseguire una prova esplorativa ordinaria e una con diagnostica. Se il costo
   delle analisi lo consente, ripetere ciascuna condizione tre volte,
   alternandone l'ordine e conservando anche fallimenti e interruzioni.
4. Confrontare i risultati canonici, oltre ai tempi. Usare le prove senza
   diagnostica per stimare le prestazioni ordinarie; le altre servono a
   spiegare il comportamento e a stimare il costo del monitoraggio.
5. Scegliere una modifica alla volta sulla base delle evidenze. Ripetere il
   confronto sugli stessi dati e parametri prima di attribuirle un beneficio.

Dal checkout si può usare il supervisore del benchmark:

```sh
python scripts/benchmark_workflows.py \
  --bamlist /dati/un-campione.txt --reference /dati/genome.fa \
  --panel /dati/DNP_list.txt --output-dir /risultati/benchmark-diagnostico \
  --sample-counts 1 --repeats 3 --workflow dnp-call --performance-diagnostics
```

Omettere `--performance-diagnostics` e scegliere una nuova cartella di output
per il riferimento ordinario. `benchmark.json` conserva i resoconti diagnostici
disponibili, le risorse e gli input di ciascun run. Non duplicare lo stesso BAM
per simulare un carico con più campioni.

La prima lettura e quelle successive possono risentire diversamente delle
cache. Il riavvio di WSL/Lima non dimostra che tutte le cache del computer
siano vuote. Anche il calcolo di checksum integrali legge i dati: usare la
stessa politica di verifica nelle prove confrontate. Per prove con copia dei
file nel filesystem Linux, misurare anche il tempo della copia.

La CI verifica la raccolta su casi sintetici, l'invarianza dei risultati e la
gestione degli errori. Non impone soglie di velocità sui runner condivisi.
I benchmark grandi restano controllati e separati dai test automatici rapidi.

## Riferimenti tecnici

- [Statistiche Docker](https://docs.docker.com/reference/cli/docker/container/stats/)
- [Contatori cgroup v2 del kernel Linux](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Risorse e memoria](RISORSE.md)
- [Registri delle esecuzioni](ESECUZIONI.md)

# Diagnostica delle prestazioni

La diagnostica è disponibile dalla 0.8.5. Le istruzioni ordinarie valgono per
la stabile **0.8.14**; il [collaudo 0.8.12](#collaudo-del-parallelismo-0812)
aggiunge il confronto delle modalità di parallelismo. Il
[collaudo 0.8.13](#collaudo-del-pileup-parallelo-0813) riguarda anche la
preparazione del pileup DNP. Il
[collaudo 0.8.14](#collaudo-delle-ottimizzazioni-0814) verifica anche thread
interni, riepilogo CPI e lettura dei blocchi. Per la stabile usare
la [release 0.8.14](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.14);
per un candidato verificare versione, commit e build effettivamente installati.

Per il candidato **0.8.10**, seguire anche la [guida al prototipo](PROTOTYPE_0.8.10.md):
gli indicatori di avanzamento sono indipendenti dalla diagnostica e il confronto
può riutilizzare run di riferimento già archiviati.

Il candidato **0.8.12** espone [modalità, massimo di processi R di calcolo e
blocchi DNP](PARALLELISMO_0.8.12.md) nel menu e nella CLI. I valori iniziali
sono automatico, 32 MiB e 64 loci; i MiB misurano input grezzo, non RAM.
Gli eventi `work/parallel/*.jsonl` descrivono la distribuzione effettiva del
calcolo anche senza la diagnostica facoltativa descritta qui.

Il candidato **0.8.13** applica lo stesso budget alla preparazione DNP per
cromosoma e conserva la diagnostica in `work/dnp-pileup.json`. Preparazione
e calcolo R sono fasi successive: i rispettivi processi non si moltiplicano.
La [guida dedicata](PILEUP_0.8.13.md) descrive le condizioni per il percorso
parallelo e il comportamento seriale di ripiego.

La **0.8.14** aggiunge i [controlli dei thread e le ottimizzazioni
mirate](OPTIMIZATIONS_0.8.14.md). In modalità seriale rimane un solo processo
di calcolo per fase; i processi di coordinamento non equivalgono a ulteriori
worker. I thread interni delle librerie devono essere distinti dai processi
del pool quando si interpreta l'uso delle CPU.

La coda DNP della versione finale è comune a campioni e blocchi: con due o più
BAM il numero di processi R non è limitato al numero di campioni. L'ordine degli
output è ricostruito al termine del calcolo. Le [note 0.8.14](RELEASE_0.8.14.md)
e le [misure storiche](https://github.com/GregorioDalia/nipat-desktop/blob/main/docs/validation/0.8.14-observed-benchmarks.json) distinguono
questa implementazione dal candidato già collaudato su Windows/WSL.

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

1. Aprire **NIPAT Desktop** e controllare che il banner riporti `0.8.14`.
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

Il valore **Peak RAM** stampato dalle versioni precedenti di DNP R è una
rilevazione parziale del processo R. Nella 0.8.13 la dicitura è
**Maximum observed R-process RSS (MiB)**: non rappresenta il picco dell'intero
container e non va sommata agli RSS degli altri processi. I confronti devono
riportare sempre la fonte della misura e non scambiare questi valori.

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
| `work/parallel/*.jsonl` (0.8.12) | Budget e attività dei processi R; disponibili anche senza monitoraggio delle prestazioni. Nei workflow composti sono nella cartella del singolo passaggio. |
| `work/dnp-acquisition-budget.json` (0.8.13) | Budget calcolato prima della preparazione DNP, usando la politica comune di risorse. |
| `work/dnp-pileup.json` | Strategia e tempi di acquisizione DNP; nella 0.8.13 include limite, attività e processi della preparazione per cromosoma. |
| `work/dnp-blocks.json` | Acquisizione, indicizzazione e lavoro dei blocchi DNP. I tempi dei task paralleli non si sommano per ottenere il tempo trascorso. |

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

## Collaudo dei cinque moduli nella 0.8.50

Per confrontare seriale, automatico e limiti manuali usare gli stessi input,
parametri, pannelli e associazioni familiari. Provare anche più campioni o
famiglie dei worker disponibili, compresi genitori condivisi fra più coppie
o terne. Nei workflow composti separare acquisizione pileup, calling e analisi
successive; il tempo totale comprende tutte queste fasi.

Il confronto numerico deve rispettare il riferimento di ciascun modulo:
DNP usa la baseline 0.8.5, SNP il modello NEWPAT 2.0, mentre CPI, Contamination
e CPIN usano i nuovi riferimenti NEWPAT congelati nella 0.8.50. Non interpretare
una differenza dovuta al modello come una regressione di parallelismo.
I nuovi parametri di acquisizione possono cambiare il lavoro e i risultati:
conservarli identici e verificare i file delle impostazioni effettive.

Le prove automatiche verificano parità delle tabelle, identità dei campioni
e budget dei processi su casi sintetici. Non applicano soglie di velocità
dipendenti dal carico del runner. Un miglioramento della sola pianificazione
dei blocchi non equivale allo stesso miglioramento nell'intera analisi BAM.
Per confrontare tempi sul portatile mantenere alimentazione da rete,
profilo energetico, risorse VM/container, politica di checksum e ordine delle
prove documentati; usare più ripetizioni e riportare mediana e variabilità.

## Collaudo del parallelismo 0.8.12

Il confronto scientifico resta contro **NIPAT v0.8.5**, commit
`eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`, comprese le modifiche di
compatibilità già distribuite. Le copie e i checksum sono congelati in
[`tests/reference_r/0.8.5`](../tests/reference_r/0.8.5/README.md).
I run 0.8.10 già conservati servono al confronto delle prestazioni precedenti;
non sostituiscono l'oracolo 0.8.5 e non vanno ripetuti se identità degli input,
parametri e risultati sono già documentate e confrontabili.

Per ciascuno dei quattro moduli usare gli stessi input e parametri scientifici
nelle condizioni seguenti. Blocchi DNP da **32 MiB / 64 loci** e limiti di VM
e container rimangono fissi in questa prima matrice:

| Condizione | Opzioni globali prima del sottocomando | Attesa |
| --- | --- | --- |
| Seriale | `--execution-mode serial` | Un processo R di calcolo. |
| Automatica | `--execution-mode auto` | Numero scelto in base a risorse e lavoro disponibili. |
| Massimo 2 | `--execution-mode auto --max-workers 2` | Al più due processi R di calcolo contemporanei. |
| Massimo 4 | `--execution-mode auto --max-workers 4` | Al più quattro processi R di calcolo contemporanei. |

Un massimo non è un numero garantito: se la memoria o le CPU disponibili
consentono meno processi, annotare il numero effettivo. Il coordinatore R
in attesa può aggiungersi ai processi di calcolo. Per qualificare una prova
come parallela verificare in `work/parallel/*.jsonl` attività temporalmente
sovrapposte di almeno due processi figli; la sola opzione richiesta non basta.
Nei workflow composti consultare `output/workflow/steps/<id>/work/parallel/`.

Esempio DNPcall in PowerShell, dalla cartella applicativa 0.8.12 contenente
`nipat.cmd`. Modificare soltanto i percorsi iniziali per usare gli stessi
file; assegnare nuovi nomi nelle ripetizioni. I comandi non rimuovono run
precedenti.

```powershell
.\nipat.cmd --version
$Opzioni = @("--runs-dir", "C:\Risultati\NIPAT-0.8.12", "--dnp-block-mib", "32", "--dnp-block-loci", "64")
$InputDnp = @("--bam", "C:\Dati\campione.bam", "--reference", "C:\Dati\genome.fa", "--panel", "C:\Dati\DNP_list.txt")
.\nipat.cmd @Opzioni --execution-mode serial dnp-call @InputDnp --run-name dnp-seriale-01
.\nipat.cmd @Opzioni --execution-mode auto dnp-call @InputDnp --run-name dnp-auto-01
.\nipat.cmd @Opzioni --execution-mode auto --max-workers 2 dnp-call @InputDnp --run-name dnp-max2-01
.\nipat.cmd @Opzioni --execution-mode auto --max-workers 4 dnp-call @InputDnp --run-name dnp-max4-01
```

Dal menu, impostare i valori comuni in **5 — Configura → 9 — Risorse,
prestazioni e provenienza → 6 — Parallelismo e blocchi**, applicare e
salvare. Per cambiare soltanto la condizione del run corrente usare
**4 — Parallelismo e blocchi** nel riepilogo dell'analisi. La
[guida 0.8.12](PARALLELISMO_0.8.12.md#menu-e-preferenze) descrive precedenza
e persistenza delle impostazioni.

Procedere così per separare correttezza e prestazioni:

1. Verificare ogni condizione contro il medesimo riferimento 0.8.5: tabelle
   complete e ordine, quantità R non arrotondate e pagine dei PDF. I soli
   valori visualizzati o arrotondati non sono una prova sufficiente.
   Ripetere le condizioni parallele anche per verificare il determinismo.
2. Usare i [test differenziali](../tests/r_optimization/README.md) nel medesimo
   runtime per la verifica automatica sui casi sintetici. Il confronto sul
   dataset reale concordato è una verifica aggiuntiva; un riepilogo positivo
   dei test sintetici non lo sostituisce.
3. Per tempi e memoria ripetere, se sostenibile, almeno tre volte ogni
   condizione alternandone l'ordine. Conservare hardware, risorse effettive,
   politica dei checksum, stato della cache, versione e build; non cambiare
   le dimensioni dei blocchi durante questa matrice.
4. Usare prove ordinarie per stimare la durata senza monitoraggio e prove
   corrispondenti con **Avvia analisi con diagnostica prestazioni** (CLI:
   `--performance-diagnostics` prima del sottocomando) per spiegare CPU,
   I/O e picco RAM. Confrontare sempre picchi dalla stessa fonte, preferendo
   il contatore cgroup dell'intero container quando disponibile.
5. Solo dopo questa matrice confrontare altre dimensioni dei blocchi, con
   lo stesso budget di parallelismo. Scegliere in base a tempi e memoria
   misurati; blocchi più grandi o più processi non garantiscono un beneficio.

Conservare `run.json`, `execution.log`, `run-report.html`, `work/parallel`,
`work/dnp-blocks.json` quando presente, diagnostica e risultati scientifici.
Non pubblicare BAM, pileup, tabelle identificative o archivi dei run nel
repository. Condividere soltanto evidenze concordate e controllate, senza
percorsi o nomi dei campioni non necessari. Il completamento dei test di
sviluppo non dichiara concluso il collaudo dei dati reali o degli installer.

## Collaudo del pileup parallelo 0.8.13

La [procedura 0.8.13](PILEUP_0.8.13.md#collaudo-windows) mantiene fissi input,
risorse, diagnostica e blocchi da **32 MiB / 64 loci**. Confronta 0.8.12 seriale
e automatica con 0.8.13 seriale e automatica; conserva i run già disponibili
quando versione, input e opzioni sono verificabili. Il riferimento dei risultati
resta 0.8.5, non la versione che risulta più veloce.

Per distinguere l'accelerazione della preparazione da quella R, registrare
separatamente i tempi di `work/dnp-pileup.json` e `work/dnp-blocks.json`, i
processi effettivi di ciascuna fase e il picco cgroup. Una scelta automatica
può usare un numero diverso di processi nelle due fasi: risorse disponibili
e numero di attività vengono valutati al momento dell'avvio di ciascuna.
La preparazione deve finire prima che inizi il calcolo dei blocchi.

Il supervisore `scripts/benchmark_workflows.py` accetta anche
`--execution-mode`, `--max-workers`, `--dnp-block-mib` e `--dnp-block-loci`.
Usare una cartella di output nuova per ogni condizione. Non modificare la
politica dei checksum fra prove cronometrate: `--input-hashes full` aggiunge
letture complete degli input prima e dopo il calcolo, oltre alla raccolta
iniziale della provenienza. Per identificare una volta BAM e FASTA grandi,
conservare hash completi fuori dall'intervallo di benchmark e verificarne la
stabilità; durante le prove mantenere comunque i controlli NIPAT attivi.

Le evidenze locali della 0.8.12 in
[`validation/0.8.12-rootless.json`](validation/0.8.12-rootless.json) restano
storiche. Non attestano la nuova acquisizione della 0.8.13 né sostituiscono
il collaudo del dataset reale o della piattaforma finale.

## Collaudo delle ottimizzazioni 0.8.14

La [guida 0.8.14](OPTIMIZATIONS_0.8.14.md#collaudo-sugli-input-reali) conserva
come base il pileup e il parallelismo già presenti nella 0.8.13. Le nuove
modifiche riguardano il controllo dei thread, il lavoro del riepilogo CPI e
la lettura dei blocchi DNP. Usare la build 0.8.13 già conservata come confronto
diretto delle prestazioni e la 0.8.5 come riferimento dei risultati.

Iniziare con 0.8.14 seriale e automatica, **32 MiB / 64 loci**, mantenendo
input, risorse e diagnostica confrontabili. Riutilizzare i run precedenti
verificabili; i nuovi devono avere nomi distinti. Separare acquisizione,
indice e calcolo dei blocchi nei resoconti DNP. Il nuovo lettore interviene
nella fase dei blocchi: un eventuale beneficio non va attribuito all'indice.
Per CPI misurare l'intero run con le stesse coppie, pannelli e cutoff.

Le equivalenze sintetiche, i microbenchmark dei singoli helper e i tempi
sul dataset reale sono evidenze diverse. Nessuno di questi elementi, da
solo, qualifica gli installer Windows/WSL o dimostra un'accelerazione in
ogni condizione. Lo stato delle verifiche della nuova versione è riportato
nella [guida del candidato](OPTIMIZATIONS_0.8.14.md#stato-delle-verifiche).

## Riferimenti tecnici

- [Statistiche Docker](https://docs.docker.com/reference/cli/docker/container/stats/)
- [Contatori cgroup v2 del kernel Linux](https://docs.kernel.org/admin-guide/cgroup-v2.html)
- [Risorse e memoria](RISORSE.md)
- [Registri delle esecuzioni](ESECUZIONI.md)

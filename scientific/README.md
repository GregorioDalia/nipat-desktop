# Componenti scientifici

Il motore NIPAT integra cinque programmi R dei progetti
[DNPcall](https://github.com/fravasini/DNPcall) e
[NEWPAT](https://github.com/lpistacchia/NEWPAT). I sorgenti distribuiti sono
identificati da [`SHA256SUMS`](SHA256SUMS), incluso nell'immagine insieme agli
script. Il motore verifica tutti gli hash prima di eseguire un'analisi.

| Workflow | Sorgente incluso |
| --- | --- |
| DNPcall | [`vendor/DNPcall/DNPcall.R`](vendor/DNPcall/DNPcall.R) |
| SNPcall | [`vendor/NEWPAT/SNPcall/SNPcall.R`](vendor/NEWPAT/SNPcall/SNPcall.R) |
| Contamination | [`vendor/NEWPAT/contamination/detect_contamination.R`](vendor/NEWPAT/contamination/detect_contamination.R) |
| CPI prenatale | [`vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R`](vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R) |
| CPIN postnatale | [`vendor/NEWPAT/CPI_postnatal/Postnatal_CPI.R`](vendor/NEWPAT/CPI_postnatal/Postnatal_CPI.R) |

L'immagine comprende anche R, samtools, le dipendenze e la libreria Python
`nipat_scientific`, che convalida e prepara i file richiesti dai programmi R.
La selezione dei file dell'utente e il tracciamento delle esecuzioni appartengono
al client. I sorgenti presenti in questa directory sono un riferimento
ispezionabile: le analisi eseguono le copie contenute nell'immagine verificata.

## Provenienza e identità

| Analisi | Riferimento per la regressione |
| --- | --- |
| DNPcall | NIPAT 0.8.5, commit `eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`. Copia in `tests/reference_r/0.8.5`. |
| SNPcall | [NEWPAT SNPcall 2.0](https://github.com/lpistacchia/NEWPAT/tree/ce59f4beeeec710b1b42d425cb87d7aad729f71d/SNPcall), blob `7a2e01e94c9e278af52aa861646fec3b16df8b1c`. Copia in `tests/reference_r/2.0/SNPcall.R`, SHA-256 `855a96c897d1bcb8ce30b725baecfa739d01be323252da07554a63aa66965da4`. |
| Contamination, CPI e CPIN | [NEWPAT](https://github.com/lpistacchia/NEWPAT/tree/9c2a8be60afcb944153710da6a61cd0559e2b4cf) e oracoli analitici. Copie dei sorgenti upstream in `tests/reference_r/NEWPAT_20261113`. |

Il [manifest scientifico](SHA256SUMS) contiene gli hash degli script operativi.
I riferimenti congelati servono ai test e identificano il modello con cui
confrontare una build. Gli adattamenti di esecuzione e presentazione sono
descritti nei contratti qui sotto.

Le versioni delle dipendenze R sono dichiarate in
[`r-packages.tsv`](../docker/scientific-runtime/r-packages.tsv) e controllate
durante la costruzione. `run.json` registra gli hash effettivamente verificati
nell'immagine, distinti dall'identità del client.

## Contratti operativi

### DNPcall

Il pannello contiene cromosoma, due posizioni adiacenti e alleli REF/ALT di
due basi. Il motore prepara un pannello normalizzato e una lista ordinata dei
BAM. Gli input di grandi dimensioni vengono montati in sola lettura. Gli alias
numerati dei campioni sono associati ai file originali nei metadati del run.
L'esecuzione parte dalla radice del run con `--out=output`, così i nomi generati
dallo script rimangono all'interno della destinazione prevista.

La copia distribuita conserva le dimensioni del data frame nella selezione
di una sola colonna di genotipo (`drop = FALSE`) nei riepiloghi. Il grafico
UpSet richiede almeno due campioni: un run con un solo campione non produce
`DNPs_covered_UpSet_plot.pdf`. Questi adattamenti riguardano i riepiloghi e
non la logica di chiamata del genotipo.

DNPcall esporta il budget comune in `work/dnp-acquisition-budget.json` e lo
passa all'helper Python incluso nel motore. Quando tutti i BAM sono indicizzati,
i dizionari delle sequenze sono compatibili e la partizione è non ambigua,
ciascun task esegue un solo `samtools mpileup -r` su un cromosoma completo.
Restano gli input originali, il BED e le opzioni scientifiche. Le porzioni
sono concatenate nell'ordine `@SQ` del BAM, indipendentemente dall'ordine di
completamento; solo dopo iniziano indice globale e calcolo R.
L'indice seleziona il cromosoma e il BED filtra le posizioni durante la
scansione: questo percorso può leggere più allineamenti della preselezione
multi-regione `view -M -L`, soprattutto con pannelli sparsi su BAM
genomici. Valutare il beneficio sugli input rappresentativi misurando
acquisizione, calcolo R e durata complessiva.

Il percorso non partizionabile esegue un processo samtools alla volta:
seleziona su disco gli input con indice e li passa, insieme agli input senza
indice e nell'ordine originale, a un unico mpileup. Un indice presente ma
danneggiato interrompe l'analisi. Il programma R distribuito passa il
budget all'helper. In modalità seriale il budget limita anche l'acquisizione
a un processo di calcolo alla volta.

Gli intermedi grandi restano sul disco Linux temporaneo del runtime.
`work/dnp-pileup.json` registra strategia, budget, task, processi osservati e
relativi esiti. Il massimo RSS osservato di un singolo processo R è distinto
dal picco complessivo del container, misurato dalla diagnostica prestazioni.
BED e pileup sono rimossi al termine, mentre il client gestisce la pulizia
del volume dell'esecuzione. La verifica degli output resta parte del
completamento del workflow.

La lettura dei blocchi riunisce in un'unica operazione le righe
richieste adiacenti nei byte del file. Conserva ordine, ripetizioni e salti
della richiesta; non ordina né deduplica le righe. L'indice globale e
l'inferenza dei tipi restano comuni all'intero pileup.

### SNPcall

SNPcall 2.0 riceve un pileup con riferimento, qualità e colonna QNAME e un pannello SNP. Il client può
accettare un pileup già disponibile oppure un BAM e il riferimento FASTA.
In quest'ultimo caso il motore genera finestre BED di tre basi ed esegue
samtools prima di R; un errore di samtools interrompe il workflow. Come
nell'upstream 2.0, `-d 0` elimina il limite predefinito di profondità. Il
pannello usa `chr`, `pos`, `ref` e `alt`. La variante a tre colonne,
`pos=chr:posizione`, `ref` e `alt`, viene normalizzata in quattro colonne.
Entrambi richiedono posizioni da 2 a 2147483646.

Il risultato è `output/SNPcall_output.txt`, con 17 colonne: coordinate e
alleli, conteggi REF/ALT/altre basi, totale e frazione REF, likelihood
`GL0`/`GL1`/`GL2`, `GT`, statistiche degli indel e basi osservate con conteggi.
Le likelihood sono logaritmi naturali, non probabilità normalizzate; usano
la qualità Phred della base centrale delle osservazioni REF/ALT.
`GT` è mancante se la frazione di altre basi è almeno 0.1. Le statistiche
degli indel si riferiscono alla base centrale prima del filtro, mentre
un indel su un fianco può comunque escludere la lettura dal calcolo.
Il rapporto `ratio` resta `N_REF / (N_REF + N_ALT)`.

Ogni finestra di tre basi viene associata al proprio SNP prima del
raggruppamento per QNAME. Le posizioni condivise da finestre vicine
contribuiscono a entrambe; il parallelismo mantiene interi i gruppi
`SNP_id`/QNAME e ripristina l'ordine prima dei calcoli. Tokenizzazione
diretta con percorso di compatibilità, aggregazione unica di basi/coordinate/
qualità e indicizzazione dei gruppi di likelihood riducono lavoro duplicato.
Il riferimento upstream resta distinto da questi adattamenti.

I risultati comprendono grafici per genotipo e conteggi REF/ALT/altre basi,
una tabella dei genotipi e riepiloghi con valori mancanti espliciti. I run
con più campioni includono la copertura condivisa. I tempi R e la memoria
residente iniziale/finale sono misure distinte dal tempo complessivo del
workflow e dal picco di memoria del container.
La lettura del pannello specifica `num_threads = 1L`: il lettore non sceglie autonomamente
un numero di thread aggiuntivi rispetto al budget di calcolo.

### Contamination

Accetta conteggi SNP (`chr`, `pos`) o DNP (`chr`, `pos1`, `pos2`) e un
pannello coerente. Filtra Other usando `Other/(REF+ALT+Other)` e calcola la
contaminazione per sito come `unexpected/(REF+ALT)`. Soglie genotipiche,
filtro Other e inclusione degli zeri sono configurabili. Il riepilogo usa
`informative_sites`, media aritmetica e deviazione standard. Senza siti
informativi riporta conteggio zero e stime `NA`.

### CPI prenatale

Accetta coppie cfDNA materno–padre, frequenze SNP/DNP e pannelli facoltativi,
anche multipli. Legge una sola volta campioni condivisi e calcola curve
tramite intervalli esatti. La soglia minima di letture fetali vale 2 di
default; le costanti d'errore differiscono per SNP e DNP. Le colonne di
metadata non partecipano al filtro sui valori scientifici mancanti.
Esporta frazione fetale, logCPI, curve e PDF paginati.

### CPIN postnatale

Accetta terne madre–padre–figlio e frequenze SNP/DNP. Entrambe le modalità
`other_allele` e `all` richiedono madre omozigote; `both` le produce insieme.
Il supporto iniziale controlla ogni allele chiamato nel figlio. La curva
successiva aumenta il supporto dell'allele paterno obbligato. Il modello PI
rimane quello upstream, con costanti d'errore configurabili.
Esporta riepilogo, siti e motivi di esclusione, curve e PDF. Cache dei campioni,
parallelismo fra terne e intervalli di supporto riducono lavoro ripetuto.

### Configurazione e tracciabilità

`nipat settings` mostra parametri, limiti e costanti; `--scientific-config`
e `--set modulo.parametro=valore` configurano i calcoli. Il registro comune
è incluso nel runtime verificato. Ogni passaggio salva le impostazioni
effettive e i riferimenti al codice; le formule e gli invarianti sono leggibili
nel registro e nel catalogo. `NA` resta distinto da zero.

## Verifica e manutenzione

La verifica dell'immagine `scripts/verify_engine_package.py` copre tutti i
workflow con input sintetici e aspettative dichiarate. Le fixture documentano
calcoli e limiti:

- [DNPcall completo](../tests/fixtures/dnp_engine/README.md);
- [SNPcall da BAM](../tests/fixtures/snp_engine/README.md);
- [Contamination](../tests/fixtures/contamination/README.md);
- [CPI](../tests/fixtures/cpi/README.md) e [costante d'errore CPI](../tests/fixtures/cpi_engine/README.md);
- [CPIN](../tests/fixtures/cpin/README.md) e [modelli e oracoli](../tests/fixtures/five_modules/README.md).

Qualsiasi modifica ai sorgenti scientifici richiede una revisione dedicata,
provenienza verificabile, aggiornamento del manifest e regressioni pertinenti.
La verifica differenziale `scripts/verify_r_equivalence.py` confronta i
candidati con i riferimenti immutabili nello stesso runtime: SNPcall 2.0
per SNP, NIPAT 0.8.5 per DNP. `scripts/verify_five_modules.py` verifica
CPI, Contamination e CPIN contro NEWPAT e oracoli analitici, per SNP e DNP.
I verificatori confrontano tabelle e valori non arrotondati, con controlli
dedicati ai grafici. CI scientifica e build degli installatori richiedono
i rapporti di verifica.
La corrispondenza degli hash o degli esempi non sostituisce la validazione
di dominio con input indipendenti.

I README dei componenti in `vendor/` appartengono ai rispettivi progetti e
possono descrivere risorse disponibili soltanto nei repository upstream.
Per installazione e percorsi NIPAT fare riferimento alle guide di questa
applicazione. Licenze e attribuzioni sono riportate in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

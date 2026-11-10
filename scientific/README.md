# Componenti scientifici

Il motore NIPAT integra quattro programmi R dei progetti
[DNPcall](https://github.com/fravasini/DNPcall) e
[NEWPAT](https://github.com/lpistacchia/NEWPAT). I sorgenti distribuiti sono
identificati da [`SHA256SUMS`](SHA256SUMS), incluso nell'immagine insieme agli
script. Il motore verifica tutti gli hash prima di eseguire un'analisi.

| Workflow | Sorgente incluso |
| --- | --- |
| DNPcall | [`vendor/DNPcall/DNPcall.R`](vendor/DNPcall/DNPcall.R) |
| SNPcall | [`vendor/NEWPAT/SNPcall/SNPcall.R`](vendor/NEWPAT/SNPcall/SNPcall.R) |
| Contamination | [`vendor/NEWPAT/contamination/detect_contamination.R`](vendor/NEWPAT/contamination/detect_contamination.R) |
| CPI | [`vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R`](vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R) |

L'immagine comprende anche R, samtools, le dipendenze e la libreria Python
`nipat_scientific`, che convalida e prepara i file richiesti dai programmi R.
La selezione dei file dell'utente e il tracciamento delle esecuzioni appartengono
al client. I sorgenti presenti in questa directory sono un riferimento
ispezionabile: le analisi eseguono le copie contenute nell'immagine verificata.

## Provenienza e identità

Le versioni di riferimento di CPI e Contamination derivano dal
[commit NEWPAT `17d2b8bbd09b1a0ff0651198c21e544aef197824`](https://github.com/lpistacchia/NEWPAT/tree/17d2b8bbd09b1a0ff0651198c21e544aef197824).
Il blob CPI originale è `a362c976f9e9280e64f5bc2ec4a7b83b1e9647e6`; il blob
Contamination è `142e6fc65b3aa1c8c5f6406d33180937d6d04ae1`.
SNPcall 2.0 deriva dal
[commit NEWPAT `ce59f4beeeec710b1b42d425cb87d7aad729f71d`](https://github.com/lpistacchia/NEWPAT/tree/ce59f4beeeec710b1b42d425cb87d7aad729f71d/SNPcall),
blob `7a2e01e94c9e278af52aa861646fec3b16df8b1c`. Il sorgente upstream
originale è congelato in `tests/reference_r/2.0/SNPcall.R`, SHA-256
`855a96c897d1bcb8ce30b725baecfa739d01be323252da07554a63aa66965da4`.
La copia operativa mantiene l'adattatore pileup NIPAT, il budget comune e
gli export del prodotto. DNPcall è identificato dai byte conservati nel
repository e dal manifest seguente.

La revisione di sviluppo **0.8.14** limita esplicitamente a un thread il
lettore readr di SNPcall, applica i limiti dei thread anche all'avvio nativo
del motore e riduce operazioni duplicate nel riepilogo CPI e nella lettura
dei blocchi DNP. La [guida 0.8.14](../docs/OPTIMIZATIONS_0.8.14.md) descrive
il perimetro e lo stato delle verifiche.

La **0.8.13** ha esteso alla preparazione del pileup DNP il budget comune
introdotto dalla **0.8.12** per i quattro programmi R. L'acquisizione può
distribuire cromosomi completi fra processi samtools, prima di avviare il
calcolo R; le due fasi condividono il limite dei processi. I blocchi R
conservano i valori iniziali di 32 MiB e 64 loci. La
[guida al pileup](../docs/PILEUP_0.8.13.md) e la
[guida al parallelismo R](../docs/PARALLELISMO_0.8.12.md) documentano queste
basi. I file conservano attribuzioni e licenze e indicano le modifiche NIPAT.

Per **DNPcall, CPI e Contamination** il riferimento numerico rimane **NIPAT v0.8.5**, commit
`eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`, con copie congelate in
[`tests/reference_r/0.8.5`](../tests/reference_r/0.8.5/README.md). Comprende
le modifiche di compatibilità già distribuite in quella versione: non è
una dichiarazione di identità con sorgenti upstream mai modificati. La
baseline non viene aggiornata per far passare un candidato. **SNPcall usa
invece il riferimento upstream 2.0 congelato**: il nuovo raggruppamento per
SNP e lettura, le qualità e le likelihood rappresentano una modifica
scientifica richiesta, non un'ottimizzazione da confrontare con il vecchio SNP.
Le correzioni dei grafici hanno verifiche proprie, distinte dall'equivalenza
delle tabelle. Il
[piano iniziale](../docs/OPTIMIZATION_0.8.9.md) e il
[contratto delle verifiche R](../tests/r_optimization/README.md) documentano
copertura, controlli di equivalenza e limiti delle evidenze.

| Componente | SHA-256 |
| --- | --- |
| DNPcall | `7163c685a41b65431c86c7e65fe68cf66df5aba4a270bd3c3c7cc40f7e37a5b9` |
| SNPcall | `cc1bf385969adaac24834234b811ba4497aa2397872f0500139a5c534964899d` |
| Contamination | `d5423528268602cd57b8ee6bb9e059457529a3fcaa48cf81b252e7b071445a26` |
| CPI | `64497a6d542300c29bb225202d4c2555e8ac1888f963495356f49e6c962481d7` |

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
multi-regione `view -M -L` della 0.8.12, soprattutto con pannelli sparsi su BAM
genomici. Il beneficio prestazionale deve quindi essere misurato sugli input
reali, non dedotto dal solo numero di processi.

Il percorso non partizionabile esegue un processo samtools alla volta:
seleziona su disco gli input con indice e li passa, insieme agli input senza
indice e nell'ordine originale, a un unico mpileup. Un indice presente ma
danneggiato continua a interrompere l'analisi. L'API interna dell'helper senza
budget conserva il percorso 0.8.12 per i confronti di regressione; il programma
R distribuito passa sempre il budget. La modalità seriale limita anche
l'acquisizione a un processo di calcolo alla volta.

Gli intermedi grandi restano sul disco Linux temporaneo del runtime.
`work/dnp-pileup.json` registra strategia, budget, task, processi osservati e
relativi esiti. Il massimo RSS osservato di un singolo processo R è distinto
dal picco complessivo del container, misurato dalla diagnostica prestazioni.
BED e pileup sono rimossi al termine, mentre il client gestisce la pulizia
del volume dell'esecuzione. La verifica degli output resta parte del
completamento del workflow.

La lettura dei blocchi 0.8.14 riunisce in un'unica operazione le righe
richieste adiacenti nei byte del file. Conserva ordine, ripetizioni e salti
della richiesta; non ordina né deduplica le righe. L'indice globale e
l'inferenza dei tipi restano comuni all'intero pileup.

### SNPcall

SNPcall 2.0 riceve un pileup con riferimento, qualità e colonna QNAME e un pannello SNP. Il client può
accettare un pileup già disponibile oppure un BAM e il riferimento FASTA.
In quest'ultimo caso il motore genera finestre BED di tre basi ed esegue
samtools prima di R; un errore di samtools interrompe il workflow. Come
nell'upstream 2.0, `-d 0` elimina il limite predefinito di profondità. Il
pannello nuovo ha colonne `chr`, `pos`, `ref`, `alt`; il formato precedente
`pos=chr:posizione`, `ref`, `alt` viene normalizzato in quattro colonne.
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
Dalla 0.8.14 la lettura del
pannello specifica `num_threads = 1L`: il lettore non sceglie autonomamente
un numero di thread aggiuntivi rispetto al budget di calcolo.

### Contamination

Le tabelle richiedono `chr`, `pos1`, `pos2`, `N_REF`, `N_ALT` e `N_Other`.
In assenza di `ratio_REF_ALT`, R calcola `N_REF / (N_REF + N_ALT)`;
i siti con denominatore nullo sono esclusi. Una colonna ratio fornita viene
passata allo script. I siti informativi con zero letture inattese contribuiscono
ai riepiloghi. Un campione senza siti informativi ha conteggio zero e stime `NA`.

La preparazione copia le tabelle senza modificarne il contenuto, normalizzando
l'estensione a `.txt` affinché il lettore R le includa. Nomi risultanti ambigui
vengono rifiutati. Il riepilogo è `contamination_summary.txt`, tabulato, con
numero dei DNP informativi, media e deviazione standard.

### CPI

CPI usa coppie di tabelle materne/paterne, frequenze di popolazione e una
costante d'errore. Può analizzare tutti i siti disponibili oppure pannelli
selezionati, anche con più etichette di cutoff. Il motore conserva i nomi
richiesti dai prefissi e prepara ogni campione condiviso una sola volta.

Il riepilogo esclude i siti con meno di due letture fetali. CSV e grafici
riportano le stime previste dallo script, comprese frazione fetale e CPI.
La 0.8.14 riusa le righe materne già selezionate dal calcolo CPI per
preparare il riepilogo, applicando ancora la formula e i filtri originali
del riepilogo. Le chiavi materne già limitate al pannello selezionano le
righe paterne nella join: non serve filtrare nuovamente il padre sullo
stesso pannello. Ordine, duplicati, formule e prodotto dei contributi CPI
rimangono parte del contratto di equivalenza.

Un risultato mancante (`NA`) non equivale a una stima nulla. Parametri e
formati di input sono descritti nella [guida per l'utilizzo](../docs/GUIDA_UTILIZZO.md).

## Verifica e manutenzione

La verifica dell'immagine `scripts/verify_engine_package.py` copre tutti i
workflow con input sintetici e aspettative dichiarate. Le fixture documentano
calcoli e limiti:

- [DNPcall completo](../tests/fixtures/dnp_engine/README.md);
- [SNPcall da BAM](../tests/fixtures/snp_engine/README.md);
- [Contamination](../tests/fixtures/contamination/README.md);
- [CPI](../tests/fixtures/cpi/README.md) e [costante d'errore CPI](../tests/fixtures/cpi_engine/README.md).

Qualsiasi modifica ai sorgenti scientifici richiede una revisione dedicata,
provenienza verificabile, aggiornamento del manifest e regressioni pertinenti.
La verifica differenziale `scripts/verify_r_equivalence.py` confronta i
candidati con i riferimenti immutabili nello stesso runtime: SNPcall 2.0
per SNP, NIPAT 0.8.5 per gli altri tre moduli. Confronta tabelle complete e
valori non arrotondati; i grafici corretti hanno controlli di presentazione
dedicati, senza imporre l'identità visiva con un istogramma difettoso.
I confronti sono obbligatori
nella CI scientifica e prima del confezionamento degli installatori.
La corrispondenza degli hash o degli esempi non sostituisce la validazione
di dominio con input indipendenti.

I README dei componenti in `vendor/` appartengono ai rispettivi progetti e
possono descrivere risorse disponibili soltanto nei repository upstream.
Per installazione e percorsi NIPAT fare riferimento alle guide di questa
applicazione. Licenze e attribuzioni sono riportate in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

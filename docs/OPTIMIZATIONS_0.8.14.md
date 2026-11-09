# Ottimizzazioni della 0.8.14

## Coda comune per più BAM e diagnostica finale

La versione finale usa una coda di attività campione/blocco condivisa da tutti
i BAM. Con due campioni e un budget di cinque processi, il calcolo non si ferma
a due worker: i blocchi possono occupare fino a cinque slot complessivi. Con
più campioni del budget, la stessa coda distribuisce il lavoro nei processi
disponibili. Non vengono creati pool annidati; ordine dei campioni e dei loci
viene ricostruito prima della scrittura delle tabelle e dei grafici.

Il budget conserva i limiti CPU, memoria, massimo configurato e modalità
seriale. Le finestre o i gruppi richiesti dalla compatibilità non vengono
spezzati per aumentare artificialmente il numero di attività. La preparazione
del pileup resta una fase precedente al calcolo R, con il proprio uso dello
stesso limite complessivo.

La raccolta esterna distingue una risposta Docker vuota durante la chiusura
da un errore su un container attivo. La terminazione deve essere confermata
sullo stesso ID e con proprietà verificata; gli altri errori restano nei
rapporti con codici diagnostici fissi. L'assenza di campioni nei run brevi non
diventa una misura di memoria zero. La diagnostica interna rimane distinta.

Nel JSON DNP, `processing_seconds` globale misura la fase della coda comune;
i tempi per campione coprono il primo e l’ultimo blocco e possono sovrapporsi.
Il tempo stampato nel registro individuale decorre dalla preparazione del
campione e comprende attesa nella coda e produzione dei grafici: non va
sommato agli altri tempi individuali per stimare la durata complessiva.

Le [note di versione](RELEASE_0.8.14.md) descrivono distribuzione e limiti.
Le [42 osservazioni Windows/WSL](https://github.com/GregorioDalia/nipat-desktop/blob/main/docs/validation/0.8.14-observed-benchmarks.json)
riguardano il candidato `e04ff883fc6417748174d2a7c3b49cadad989308`, precedente
a queste modifiche. Hanno guidato la revisione del budget con più BAM;
non misurano le prestazioni del nuovo installer.

## Primo ciclo del candidato: evidenza storica

Le sezioni seguenti conservano interventi e misure del primo candidato
0.8.14, successivo alla 0.8.13. I rapporti locali collegati sono storici e non
vengono riscritti per attribuirli alla nuova build. Il riferimento scientifico
resta **NIPAT 0.8.5**, commit
`eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`.

## Punto di partenza

Il controllo dello stato del codice ha distinto le funzioni già presenti
dagli interventi nuovi:

| Funzione | Provenienza | Intervento 0.8.14 |
| --- | --- | --- |
| Modalità automatica o seriale, massimo di processi e blocchi configurabili | 0.8.12 | Controllo aggiuntivo dei thread di readr e dell'avvio nativo del motore. |
| Parallelismo nei quattro programmi R | 0.8.12 | Conservato; ottimizzazione mirata del riepilogo CPI. |
| Preparazione del pileup DNP per cromosoma | 0.8.13 | Conservata con lo stesso budget complessivo. |
| Lettura dei blocchi DNP dall'indice globale | 0.8.10, estesa dal parallelismo successivo | Lettura congiunta di righe contigue nei byte del file. |

La [guida 0.8.12](PARALLELISMO_0.8.12.md) descrive la distribuzione del lavoro
R; la [guida 0.8.13](PILEUP_0.8.13.md) descrive acquisizione del pileup,
condizioni del percorso parallelo e ripiego seriale. Contamination mantiene
il calcolo per campione e, quando applicabile, per blocchi di righe. SNPcall
mantiene i gruppi di QNAME completi. CPI mantiene coppie, pannelli/cutoff e
intervalli di soglie come livelli alternativi di distribuzione del lavoro.
Non vengono aperti pool annidati.

## Seriale e limite complessivo

`--execution-mode serial` esegue una sola attività di calcolo alla volta:
un processo samtools nella preparazione, quindi il calcolo R seriale. Le
fasi sono successive. L'automatico sceglie invece il numero di processi in
base alle risorse effettive e al lavoro disponibile; `--max-workers N`
impone un massimo, senza garantire che vengano usati tutti gli N processi.

Esempio: con un massimo di quattro processi, la preparazione può lavorare
su quattro cromosomi contemporaneamente. Quando finisce, R può calcolare
quattro blocchi contemporaneamente. Non si avviano quattro blocchi per
ciascuno dei quattro processi di preparazione.

Il client, Python, il coordinatore R e l'eventuale monitoraggio possono
restare presenti. Non sono ulteriori attività scientifiche del pool: la
modalità seriale non significa un unico processo del sistema operativo né
un vincolo sull'attività delle altre applicazioni del computer.

La 0.8.14 chiude due percorsi che potevano introdurre thread aggiuntivi:

- La lettura del pannello SNP con `readr::read_tsv()` passa esplicitamente
  `num_threads = 1L`, indipendentemente dall'opzione readr dell'ambiente.
- Il runtime imposta anche `VROOM_THREADS=1` e applica i limiti dei thread
  all'ingresso nativo `run` del motore, oltre ai percorsi Desktop e JSON.
  Rimangono i limiti delle librerie numeriche già previsti dal runtime.

Anche in modalità automatica i thread interni restano limitati: il
parallelismo richiesto è distribuito dai processi NIPAT, evitando che ogni
processo apra autonomamente un altro gruppo di thread.

## Riepilogo CPI

Il calcolo CPI produce già le righe materne informative per la coppia e il
pannello correnti. Il riepilogo della 0.8.13 filtrava nuovamente la tabella
materna originale sullo stesso pannello; la 0.8.14 riusa `out$madre_info`.
Applica poi la stessa formula del riepilogo per letture fetali e frazione
fetale, gli stessi controlli sui valori mancanti e sulla positività e la
stessa soglia di almeno due letture.

Le chiavi materne sono già limitate al pannello. La join con la tabella
paterna originale seleziona quindi le stesse righe paterne, evitando un
secondo filtro del padre sul pannello. La chiamata e gli argomenti di
`run_CPI_iteration()` restano invariati, così come le formule, l'ordine dei
prodotti CPI e la gestione dei duplicati.

L'intervento riguarda il lavoro ripetuto per costruire il riepilogo; non
modifica la definizione dei siti informativi né l'algoritmo scientifico.
La sua utilità prestazionale dipende dal numero di coppie, pannelli, cutoff
e righe: deve essere misurata separatamente dalla correttezza.

## Lettura DNP e indicizzazione

Il lettore precedente eseguiva una coppia `seek()`/`readChar()` per ogni
riga richiesta. Il nuovo helper combina soltanto righe adiacenti nei byte
del file e nello stesso ordine della richiesta. Ogni intervallo temporaneo
ha un obiettivo massimo di 8 MiB, salvo una singola riga indivisibile più
grande. Questo valore interno riguarda le letture del file: è distinto dal
blocco di calcolo configurabile, inizialmente da **32 MiB / 64 loci**.

L'helper conserva richieste con salti, righe ripetute o ordine inverso;
non ordina né deduplica gli indici. Quando nessuna coppia di righe è
adiacente, mantiene direttamente il percorso precedente. I byte letti passano
allo stesso parser
`read.csv()` e alle classi inferite sull'intero pileup. Se una lettura
congiunta produce avvisi o viene troncata, torna alla lettura delle singole
righe per conservare il comportamento precedente sui byte anomali.

L'indice globale continua a precedere il calcolo dei blocchi e conserva i
controlli su QNAME e coordinate e l'inferenza dei tipi. La sola sostituzione
del lettore non accelera necessariamente la costruzione dell'indice:
parsing, controlli e inferenza possono contribuire al suo costo. Una
riscrittura dell'indice richiederebbe un beneficio misurato e una verifica
separata di metadati e risultati.

## Microbenchmark degli interventi

Le [misure locali degli helper](validation/0.8.14-microbenchmarks.json)
separano il costo dell'operazione modificata dal workflow completo. Non
sono misure del dataset reale né degli installer Windows/WSL.

Per CPI sono state eseguite due sessioni di cinque ripetizioni della
costruzione del riepilogo a partire dallo stesso risultato CPI già calcolato.
La seconda verifica anche l'harness riproducibile finale. Sono esclusi
lettura dei file, calcolo del core, grafici e caricamento dei pacchetti.
Con 50.000 loci, le mediane osservate sono:

| Sessione | Selezione CPI | 0.8.13 | 0.8.14 |
| --- | --- | ---: | ---: |
| Prima misura | Pannello completo | 36 ms | 21 ms |
| Prima misura | Pannello con il 10% dei loci | 16 ms | 10 ms |
| Prima misura | ALL, senza selezione su pannello | 20 ms | 20 ms |
| Ripetizione con harness finale | Pannello completo | 41 ms | 36 ms |
| Ripetizione con harness finale | Pannello con il 10% dei loci | 18 ms | 10 ms |
| Ripetizione con harness finale | ALL, senza selezione su pannello | 22 ms | 22 ms |

Il beneficio assoluto osservato è ridotto, varia fra le sessioni e riguarda
il solo riepilogo. Non tutti i casi migliorano: nel replay con 5.000 loci
in modalità ALL la mediana passa da 8 a 10 ms. La rimozione di lavoro
ridondante non implica quindi una percentuale di accelerazione stabile.
Gli oggetti R confrontati con 0.8.5 e 0.8.13 sono identici secondo `identical()`;
coincidono inoltre i byte delle tabelle e dei dati/etichette dei grafici
esportati dal microbenchmark. Questi controlli isolati non sostituiscono il
confronto degli output dell'intero programma.

Per DNP il microbenchmark confronta lettura e parsing dello stesso blocco,
con cinque ripetizioni alternate e risultati identici. Le mediane sono:

| Blocco sintetico | Dimensione | 0.8.13 | 0.8.14 |
| --- | ---: | ---: | ---: |
| 512 righe contigue, profondità 6.000 | 38,096 MiB | 1,292 s | 1,303 s |
| 20.000 righe contigue, profondità 4 | 1,335 MiB | 0,204 s | 0,039 s |
| 10.000 righe corte con salti | 0,668 MiB | 0,090 s | 0,085 s |

Il caso con righe profonde è sostanzialmente neutro: la riduzione delle
chiamate di lettura non riduce il tempo complessivo di lettura e parsing.
Il beneficio maggiore compare sulle molte righe corte contigue. La prova
con salti segue il percorso diretto e mostra una differenza piccola. Queste
misure non permettono di prevedere una riduzione del tempo totale del run
reale, né del tempo di costruzione dell'indice.

La lettura congiunta comporta un piccolo costo di memoria nel caso profondo.
Misurando tre processi R nuovi e separati per ciascun metodo, la mediana
del massimo RSS passa da **188,586 a 200,145 MiB**, circa **11,56 MiB in più**.
È il picco del processo R che legge il blocco con l'indice già costruito,
non quello di un workflow o del container. Le allocazioni cumulative
misurate restano circa 114,9 MiB: questa somma non misura il picco di memoria.

Il profiling esplorativo dell'indice sullo stesso caso profondo ha osservato
0,817 s complessivi. Nei 0,79 s campionati, `readLines()` e `strsplit()`
rappresentano rispettivamente il 46,84% e il 37,97% del tempo proprio. È una
singola prova sintetica breve, insufficiente per stimare il costo sul dataset
reale. L'indicizzazione rimane invariata: non è stata adottata una nuova
implementazione con beneficio ed equivalenza già dimostrati.

## Stato delle verifiche

La [qualificazione locale 0.8.14](validation/0.8.14-rootless.json) è stata
completata sui sorgenti identificati dagli hash nel rapporto: **20 casi,
64 esecuzioni scientifiche e 44 confronti con 0.8.5**. Coincidono i byte di
145 confronti di tabelle, gli oggetti R scientifici non arrotondati e
137 pagine PDF renderizzate a 36 DPI, escludendo i metadati PDF. Sono
passati anche dieci controlli R mirati, 25 casi di acquisizione pileup e
il controllo della cancellazione R. I checksum confermano che i 154 file
sorgente sorvegliati e i 55 input non sono cambiati durante la prova.

Le varianti comprendono seriale, automatico, massimo due, massimo quattro
e ripetizione del massimo quattro. Nei casi che esercitano il pool R, il
budget dell'host ha selezionato un worker in seriale, senza PID figli,
fino a due con massimo due e fino a tre in automatico e con massimo quattro.
CPI con una coppia e due cutoff usa due worker perché ha soltanto due task.
Il massimo richiesto non è quindi un numero di processi garantito. I test della preparazione pileup
hanno osservato direttamente massimi di uno, due e quattro processi
samtools. Ordine dei risultati e ripetibilità sono inclusi nei confronti.

Le prove usano R 4.4.2 e samtools 1.21 su Linux, con runtime rilocato e
sorgenti del checkout verificati. Non usano Docker o Windows/WSL e non
applicano le quote del container: qualificano i casi e i sorgenti riportati,
non gli installer o le prestazioni del dataset reale.

Sono stati completati anche:

- Suite Python di 1.081 test, con quattro casi saltati; 224 test degli script
  di controllo della CI e controllo Ruff superati. I test locali degli
  script non equivalgono all'esecuzione dei workflow remoti della nuova build.
- Tutti e quattro i cataloghi caricati con verifica completa delle dipendenze,
  17 test del catalogo superati e checksum dei quattro sorgenti R verificati.
- Controllo dei collegamenti della documentazione su 55 file Markdown e
  microbenchmark degli helper riportati sopra.

La distribuzione del candidato richiede inoltre CI e qualificazione degli
installer sullo stesso commit: gli esiti sono associati alla relativa build
GitHub Actions. Rimane distinto il collaudo del dataset reale in Windows/WSL
con tempi delle fasi e memoria dell'intero container. Nessuna accelerazione sui dati
reali della nuova versione è dichiarata da questa guida. Le evidenze della
[0.8.13](validation/0.8.13-rootless.json) rimangono un riferimento storico
separato.

## Collaudo sugli input reali

1. Verificare versione, commit e build effettivamente installati. Conservare
   il candidato 0.8.13 e i run precedenti; non dedurre la versione dal nome
   della cartella risultati.
2. Mantenere gli stessi input, parametri scientifici, risorse WSL/container,
   politica dei checksum e diagnostica. Iniziare con **32 MiB / 64 loci**.
3. Nel riepilogo dell'analisi scegliere **4 — Parallelismo e blocchi**, poi
   modalità **seriale** per il primo run e **automatica** per il secondo.
   Usare nomi nuovi, per esempio `test0814-serial32-01` e
   `test0814-auto32-01`. La scelta nel riepilogo riguarda il run corrente.
4. Confrontare risultati e ordine delle tabelle; il riferimento scientifico
   resta 0.8.5. Per i tempi riutilizzare i run 0.8.13 verificabili e
   confrontabili. Se sostenibile, alternare le condizioni e ripeterle tre
   volte, includendo fallimenti e interruzioni.
5. Per DNP distinguere acquisizione, indice e blocchi. Per CPI conservare
   coppie, pannelli e cutoff effettivi. Non attribuire al nuovo lettore una
   differenza osservata nella preparazione samtools o nell'indice.

Conservare `run.json`, `execution.log`, `run-report.html`, risultati, `work/`
e `performance/` quando presente. La [guida alle prestazioni](PERFORMANCE.md)
spiega quali contatori confrontare. I MiB dei blocchi misurano input grezzo,
non RAM: il consumo dipende anche da strutture R, numero di processi e cache.

I log e i risultati permettono il primo confronto senza trasferire BAM e
FASTA completi. Gli input originali diventano utili per riprodurre un errore
o profilare un collo di bottiglia che i resoconti non spiegano; non vanno
inclusi nel repository o nei pacchetti distribuiti.

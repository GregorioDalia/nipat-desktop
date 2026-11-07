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
SNPcall e DNPcall sono identificati dai byte conservati nel repository e dal
manifest seguente.

La revisione di sviluppo **0.8.12** aggiunge un budget comune per il
parallelismo dei quattro programmi R alle ottimizzazioni introdotte dalla
0.8.9 e all'elaborazione DNP per blocchi. Modalità, limiti e unità di lavoro
sono descritti nella [guida al parallelismo](../docs/PARALLELISMO_0.8.12.md).
I file conservano attribuzioni e licenze e indicano le modifiche NIPAT.

Il riferimento per l'equivalenza rimane **NIPAT v0.8.5**, commit
`eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`, con copie congelate in
[`tests/reference_r/0.8.5`](../tests/reference_r/0.8.5/README.md). Comprende
le modifiche di compatibilità già distribuite in quella versione: non è
una dichiarazione di identità con sorgenti upstream mai modificati. La
baseline non viene aggiornata per far passare un candidato. Il
[piano iniziale](../docs/OPTIMIZATION_0.8.9.md) e il
[contratto delle verifiche R](../tests/r_optimization/README.md) documentano
copertura, controlli di equivalenza e limiti delle evidenze.

| Componente | SHA-256 |
| --- | --- |
| DNPcall | `e9725291a572a3c7dc832905fee3b4d665cf6767cb914088788a9d0c6401423b` |
| SNPcall | `66003583814f39102f3137485d7b8157c54e51a9c93094d68ee9769dc4d1ea64` |
| Contamination | `d5423528268602cd57b8ee6bb9e059457529a3fcaa48cf81b252e7b071445a26` |
| CPI | `d144d8131ec220b913a92f995491c676a80812812f3ab79d60ca23e5b87610c1` |

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

DNPcall acquisisce il pileup tramite l'helper Python incluso nel motore e
interrompe l'analisi se l'acquisizione fallisce. Gli indici BAM disponibili
consentono la selezione delle letture nelle regioni richieste; in loro assenza
si usa la scansione sequenziale. Gli intermedi grandi vengono scritti sul
disco Linux temporaneo del runtime. BED e pileup sono rimossi al termine,
mentre il client gestisce la pulizia del volume dell'esecuzione. La verifica
degli output resta parte del completamento del workflow.

### SNPcall

SNPcall riceve un pileup con colonna QNAME e un pannello SNP. Il client può
accettare un pileup già disponibile oppure un BAM e il riferimento FASTA.
In quest'ultimo caso il motore genera finestre BED di tre basi ed esegue
samtools prima di R; un errore di samtools interrompe il workflow.
Il risultato è `output/SNPcall_output.txt`.

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
candidati con il riferimento immutabile 0.8.5 nello stesso runtime: tabelle
complete, valori non arrotondati e resa dei PDF. I confronti sono obbligatori
nella CI scientifica e prima del confezionamento degli installatori.
La corrispondenza degli hash o degli esempi non sostituisce la validazione
di dominio con input indipendenti.

I README dei componenti in `vendor/` appartengono ai rispettivi progetti e
possono descrivere risorse disponibili soltanto nei repository upstream.
Per installazione e percorsi NIPAT fare riferimento alle guide di questa
applicazione. Licenze e attribuzioni sono riportate in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

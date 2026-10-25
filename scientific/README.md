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

CPI e Contamination sono copie senza modifiche locali del
[commit NEWPAT `17d2b8bbd09b1a0ff0651198c21e544aef197824`](https://github.com/lpistacchia/NEWPAT/tree/17d2b8bbd09b1a0ff0651198c21e544aef197824).
Il blob CPI è `a362c976f9e9280e64f5bc2ec4a7b83b1e9647e6`; il blob
Contamination è `142e6fc65b3aa1c8c5f6406d33180937d6d04ae1`.
SNPcall e DNPcall sono identificati dai byte conservati nel repository e dal
manifest seguente.

| Componente | SHA-256 |
| --- | --- |
| DNPcall | `d0600427d058a141da8683d98904c51be95ec09ebd5804ea879164d1f5ce7e36` |
| SNPcall | `00068e501d1fefe2b721001f141fc2595be42c9349873ee353a29a305816c9c9` |
| Contamination | `28f0d0298cdce06c6d9f33ec5d7a224a8c9fa7dfb6fde87b930ee938e703cc08` |
| CPI | `10ca01a476f5259b65a063aea95ff76e57c11567a304667065ea9c7b9206545a` |

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

DNPcall elimina i propri file temporanei BED e pileup al termine. La sua
chiamata interna a samtools sopprime lo stderr e non ne controlla esplicitamente
il codice di uscita. La verifica degli output resta quindi necessaria anche
quando R termina senza errore.

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
La corrispondenza degli hash o degli esempi non sostituisce la validazione
di dominio con input indipendenti.

I README dei componenti in `vendor/` appartengono ai rispettivi progetti e
possono descrivere risorse disponibili soltanto nei repository upstream.
Per installazione e percorsi NIPAT fare riferimento alle guide di questa
applicazione. Licenze e attribuzioni sono riportate in
[`THIRD_PARTY_NOTICES.md`](../THIRD_PARTY_NOTICES.md).

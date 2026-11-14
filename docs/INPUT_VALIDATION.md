# Controlli degli input e dei risultati

NIPAT Desktop controlla gli input nel livello Python prima di avviare
gli script R. I validatori sono condivisi dal client e dal motore scientifico
incorporato nell'immagine. Il menu e la CLI diretta applicano gli stessi
requisiti ai file selezionati; il motore ripete i controlli nell'ambiente
di esecuzione.

Questi controlli verificano formati, valori e relazioni necessarie per
eseguire le analisi. La scelta dell'assemblaggio genomico, dei campioni,
dei ruoli biologici e delle frequenze appropriate resta una responsabilità
scientifica. Un file accettato non certifica l'idoneità del campione al metodo.

## Originali e copie di lavoro

Gli input selezionati vengono montati in sola lettura. Le trasformazioni
necessarie agli script riguardano copie nella cartella `work` del run o del
singolo passaggio. NIPAT conserva il collegamento con il file originale.
Non modifica il contenuto scientifico degli originali, non deduplica loci
silenziosamente e non sostituisce conteggi o frequenze non validi.

Nei pannelli DNP e SNP, gli alleli vengono verificati e scritti in maiuscolo
nella copia di lavoro. Per esempio, un allele SNP `g` diventa `G` prima del
confronto con le basi osservate. Questa normalizzazione del formato non
cambia la base indicata dall'utente. Alleli vuoti o non ammessi sono segnalati
con un errore da correggere nel file sorgente.

## Formati e interpretazione

Le tabelle devono rispettare colonne, delimitatori e modalità descritti
nella [guida per l'utilizzo](GUIDA_UTILIZZO.md#input-dei-cinque-moduli).
I file testuali vengono letti come UTF-8; un errore di codifica o una tabella
malformata produce una segnalazione di validazione. Le intestazioni richieste
devono essere presenti, senza nomi vuoti o duplicati; ogni riga deve avere
il numero di colonne dichiarato. I parametri numerici CLI usano il punto come
separatore decimale. Nel file delle frequenze CPI è accettata anche la virgola
decimale, secondo il formato dello script.

| Input | Controlli applicati |
| --- | --- |
| Pannello DNPcall | Cinque colonne; coordinate adiacenti con prima posizione almeno 2, per consentire la finestra precedente al sito; loci univoci; alleli di due basi A/C/G/T, normalizzati in maiuscolo nella copia di lavoro. |
| Pannello SNPcall 2.0 | Colonne `chr`, `pos`, `ref`, `alt`; è accettato anche il formato `pos`, `ref`, `alt` con `pos=chr:posizione`. Coordinate univoche, posizione da 2 a 2147483646 in entrambe le modalità e cromosoma senza spazi o `:`; alleli distinti di una base A/C/G/T, normalizzati in maiuscolo. La copia di lavoro usa sempre quattro colonne. |
| Pileup SNPcall | Almeno sette colonne samtools: riferimento nella terza, profondità nella quarta, basi nella quinta, qualità nella sesta e QNAME nella settima; cromosoma presente, posizione positiva e profondità non negativa su tutte le righe non vuote. Il file importato non può essere vuoto. |
| Tabelle Contamination | Colonne richieste; coordinate positive e ordinate; loci univoci; `N_REF`, `N_ALT` e `N_Other` finiti, interi e non negativi. |
| Tabelle CPI/CPIN | Requisiti dei conteggi; `REF` e `ALT` di una base per SNP o due per DNP; `total_count` intero non negativo, con i valori mancanti previsti nei siti senza copertura. |
| Frequenze CPI/CPIN | Tipo di marcatore coerente con le tabelle; loci univoci; `Ref_f.pop` e `Alt_f.pop` finite, strettamente maggiori di 0 e al massimo 1. La tabella deve contenere almeno un locus. |

BAM e FASTA sono verificati per presenza, accessibilità e file di indice
richiesti. Prima del pileup, samtools legge il dizionario dei contig di ogni
BAM. Tutti i contig del pannello devono comparire nel BAM con la stessa
lunghezza indicata dall'indice FASTA. DNPcall confronta anche ordine, nomi e
lunghezze dell'intero dizionario quando usa più BAM, sia con sia senza indici
BAM. Un contig presente senza letture conserva i risultati a copertura zero;
un contig assente o discordante rende l'input incompatibile. Il controllo del
pileup importato è strutturale e scorre tutte le righe:
non ricostruisce il procedimento di produzione e non verifica l'intera
grammatica delle basi codificate. Le tabelle di conteggi con sola intestazione
sono ammesse per rappresentare l'assenza di siti; pannelli e frequenze di
popolazione vuoti sono invece rifiutati.

CPI e CPIN verificano anche l'identità fisica dei file: campioni distinti
non possono riferirsi allo stesso file attraverso alias o hard link.
Nei workflow automatici coppie e terne fanno riferimento agli ID espliciti
dei campioni. Nei comandi singoli gli identificativi sono locali al ruolo:
per esempio `A:A:A` è valido per CPIN soltanto quando i prefissi individuano
tre file distinti.

Contamination calcola la frazione REF dai conteggi `N_REF` e `N_ALT`.
La colonna facoltativa `ratio_REF_ALT` viene controllata e le discrepanze
sono registrate come avvisi. Se presente, un rapporto numerico deve essere
finito e compreso fra 0 e 1. I siti senza letture REF o ALT sono esclusi.

CPI e CPIN richiedono frequenze positive e `total_count` uguale a
`N_REF + N_ALT + N_Other`. Un totale `NA` è ammesso al locus con tutti i
conteggi a zero. Un totale discordante in Contamination o una somma
delle frequenze REF e ALT diversa da uno sono registrati come avvisi.

`work/input-validation.json` conserva avvisi e normalizzazioni, con il
checksum del pannello originale e della copia preparata. Nei workflow
automatici il file appartiene alla cartella `work` del singolo passaggio.
Gli avvisi vengono riportati anche nel log.

Un errore di validazione identifica il file e, quando disponibile, la riga
o la colonna interessata. Correggere l'input e avviare una nuova esecuzione:
un run già creato rimane disponibile per la diagnosi e non viene sovrascritto.

## Risultati e qualità numerica

Le analisi singole e i workflow automatici controllano anche gli output
attesi prima di registrare il successo. Presenza dei file, schema delle
tabelle e corrispondenza fra risultati e campioni sono verifiche tecniche;
non costituiscono una valutazione biologica dei risultati.

I valori mancanti previsti, per esempio una stima `NA` in assenza di siti
informativi, devono essere distinti da valori numericamente problematici.
Una deviazione standard `NA` è ammessa anche quando rimane un solo sito.
Una stima `NA` inattesa produce `output.missing_estimate`; `NaN` e valori
infiniti producono `output.nonfinite`, anche con zero siti. Un valore vuoto
o non numerico in una colonna numerica richiesta è un errore di output.
Le segnalazioni di qualità conservano il risultato originale prodotto da R
e indicano l'elemento da verificare. NIPAT non corregge automaticamente una
stima scientifica e non applica nuovi filtri ai dati CPI in base alla stima
Contamination.

SNPcall conserva i nomi dei contig come testo anche durante il conteggio
delle letture. Per esempio, `01` e `1` indicano contig distinti.
SNPcall 2.0 distingue anche `-Inf` nelle likelihood: una qualità Phred zero
può produrre `log(0)`, previsto dal modello. `NaN` e `+Inf` nelle colonne GL
non sono accettati. I conteggi e le coordinate del risultato devono
corrispondere al pannello; i genotipi sono `0/0`, `0/1`, `1/1` oppure `NA`.
Il riepilogo dei genotipi DNP deve riportare gli stessi campioni, loci,
alleli e genotipi delle tabelle individuali.

Tutti i moduli devono produrre `output/scientific-settings.json` coerente
con i valori richiesti e con il registro distribuito. Un file assente,
parametri mancanti o estranei, tipi errati o valori diversi interrompono
il completamento. CPI e CPIN verificano inoltre tipo di marcatore, letture
minime e costante d'errore dichiarati nei riepiloghi.

Per un'analisi singola il resoconto è in
`work/scientific-validation.json`. Nei piani automatici gli avvisi sono
registrati in `artifacts.quality_warnings` per il passaggio interessato,
dentro `workflow-state.json`. La presenza di un avviso richiede la lettura
del messaggio e del risultato originale; non va interpretata come una
correzione già effettuata dal programma.

Il [catalogo scientifico](CATALOGO_SCIENTIFICO.md) distingue le regole degli
script R dai controlli e dalle trasformazioni degli adattatori Python.
I parametri e le evidenze effettive del run sono descritti in
[Esecuzioni e risultati](ESECUZIONI.md); la
[scheda di validazione](VALIDAZIONE.md) consente di confrontarli con attese
indipendenti.

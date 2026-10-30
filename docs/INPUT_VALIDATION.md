# Controlli degli input e dei risultati

NIPAT Experimental08 0.8.0a1 controlla gli input nel livello Python prima di avviare
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
nella [guida per l'utilizzo](GUIDA_UTILIZZO.md#input-dei-quattro-workflow).
I file testuali vengono letti come UTF-8; un errore di codifica o una tabella
malformata produce una segnalazione di validazione. Le intestazioni richieste
devono essere presenti, senza nomi vuoti o duplicati; ogni riga deve avere
il numero di colonne dichiarato. I parametri numerici CLI usano il punto come
separatore decimale. Nel file delle frequenze CPI è accettata anche la virgola
decimale, secondo il formato dello script.

| Input | Controlli applicati |
| --- | --- |
| Pannello DNPcall | Cinque colonne; coordinate positive e adiacenti; loci univoci; alleli di due basi A/C/G/T, normalizzati in maiuscolo nella copia di lavoro. |
| Pannello SNPcall | Colonne `pos`, `ref`, `alt`; coordinate univoche; alleli distinti di una base A/C/G/T, normalizzati in maiuscolo. In modalità BAM la posizione deve permettere una finestra di tre basi. |
| Pileup SNPcall | Almeno sette colonne con QNAME nella settima; cromosoma presente, posizione positiva e profondità non negativa su tutte le righe non vuote. |
| Tabelle Contamination | Colonne richieste; coordinate positive e ordinate; loci univoci; `N_REF`, `N_ALT` e `N_Other` finiti, interi e non negativi. |
| Tabelle CPI | Requisiti dei conteggi, `REF` e `ALT` dinucleotidi A/C/G/T e `total_count` intero non negativo. |
| Frequenze CPI | Loci univoci; `Ref_f.pop` e `Alt_f.pop` finite comprese tra 0 e 1. La tabella deve contenere almeno un locus. |

BAM e FASTA sono verificati per presenza, accessibilità e file di indice
richiesti; la decodifica effettiva dei dati binari e del riferimento compete
a samtools. Il controllo del pileup è strutturale e scorre tutte le righe:
non ricostruisce il procedimento di produzione e non verifica l'intera
grammatica delle basi codificate. Le tabelle di conteggi con sola intestazione
sono ammesse per rappresentare l'assenza di siti; pannelli e frequenze di
popolazione vuoti sono invece rifiutati.

Quando `ratio_REF_ALT` è presente, un valore numerico deve essere finito e
compreso tra 0 e 1. Un rapporto mancante con letture REF/ALT disponibili
produce una segnalazione: lo script può escludere quel locus. L'assenza
della colonna resta una modalità supportata da Contamination, che calcola
il rapporto dai conteggi.

Alcune incoerenze richiedono interpretazione di dominio e vengono registrate
come **avvisi**, senza riscrivere i valori: frequenza zero, somma delle frequenze
REF/ALT diversa da uno, `total_count` diverso dalla somma dei tre conteggi e
rapporto fornito diverso da quello ricavabile dai conteggi. Questi avvisi non
impediscono automaticamente il calcolo; devono essere valutati prima di usare
il risultato. Una frequenza zero può causare una divisione per zero nel CPI.

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

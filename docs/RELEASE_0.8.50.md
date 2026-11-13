# NIPAT Desktop 0.8.50

La 0.8.50 integra cinque moduli: DNPcall, SNPcall 2.0, Contamination,
CPI prenatale e CPIN postnatale. Gli output DNP e SNP possono alimentare
qualsiasi combinazione delle tre analisi successive. I risultati dei due
tipi di marcatore rimangono distinti. Fetal sex non è incluso.

## Analisi e workflow

**W → 5** nel menu e `workflow analyze` nella CLI permettono di comporre
il workflow da BAM, pileup SNP o tabelle già disponibili. Per ogni campione
e caller i conteggi sono prodotti una sola volta e poi riutilizzati.
`--dnp-analyses` e `--snp-analyses` consentono scelte diverse sui due rami.
CPI richiede coppie cfDNA materno–padre; CPIN richiede terne madre–padre–figlio.
Le associazioni sono esplicite e conservate nei risultati e nel report HTML.
Il programma non deduce ruoli biologici dai nomi dei file.

CPIN è disponibile anche come analisi singola, attraverso **N** nel menu
o `nipat cpin`. Include selezione `other_allele`, `all` e `both`, frequenze
di popolazione, pannelli facoltativi, riepiloghi, siti con motivi di
esclusione, curve per soglia e PDF. Le terne indipendenti possono essere
eseguite in parallelo; i campioni condivisi sono letti una sola volta.
Le curve usano intervalli esatti di supporto, evitando una scansione dei
loci per ogni possibile soglia di copertura.

## Modelli scientifici

CPI, Contamination e CPIN si basano su
[NEWPAT, commit 9c2a8be6](https://github.com/lpistacchia/NEWPAT/tree/9c2a8be60afcb944153710da6a61cd0559e2b4cf).
I sorgenti di riferimento sono congelati separatamente dalle implementazioni
ottimizzate. SNP mantiene il riferimento NEWPAT 2.0; DNP conserva la baseline
numerica NIPAT 0.8.5.

Contamination applica il filtro `Other/(REF+ALT+Other)`; la stima per sito
resta `unexpected/(REF+ALT)`. Gli zeri sono inclusi per impostazione
predefinita e la stima complessiva è la media aritmetica dei siti informativi.
Il riepilogo espone `informative_sites`.

CPI distingue SNP e DNP, usa costanti d'errore specifiche e una soglia
configurabile di letture fetali. Mantiene pannelli multipli, cache dei
campioni e curve per intervalli. I valori mancanti nelle colonne accessorie
non eliminano siti validi. CPIN gestisce anche tabelle con sola intestazione
e campioni senza copertura, producendo un esito senza siti informativi.

Questi aggiornamenti possono cambiare i risultati rispetto alla 0.8.35:
il confronto delle prestazioni deve usare lo stesso modello, gli stessi
input e gli stessi parametri.

## Parametri e tracciabilità

`nipat settings` e **Configura → S** espongono parametri, default, limiti
e costanti. `--scientific-config` importa un file JSON e `--set` applica
modifiche esplicite. Sono configurabili anche acquisizione pileup, soglie
genotipiche, filtri, letture minime, costanti d'errore e opzioni CPIN.
Le regole strutturali e le formule del modello sono consultabili.

Python e R leggono lo stesso registro. Ogni passaggio conserva i valori
richiesti in `work/effective-scientific-settings.json` e quelli usati da R
in `output/scientific-settings.json`. Il completamento richiede la loro
coerenza. Configurazioni duplicate, valori non validi e metadati alterati
sono rifiutati. I riepiloghi CPI e CPIN vengono controllati anche rispetto
al tipo di marcatore, alla soglia di letture e alla costante richiesta.

## Verifiche e distribuzione

La CI raccoglie test Python sia `unittest` sia `pytest`. Le verifiche
scientifiche distinguono equivalenza dei caller e confronto dei tre modelli
aggiornati con i rispettivi riferimenti. Il runtime costruito esegue
batch da 2, 3 e 5 elementi in seriale, automatico e con limite di due
processi, oltre a un workflow completo da tre BAM in seriale e con limite 2.
I controlli verificano valori attesi, identità dei campioni, parametri
effettivi, budget di risorse, parità delle tabelle e integrità degli input.

Il processo di pubblicazione collega i rapporti scientifici all'immagine
immutabile, al commit e ai byte dei quattro installer. La release riutilizza
gli artefatti qualificati senza ricompilarli. I nuovi profili propongono
il canale di aggiornamento `stable`; una scelta esplicita `testing`
rimane rispettata.

Le prove automatiche su dati sintetici non quantificano il miglioramento
su BAM reali e non sostituiscono la validazione di dominio. I controlli del
client e dei pacchetti Windows/macOS restano distinti dalle prove complete
WSL/Lima sui dispositivi finali. Le evidenze e le verifiche rinviate sono
riportate nel record di accettazione della release.

## Aggiornamento

Scaricare il pacchetto del proprio sistema dalla
[release 0.8.50](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.50)
oppure usare **Verifica aggiornamenti**. Chiudere le analisi prima
dell'aggiornamento e controllare che NIPAT riporti **0.8.50**.
Eseguire `nipat self-test` per i casi distribuiti, quindi un nuovo run
con i propri input; le esecuzioni precedenti rimangono conservate.

La procedura Windows mantiene l'avvio tramite script e PowerShell.
Il setup resta privo di firma Authenticode NIPAT; non è garantita
l'accettazione da parte di Smart App Control. I pacchetti Mac non sono
notarizzati. Consultare le guide [Windows](INSTALLATORE_WINDOWS.md),
[macOS](INSTALLATORE_MACOS.md) e [Ubuntu](INSTALLATORE_LINUX.md), e la
[guida ai cinque moduli](DEVELOPMENT_0.8.50.md).

# Collaudo dei risultati e dei workflow della 0.8.50 installata

Questo collaudo viene eseguito sul PC Windows che ospita NIPAT Desktop 0.8.50,
usando il suo Python, la sua distribuzione WSL e la sua immagine scientifica.
Ogni caso usa la CLI pubblica dell'applicazione e una nuova cartella di risultati.
Il pacchetto di test è separato dall'applicazione: il rapporto identifica sia il
commit installato sia il commit e gli hash del collaudo.

## Che cosa controlla

La suite comprende 54 esecuzioni: 48 con risultati positivi attesi e 6 con
input da rifiutare. A queste si aggiungono i controlli dei prerequisiti,
dell'integrità dei file e della concordanza fra le esecuzioni.

| Parte | Evidenza richiesta |
| --- | --- |
| DNPcall | Conteggi della ricetta SAM, genotipi, likelihood eterozigote, identità dei campioni, riepiloghi e PDF. |
| SNPcall | Tutti i 17 campi attesi; concordanza fra input BAM e pileup e fra elaborazioni di più campioni. |
| Contamination | Entrambi i marker, denominatore corretto, inclusione/esclusione degli zeri, media, deviazione standard, siti selezionati e PDF. |
| CPI prenatale | Entrambi i marker, frazione fetale, prodotti degli indici, intera curva, supporto minimo modificato, mismatch, metadati mancanti e assenza di siti informativi. |
| CPIN postnatale | Entrambi i marker, due selezioni dei siti, trasmissione compatibile e mismatch, indici per sito, intere curve e motivi di esclusione. |
| Workflow | Preset DNP, SNP batch e piano con tutti i cinque moduli; campioni e ruoli corretti, riferimenti tra step, artefatti e risultati numerici dei caller. Una catena CPI da BAM ha risultati positivi attesi indipendentemente. |
| Ripetibilità | Tabelle scientifiche confrontate fra seriale, automatico e parallelismo limitato a due processi; controlli separati sui risultati analitici attesi. |
| Errori di input | Dati costruiti appositamente per essere rifiutati: il successo del test richiede il rifiuto pertinente, non un generico errore del runtime. |

Le 16 prove analitiche dei modelli downstream e le 18 prove batch usano conteggi
e frequenze artificiali con risposte calcolabili direttamente. Per esempio,
la curva CPI di riferimento contiene i prodotti 20, 4 e 2 e la frazione fetale
mediana è 6%; la contaminazione media è 0,025 includendo gli zeri e 0,05
escludendoli. Le costanti di mismatch SNP e DNP vengono controllate separatamente.
Le ricette e gli oracoli di origine sono inclusi tra le fixture del rapporto.

Il piano completo con tre BAM verifica anche il collegamento fra moduli. Quei
tre campioni non rappresentano un trio biologico valido: i risultati positivi
CPIN sono verificati dalle prove analitiche dedicate. La concordanza tra due
esecuzioni della stessa implementazione è una prova di ripetibilità, mentre
gli oracoli indipendenti controllano l'esattezza sui casi artificiali definiti.

## Esecuzione

Usare `scripts/windows/test-installed-0850.ps1` da PowerShell normale,
specificando `-SourceCommit` con il commit Git completo del collaudo.
Lo script verifica il manifest del test e ciascuno dei quattro file scaricati
prima di eseguirli. Il checksum del manifest è fissato nel wrapper; la modifica
dei file del collaudo richiede di rigenerare questo collegamento.

L'installazione richiesta è il pacchetto ufficiale 0.8.50 del commit
`b54ef493ba7f0539a8786b97874fe946b2d26393`, con stato `ready`; la correzione locale
dell'import CPIN è compatibile. L'ID dell'immagine importata in WSL è registrato
separatamente dall'ID dell'immagine originaria della build.

Ogni avvio crea una sessione distinta in
`%LOCALAPPDATA%\NIPAT-Desktop\collaudi`. Il Python e samtools usati appartengono
all'installazione esistente. I BAM vengono generati dai SAM artificiali, senza
richiedere dati personali o installazioni aggiuntive. Il terminale mostra
l'avanzamento dei casi; il rapporto viene aggiornato e conservato anche quando
una verifica fallisce.

## Risultati da leggere e condividere

- `report.html`: riepilogo leggibile, esito e dettaglio delle prove.
- `report.json`: esiti strutturati, comandi, tempi e provenienza.
- `report.zip`: raccolta dei risultati e dei log da condividere per l'analisi.
- `runs` e `logs`: risultati delle singole analisi e relativa diagnostica.

Un caso superato deve soddisfare anche le sue verifiche sui risultati. Un
prerequisito mancante o un caso non eseguito non è un successo. Il rapporto
distingue controlli superati, falliti e bloccati e conserva le eventuali
omissioni dalla raccolta dei file. In caso di errore inviare lo ZIP indicato dal
terminale, invece di una sola schermata dell'ultimo messaggio.

La copertura riguarda i moduli e i workflow elencati, sui dati sintetici inclusi.
La verifica su campioni reali, l'interfaccia interattiva e il comportamento di
nuove installazioni restano osservazioni distinte da questo collaudo.

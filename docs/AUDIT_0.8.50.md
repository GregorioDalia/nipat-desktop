# Revisione tecnica 0.8.50

La revisione riguarda i cinque script R, gli helper scientifici, gli adattatori
Python, il client, i workflow, la presentazione, i pacchetti e il processo
di CI/pubblicazione. Le verifiche confrontano il codice corrente con i
riferimenti scientifici congelati; i risultati storici non vengono attribuiti
alla candidata.

## Difetti corretti

| Area | Evidenza e impatto | Intervento |
| --- | --- | --- |
| CPIN senza siti | Le tabelle con sola intestazione e le colonne `total_count` interamente `NA` su siti tutti a copertura zero venivano lette da R come logiche e rifiutate. Erano input ammessi dall'adattatore Python. | Tipizzazione esplicita e gestione dei vettori di lunghezza zero; regressioni SNP e DNP. Conteggi mancanti fuori dal caso supportato restano invalidi. |
| CPIN con frequenze molto piccole | La divisione per una frequenza positiva estrema poteva produrre overflow prima del logaritmo, rendendo infinito un log CPI matematicamente finito. | Calcolo nel dominio logaritmico soltanto in caso di overflow con frequenza positiva finita; risultati ordinari invariati. Le frequenze zero restano rifiutate dalla validazione, come verificato dalle regressioni. |
| Pannello DNP | Alleli REF/ALT identici e delimitatori interni nel cromosoma potevano raggiungere un caller che non li rappresenta correttamente. | Rifiuto preliminare con messaggio di validazione e regressioni. |
| Impostazioni scientifiche | Un output privo del file di parametri R poteva essere accettato; alcune uguaglianze Python accettavano booleani al posto di numeri. | File obbligatorio per tutti i moduli; controllo completo di schema, nomi, tipi, valori e costanti. |
| Riepiloghi CPI/CPIN | Tipo di marcatore, letture minime e costante d'errore non erano confrontati con la richiesta. | Verifica dei valori effettivi prima del successo. |
| Identità dei campioni | Alias o hard link potevano assegnare lo stesso file fisico a campioni distinti nelle analisi familiari. | Rifiuto esplicito prima della preparazione. Il riuso intenzionale di un genitore in famiglie diverse resta supportato. |
| Configurazione JSON | Chiavi duplicate potevano nascondere un valore precedente senza avvisare. | Rifiuto di moduli o parametri duplicati. |
| Report HTML | Le associazioni familiari dei piani generici non erano riportate, pur essendo registrate nel piano. | Famiglie e ruoli CPI/CPIN esposti anche nelle composizioni asimmetriche. |
| Canale aggiornamenti | Un profilo nuovo proponeva `testing` anche per una versione ufficiale. | Default `stable`; la scelta esplicita `testing` rimane rispettata e modificabile dal menu. |
| Raccolta dei test | La scoperta tramite solo `unittest` non eseguiva i test in stile `pytest`; nei runner puliti mancava anche la dipendenza. | Dipendenze di qualità fissate e raccolta di entrambi gli stili tramite `pytest`. |
| Test specifici dell'ambiente | Alcuni test assumevano R con dipendenze complete o percorsi host Linux anche sui runner Windows. | Prerequisiti dichiarati sui test host e verifica R obbligatoria nel runtime scientifico esatto, senza test saltati in quel controllo. |
| Contratti del collaudo distribuito | Alcune attese conservavano il piano senza tipo di marcatore e il precedente formato dei pannelli CPI; un controllo R richiedeva inoltre un pacchetto non usato. | Attese esplicite per il piano normalizzato e i pannelli con alleli; prerequisiti coincidenti con le dipendenze effettive. Le verifiche restano distinte dall'esecuzione nell'immagine finale. |

## Prestazioni e manutenzione

Il collaudo degli installer ha inoltre evidenziato tre problemi operativi.
Le evidenze dei test Docker ora sono scritte con UID/GID del runner, conservando
i permessi riservati dei file. I test dell'avanzamento usano un orologio
deterministico, mantenendo thread reali e i casi di successo, errore e annullamento.
Per una terminazione 137/-9, la diagnosi ricontrolla brevemente lo stato Docker
prima della rimozione del container: accetta un eventuale flag OOM tardivo solo
per la stessa identità verificata, entro un budget di due secondi.
Senza quel flag, la causa resta non confermata; il codice 137 da solo non prova
un esaurimento della memoria. Il test di integrazione continua a richiedere
la conferma esplicita di Docker per l'OOM provocato intenzionalmente.

La matrice completa dei cinque moduli produce oltre 3.500 file testuali di
evidenza. Il tetto del numero di file nell'archivio di qualificazione passa
da 3.000 a 5.000 per conservarli integralmente. Restano i limiti di 64 MiB
complessivi e 8 MiB per file, l'elenco dei formati ammessi e la verifica
indipendente di identità, nomi, dimensioni e hash. Gli errori distinguono
ora il superamento del numero di file da quello dei byte complessivi.

La preparazione CPI/CPIN conserva una cache limitata al singolo preflight per
evitare nuove scansioni delle tabelle dei genitori condivisi. La cache non
persiste tra esecuzioni e non sostituisce la convalida nel runtime.
Su 100 terne con due genitori condivisi e 100 figli distinti, le scansioni
complete delle tabelle passano da 300 a 102, una per campione distinto.
La prova verifica anche che gli input restino identici e che il preflight
non crei una cartella di esecuzione.

La pianificazione DNP indicizza una volta l'associazione fra loci, coordinate
e righe del pileup. Elimina le scansioni ripetute dell'intero pannello per
ciascun gruppo e mantiene gli stessi blocchi e lo stesso ordine. I test
confrontano il piano completo con il precedente algoritmo, anche per
coordinate sovrapposte e casi di inferenza dei tipi.

Nel microbenchmark locale con 10.000 marcatori, tre prove alternate della
sola pianificazione hanno misurato 8,345/7,913/7,988 secondi per la versione
precedente e 0,546/0,560/0,620 secondi per l'indicizzazione nuova. Le mediane
sono 7,988 e 0,560 secondi. I 18 confronti dei piani hanno dato identità esatta.

Restano il budget comune di CPU/memoria, la modalità seriale e l'assenza di
pool annidati. CPIN usa cache dei campioni e curve per intervalli; CPI
conserva la cache e le ottimizzazioni precedenti. Nessuna ulteriore riscrittura
del client o del setup è stata giustificata da un collo di bottiglia verificato.

Resta un possibile costo per report molto grandi: l'esportazione delle tabelle
per la presentazione le carica interamente per sostituire le etichette.
Una conversione incrementale è un miglioramento successivo; non è stata
attribuita a questo passaggio una regressione misurata sui BAM reali.

I microbenchmark della pianificazione misurano una sola fase. Non attestano
la velocità complessiva su BAM reali, che richiede il protocollo descritto
in [PERFORMANCE.md](PERFORMANCE.md#collaudo-dei-cinque-moduli-nella-0850).

## Qualificazione scientifica e CI

I riferimenti originali restano immutabili. I controlli distinguono:

- equivalenza DNP con NIPAT 0.8.5 ed equivalenza SNP con NEWPAT 2.0;
- confronto di CPI, Contamination e CPIN con i tre nuovi sorgenti NEWPAT
  e con attese analitiche indipendenti;
- batch di 2, 3 e 5 elementi, parametri diversi, assenza di siti informativi,
  seriale, automatico e limite manuale;
- workflow completo da tre BAM, entrambi i tipi di marcatore e tutte le
  analisi successive, con confronto di 30 tabelle fra seriale e limite 2;
- regressioni dei contratti, input invalidi, annullamento, diagnosi e integrità
  degli artefatti.

Le nuove regressioni dei casi limite effettuano 16 esecuzioni R su SNP e DNP:
campioni e terne vuoti, copertura interamente nulla con totale mancante,
totali malformati, frequenze positive estreme e frequenze zero. Verificano
stime e curve vuote nei casi ammessi, errori espliciti per input invalidi
e log CPI confrontati con valori analitici nei casi di overflow.

La qualificazione dei modelli aggiornati registra hash di input, output,
log, sorgenti, riferimenti e verificatore, insieme ai parametri realmente
scritti da R e all'attività dei worker. L'immagine finale esegue anche il
workflow completo attraverso il client pubblico, senza montare i sorgenti
scientifici del checkout al posto di quelli installati.

Lo schema 7 di accettazione collega entrambi i rapporti scientifici al commit
e all'immagine immutabile, insieme alle evidenze dei quattro pacchetti.
Non richiede falsa equivalenza dei modelli aggiornati con quelli precedenti.
I test del processo di rilascio verificano anche rifiuto di rapporti mancanti,
identità discordanti, copertura incompleta e dati alterati.

## Pacchetti e limiti delle prove

La lettura del confezionamento non ha individuato un nuovo difetto
nell'avvio Windows `.cmd` → PowerShell, nell'inventario dei file, nella
separazione delle cartelle o nel riuso verificato degli archivi. Il controllo
della distribuzione verifica anche che ogni script incluso abbia le proprie
dipendenze locali. Il setup conserva le protezioni e non modifica le policy
di Smart App Control.

La build e i controlli dei pacchetti non equivalgono a una prova completa su
Windows 10/11 con WSL o su macOS con Lima. Il record di accettazione mantiene
separate prove automatiche, osservazioni storiche, scenari desktop rinviati
e validazione di dominio. Le firme dei componenti e i checksum non vengono
presentati come una firma NIPAT o come prova di accettazione SAC/Gatekeeper.

Gli esiti finali, il commit compilato e i rapporti conservati sono collegati
dal record `.github/release-acceptance/v0.8.50.json` preparato dopo la build.
Le [note di versione](RELEASE_0.8.50.md) descrivono il comportamento distribuito.

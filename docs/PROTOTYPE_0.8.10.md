# NIPAT Desktop 0.8.10 — prototipo integrato

La 0.8.10 è un unico candidato di sviluppo per le prove delle ottimizzazioni
DNPcall e degli indicatori di avanzamento. La release ufficiale rimane la
[0.8.9](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.9).
Il candidato non è pubblicato nel canale stabile e non viene proposto
automaticamente dall'aggiornatore.

## Ottenere e identificare un candidato

Aprire il workflow
[Installers (review build)](https://github.com/GregorioDalia/nipat-desktop/actions/workflows/windows-installer.yml)
e scegliere una build completata con successo del branch `release/0.8.10-test`.
Il suo commit deve corrispondere al candidato da provare. Nel riepilogo del
controllo congiunto `installer-required` sono disponibili i collegamenti ai
singoli pacchetti verificati:

| Sistema | Pacchetto |
| --- | --- |
| Windows x64 | `NIPAT-Setup.exe` |
| Ubuntu 24.04 x86_64 | `nipat-desktop_0.8.10_amd64.deb` |
| macOS Apple Silicon | `NIPAT-0.8.10-macos-arm64.pkg` |
| macOS Intel | `NIPAT-0.8.10-macos-x86_64.pkg` |

Scaricare il pacchetto del proprio sistema dal riepilogo della build. Gli
artefatti di GitHub Actions sono temporanei: conservare il pacchetto e il
riferimento a commit, build e checksum. Il solo numero `0.8.10` non distingue
due candidati successivi. La compilazione e il controllo dei pacchetti non
equivalgono a una prova su ciascun computer finale.

Gli installer usano il profilo **NIPAT Desktop**: installare manualmente il
candidato aggiorna l'installazione locale riconosciuta, senza creare
automaticamente un'applicazione affiancata. Chiudere le analisi prima del setup
e conservare i run di riferimento. Seguire le guide
[Windows](INSTALLATORE_WINDOWS.md), [Ubuntu](INSTALLATORE_LINUX.md) e
[macOS](INSTALLATORE_MACOS.md) per requisiti e procedure del sistema.
La disponibilità della build non modifica la release ufficiale su GitHub.

Windows continua a usare WSL2 con Docker Engine gestito da NIPAT; macOS usa
Lima; Ubuntu usa Docker Engine locale. Il core scientifico resta R.

## Interventi nel candidato

| Area | Comportamento |
| --- | --- |
| Preparazione DNPcall | Con un indice BAM disponibile, seleziona le letture delle regioni richieste prima di eseguire il pileup. Mantiene BED, opzioni di `mpileup`, profondità massima, BAQ e filtri scientifici. Gli indici mancanti consentono la scansione sequenziale; un indice presente ma inutilizzabile produce un errore. |
| Elaborazione R | Indicizza le righe del pileup e legge gruppi di finestre DNP complete, rilasciando i dati consumati. Conserva l'inferenza globale dei tipi, gli identificativi dei loci e l'ordine richiesto dai calcoli e dagli output. Quando le regole esistenti creano dipendenze fra finestre, usa automaticamente un unico blocco per campione. |
| Intermedi | Usa un volume temporaneo anonimo sul filesystem Linux del runtime. Il BAM originale viene letto dal mount in sola lettura; gli intermedi grandi non vengono collocati nel RAM disk. |
| Avanzamento | Mostra fase, campione e tempo trascorso anche senza diagnostica. Espone conteggi solo nelle fasi che hanno un totale misurabile; uno stato di esecuzione attivo non è una percentuale di completamento. |

Il limite ordinario è di **64 loci e 8 MiB di righe pileup per blocco**.
Finestre complete e gruppi con la stessa posizione effettiva rimangono
indivisibili anche quando superano questi limiti. Le finestre sovrapposte
possono condividere osservazioni: ogni blocco contiene tutti i dati necessari
ai loci assegnati. Gli 8 MiB misurano l'input grezzo, **non un limite della
RAM di R**; le letture non vengono eliminate per rientrare nel budget.

La verifica preliminare riconosce inoltre due casi in cui il raggruppamento
del codice precedente può collegare finestre diverse: coordinate del pileup
non associabili alle finestre secondo le regole esistenti e QNAME ripetuti
nella stessa riga del pileup. In questi casi il candidato usa automaticamente
un unico blocco per l'intero campione e registra la motivazione in
`work/dnp-blocks.json`. Questo percorso conserva la semantica esistente, ma
può richiedere la memoria dell'elaborazione completa. Il semplice riutilizzo
di un QNAME in loci diversi non richiede questo ripiego.

I blocchi di un campione sono elaborati in sequenza; il parallelismo già
disponibile fra campioni è limitato al numero dei campioni effettivi.

Con un solo BAM indicizzato, selezione delle letture e pileup sono collegati
da una pipeline. Con più BAM, le selezioni indicizzate vengono preparate su
disco Linux mantenendo l'ordine dei campioni. I tempi delle fasi sovrapposte
non devono essere sommati; la durata complessiva comprende anche la preparazione
degli intermedi.

I risultati e i log restano nella cartella del run. Gli intermedi temporanei
vengono rimossi alla chiusura della loro elaborazione; il client raccoglie
prima la diagnostica del container e poi rimuove il container posseduto e il
suo volume anonimo. Il recupero delle esecuzioni interrotte conserva i
controlli di identità prima della pulizia.

La configurazione delle risorse mantiene la distinzione fra valori salvati,
risorse effettive, suggerimenti e nuovi valori. **Invio conserva il valore
corrente**. Aumentare le CPU disponibili non garantisce di accelerare un
singolo BAM: il comportamento va valutato sull'intero run, compresi I/O,
preparazione e grafici.

Gli indicatori distinguono preparazione, lettura del BAM, calcolo DNP, grafici
e controllo/esportazione dei risultati. Il tempo trascorso continua ad
aggiornarsi anche quando R non scrive nuove righe nel log. Il candidato non
mostra una stima del tempo residuo. Gli eventi strutturati e le istantanee
di avanzamento sono riutilizzabili da una futura GUI.

| File relativo all'elaborazione DNP | Contenuto |
| --- | --- |
| `work/dnp-pileup.json` | Strategia di accesso, tempi di selezione/pileup, dimensioni degli intermedi e del pileup. Un conteggio non misurato rimane assente o nullo. |
| `work/dnp-blocks.json` | Lettura dell'indice, limiti dei blocchi, eventuali motivi del blocco unico di compatibilità, loci/righe/byte elaborati e tempi per campione e blocco. |
| `progress/` nella cartella del run | Eventi di avanzamento per processo, disponibili anche senza diagnostica. |

Nei workflow automatici i due rapporti DNP si trovano nella cartella del
relativo passaggio. Gli eventi di avanzamento rimangono distinti dal
monitoraggio di CPU e memoria descritto nella guida alle prestazioni.

## Prima prova e confronto con i run archiviati

1. Controllare `NIPAT 0.8.10` all'avvio e registrare commit e build del pacchetto.
   Eseguire **8 — Verifica ambiente**.
2. Scegliere un BAM già analizzato e riutilizzare esattamente FASTA, pannello,
   parametri, verifica degli input e limiti di risorse del run di riferimento.
   Usare una nuova cartella di esecuzione; conservare l'archivio precedente.
3. Se il riferimento include la diagnostica, scegliere **Avvia analisi con
   diagnostica prestazioni** anche per il candidato. Una prova breve con
   **Avvia analisi** permette inoltre di verificare gli indicatori senza
   attivare la diagnostica.
4. Confrontare prima tabelle individuali, riepiloghi, tabelle per la
   consultazione e PDF. Per i PDF distinguere il contenuto e il rendering
   dai metadati di creazione. I confronti automatizzati di sviluppo verificano
   anche le quantità R non arrotondate e, per il percorso indicizzato, i byte
   del pileup.
5. Confrontare durata totale e fasi, includendo lettura, scrittura e ogni
   eventuale copia degli intermedi. Separare il picco del container dalle
   rilevazioni parziali **Peak RAM** stampate da R. Conservare il run completo,
   anche in caso di fallimento o annullamento.

Non è necessario rieseguire una vecchia versione quando sono già disponibili
risultati di riferimento e metadati adeguati al confronto. I tempi ricavati da
run storici sono osservazioni: differenze di cache, carico o risorse vanno
considerate prima di attribuire un guadagno alla nuova versione. La
[guida alle prestazioni](PERFORMANCE.md#misure-e-significato) descrive le fonti
delle misure e il loro significato.

Per una prova di annullamento usare un nuovo run e premere **Ctrl+C** durante
l'analisi. Verificare il ritorno al menu e lo stato interrotto; gli eventuali
output parziali non costituiscono un risultato completato. Non sovrascrivere
un run riuscito per eseguire questa prova.

## Evidenze e stato delle prove

La build deve conservare la corrispondenza fra commit, immagine scientifica,
installer e rapporti. Consultare gli esiti dei job e gli artefatti di quella
build: un controllo saltato non è un controllo superato. I test sintetici
coprono l'equivalenza nei casi eseguiti; le prove su dati reali e sui sistemi
finali restano evidenze distinte. In particolare, un controllo del pacchetto
Mac non attesta una prova completa della VM Lima/Rosetta.

Le prestazioni del candidato devono essere misurate sul sistema di utilizzo;
questa guida non attribuisce un incremento di velocità o una riduzione di
memoria prima delle relative misure. Non pubblicare su GitHub BAM, output di
campioni reali o archivi di run che li contengono. Log e metadati possono
includere nomi dei campioni e percorsi locali.

## Versionamento

Più commit e build possono concorrere alla preparazione della 0.8.10 prima
della pubblicazione. Per passare a un altro candidato con lo stesso numero
di versione occorre scaricarne manualmente il pacchetto: l'aggiornatore
confronta la versione, non il commit. Una release pubblicata rimane immutabile;
ogni successivo pacchetto ufficiale avrà una versione superiore.

SNP 2.0 e il quinto modulo R non fanno parte di questo candidato. La loro
integrazione sarà definita dopo la disponibilità degli script scientifici.

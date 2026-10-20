# NIPAT: stato del progetto e funzionamento

**CLI 0.2.0a2 in preparazione per la validazione con l'esperta di dominio.**
NIPAT riunisce quattro analisi locali: Python gestisce file ed esecuzioni,
mentre gli script R di DNPcall e NEWPAT eseguono i calcoli con samtools in
Docker. La GUI verrà dopo la validazione della CLI.

| Analisi | Input disponibili | Risultati |
| --- | --- | --- |
| DNPcall | Uno o più BAM, anche tramite lista; FASTA indicizzato e pannello DNP | Conteggi, genotipi, riepiloghi e grafici. |
| SNPcall | BAM e FASTA indicizzato oppure pileup già pronto; lista SNP | Tabella dei conteggi SNP. |
| Contamination | Tabelle DNPcall scelte singolarmente o da una cartella; pannello di coordinate | Stima per sito e riepilogo per campione. |
| CPI | Tabelle materne/paterne, coppie e frequenze; tutti i siti, un pannello o più cutoff | Frazione fetale, CPI e grafici. |

## Dove siamo

La versione precedente ha corretto i problemi di compatibilità di DNPcall e
integrato gli aggiornamenti CPI e Contamination di NEWPAT acquisiti il
19 ottobre 2026. Le prove già svolte comprendono DNPcall e SNPcall su un
campione reale, il passaggio DNPcall → Contamination, l'esempio SNPcall degli
autori e casi sintetici CPI/Contamination. Sul PC Windows di sviluppo, per
`0.2.0a1`, sono stati superati 48 test Python, con un test saltato, e i tre
autotest numerici Docker.

La revisione `0.2.0a2` elimina il vincolo che imponeva input dentro progetto,
`data` o `runs` e rende disponibili nel menu tutte le modalità di input
supportate. Non cambia gli algoritmi R né i valori predefiniti scientifici.
Il 20 ottobre 2026 sono riusciti, sul PC Windows di sviluppo, setup, quattro
gruppi di autotest e scelta della cartella risultati. DNPcall con input esterni
ha riprodotto i precedenti 11 siti e tutte le 17 colonne di un BAM reale.
Gli [esiti dettagliati](docs/DISTRIBUZIONE.md) distinguono queste prove dalla
validazione della collega e dall'installazione su un altro PC, ancora da svolgere.
Il tag `v0.2.0a1` resta invariato; la nuova revisione va pubblicata separatamente.

## Come si usa

Il canale scelto è GitHub: si scarica la versione indicata, si estrae il
progetto e si avvia `1_SETUP.cmd`, poi `2_AVVIA.cmd`. Serve Docker Desktop
avviato con container Linux; il primo setup richiede Internet e prepara
Python locale e il runtime scientifico.

Gli input possono restare nelle loro cartelle originali, anche su un'altra
unità accessibile a Docker. NIPAT rende disponibili al container i file
selezionati in sola lettura, senza copiare BAM e FASTA. Si può scegliere la
cartella dei risultati: ogni analisi crea un nuovo run, conserva i nomi
degli output scientifici e registra input, corrispondenze dei percorsi,
parametri ed esito in `run.json` e `execution.log`. I run esistenti non vengono
sovrascritti e i dati delle analisi restano sul computer.

Per cominciare: [guida della collega](docs/GUIDA_COLLEGA.md).
Per riportare le prove: [scheda di validazione](docs/VALIDAZIONE.md).

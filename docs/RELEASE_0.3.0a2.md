# NIPAT CLI 0.3.0a2 — interazione guidata e avvio Windows

Candidato per la revisione dell'interfaccia testuale e dei due pacchetti Windows.
L'installatore attualmente pubblicato resta `v0.3.0a1`; queste note non annunciano
una nuova release già disponibile. La consegna per i test esterni dovrà utilizzare
il pacchetto finale con l'interfaccia più recente verificata dal manutentore.

## Novità

- Avvio con doppio clic su `NIPAT.exe` nell'installazione WSL e nel pacchetto
  Docker Desktop. Il launcher apre la CLI e conserva i comandi diretti;
  non occorre aprire PowerShell manualmente.
- Due modalità di distribuzione della stessa versione: `NIPAT-Setup.exe`
  e `NIPAT-DockerDesktop-0.3.0a2-windows-x64.zip`. Lo ZIP contiene Python
  portabile e lo stesso archivio scientifico verificato del pacchetto WSL;
  richiede Docker Desktop con container Linux già disponibile.
- Identità dell'immagine importata risolta dal caricamento dell'archivio
  verificato anche nel setup Docker Desktop, senza presumere che coincida
  con l'identificativo del motore usato per esportarla.
- Licenza GPL-3.0-or-later per il codice originale NIPAT e documentazione
  delle licenze e attribuzioni dei componenti inclusi.
- Banner NIPAT con versione e menu verticale, con frecce/Invio nei terminali
  supportati e scelta numerica disponibile anche in testo semplice.
- Controllo degli input durante la compilazione, ritorno al campo precedente
  con `:indietro` e conservazione dei valori durante le correzioni.
- Indicazioni contestuali nei quattro workflow, anche dopo la scelta della
  modalità e dentro i campi, con esempi e spiegazione dei comandi disponibili.
  Nelle liste, Invio prima del primo file ripropone le istruzioni; termina
  l'elenco soltanto dopo l'inserimento di almeno un file. Nei campi si annulla
  con `:annulla`, non con `0`.
- Riepilogo modificabile di input, parametri e destinazione prima di
  **Avvia analisi**.
- Schermata finale per aprire risultati, cartella del run e log e consultare
  i metadati dell'esecuzione; richiamo dell'ultima esecuzione nella sessione.
- **7 — Guida all'uso**, con **1 — Come usare NIPAT** e
  **2 — Verifica strumenti di analisi**. Il controllo viene richiesto
  separatamente e non viene eseguito in `--dry-run`.

I quattro workflow e le loro modalità di input restano disponibili. La
revisione non cambia gli algoritmi R né i valori predefiniti scientifici e
non aggiunge dipendenze Python esterne. La cartella risultati e il richiamo
dell'ultima esecuzione restano limitati alla sessione: cronologia persistente
e concatenamento automatico dei workflow non sono inclusi.

## Verifiche del candidato

Controlli locali della revisione con launcher e doppio pacchetto:

- 178 test Python superati con Python 3.12.14.
- 17 test della procedura di pubblicazione superati, incluso il passaggio di
  un pacchetto prodotto dal generatore reale ai controlli di pubblicazione.
- 32 asserzioni sul caricamento del runtime portabile superate con PowerShell
  7.6.7 su Linux: archivio verificato, identità locale, piattaforma ed errori.

I test dell'EXE compilato e di PowerShell 5.1 sono eseguiti dalla CI Windows;
il loro esito va associato alla build effettivamente consegnata. Le evidenze
storiche dell'interfaccia sono riportate di seguito.

Revisione delle indicazioni contestuali e del menu Guida al commit `5be5094`,
con Python 3.12.14:

- 173 test automatici superati. I nuovi casi verificano Invio nei campi
  obbligatori e nelle liste, mantenimento degli elementi, annullamento,
  correzione dei percorsi errati e verifica degli strumenti su richiesta.
- Riprodotta in una console POSIX la sequenza DNPcall con Invio ripetuto prima
  del primo BAM: istruzioni neutre, campo ancora aperto e annullamento riuscito.
- SNPcall in `--dry-run` attraverso menu e servizi reali: stato `planned`,
  nessun risultato scientifico e uscita senza errori.

Controlli locali completati sulla base `cf16710`, con Python 3.12.14,
prima della revisione delle indicazioni contestuali e del menu Guida:

- 164 test automatici superati, inclusi i quattro workflow, la correzione dei
  campi, la conferma prima dell'avvio e la gestione dei risultati.
- Importazione dei nuovi moduli con Python isolato, senza `site-packages`.
- Navigazione con frecce, Invio ed Esc in un terminale POSIX reale, oltre
  al menu numerico in testo semplice.
- SNPcall in `--dry-run` attraverso il menu e i servizi reali: metadati con
  stato `planned`, nessun risultato scientifico e nessun falso messaggio di
  analisi completata.
- Versione del pacchetto, controllo del manifest e versione visualizzata
  dall'installatore allineati a `0.3.0a2`, con un test per rilevare divergenze.
  Manifest generato da Python accettato dal controllo PowerShell; 64 asserzioni
  dei controlli installer superate con PowerShell 7 su Linux.

Questi controlli non sostituiscono la verifica manuale della console Windows.
Prima della distribuzione del nuovo installatore occorre provare su Windows:

1. Avvio tramite `NIPAT.exe` in entrambe le modalità, completamento del setup
   e degli autotest del pacchetto finale; conferma di un'analisi reale.
2. Menu con frecce, Invio e selezione numerica; indicazioni contestuali nelle
   modalità di tutti e quattro i workflow.
3. Invio prima del primo file e dopo almeno un file nelle liste, percorso
   errato seguito da correzione, `:indietro` e `:annulla`.
4. Distinzione tra guida e verifica degli strumenti, compreso `--dry-run`.
5. Modifica di un campo dal riepilogo e avvio soltanto dopo conferma.
6. Apertura della cartella risultati e del log dopo un'analisi.

La migrazione automatica di una distribuzione WSL esistente e la scelta della
lingua restano da implementare. Il setup non deve sostituire automaticamente
un ambiente esistente diverso da quello previsto.

La validazione scientifica su casi indipendenti rimane distinta. Gli esiti
delle versioni precedenti non costituiscono verifica delle nuove interazioni.

- [Guida per l'utilizzo](GUIDA_UTILIZZO.md)
- [Sunto del progetto](../SUNTO.md)
- [Scheda di validazione](VALIDAZIONE.md)

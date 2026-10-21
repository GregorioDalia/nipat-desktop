# NIPAT CLI 0.3.0a2 — interazione guidata

Candidato per la revisione dell'interfaccia testuale. L'installatore attualmente
pubblicato resta `v0.3.0a1`; queste note descrivono il nuovo candidato da sorgenti.

## Novità

- Banner NIPAT con versione e menu verticale, con frecce/Invio nei terminali
  supportati e scelta numerica disponibile anche in testo semplice.
- Controllo degli input durante la compilazione, ritorno al campo precedente
  con `:indietro` e conservazione dei valori durante le correzioni.
- Riepilogo modificabile di input, parametri e destinazione prima di
  **Avvia analisi**.
- Schermata finale per aprire risultati, cartella del run e log e consultare
  i metadati dell'esecuzione; richiamo dell'ultima esecuzione nella sessione.
- Guida essenziale e controllo dell'ambiente su richiesta dal menu.

I quattro workflow e le loro modalità di input restano disponibili. La
revisione non cambia gli algoritmi R né i valori predefiniti scientifici e
non aggiunge dipendenze Python esterne. La cartella risultati e il richiamo
dell'ultima esecuzione restano limitati alla sessione: cronologia persistente
e concatenamento automatico dei workflow non sono inclusi.

## Verifiche del candidato

Controlli locali completati con Python 3.12.14:

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

1. Menu con frecce, Invio e selezione numerica.
2. Percorso errato seguito da correzione, `:indietro` e `:annulla`.
3. Modifica di un campo dal riepilogo e avvio soltanto dopo conferma.
4. Apertura della cartella risultati e del log dopo un'analisi.

La validazione scientifica su casi indipendenti rimane distinta. Gli esiti
delle versioni precedenti non costituiscono verifica delle nuove interazioni.

- [Guida per l'utilizzo](GUIDA_UTILIZZO.md)
- [Sunto del progetto](../SUNTO.md)
- [Scheda di validazione](VALIDAZIONE.md)

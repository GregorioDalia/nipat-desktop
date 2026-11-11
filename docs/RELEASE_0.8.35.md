# NIPAT Desktop 0.8.35

Questa versione corregge un errore intermittente di coordinamento nei batch
SNP paralleli e amplia i controlli sul codice e sull'immagine scientifica
distribuita. Il modello scientifico resta SNPcall 2.0.

## SNPcall e gestione dei processi

Il riferimento è [NEWPAT, commit ce59f4be](https://github.com/lpistacchia/NEWPAT/tree/ce59f4beeeec710b1b42d425cb87d7aad729f71d/SNPcall),
verificato come ultimo aggiornamento upstream di SNPcall l'11 novembre 2026.
Il sorgente originale coincide con il riferimento congelato nella 0.8.30:
questa release non introduce un ulteriore cambiamento delle formule SNP.
Le [note della 0.8.30](RELEASE_0.8.30.md) descrivono le 17 colonne,
i genotipi, gli indel e i riepiloghi per più campioni.

Il coordinatore legge ora lo stato finale di ciascun processo soltanto dopo
la sua uscita. Un errore transitorio nella visibilità del file viene ritentato
con un limite di 20 tentativi e 0,95 secondi complessivi di attesa.
L'avanzamento continua a usare i propri eventi. Un'identità diversa del
campione o uno stato finale illeggibile rimangono errori espliciti.

La diagnostica conserva tipo e messaggio dell'errore di lettura. Durante
l'arresto del batch, un eventuale errore di lettura di un altro processo non
sostituisce la causa principale. I processi avviati e i loro discendenti
vengono arrestati; i campioni ancora in attesa non partono dopo un fallimento.
È gestito separatamente il caso macOS di un gruppo già terminato che risponde
con un errore di autorizzazione al segnale di pulizia.

## Controlli di regressione

La CI e la build degli installer eseguono:

- test con processi reali e guasti di lettura simulati: sostituzione dello stato
  durante l'esecuzione, visibilità ritardata, file assente o malformato,
  identità errata, annullamento e conservazione dell'errore originale;
- prove nell'immagine scientifica con 2, 3 e 5 percorsi BAM, in seriale e con
  massimo due processi, oltre a ripetizioni automatiche con tre campioni;
- confronto con conteggi, likelihood e genotipi attesi indipendenti, parità
  esatta delle tabelle e dei genotipi aggregati, identità dei campioni,
  stati finali dei processi e rispetto del budget comune;
- regressioni dei quattro moduli, confronto con i riferimenti scientifici,
  verifiche della presentazione, del client e dei quattro installer.

Il caso a cinque BAM riutilizza tre fixture sintetiche con percorsi distinti:
verifica la gestione del batch, senza rappresentare cinque campioni biologici
indipendenti. I test Linux e i guasti simulati non attestano una riproduzione
nativa del problema su Windows/WSL. Il collaudo sul dispositivo destinatario
resta distinto dalla qualificazione automatica.

## Installazione e collaudo

Scaricare il pacchetto del proprio sistema dalla
[release 0.8.35](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.35)
oppure usare **Verifica aggiornamenti**. Chiudere le analisi prima
dell'aggiornamento e verificare che NIPAT riporti **0.8.35**.

Per il primo controllo eseguire `nipat self-test`, che usa i dati di esempio
distribuiti. Per un confronto del parallelismo selezionare gli stessi
tre o più BAM e lo stesso pannello SNP, ripetere il batch in seriale,
con massimo due processi e in automatico, usando nomi di run distinti.
Le tabelle SNP e i genotipi aggregati devono coincidere; tempi e memoria
possono differire. Ripetere la modalità automatica per valutare gli errori
intermittenti. Conservare `run.json`, `workflow-state.json`, risultati e log.
Gli script di collaudo con controllo rigido della versione 0.8.30 richiedono
un aggiornamento esplicito prima di provare la 0.8.35.

Non cambia la procedura di installazione rispetto alla 0.8.30. Il setup
Windows resta privo di firma Authenticode NIPAT e non garantisce l'accettazione
di Smart App Control. I pacchetti Mac non sono notarizzati; le prove Lima
sui dispositivi finali rimangono separate dai controlli dei pacchetti.
Consultare le guide [Windows](INSTALLATORE_WINDOWS.md),
[macOS](INSTALLATORE_MACOS.md) e [Ubuntu](INSTALLATORE_LINUX.md).

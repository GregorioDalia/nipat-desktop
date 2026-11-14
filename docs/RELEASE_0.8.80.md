# NIPAT Desktop 0.8.80 — versione stabile pre-GUI

La 0.8.80 conclude il consolidamento della versione con menu testuale e CLI.
I cinque moduli e i workflow composti costituiscono la base funzionale per
l'interfaccia grafica. La manutenzione correttiva rimane prevista.

## Correttezza degli input e dei risultati

- SNPcall conserva esattamente gli identificativi dei contig, inclusi `01`,
  `1` e `NA`. I caller controllano i dizionari dei BAM e la compatibilità con
  il riferimento e i marcatori richiesti.
- Il riepilogo DNP viene confrontato con i genotipi delle tabelle individuali
  di tutti i campioni e loci.
- Il piano di analisi e il menu guidato usano gli stessi rami attivi, file e
  ruoli familiari. Risultati, resoconto e recupero leggono l'esito registrato
  dopo i controlli finali sugli input.
- Un errore samtools nella lettura dell'header o nella preparazione SNP
  conserva il codice di uscita e il percorso del log.

## Affidabilità del client e dell'installazione

- Le preferenze salvate da più finestre conservano le modifiche indipendenti
  e segnalano i conflitti sullo stesso campo.
- I comandi di configurazione delle risorse e arresto dei run restituiscono
  un codice non nullo quando l'operazione richiesta rimane incompleta.
- I controlli di preparazione hanno log durante l'esecuzione e limiti
  temporali distinti, con diagnostica e possibilità di ripresa. Le analisi
  scientifiche e il menu interattivo mantengono la propria durata.
- L'aggiornamento Ubuntu distingue l'avvio del componente di aggiornamento
  dalla verifica del pacchetto, conservando il controllo del digest prima di APT.
- La guida incorporata descrive i workflow completi e il canale di aggiornamento.

## Installazione e verifiche

Scaricare `NIPAT-Setup.exe` per Windows, il DEB per Ubuntu 24.04 o il PKG
macOS dell'architettura del computer. Le [guide](README.md#installare)
descrivono requisiti, aggiornamento e verifica.

Le evidenze della build e il record `desktop-acceptance.json` identificano
le prove eseguite sugli stessi pacchetti distribuiti. I collaudi storici
rimangono attribuiti alle versioni provate. Le prove desktop rinviate e la
validazione di dominio sono distinte dalle verifiche automatiche.

Per verificare l'installazione Windows seguire il [collaudo dei cinque
moduli](COLLAUDO_INSTALLAZIONE.md). Per confrontare risultati su dati
rappresentativi usare la [procedura di validazione](VALIDAZIONE.md).

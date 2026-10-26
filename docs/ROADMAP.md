# Piano di sviluppo

NIPAT Desktop 0.6 esegue le quattro analisi singolarmente. La versione 0.7
è destinata alla valutazione delle esperte di dominio e introduce la
composizione automatica delle analisi compatibili. Questo documento definisce
gli obiettivi di sviluppo; le funzionalità disponibili sono descritte nelle
note della versione effettivamente pubblicata.

Il core scientifico rimane in R. Il motore e la gestione dei workflow
scientifici risiedono nell'immagine Linux autonoma, utilizzata tramite WSL2
su Windows e Docker Engine su Linux. Il client conserva interazione,
configurazione, accesso ai file locali, installazione e aggiornamenti.
La GUI grafica è successiva alla versione 0.7.

Lo sviluppo 0.7.0a1 comprende il [catalogo scientifico](CATALOGO_SCIENTIFICO.md)
bilingue, il [contratto dei piani](WORKFLOW_CONTRACT.md) e i workflow automatici
DNPcall → Contamination, DNPcall → CPI e DNPcall → Contamination e CPI dal
menu e dalla CLI, con SNPcall facoltativo sugli stessi BAM. Il workflow
SNPcall su più campioni accetta BAM oppure pileup importati. L'orchestrazione
risiede nell'immagine e conserva risultati e stato di ogni passaggio, con
ruoli CPI e coppie espliciti. Validatore ed esecutore supportano le quattro
analisi; SNPcall resta indipendente dai risultati delle altre tre.
Gli obiettivi seguenti comprendono le funzionalità necessarie per completare
la 0.7, la cui release non è ancora disponibile.
Le [note della candidata 0.7.0a1](RELEASE_0.7.0a1.md) identificano le
funzionalità da verificare attraverso i pacchetti Windows e Ubuntu.

## Versione 0.7: parametri e impostazioni del motore

La configurazione deve rappresentare tutte le opzioni dell'interfaccia
pubblica dei quattro script R. Le destinazioni degli output restano gestite
da NIPAT; eventuali nomi standardizzati devono essere espliciti nella guida.
Un inventario versionato deve distinguere:

- parametri configurabili, con valore predefinito, valore effettivo, unità,
  vincoli e corrispondenza con l'argomento R;
- soglie e regole interne, consultabili in sola lettura;
- formule del modello e impostazioni di presentazione dei risultati;
- impostazioni della preparazione NIPAT e default delle dipendenze,
  identificati dalla versione del componente che li applica.

Il catalogo deve essere consultabile dal menu e associato ai record delle
esecuzioni. Una modifica ai sorgenti scientifici o alle dipendenze deve
rendere verificabile l'eventuale necessità di aggiornare il catalogo.
Per input preparati esternamente, le impostazioni non ricostruibili devono
essere indicate come non note, senza attribuire loro i default di NIPAT.

Le costanti interne non diventano automaticamente parametri modificabili.
Un cambiamento del modello o del comportamento R richiede una valutazione
scientifica distinta e casi di verifica appropriati.

## Versione 0.7: workflow automatici

L'utente configura campioni, riferimenti, pannelli e parametri dei passaggi,
verifica un riepilogo e conferma l'esecuzione. Il motore gestisce dipendenze,
preparazione degli input e trasferimento degli output compatibili, conservando
un risultato identificabile per ciascun passaggio.

| Composizione | Stato nella 0.7.0a1 di sviluppo | Requisiti |
| --- | --- | --- |
| DNPcall → Contamination | Eseguibile automaticamente. | Tabelle individuali compatibili e pannello di coordinate selezionato. |
| DNPcall → CPI | Eseguibile automaticamente. | Identificazione esplicita dei campioni cfDNA materni e paterni, coppie, frequenze di popolazione ed eventuali pannelli. |
| DNPcall → Contamination e CPI | Eseguibile automaticamente, in sequenza. | Due elaborazioni dei conteggi prodotti, ciascuna con i propri input e parametri. La stima di contaminazione non modifica i dati usati dal CPI. |
| SNPcall nei workflow DNPcall | Eseguibile per ogni BAM distinto selezionato, con pannello SNP esplicito. | Stesso FASTA del passaggio DNPcall; l'output SNP non è un input di Contamination o CPI. |
| SNPcall su più campioni | Eseguibile da BAM o pileup, con un passaggio per campione. | Un pannello SNP comune; FASTA indicizzato soltanto in modalità BAM. |

La prima implementazione usa un ordine di esecuzione deterministico.
La selezione delle dipendenze appartiene al motore nell'immagine; il client
invia il piano e presenta avanzamento, risultati ed errori. Non deve essere
necessario montare i sorgenti dell'applicazione nel container per eseguire
il workflow. Il contratto deve permettere la stessa esecuzione da client
Windows, client Linux o un futuro servizio.

I ruoli biologici e le coppie non devono essere dedotti implicitamente dai
nomi dei file. Gli adattatori devono conservare l'associazione tra campioni
originali, nomi interni e risultati. Un passaggio fallito impedisce l'avvio
di tutti i passaggi non ancora avviati, anche indipendenti; i risultati
parziali e i log rimangono disponibili. Gli input originali e i run esistenti non vengono sovrascritti.

Ogni esecuzione deve registrare il piano, i parametri effettivi per passaggio,
le dipendenze, gli stati e l'identità del motore. L'interruzione deve essere
gestita anche durante un passaggio R o samtools. I comandi delle singole
analisi restano disponibili.

## Verifica automatica e valutazione di dominio

I test della 0.7 estendono la [CI esistente](CI_CD.md) con verifiche di:

- corrispondenza fra opzioni R, CLI, menu e richiesta al motore, inclusi
  valori non predefiniti e impostazioni salvate;
- risultati numerici delle regole rilevanti, con casi sotto, sulla e sopra
  le soglie, e confronto con le esecuzioni separate;
- esecuzione completa delle composizioni supportate, con risultati attesi
  indipendenti dove disponibili;
- errori negli input, dipendenze mancanti, annullamento, arresto dei passaggi
  dipendenti e conservazione dei dati;
- funzionamento del motore senza sorgenti scientifici sul sistema ospite
  e coerenza dell'immagine incorporata nei due installatori.

Le prove automatiche distinguono controlli simulati, esecuzioni reali di R
e prove dei pacchetti installati. Le evidenze dei singoli livelli devono
restare riconoscibili nei resoconti.

La versione 0.7 è la versione prevista per la consegna alle esperte di dominio.
Le prove sui loro sistemi devono documentare installazione, funzionamento
con input rappresentativi, interpretazione dei risultati e problemi
riproducibili. L'esito di una prova si riferisce alla versione e ai dati
effettivamente utilizzati. La [scheda di validazione](VALIDAZIONE.md)
fornisce il riferimento per raccogliere gli esiti.

## Italiano e inglese

L'obiettivo è offrire italiano e inglese per README, guide e note delle
release su GitHub, menu, aiuti contestuali e messaggi NIPAT, oltre alla futura
GUI. La traduzione completa è un incremento dedicato, successivo alle priorità
funzionali della 0.7; la separazione tra testi e identificatori deve essere
prevista fin dall'introduzione dei nuovi workflow.

La lingua selezionata riguarda la presentazione. Nomi dei comandi, opzioni
CLI, chiavi JSON, identificatori dei passaggi, nomi delle colonne scientifiche
e valori registrati nei contratti rimangono stabili. Cambiare lingua non deve
modificare formule, parametri, separatori dei file o risultati.

I testi di NIPAT devono provenire da cataloghi di messaggi condivisi fra menu
e futura GUI, con una scelta della lingua salvabile. I messaggi strutturati
del motore devono essere traducibili dal client. L'output originale degli
script R e degli strumenti esterni rimane disponibile nei log nella lingua
prodotta dai componenti; eventuali spiegazioni tradotte devono essere separate.

La documentazione deve offrire collegamenti reciproci tra italiano e inglese
e identificare la versione descritta. I controlli automatici devono rilevare
chiavi di traduzione mancanti e collegamenti non validi. Le prove devono
confermare che entrambe le lingue producano richieste scientifiche equivalenti.

## Incrementi successivi

La build della candidata 0.7.0a1 prepara i pacchetti Windows e Ubuntu dal
medesimo motore.
Prima della distribuzione occorre verificarne integrità e funzionamento e
registrare le prove sul pacchetto destinato alla consegna. Le evidenze delle regressioni
su sorgenti e container rimangono distinte da quelle degli installatori.
La pubblicazione segue la [procedura di release](../.github/RELEASE.md);
la 0.6 ufficiale rimane disponibile fino alla pubblicazione della successiva.

Una possibile versione 0.7.5 comprende parallelismo controllato fra attività
indipendenti e ripresa di esecuzioni interrotte. Il parallelismo deve rispettare
un limite complessivo di risorse, considerando anche quello interno a DNPcall.
La ripresa richiede una verifica affidabile di input, parametri, output e
identità del motore prima di riutilizzare un passaggio completato; dimensione
e data di modifica dei file da sole non dimostrano l'identità dei contenuti.

La GUI utilizzerà gli stessi contratti del motore, il catalogo dei parametri
e i testi localizzati. La sua progettazione seguirà i risultati della
valutazione della CLI e dei workflow, mantenendo una sola implementazione
della logica scientifica e di orchestrazione nell'immagine.

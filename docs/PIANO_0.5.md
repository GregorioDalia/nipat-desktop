# Percorso incrementale verso NIPAT 0.5

Stato: quinto incremento tecnico in sviluppo, 23 ottobre 2026. Questo documento
registra le decisioni, il lavoro già svolto e i controlli ancora necessari.

## Baseline e separazione dalla validazione in corso

- La versione consegnata per le prove di dominio è `v0.4.1`, commit
  `8e1f57d4721d7864051747cb5d5b10cfe8408a77`.
- Il punto di partenza dello sviluppo 0.5 è `main` al commit
  `30a623a3133171b9ff5610dffa04d4d3b78e783a`, che include i successivi controlli CI/CD.
- Lo sviluppo parte sul branch `feature/0.5-foundation`, in un checkout separato.
- Tag, asset, manifest e note della release 0.4.1 restano invariati. La dismissione
  dell'edizione Docker Desktop riguarda il nuovo prodotto, non gli archivi storici.
- I candidati 0.5 devono poter essere provati senza sostituire l'applicazione 0.4.1:
  identità dell'installazione, collegamenti, configurazione, distribuzione WSL e
  cartelle predefinite dei risultati devono essere distinti durante le prove.
  Non basta creare un nuovo branch: l'installer attuale usa una destinazione fissa.
- Nessuna pubblicazione automatica o sostituzione degli asset distribuiti.
  L'eventuale migrazione dalla 0.4.1 sarà un passaggio esplicito e verificato.

## Decisioni acquisite

1. Il core scientifico rimane in R. La migrazione di confezionamento conserva
   i file R e il loro manifest SHA-256; non comprende modifiche agli algoritmi.
2. Su Windows il percorso definitivo è la distribuzione WSL2 dedicata con
   Docker Engine gestito da NIPAT. L'edizione Docker Desktop sarà rimossa
   dall'applicazione, dai nuovi installatori e dal percorso attivo di distribuzione.
3. R e samtools sono già presenti nell'immagine attuale. Il nuovo motore deve
   includere anche gli script e la preparazione necessaria ai quattro workflow,
   senza dipendere dal checkout o dalla cartella dell'applicazione Windows.
4. Gli adattatori Python necessari alla preparazione scientifica possono essere
   inclusi nel motore. Questo non cambia il linguaggio degli algoritmi R.
5. L'interfaccia desktop rimane esterna al motore. Il lavoro sull'infrastruttura
   deve poter procedere usando la CLI guidata esistente.
6. La distribuzione 0.5 dovrà offrire tramite GitHub un installer Windows e
   un installer Linux. I due pacchetti useranno lo stesso archivio del motore
   per l'architettura supportata, costruito e verificato una sola volta.
7. Docker Engine nativo rimane necessario per l'edizione Linux. La rimozione
   di Docker Desktop non implica la rimozione del trasporto Docker per Linux.

## Perimetro confermato

- Sistema Linux iniziale: **Ubuntu 24.04 LTS x86_64**. Il formato dell'installer
  e la preparazione delle dipendenze saranno scelti per questo sistema;
  non viene dichiarato supporto a tutte le distribuzioni.
- Interfaccia della release 0.5: **CLI guidata, senza GUI**. La futura GUI resta
  esterna al motore e utilizzerà il medesimo contratto di esecuzione.

## Primo incremento: confezionamento del codice R

Il Dockerfile include i quattro script R invariati, le licenze e il manifest
in `/opt/nipat`. L'ingresso `engine/main.py` verifica gli hash e offre i comandi
`describe`, `verify` e `run`, con argomenti nativi degli script.

Le verifiche locali comprendono 204 test Python e 37 test della selezione CI
e del publisher. Il controllo `scripts/verify_engine_package.py`, aggiunto
alla CI e alla build di revisione dell'installer, esegue SNPcall, Contamination
e CPI senza mount dell'applicazione o del checkout, con rete disabilitata e
filesystem dell'immagine in sola lettura. Verifica gli stessi valori numerici
attesi delle regressioni esistenti. L'esito reale dell'immagine va consultato
nella relativa esecuzione GitHub Actions: i test Python da soli non lo provano.

Il primo incremento è stato verificato nella
[CI 39806767798](https://github.com/GregorioDalia/nipat-desktop/actions/runs/39806767798)
e nella [build di revisione 39806767596](https://github.com/GregorioDalia/nipat-desktop/actions/runs/39806767596),
entrambe concluse con successo sul commit `22e0677`.
DNPcall è incorporato e verificato tramite hash; manca ancora la regressione
BAM attraverso il nuovo ingresso. Gli artifact dell'installer generati durante
questo incremento sono soltanto build di revisione della struttura attuale:
**non sono candidati 0.5 installabili accanto alla 0.4.1**. La separazione delle
identità di installazione e i due nuovi installer appartengono ai passi seguenti.

## Secondo incremento: workflow Contamination completo

La CLI ora invia al motore una richiesta `contamination-v1` con il pannello
originale, i file selezionati, i nomi dei campioni e le destinazioni del run.
Selezione di file espliciti e ricerca ricorsiva in una cartella rimangono disponibili.
Il motore convalida gli input, normalizza il pannello, prepara le tabelle `.txt`
ed esegue lo script R invariato. I moduli condivisi `nipat_scientific` conservano
un'unica implementazione dei validatori usati dal client e dal motore.

L'esecuzione usa un documento Compose autonomo: soli input selezionati in lettura
e singolo run in scrittura, senza mount dell'applicazione o dei dati globali,
con rete disabilitata e filesystem dell'immagine in sola lettura.
`runtime.engine` registra gli hash effettivi degli script e del codice Python di
preparazione; gli hash locali del client sono distinti. Un'immagine precedente,
priva del contratto richiesto, viene rifiutata prima dell'analisi.

Le nuove prove coprono preparazione, nomi e byte dei campioni, richieste non valide,
tracciamento e interruzione. Il controllo reale dell'immagine include anche un run
CLI da una cartella applicativa che contiene soltanto `compose.yaml`, senza
sorgenti scientifici. SNPcall, DNPcall e CPI mantengono ancora il percorso precedente.
La suite locale comprende 224 test Python e 37 controlli CI/publisher superati;
la prova dell'immagine e il confezionamento sono verifiche distinte in GitHub Actions.
Questo incremento non modifica gli installer pubblicati né completa la release 0.5.

Il secondo incremento è stato verificato nella
[CI 39812476371](https://github.com/GregorioDalia/nipat-desktop/actions/runs/39812476371)
e nella [build di revisione 39812476253](https://github.com/GregorioDalia/nipat-desktop/actions/runs/39812476253),
entrambe concluse con successo sul commit `56701ee`.

## Terzo incremento: workflow SNPcall completo

La richiesta `snp-call-v1` comprende entrambe le modalità esistenti. Con pileup
già disponibile, il motore verifica il formato con colonna QNAME e avvia R.
Con BAM e riferimento FASTA, verifica gli input e gli indici richiesti del
riferimento, genera le finestre BED di tre basi e il pileup tramite samtools,
quindi avvia R soltanto dopo il successo di samtools. L'indice BAM resta opzionale.
Sono mantenuti i riferimenti BGZF con indici `.fai` e `.gzi`.

La CLI usa gli stessi mount selettivi e lo stesso isolamento di Contamination.
Gli intermedi `work/snp_regions.bed` e `work/pileup.txt` rimangono consultabili;
il risultato continua a essere `output/SNPcall_output.txt`. Anche l'autotest
SNPcall usa il percorso di esecuzione completo. Lo script R e il manifest
scientifico rimangono invariati.

Le verifiche comprendono le nove righe di riferimento già distribuite e una
fixture BAM sintetica con conteggi attesi espliciti, entrambe le modalità CLI
da una cartella applicativa priva di sorgenti scientifici, input non validi,
fallimento di samtools e gestione dell'interruzione. L'esecuzione reale
dell'immagine viene verificata in GitHub Actions, separatamente dai test Python.
I controlli locali comprendono 243 test Python e 37 test CI/publisher superati;
gli esiti numerici e di confezionamento del commit sono riportati nella PR di sviluppo.
Il terzo incremento è stato verificato nella
[CI 39940948277](https://github.com/GregorioDalia/nipat-desktop/actions/runs/39940948277)
e nella [build di revisione 39940948282](https://github.com/GregorioDalia/nipat-desktop/actions/runs/39940948282),
entrambe concluse con successo sul commit `aad3002`.

## Quarto incremento: workflow DNPcall completo

La richiesta `dnp-call-v1` trasferisce al motore il pannello originale, l'elenco
ordinato dei BAM, il riferimento e la scelta sequenziale/parallela. Il client
mantiene le modalità BAM singolo, più BAM e lista, con percorsi relativi alla
lista e corrispondenza fra alias sicuri e file originali in `run.json`.
Il motore prepara `work/DNP_list.txt` e `work/bamlist.txt`, quindi esegue lo
script R dalla radice del run con argomenti relativi compatibili con i suoi
nomi di output. BAM e FASTA vengono montati in sola lettura, senza copiarli.

Le prove dell'immagine usano BAM sintetici costruiti da SAM e FASTA leggibili,
con conteggi e genotipi attesi indipendenti. Coprono il motore completo e la CLI
senza mount dei sorgenti, campioni singoli e multipli, liste relative,
corrispondenza dei campioni e parità sequenziale/parallela. Il confronto con
l'invocazione R nativa verifica anche che il confezionamento conservi gli output.
Gli esiti effettivi e i limiti delle prove sono riportati nella PR di sviluppo.
I controlli locali comprendono 266 test Python e 37 test CI/publisher superati;
l'esecuzione numerica nell'immagine resta una verifica distinta in GitHub Actions.

Il codice R e il manifest rimangono invariati. Rimane quindi anche il comportamento
interno di DNPcall: elimina pileup e BED al termine e non verifica esplicitamente
lo stato della chiamata a samtools, di cui nasconde lo stderr. Il successo del
processo non equivale alla verifica scientifica degli output.

Il quarto incremento è stato verificato nella
[CI 39946173365](https://github.com/GregorioDalia/nipat-desktop/actions/runs/39946173365)
e nella [build di revisione 39946173352](https://github.com/GregorioDalia/nipat-desktop/actions/runs/39946173352),
entrambe concluse con successo sul commit `2592935`.

## Quinto incremento: workflow CPI completo

La richiesta `cpi-v1` trasferisce al motore le tabelle parentali selezionate,
le coppie, i prefissi, le frequenze di popolazione, la costante d'errore e i
pannelli richiesti. Il motore verifica questi input, conserva le tabelle senza
modificarne i byte in `work/inputs` e normalizza i pannelli prima di eseguire R.
Un campione condiviso fra coppie viene preparato una sola volta. La CLI usa
l'esecuzione isolata e i metadati dell'immagine già introdotti per gli altri workflow.

Rimangono disponibili ALL senza pannello, `--panel`, `--cutoff` ripetuto e
`--cutoff-map`. Sono conservati anche il percorso come etichetta per il pannello
singolo, le etichette esplicite dei cutoff, i prefissi personalizzati o vuoti e
la costante d'errore nulla. Nomi che collidono nello staging o nei PDF delle
coppie sono rifiutati prima di scrivere, anche quando differiscono soltanto
per maiuscole/minuscole. Questo evita sovrascritture su filesystem Windows.

Le regressioni dell'immagine confrontano le modalità migrate con i valori
analitici già disponibili, includono il caso senza siti informativi e verificano
CSV, PDF, isolamento dei mount e input originali invariati. Una fixture aggiuntiva
con incompatibilità paterna dimostra numericamente l'effetto della costante
d'errore: per i due siti sintetici i prodotti CPI sono `20e²` e `4e`, verificati
con `e = 0.01`, `0.1` e `0`. Le prove usano anche il client senza sorgenti
scientifici nella sua cartella applicativa. Gli esiti reali della CI e del
confezionamento vengono riportati nella PR di sviluppo.
I controlli locali comprendono 293 test Python e 37 controlli CI/publisher superati;
la verifica numerica nello script R reale rimane distinta e viene eseguita in CI.

Con questo incremento i quattro workflow analitici sono migrati. Restano
l'adeguamento della diagnostica e del client Windows, l'isolamento delle identità
di installazione, la dismissione Docker Desktop e i nuovi installer Windows/Linux.
Le build di revisione non sono candidati 0.5 da distribuire e non devono sostituire
l'installazione 0.4.1. Il codice R e il manifest scientifico rimangono invariati.

## Passaggi e criteri di completamento

Ogni passaggio richiede una modifica circoscritta, verifiche locali applicabili
e una revisione separata prima di proseguire all'integrazione successiva.

### 1. Motore scientifico autosufficiente

Definire il contratto di input, parametri, stato e output. Incorporare gli script
R e gli adattatori necessari, conservando le dipendenze del punto di partenza.
Separare il calcolo dalla selezione dei percorsi Windows e dall'avvio di Docker.

Il primo incremento tecnico include soltanto codice R, risorse, manifest e
identificazione del motore in un percorso interno che i mount non nascondano.
Una prova senza sorgenti esterni verifica questo confezionamento. Seguono
incrementi separati per trasferire la preparazione e l'esecuzione di un workflow
alla volta, iniziando da uno già coperto da regressioni numeriche. La sola
inclusione dei file R non completa l'autosufficienza di tutti i workflow.

Verifiche di completamento:

- esecuzione dei quattro workflow con soli input, configurazione e destinazioni
  di lavoro/output montati, senza montare il checkout o l'applicazione;
- regressioni numeriche con valori attesi e tolleranze dichiarate, casi senza
  siti informativi e modalità di input previste;
- conservazione delle identità dei campioni e dei metadati delle esecuzioni;
- file R e manifest scientifico invariati;
- identificazione verificabile della versione del motore e del suo contratto.

### 2. Client Windows con solo runtime WSL

Collegare la CLI al nuovo motore e rimuovere il percorso Windows Docker Desktop,
compresi launcher, preparazione, installer e messaggi che lo propongono.
Mantenere il codice di esecuzione nativo richiesto su Linux.

Verifiche di completamento:

- installazione del candidato separata dalla 0.4.1, senza riutilizzarne stato
  mutabile o configurazione;
- avvio, analisi, annullamento, diagnosi degli errori e nuovo avvio dopo arresto
  del runtime;
- percorsi Windows supportati, inclusi spazi e unità locali diverse;
- una sola procedura di installazione e una sola icona per il candidato Windows;
- prova reale Windows/WSL del pacchetto, distinta dai controlli simulati in CI.

### 3. Installer Linux

Preparare un singolo pacchetto per il sistema Linux approvato, con il medesimo
motore scientifico e una procedura definita per le dipendenze. Installazione,
avvio e permessi devono essere verificati come parte del prodotto.

Verifiche di completamento:

- installazione su ambiente pulito del sistema dichiarato supportato;
- importazione e identità del medesimo archivio scientifico usato da Windows;
- esecuzione dei workflow e accessibilità dei risultati da parte dell'utente;
- gestione di errori e disinstallazione che conservi i dati dell'utilizzatore.

### 4. CI/CD e preparazione della release

Adeguare progressivamente i controlli insieme ai cambiamenti dei passaggi
precedenti, quindi verificare l'intero percorso dei due installatori.

Interventi già individuati nell'audit della baseline:

- aggiungere il test del motore senza mount dei sorgenti: gli attuali autotest
  tramite Compose non dimostrano questa proprietà;
- aggiornare selezione dei test e percorsi che attivano le build quando cambia
  un componente incorporato nell'immagine;
- sostituire le prove e gli artifact Docker Desktop con quelli Linux;
- conservare il controllo aggregato `required` e il fallimento quando manca
  una verifica obbligatoria;
- adeguare il publisher: attualmente richiede l'installer Docker Desktop anche
  per versioni successive alla 0.4.1;
- richiedere installer Windows e Linux, manifest e checksum coerenti con lo
  stesso commit e archivio scientifico;
- pubblicare manualmente gli artifact verificati, senza ricostruirli durante
  la pubblicazione e senza modificare release già pubblicate.

Le prove del motore in CI, l'installazione su Windows/Linux e la validazione
scientifica di dominio restano evidenze distinte. La 0.5 potrà essere proposta
come candidato solo con l'esito e i limiti di ciascuna verifica esplicitati.

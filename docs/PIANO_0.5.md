# Percorso incrementale verso NIPAT 0.5

Stato: preparazione del lavoro, 22 ottobre 2026. Questo documento registra
le decisioni e i controlli necessari; non descrive funzionalità già implementate.

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

## Perimetro da definire prima del packaging

- Sistema Linux iniziale: proposta Ubuntu 24.04 LTS x86_64. Il formato
  dell'installer e la preparazione delle dipendenze vanno scelti per il sistema
  effettivamente approvato; non viene dichiarato supporto a tutte le distribuzioni.
- Interfaccia della release 0.5: chiarire se mantenere la CLI guidata durante
  il consolidamento o includere anche la prima GUI. In entrambi i casi
  l'interfaccia utilizzerà il medesimo contratto di esecuzione del motore.

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

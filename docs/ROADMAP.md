# Piano di sviluppo

**NIPAT Desktop 0.7.1** offre quattro analisi singole, workflow automatici e
un catalogo delle impostazioni scientifiche. La priorità è raccogliere la
valutazione delle esperte di dominio su input rappresentativi e rendere
riproducibili le segnalazioni. Le funzionalità disponibili e i requisiti sono
nelle [note della versione](RELEASE_0.7.1.md) e nella
[guida per l'utilizzo](GUIDA_UTILIZZO.md).

Il core scientifico rimane in R. Preparazione ed esecuzione delle analisi
risiedono nell'immagine Linux autonoma, usata tramite WSL2 su Windows e Docker
Engine su Ubuntu. Il client gestisce interazione, configurazione, accesso ai
file locali, installazione e aggiornamenti. La GUI è un incremento successivo
alla valutazione della CLI.

## Funzionalità disponibili

| Area | Comportamento della 0.7.1 |
| --- | --- |
| Analisi singole | DNPcall, SNPcall, Contamination e CPI dal menu e dalla CLI diretta. |
| Composizioni DNPcall | DNPcall → Contamination, DNPcall → CPI e DNPcall → Contamination e CPI. |
| SNPcall | Passaggi indipendenti sui BAM delle composizioni oppure batch da BAM o pileup. |
| Campioni e coppie | Ruoli cfDNA materno/paterno assegnati esplicitamente; campioni condivisi elaborati una sola volta e associazioni conservate nei risultati. |
| Parametri | Opzioni pubbliche R esposte o adattate da NIPAT; catalogo italiano/inglese di parametri, regole interne e preparazione. |
| Esecuzione | Un piano in un container, ordine sequenziale, arresto su errore o annullamento e risultati distinti per passaggio. |
| Interazione | Campi modificabili, configurazione persistente, annullamento globale, indicazioni contestuali e navigazione testuale alternativa alle frecce. |
| Distribuzione | Un installatore Windows e un pacchetto Ubuntu, con immagine scientifica incorporata e verifica degli aggiornamenti dal menu. |

Contamination e CPI consumano le tabelle originali DNPcall; la stima di
contaminazione non filtra gli input CPI. SNPcall usa un proprio pannello e
non produce input per Contamination o CPI. Un fallimento arresta tutti i
passaggi rimanenti, anche indipendenti. Non sono implementati parallelismo
fra passaggi o ripresa automatica; resta disponibile il parallelismo interno
a DNPcall.

Il [catalogo scientifico](CATALOGO_SCIENTIFICO.md) conserva il riferimento
ai sorgenti distribuiti. Le costanti interne sono consultabili e non diventano
automaticamente modificabili. Una variazione del modello o del comportamento
R richiede una valutazione scientifica distinta e casi di verifica appropriati.
Il [contratto dei piani](WORKFLOW_CONTRACT.md) separa la presentazione del
client dalla logica scientifica, consentendone l'uso da client Windows, Linux
o da un futuro servizio.

## Valutazione di dominio e affidabilità

La campagna di valutazione deve includere installazione, compilazione degli
input, interpretazione dei risultati, uso di parametri non predefiniti e casi
limite scelti dalle esperte. Ogni prova identifica versione, ambiente, dati,
attese e risultati; la [scheda di validazione](VALIDAZIONE.md) fornisce il
formato di raccolta.

I difetti riproducibili diventano casi della [CI](CI_CD.md). La copertura
comprende propagazione dei parametri, equivalenza tra analisi separate e
composizioni, identità dei campioni, risultati numerici noti, input non validi,
interruzioni e conservazione dei dati. Test simulati, calcoli reali R/samtools
e prove dei pacchetti installati mantengono evidenze distinte.

Il collaudo degli installatori procede per scenari: prima installazione,
aggiornamento, riavvio, percorsi personalizzati, riparazione e rimozione.
La distribuzione per ricerca pre-1.0 documenta il perimetro verificato e i
casi ancora da provare; non richiede di dichiarare completata la qualificazione
desktop estesa. I criteri sono nel
[protocollo degli installatori](ACCETTAZIONE_INSTALLATORI.md).

## Italiano e inglese

Il catalogo scientifico è già disponibile in italiano e inglese. La traduzione
completa deve estendersi a README, guide, note delle release, menu, aiuti
contestuali e messaggi NIPAT, oltre alla futura GUI. La lingua deve essere
selezionabile e conservata nelle preferenze.

Nomi dei comandi, opzioni CLI, chiavi JSON, identificatori dei passaggi e
colonne scientifiche rimangono stabili. Cambiare lingua non deve modificare
formule, parametri, separatori o risultati. I testi del client devono provenire
da cataloghi condivisi con la GUI; i messaggi strutturati del motore devono
essere traducibili. L'output originale di R e degli strumenti esterni resta
nei log nella lingua prodotta dai componenti.

Le guide tradotte devono riportare la versione descritta e offrire collegamenti
reciproci. I controlli automatici devono rilevare traduzioni e collegamenti
mancanti e confermare l'equivalenza delle richieste scientifiche fra le lingue.

## Incrementi successivi

La futura GUI userà gli stessi contratti del motore, il catalogo dei parametri
e i testi localizzati. La progettazione seguirà i risultati della valutazione
della CLI, con selezione dei file, configurazione delle analisi, visualizzazione
dei passaggi e consultazione dei risultati. La logica scientifica e di
orchestrazione conserverà una sola implementazione nell'immagine.

Parallelismo controllato fra attività indipendenti e ripresa delle esecuzioni
sono estensioni da valutare separatamente. Il primo richiede un limite
complessivo delle risorse, considerando anche il parallelismo interno a
DNPcall. La ripresa richiede verifiche affidabili di input, parametri, output
e identità del motore prima di riutilizzare un passaggio completato: dimensione
e data di modifica dei file da sole non dimostrano l'identità dei contenuti.

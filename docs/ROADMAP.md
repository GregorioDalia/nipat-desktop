# Piano di sviluppo

**NIPAT Experimental08 0.8.0a1** estende la portabilità a Windows 10 e macOS,
conservando le quattro analisi, i workflow automatici e il catalogo scientifico.
La distribuzione stabile NIPAT Desktop 0.7.2 rimane separata e disponibile
per la valutazione di dominio. L'esperimento ha identità, installer e cartelle
propri; non viene proposto come aggiornamento della stabile.
Ambito e requisiti sono nelle [note della versione](RELEASE_0.8.0a1.md)
e nella [guida per l'utilizzo](GUIDA_UTILIZZO.md).

Il core scientifico rimane in R. Preparazione ed esecuzione delle analisi
risiedono nell'immagine Linux autonoma, usata tramite WSL2 su Windows, Lima su macOS e Docker
Engine su Ubuntu. Il client gestisce interazione, configurazione, accesso ai
file locali, installazione e aggiornamenti. La GUI è un incremento successivo
alla valutazione della CLI.

## Funzionalità disponibili

| Area | Comportamento della 0.8.0a1 |
| --- | --- |
| Analisi singole | DNPcall, SNPcall, Contamination e CPI dal menu e dalla CLI diretta. |
| Composizioni DNPcall | DNPcall → Contamination, DNPcall → CPI e DNPcall → Contamination e CPI. |
| SNPcall | Passaggi indipendenti sui BAM delle composizioni oppure batch da BAM o pileup. |
| Campioni e coppie | Ruoli cfDNA materno/paterno assegnati esplicitamente; campioni condivisi elaborati una sola volta e associazioni conservate nei risultati. |
| Parametri | Opzioni pubbliche R esposte o adattate da NIPAT; catalogo italiano/inglese di parametri, regole interne e preparazione. |
| Esecuzione | Un piano in un container, ordine sequenziale, arresto su errore o annullamento, limiti facoltativi di CPU/memoria/processi e risultati distinti per passaggio. |
| Validazione dei dati | Controlli Python condivisi prima di R, copie dei pannelli normalizzate, risultati verificati e avvisi numerici consultabili. |
| Provenienza e diagnosi | Checksum integrali facoltativi degli input, consultazione dei run incompleti e arresto dei soli container identificati. |
| Manutenzione Windows | Inventario dello spazio, rimozione selettiva di componenti precedenti verificati e ripresa della preparazione della versione installata. |
| Interazione | Campi modificabili, configurazione persistente, annullamento globale, indicazioni contestuali e navigazione testuale alternativa alle frecce. |
| Distribuzione | Esperimento Windows 10/11 e macOS Intel/Apple Silicon, installatori distinti e immagine scientifica AMD64 comune; aggiornamenti stabili esclusi. |

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

## Qualificazione della portabilità

La CI estende le prove del client a macOS e verifica le decisioni del bootstrap
Windows per build, architettura e stato WSL. Il confezionamento Mac viene
verificato per entrambe le architetture. Le regressioni scientifiche continuano
su Linux; una prova Lima reale è distinta dal controllo del client su runner
macOS ospitati.

Le prove da raccogliere sull'esperimento sono installazione Windows 10 con e
senza WSL pronto, ripresa dopo riavvio, avvio su Windows 11, prima installazione
e riapertura su Mac Intel/Apple Silicon, percorsi con spazi, accesso ai file,
interruzione di un calcolo e conservazione dei risultati. Rosetta richiede
confronti numerici e osservazione dei tempi e delle risorse sui due tipi di Mac.
Una casella ancora da provare resta esplicita; non impedisce di distribuire
un esperimento chiaramente identificato, né viene presentata come superata.

La documentazione deve identificare i pacchetti effettivamente costruiti e
separare test simulati, runtime reali e osservazioni sui computer dei ricercatori.
L'eventuale promozione a distribuzione generale dipenderà da queste evidenze.

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

Il catalogo scientifico è già disponibile in italiano e inglese. Un catalogo
condiviso di messaggi supporta anche le nuove risposte della diagnostica dei
run, con `--lang it|en`; non cambia la lingua del menu generale. La traduzione
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

La distribuzione transazionale con attivazione della versione candidata e
ripristino automatico completo della precedente richiede una progettazione
dedicata. I backup selettivi e la ripresa del setup conservano informazioni
utili, ma non implementano tale comportamento. La manutenzione disponibile
ripara la preparazione della versione installata; non è un rollback.

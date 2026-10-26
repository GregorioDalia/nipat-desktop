# NIPAT Desktop 0.7.1

NIPAT Desktop 0.7.1 è una distribuzione per ricerca destinata alla valutazione
delle esperte di dominio. Offre le quattro analisi scientifiche, workflow
automatici e un catalogo delle impostazioni tramite menu testuale e CLI diretta.
Non include una GUI grafica. Gli algoritmi R restano il core scientifico;
la distribuzione non attesta una validazione clinica o scientifica generale.

Gli installatori e le evidenze della versione sono disponibili nella pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
La [guida per l'utilizzo](GUIDA_UTILIZZO.md) descrive input, parametri e risultati;
la [scheda di validazione](VALIDAZIONE.md) permette di registrare gli esiti
delle prove e le eventuali difficoltà.

## Installazione

| Piattaforma | File da scaricare | Esecuzione |
| --- | --- | --- |
| Windows 11 x64 | `NIPAT-Setup.exe` | Doppio clic per installare, poi collegamento **NIPAT Desktop**. WSL2 con distribuzione dedicata e Docker Engine interno. |
| Ubuntu 24.04 LTS x86_64 | `nipat-desktop_0.7.1_amd64.deb` | Installazione con APT, poi collegamento **NIPAT Desktop** o comando `nipat`. Docker Engine locale e Compose v2. |

Entrambi i pacchetti incorporano lo stesso archivio scientifico, con R,
samtools, dipendenze, script e gestione dei workflow. Non occorre scaricare
o spostare archivi separati. Windows include Python portabile; l'attivazione
di WSL2 può richiedere autorizzazione amministrativa, Internet e riavvio.
Su Ubuntu APT installa le dipendenze mancanti; l'accesso dell'account a Docker
richiede autorizzazione amministrativa distinta. NIPAT non va eseguito come root.

L'installazione aggiorna l'applicazione **NIPAT Desktop** già presente,
conservando dati, risultati e preferenze. I risultati già prodotti rimangono
associati alla versione che li ha generati. Requisiti e procedure sono nelle
guide [Windows](INSTALLATORE_WINDOWS.md) e [Ubuntu](INSTALLATORE_LINUX.md).
Il pacchetto Windows non dispone di una firma Authenticode NIPAT; eventuali
blocchi di download o esecuzione devono essere documentati sul dispositivo.

## Analisi e workflow

Le voci **1–4** avviano DNPcall, SNPcall, Contamination e CPI singolarmente.
La voce **W — Workflow automatici** offre:

| Scelta | Sequenza | Input specifici |
| --- | --- | --- |
| W → 1 | DNPcall → Contamination | Uno o più BAM, FASTA e pannello DNP; pannello Contamination uguale o distinto. |
| W → 2 | DNPcall → CPI | Coppie di BAM cfDNA materno/paterno con ruoli noti, frequenze di popolazione e scelta dei siti CPI. |
| W → 3 | DNPcall → Contamination e CPI | Input delle due analisi successive, che consumano le stesse tabelle DNPcall. |
| W → 4 | SNPcall su più campioni | BAM con FASTA oppure pileup compatibili, con un pannello SNP comune. |

SNPcall può essere aggiunto anche ai primi tre workflow sugli stessi BAM,
con un pannello SNP esplicito. È un'analisi indipendente: i suoi risultati
non alimentano Contamination o CPI. Contamination non modifica i conteggi
DNPcall e non filtra automaticamente i campioni del CPI.

Una sola conferma avvia il piano nel container scientifico. I passaggi sono
sequenziali; un errore o un annullamento impedisce l'avvio dei rimanenti.
Ogni fase conserva input preparati, risultati, log e stato. I campioni
condivisi fra coppie vengono elaborati una sola volta, conservando ruoli e
associazioni. Non è prevista la ripresa automatica dei run interrotti.

## Interazione e trasparenza

Il menu distingue analisi singole, workflow automatici e strumenti. La
navigazione a frecce si adatta al ridimensionamento della finestra; quando
non è utilizzabile, un messaggio spiega il passaggio alla selezione testuale.
Numeri e lettere delle voci, inclusa **W**, restano disponibili.

Le indicazioni dei campi chiariscono:

- **File FASTA di riferimento:** selezionare il file delle sequenze, non i
  suoi indici `.fai` o `.gzi`. La selezione di un indice produce una correzione
  esplicita, senza sostituire automaticamente il file scelto.
- **Pannello DNP:** contiene posizioni e alleli da analizzare; `DNP_list.txt`
  è un nome di esempio, non un nome imposto dal programma.
- **Percorsi relativi:** sono risolti rispetto alla cartella corrente mostrata
  prima del campo, non automaticamente rispetto alla cartella configurata come
  **Dati**. Le voci di una bamlist restano relative alla cartella della lista.
- **ID coppia:** è un'etichetta scelta dall'utente, come `Coppia01`, per
  riconoscere l'associazione fra due campioni con ruoli noti. Non è un parametro
  scientifico né un nome che debba coincidere con quello dei BAM.

Per tornare al menu principale, digitare `:annulla` e premere Invio nei campi
testuali, oppure premere Ctrl+C anche durante il calcolo. NIPAT tenta di arrestare il container prima
del ritorno e segnala eventuali arresti non confermati. Log e output parziali
restano disponibili da **Ultima esecuzione**; le modifiche non salvate alle
preferenze vengono scartate. **0 — Esci** nel menu principale chiude la sessione.

Il [catalogo scientifico](CATALOGO_SCIENTIFICO.md), consultabile da **Guida e
informazioni** o con `nipat parameters`, distingue opzioni pubbliche R,
regole interne e preparazione. Il catalogo è disponibile in italiano e
inglese; la traduzione completa dell'applicazione e delle guide è prevista
nel [piano di sviluppo](ROADMAP.md).

## Verifiche e ambito della distribuzione

La pubblicazione associa i pacchetti al commit compilato, alla build GitHub
Actions e ai checksum. Il record di accettazione e le evidenze automatiche
identificano i controlli applicabili agli installatori esatti, secondo il
[protocollo di distribuzione per ricerca](ACCETTAZIONE_INSTALLATORI.md).

Le verifiche automatiche comprendono test Windows/Linux del client,
regressioni numeriche reali di R e samtools, composizioni e analisi separate,
identità dei campioni, propagazione dei parametri, annullamento e conservazione
dei risultati. La build prova il client Windows preparato con Python portabile
e il pacchetto Ubuntu installato. Questi livelli di verifica sono descritti
in [CI_CD.md](CI_CD.md) e non sono equivalenti a un collaudo completo di tutti
i desktop destinatari.

Il riferimento manuale Windows è la build 0.7.0a1 del commit
`1b601081a4aff9efe1806c921fd7ac963feea7b7`: sul sistema con WSL2 è stata
eseguita la composizione DNPcall → Contamination su un BAM reale. Le tabelle
mostrate hanno riprodotto i conteggi e i genotipi delle esecuzioni separate
per 11 siti DNP; Contamination ha mantenuto 10 siti, con media e deviazione
standard pari a zero. Questa prova verifica il caso osservato e non dimostra
biologicamente l'assenza di contaminazione o la validità generale del metodo.

Il riferimento precedente resta distinto dal nuovo installatore 0.7.1.
Il controllo di pubblicazione confronta i sorgenti scientifici e del runtime
e richiede la revisione esplicita delle modifiche del client e della
preparazione dei pacchetti. Non attribuisce al nuovo EXE una prova manuale
non eseguita. La valutazione sui computer delle ricercatrici, le prove con
più campioni e le analisi CPI su dati di dominio costituiscono la campagna
di accettazione di questa versione.

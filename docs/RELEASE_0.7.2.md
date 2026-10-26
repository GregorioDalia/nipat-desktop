# NIPAT Desktop 0.7.2

NIPAT Desktop esegue DNPcall, SNPcall, Contamination e CPI attraverso un
menu testuale guidato e comandi riproducibili. I workflow automatici collegano
le analisi compatibili, conservando input, parametri, stati, log e risultati
di ogni passaggio. Il core scientifico è composto dagli script R distribuiti
nell'immagine autonoma.

## Pacchetti e utilizzo

| Piattaforma | Pacchetto | Ambiente |
| --- | --- | --- |
| Windows 11 x64 | `NIPAT-Setup.exe` | Python incluso, distribuzione WSL2 dedicata e Docker Engine gestito da NIPAT. |
| Ubuntu 24.04 LTS x86_64 | `nipat-desktop_0.7.2_amd64.deb` | Python 3.12, Docker Engine locale e Compose v2 accessibili all'utente. |

Per Windows scaricare l'unico EXE e avviarlo con doppio clic dal proprio
account. Il setup consente di scegliere le cartelle e completa la preparazione
del motore; gli avvii successivi usano il collegamento **NIPAT Desktop**.
L'attivazione di WSL2 può richiedere autorizzazione amministrativa, Internet
e riavvio. Il pacchetto Windows non è firmato digitalmente da NIPAT:
le protezioni del dispositivo possono limitarne l'installazione o l'avvio.

Su Ubuntu installare il `.deb` tramite APT, che risolve le dipendenze dai
repository configurati. L'autorizzazione dell'utente a Docker è distinta
dall'installazione dei pacchetti. Il collegamento **NIPAT Desktop** o il
comando `nipat` apre il menu.

La [guida per l'utilizzo](GUIDA_UTILIZZO.md) descrive preparazione, formati,
parametri e consultazione dei risultati. La [distribuzione](DISTRIBUZIONE.md)
specifica requisiti e gestione delle installazioni.

## Controlli e affidabilità

Il livello Python condiviso verifica gli input dei quattro script prima
di R e controlla gli output delle analisi singole e dei workflow. I pannelli
SNP e DNP vengono normalizzati in copie di lavoro, conservando intatti gli
originali. Le segnalazioni distinguono errori di formato, vincoli sui dati
e informazioni di qualità da esaminare. Il
[contratto degli input](INPUT_VALIDATION.md) documenta il perimetro dei controlli.

Il menu rende consultabili anche le esecuzioni fallite. L'annullamento torna
al menu principale dopo la procedura di arresto; log e risultati parziali
rimangono disponibili. I controlli di provenienza e delle esecuzioni incomplete
sono descritti in [ESECUZIONI.md](ESECUZIONI.md).
La verifica SHA-256 integrale degli input è selezionabile con
`--input-hashes full`; il comportamento predefinito `auto` applica SHA-256
ai file fino a 16 MiB e registra metadati per quelli più grandi. CPU, memoria
e numero di processi del container possono essere limitati senza modificare
i parametri R. `runs inspect` consulta i run incompleti; `runs stop` richiede
conferma e riconosce l'identità del container prima di arrestarlo.

Su Windows, **Guida e informazioni → Installazione e spazio** mostra
ambienti e cache verificati, consente la rimozione selettiva di componenti
precedenti e la ripresa della preparazione della versione installata.
Ambiente attivo, precedente più recente, dati e risultati restano protetti.
La funzione non ripristina una versione precedente. Il componente WSL possiede
un'identità separata dall'applicazione, così gli archivi pubblicati possono
essere riutilizzati quando sorgenti e dipendenze risolte coincidono.

## Ambito della distribuzione

La versione è destinata alla ricerca e alla valutazione di dominio.
Le regressioni automatiche verificano casi sintetici e risultati attesi,
separatamente dalle prove degli installatori e dai test sui campioni reali.
La copertura è descritta in [CI/CD](CI_CD.md) e il record associato ai
pacchetti identifica i file accettati e le prove effettivamente disponibili.
Le evidenze pubblicate comprendono inventari dei componenti, rapporto e
archivio delle verifiche sintetiche e prova di aggiornamento Ubuntu dalla
0.7.1. Le nuove release proteggono asset e tag pubblicati tramite l'immutabilità
GitHub. La revisione distingue la prova manuale storica della piattaforma dai
controlli della candidata: non dichiara eseguita un'installazione manuale
Windows della 0.7.2. I sorgenti R sono invariati; le modifiche agli adattatori
Python e agli altri componenti sono verificate separatamente.
La [scheda di validazione](VALIDAZIONE.md) permette di registrare ulteriori
prove e segnalazioni riproducibili.

Non sono presenti una GUI, la ripresa automatica dei run o il parallelismo
fra i passaggi di un piano. Resta disponibile il parallelismo interno DNPcall.
L'interfaccia generale è in italiano; il catalogo scientifico è consultabile
anche in inglese; la diagnostica `runs` offre messaggi italiani e inglesi.
La traduzione completa dell'interfaccia non è inclusa. Un esito tecnico `succeeded` non equivale alla validazione
scientifica di un campione o di uno scenario d'impiego.

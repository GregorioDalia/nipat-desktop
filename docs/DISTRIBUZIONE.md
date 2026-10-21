# Distribuzione tramite GitHub

## Pre-release 0.4.1: due pacchetti per le prove di dominio

[NIPAT 0.4.1](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.4.1) identifica la versione da
condividere per il testing di dominio, con l'interfaccia guidata e il launcher
Windows. È una pre-release, non una dichiarazione di validazione scientifica
completa. Le [note della versione](RELEASE_0.4.1.md) ne precisano il perimetro.

La release offre due modalità di distribuzione:

| Asset | Contenuto e prerequisiti | Avvio |
| --- | --- | --- |
| [NIPAT-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-Setup.exe) | Un solo file con applicazione, Python portabile, ambiente Linux interno e runtime scientifico incorporati. Il perimetro iniziale resta Windows 11 x64 con WSL2 funzionante. | Doppio clic per installare; poi icona **NIPAT** che avvia `NIPAT.exe`. |
| [NIPAT-DockerDesktop-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-DockerDesktop-Setup.exe) | Un solo installatore con applicazione, Python portabile e runtime scientifico. Richiede Docker Desktop installato e avviato con container Linux. | Doppio clic per installare; poi icona **NIPAT (Docker Desktop)**, con preparazione automatica prima del menu. |

`NIPAT.exe` apre la CLI guidata senza richiedere un terminale già aperto.
Entrambi i percorsi richiedono un solo EXE: l'utilizzatore non deve estrarre
ZIP, spostare archivi o preparare cartelle `assets`. Nel percorso Docker
Desktop non occorre eseguire `1_SETUP.cmd`: l'applicazione prepara l'ambiente
e gli autotest prima del menu e riprende dalla stessa icona dopo un errore.
Il setup conserva automaticamente i componenti necessari alla ripresa.
I due installatori usano lo stesso launcher e i sorgenti dello
stesso commit. Il pacchetto Docker riutilizza esattamente l'archivio scientifico
esportato per WSL, identificato da dimensione e SHA-256; non lo ricostruisce sul
PC dell'utilizzatore. L'identificativo locale dell'immagine viene risolto dopo
l'importazione, perché motori diversi possono identificare oggetti differenti.

Gli artefatti di revisione restano separati dalla pubblicazione. La procedura
in [.github/RELEASE.md](../.github/RELEASE.md) verifica commit, manifest,
contenuto dei pacchetti e checksum prima di pubblicare una pre-release.
Una build di pull request serve alla revisione; il commit scelto deve essere
integrato e costruito con la procedura ammessa per la pubblicazione.
Non sostituire gli asset di una release già distribuita.

Per ciascuna installazione, registrare la prova del pacchetto su Windows:
completamento del setup e degli autotest, apertura di `NIPAT.exe`, uso dell'interfaccia e almeno
un'esecuzione reale. La validazione di dominio utilizza la
[scheda dedicata](VALIDAZIONE.md), con risultati attesi e osservati.
Nel percorso WSL l'aggiornamento riguarda l'ambiente Linux interno usato da NIPAT per le analisi:
non richiede una manutenzione manuale di Windows o WSL. Il setup prepara
un ambiente separato quando cambia il rootfs. Conserva quello precedente e
le cartelle dati/risultati, verifica il nuovo ambiente con `doctor` e `self-test`, quindi
attiva la nuova configurazione. La ripetizione del setup riprende lo stesso
target; non occorre eliminare distribuzioni o sovrascrivere la configurazione.
Se il setup non termina, la nuova applicazione resta bloccata: i vecchi file
applicativi non vengono ripristinati automaticamente. Le prove reali di prima
installazione e aggiornamento su Windows devono ancora essere registrate per
il pacchetto finale, oltre ai controlli automatici dell'implementazione.

Il codice originale NIPAT è distribuito con licenza GPL-3.0-or-later; le licenze
e le attribuzioni dei componenti inclusi sono conservate in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md) e nei rispettivi percorsi.

## Versione precedente: 0.4.0

La [pre-release 0.4.0](RELEASE_0.4.0.md) prevedeva lo ZIP Docker Desktop e un
passaggio separato con `1_SETUP.cmd`. Quella procedura resta documentata per
la relativa versione; il normale percorso `0.4.1` usa gli EXE sopra indicati.

## Versione precedente: installatore 0.3.0a1

Il percorso pubblicato prepara **NIPAT-Setup.exe** attraverso GitHub Actions.
L’installatore contiene l’applicazione e un manifest con gli hash dei due
asset della stessa versione: ambiente WSL dedicato e immagine scientifica.
Li scarica dalla release GitHub e li verifica prima di importarli.
Python portabile viene verificato con il suo hash. Non occorre che chi
utilizza il programma installi o configuri Docker Desktop.

Le dipendenze R vengono risolte in fase di costruzione del runtime su GitHub;
gli autotest vengono eseguiti sull’immagine risultante. L’immagine viene quindi
esportata e identificata dal suo ID: ogni installazione della stessa release
riceve gli stessi byte. Una ricompilazione futura può produrre un’immagine
diversa e richiede una nuova verifica. Non modificare gli asset di una release
già distribuita.

Il workflow produce artefatti da verificare, senza pubblicare automaticamente
una release. I passaggi di compilazione, prova su Windows e pubblicazione
sono descritti in [INSTALLATORE_WINDOWS.md](INSTALLATORE_WINDOWS.md).
La [guida per l’utilizzo](GUIDA_UTILIZZO.md) descrive l’avvio e gli input.

La prima consegna `0.3.0a1` è una **pre-release per prove di dominio su Windows
11 x64 con WSL2 già funzionante**. L'utilizzatore scarica soltanto l'EXE dalla
release e attende `NIPAT: ready`; Git e PyCharm non servono. L'attivazione
iniziale di WSL e la ripresa dopo riavvio Windows restano da verificare.
Le [note della pre-release](RELEASE_0.3.0a1.md) descrivono il perimetro e i limiti.

Il candidato corretto localmente ha completato setup, autotest, riavvio del
motore dopo arresto WSL e confronto DNPcall su un BAM reale. La build GitHub
`39581854492` ha poi superato i controlli anche nel motore effettivamente
distribuito. Sono evidenze distinte, dettagliate in
[INSTALLATORE_WINDOWS.md](INSTALLATORE_WINDOWS.md); non attestano la prima
installazione del nuovo EXE su un altro PC né una validazione di dominio completa.

## Evidenze della release precedente

La release `v0.2.0a2` identifica il commit
`70e944b5dcbf84954492798dc387e8d61134343c`. Si utilizza tramite archivio
sorgente, `1_SETUP.cmd` e `2_AVVIA.cmd`, con Docker Desktop già attivo.
I tag `v0.2.0a1` e `v0.2.0a2` restano invariati.

### Verifiche osservate il 20 ottobre 2026

Le prove riguardano la revisione locale `0.2.0a2` sul PC dello sviluppatore,
prima del commit e della nuova release. Non costituiscono una prova di
prima installazione su un PC diverso.

| Controllo | Esito osservato |
| --- | --- |
| Suite Python Windows | 100 test raccolti: 99 superati, uno saltato perché i collegamenti simbolici non erano disponibili. |
| Correzione degli import con Python portabile | Successiva esecuzione dei 34 test CLI, incluso il nuovo caso di regressione: tutti superati. Le due esecuzioni non equivalgono a una singola suite Windows da 101 test. |
| `1_SETUP.cmd` | Completato con Python 3.12.10 portabile e runtime Docker Linux disponibile. |
| Autotest numerici di base | Esempio SNPcall: 9 righe corrispondenti; CPI e Contamination: valori attesi, inclusi i casi senza siti informativi. |
| Input esterni | Quattro analisi Docker riuscite con input su un'altra unità, in percorsi contenenti spazi e caratteri speciali: SNPcall da pileup, Contamination da cartella, CPI con due cutoff e CPI ALL. Input originali invariati. |
| Menu e destinazione risultati | Scelta di una cartella tramite percorso relativo, ritorno al menu e uscita con codice 0. |
| DNPcall da BAM reale | Input esterni alla radice `data` configurata e risultati in una nuova radice: tutti gli 11 siti e le 17 colonne dell'output individuale coincidono con il run precedente, indipendentemente dall'ordine delle righe. Alias e BAM originale associati in `run.json`. |

I quattro gruppi di `self-test` comprendono sette analisi scientifiche; la prova
DNPcall è separata e non viene eseguita dal setup. Il confronto DNPcall usa un
risultato precedente dello stesso programma, non un riferimento indipendente.
Riguarda un solo campione: restano da provare con dati appropriati l'esecuzione
DNPcall con più campioni e parallela, l'equivalenza delle modalità di input e
gli altri casi scelti per la validazione. Le precedenti prove SNPcall da BAM non sono
state ripetute in questa revisione.

# NIPAT: stato del progetto e funzionamento

**Installatore pubblicato: CLI 0.3.0a1. Candidato in revisione: CLI 0.3.0a2.**
L'installatore è destinato alle prove di dominio su Windows 11 x64 con WSL2
funzionante; il nuovo candidato introduce la revisione dell'interfaccia testuale
e l'avvio con `NIPAT.exe` per entrambe le modalità di distribuzione.
NIPAT riunisce quattro analisi locali: Python gestisce file ed esecuzioni,
mentre gli script R di DNPcall e NEWPAT eseguono i calcoli con samtools in
Docker. La GUI verrà dopo la validazione della CLI.

| Analisi | Input disponibili | Risultati |
| --- | --- | --- |
| DNPcall | Uno o più BAM, anche tramite lista; FASTA indicizzato e pannello DNP | Conteggi, genotipi, riepiloghi e grafici. |
| SNPcall | BAM e FASTA indicizzato oppure pileup già pronto; lista SNP | Tabella dei conteggi SNP. |
| Contamination | Tabelle DNPcall scelte singolarmente o da una cartella; pannello di coordinate | Stima per sito e riepilogo per campione. |
| CPI | Tabelle materne/paterne, coppie e frequenze; tutti i siti, un pannello o più cutoff | Frazione fetale, CPI e grafici. |

## Dove siamo

La versione precedente ha corretto i problemi di compatibilità di DNPcall e
integrato gli aggiornamenti CPI e Contamination di NEWPAT acquisiti il
19 ottobre 2026. Le prove già svolte comprendono DNPcall e SNPcall su un
campione reale, il passaggio DNPcall → Contamination, l'esempio SNPcall degli
autori e casi sintetici CPI/Contamination. Sul PC Windows di sviluppo, per
`0.2.0a1`, sono stati superati 48 test Python, con un test saltato, e i tre
autotest numerici Docker.

La revisione `0.2.0a2` elimina il vincolo che imponeva input dentro progetto,
`data` o `runs` e rende disponibili nel menu tutte le modalità di input
supportate. Non cambia gli algoritmi R né i valori predefiniti scientifici.
Il 20 ottobre 2026 sono riusciti, sul PC Windows di sviluppo, setup, quattro
gruppi di autotest e scelta della cartella risultati. DNPcall con input esterni
ha riprodotto i precedenti 11 siti e tutte le 17 colonne di un BAM reale.
Gli [esiti dettagliati](docs/DISTRIBUZIONE.md) distinguono queste prove dalla
validazione di dominio e dall'installazione su un altro PC, ancora da svolgere.
La release pubblicata `v0.2.0a2` resta invariata. La revisione `0.3.0a1`
aggiunge un installatore che prepara WSL2 e Docker Engine in un ambiente
dedicato. Mantiene i quattro workflow e gli script scientifici esistenti.
Il 21 ottobre il candidato WSL corretto localmente ha completato setup e
autotest, riavviato il proprio motore dopo l'arresto di WSL e riprodotto
11 siti e le 11 colonne confrontate di conteggi/genotipi del BAM reale.
La successiva compilazione GitHub ha superato anche caricamento, esecuzione e
ricaricamento dell'immagine nel motore distribuito. Queste prove sono distinte
dalla prima installazione del nuovo EXE su un altro PC. Per la consegna attuale
si assume WSL2 già funzionante; attivazione iniziale e ripresa dopo riavvio
Windows restano da verificare. La validazione scientifica su altri casi è aperta.

Il candidato `0.3.0a2` introduce il banner NIPAT, il menu verticale, la
correzione degli input senza ricominciare la compilazione e un riepilogo da
confermare prima dell'avvio. La schermata finale permette di aprire risultati
e log e di consultare i metadati dell'esecuzione. Le nuove interazioni del
terminale sono da verificare manualmente su Windows; le prove delle versioni
precedenti non attestano questa revisione. Algoritmi, modalità di input e
parametri scientifici predefiniti restano quelli esistenti.
Il candidato prepara due pacchetti della stessa versione, con lo stesso
archivio scientifico verificato: installatore WSL e ZIP per Docker Desktop.
Entrambi aprono la CLI con doppio clic su `NIPAT.exe`. La consegna esterna
attenderà la pubblicazione del pacchetto finale con l'interfaccia più recente
verificata dal manutentore; l'installatore `0.3.0a1` non la contiene.

## Come si usa

Il canale di distribuzione è la pre-release GitHub `v0.3.0a1`. Scaricare
`NIPAT-Setup.exe` e avviarlo con doppio clic dal proprio account Windows.
La configurazione prepara Python, l'ambiente WSL dedicato, Docker Engine e
il runtime scientifico, poi esegue gli autotest. Attendere **`NIPAT: ready`**,
quindi aprire **NIPAT** dal menu Start. Non occorre installare Docker Desktop,
Python, R o samtools separatamente. Il primo download richiede Internet;
le analisi sono locali. Il caso senza WSL funzionante è fuori dal perimetro
di questa prima consegna per le prove di dominio.
Per la release già pubblicata `0.2.0a2` resta il percorso con archivio sorgente,
`1_SETUP.cmd`, `2_AVVIA.cmd` e Docker Desktop avviato.

Per il candidato `0.3.0a2`, il collegamento dell'installazione WSL avvia
`NIPAT.exe`. Il pacchetto Docker richiede invece di estrarre tutto lo ZIP,
aprire `1_SETUP.cmd` una volta con Docker Desktop attivo e poi `NIPAT.exe`.
Il menu non richiede di aprire PowerShell. Confermare **Avvia analisi** esegue
realmente gli script R e gli altri strumenti previsti dal workflow.
L'aggiornamento di un ambiente WSL NIPAT già presente richiede ancora una
procedura di migrazione; non è automatico.

Gli input possono restare nelle loro cartelle originali, anche su un'altra
unità locale accessibile al runtime. Il nuovo backend WSL non supporta
inizialmente condivisioni UNC o unità di rete. NIPAT rende disponibili al container i file
selezionati in sola lettura, senza copiare BAM e FASTA. Si può scegliere la
cartella dei risultati: ogni analisi crea un nuovo run, conserva i nomi
degli output scientifici e registra input, corrispondenze dei percorsi,
parametri ed esito in `run.json` e `execution.log`. I run esistenti non vengono
sovrascritti e i dati delle analisi restano sul computer.

I risultati si consultano nel file system: `output` contiene i risultati,
`work` gli intermedi. Nel candidato `0.3.0a2` si possono aprire queste cartelle
dalla schermata finale; **6 — Ultima esecuzione** richiama l'ultima analisi della
sessione corrente. Per concatenare analisi, selezionare gli output compatibili
del run precedente come input del successivo, ad esempio le tabelle individuali
DNPcall per Contamination. La CLI non concatena automaticamente i workflow.
La scelta della cartella risultati e il richiamo dell'ultima esecuzione valgono
per la sessione corrente; preferenze persistenti e cronologia completa sono
interventi successivi.

Per cominciare: [guida per l’utilizzo](docs/GUIDA_UTILIZZO.md).
Per riportare le prove: [scheda di validazione](docs/VALIDAZIONE.md).

Il codice originale NIPAT è open source con licenza
[GPL-3.0-or-later](LICENSE); i componenti inclusi conservano le proprie
[licenze e attribuzioni](THIRD_PARTY_NOTICES.md). La scelta della lingua
è prevista per una revisione successiva.

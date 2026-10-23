# NIPAT: stato del progetto e funzionamento

**Sviluppo CLI 0.5.0a1, non pubblicato; la versione per le prove di dominio resta 0.4.1.**
NIPAT riunisce quattro analisi locali in un'interfaccia testuale guidata.
Python gestisce gli input e le esecuzioni; gli script R di DNPcall e NEWPAT
eseguono i calcoli nel runtime scientifico, insieme a samtools.
Nella 0.5, preparazione degli input e calcolo dei quattro workflow avvengono
nell'immagine scientifica, che comprende anche gli script R invariati.
La disponibilità della 0.4.1 per il testing non equivale a validazione scientifica completa.

| Analisi | Input disponibili | Risultati |
| --- | --- | --- |
| DNPcall | Uno o più BAM, anche tramite lista; FASTA indicizzato e pannello DNP | Conteggi, genotipi, riepiloghi e grafici. |
| SNPcall | BAM e FASTA indicizzato oppure pileup già pronto; lista SNP | Tabella dei conteggi SNP. |
| Contamination | Tabelle DNPcall scelte singolarmente o da una cartella; pannello di coordinate | Stima per sito e riepilogo per campione. |
| CPI | Tabelle materne/paterne, coppie e frequenze; tutti i siti, un pannello o più cutoff | Frazione fetale, CPI e grafici. |

## Cosa è integrato

Sono presenti gli aggiornamenti CPI e Contamination di NEWPAT acquisiti il
19 ottobre 2026 e le correzioni di compatibilità DNPcall documentate nel progetto.
Gli input possono essere scelti nelle proprie cartelle; le modalità di analisi
sono disponibili sia dal menu sia dalla riga di comando.
Il menu include indicazioni contestuali, controllo degli input, correzione dei
campi e un riepilogo da confermare prima di avviare gli script scientifici.
Al termine si possono aprire risultati, intermedi e log e consultare i metadati
dell'esecuzione. La GUI grafica resta un intervento successivo.

La versione `0.4.1` distribuisce la stessa interfaccia e lo stesso runtime in
due installatori Windows: ambiente WSL dedicato oppure Docker Desktop. Per queste prove
si assume WSL2 funzionante. Registrare separatamente installazione e analisi
per ciascun pacchetto. Le prove precedenti e i relativi limiti restano nella
[documentazione delle verifiche](docs/DISTRIBUZIONE.md).

## Separazione della 0.5 in sviluppo

Il candidato Windows usa il nome **NIPAT 0.5 Preview**, una cartella applicativa
propria e un ambiente WSL distinto. Configurazione, dati, risultati predefiniti,
cache e ripresa del setup sono separati dalla 0.4.1. Gli aggiornamenti successivi
dello stesso canale Preview possono conservare le proprie cartelle configurate.
Il componente WSL di Windows rimane un prerequisito comune del sistema.

La 0.5 non è ancora da distribuire: restano la verifica dell'installazione reale,
la rimozione del percorso Docker Desktop e l'installer Ubuntu 24.04 x86_64.
La GUI non rientra nella 0.5. Il [piano di sviluppo](docs/PIANO_0.5.md) distingue
l'implementazione dai controlli effettivamente conclusi.

## Come si usa la versione pubblicata 0.4.1

Il percorso principale è un unico [NIPAT-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-Setup.exe):
scaricarlo dalla [pre-release v0.4.1](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.4.1),
fare doppio clic e attendere **`NIPAT: ready`**. Poi aprire l'icona **NIPAT**
dal menu Start o dal desktop. L'installatore contiene i componenti per le
analisi e li prepara automaticamente: non occorre organizzare archivi o
installare separatamente Python, R, samtools o Docker Desktop.

L'ambiente Linux interno viene eseguito tramite WSL2. Il perimetro iniziale
assume WSL2 funzionante; la sua attivazione su Windows può richiedere Internet,
autorizzazioni e riavvio e resta una prova separata. Gli aggiornamenti
all'ambiente interno sono gestiti dal setup NIPAT, mantenendo dati e risultati.
Se la preparazione fallisce, si riprende dal menu Start; la nuova applicazione
resta bloccata fino al completamento.

Chi usa già Docker Desktop con container Linux può scaricare
[NIPAT-DockerDesktop-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-DockerDesktop-Setup.exe),
installarlo con doppio clic e aprire l'icona **NIPAT (Docker Desktop)**. La
preparazione e gli autotest avvengono automaticamente prima del menu; in caso
di errore si riprova dalla stessa icona. Non occorre avviare script separati.
La [procedura di prima prova](docs/VALIDAZIONE.md#prima-prova-con-docker-desktop)
spiega come verificare anche un'analisi reale. In entrambi i pacchetti,
**Avvia analisi** esegue realmente gli script R e gli strumenti del workflow.

Gli input rimangono nelle cartelle originali e vengono montati in sola lettura.
Per WSL sono supportati dischi locali fissi, non condivisioni UNC o unità di rete.
Si può scegliere la cartella dei risultati: ogni analisi crea un nuovo run con
`output`, `work`, `run.json` ed `execution.log`, senza sovrascrivere i run esistenti.
Per concatenare analisi si scelgono gli output compatibili del run precedente
come input del successivo, ad esempio le tabelle individuali DNPcall per
Contamination. La CLI non concatena automaticamente i workflow.
La cartella risultati e **6 — Ultima esecuzione** valgono per la sessione corrente.

La [guida per l’utilizzo](docs/GUIDA_UTILIZZO.md) descrive input e menu;
la [scheda di validazione](docs/VALIDAZIONE.md) raccoglie risultati attesi e osservati.
Il codice originale NIPAT è distribuito con licenza [GPL-3.0-or-later](LICENSE);
i componenti inclusi conservano le proprie [licenze e attribuzioni](THIRD_PARTY_NOTICES.md).
La scelta della lingua è prevista per una revisione successiva.

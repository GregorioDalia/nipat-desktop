# NIPAT in sintesi

**NIPAT 0.5.0a1** è un'applicazione locale per eseguire quattro workflow
scientifici da un menu testuale guidato o dalla riga di comando. Questa
versione non è ancora pubblicata e non include una GUI grafica.

| Workflow | Funzione |
| --- | --- |
| DNPcall | Conteggi e genotipi di dinucleotidi da uno o più BAM. |
| SNPcall | Conteggi SNP da BAM o pileup con nomi delle letture. |
| Contamination | Stima della contaminazione da tabelle di conteggi compatibili. |
| CPI | Stima della frazione fetale e calcolo dell'indice di paternità. |

Il client Python gestisce selezione degli input, parametri e registrazione
delle esecuzioni. Un'immagine scientifica autonoma contiene la preparazione
degli input, gli script R, samtools e le dipendenze. Su Windows l'immagine
viene eseguita in un ambiente WSL2 dedicato; su Ubuntu tramite Docker Engine
nativo. I calcoli e i dati rimangono sul computer.

Il pacchetto Windows è predisposto come un singolo `NIPAT-Setup.exe`, con
avvio tramite l'icona **NIPAT 0.5 Preview**. Non richiede l'installazione
separata degli strumenti scientifici. Il pacchetto non è ancora pubblicato;
per Ubuntu 24.04 x86_64 è disponibile il percorso da sorgenti e non è presente
un installatore Linux. WSL2 su Windows e Docker Engine su Linux costituiscono
l'ambiente necessario alle analisi.

Per utilizzare NIPAT si sceglie il workflow, si indicano file e parametri e
si conferma il riepilogo con **Avvia analisi**. Le indicazioni nei campi
spiegano formati, valori predefiniti e comandi di navigazione. Gli input
possono restare nelle cartelle originali e vengono letti senza modificarli.
Su Windows sono supportati dischi locali fissi.

Ogni analisi crea un nuovo run con risultati in `output`, intermedi conservati
in `work`, metadati in `run.json` e messaggi in `execution.log`. Le cartelle
esistenti non vengono sovrascritte. Per concatenare analisi si selezionano i
risultati compatibili del run precedente, ad esempio le tabelle individuali
DNPcall come input di Contamination.

La verifica degli strumenti controlla l'ambiente di esecuzione; gli autotest
confrontano casi noti. Il completamento di un run non sostituisce la
validazione scientifica sui campioni e sullo scenario d'uso.

La [guida per l'utilizzo](docs/GUIDA_UTILIZZO.md) descrive la procedura operativa;
la [scheda di validazione](docs/VALIDAZIONE.md) aiuta a documentare le prove.
Il codice originale è distribuito con licenza [GPL-3.0-or-later](LICENSE).

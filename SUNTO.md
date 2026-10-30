# NIPAT in sintesi

**NIPAT Experimental08 0.8.0a1** è un'applicazione locale per eseguire quattro workflow
scientifici da un menu testuale guidato o dalla riga di comando. Le analisi
possono essere avviate singolarmente oppure nei workflow automatici
**DNPcall → Contamination**, **DNPcall → CPI** e **DNPcall → Contamination e CPI**.
SNPcall può essere aggiunto sugli stessi BAM o eseguito da solo su più BAM
o pileup. Una sola conferma avvia tutti i passaggi selezionati.
Questa versione non include una GUI grafica.

Il catalogo scientifico consultabile dal menu o con `nipat parameters`
descrive in italiano e inglese le opzioni R, le regole interne e la
preparazione degli input. Il motore convalida i piani concatenati e ne
esegue le quattro analisi in sequenza, rispettandone le dipendenze. SNPcall
rimane un'attività indipendente anche quando appartiene allo stesso piano.
La versione è un esperimento di portabilità separato da NIPAT Desktop 0.7.2,
che rimane la distribuzione stabile. Windows 10 e macOS sono nuovi obiettivi
di collaudo, non piattaforme già qualificate. Le
[note della versione](docs/RELEASE_0.8.0a1.md) distinguono funzionalità,
pacchetti e verifiche ancora da eseguire.

| Workflow | Funzione |
| --- | --- |
| DNPcall | Conteggi e genotipi di dinucleotidi da uno o più BAM. |
| SNPcall | Conteggi SNP da BAM o pileup con nomi delle letture. |
| Contamination | Stima della contaminazione da tabelle di conteggi compatibili. |
| CPI | Stima della frazione fetale e calcolo dell'indice di paternità. |

Il client Python gestisce selezione degli input, parametri e registrazione
delle esecuzioni. Un'immagine scientifica autonoma contiene la preparazione
degli input, l'esecuzione dei piani, gli script R, samtools e le dipendenze. Su Windows l'immagine
viene eseguita in un ambiente WSL2 dedicato; su macOS in una VM Lima.
Su Apple Silicon Rosetta esegue la medesima immagine Linux AMD64.
Il codice R non viene riscritto. I calcoli e i dati rimangono sul computer.

Prima di R, il motore Python controlla formato e contenuto degli input.
I pannelli vengono normalizzati in copie di lavoro; conteggi e frequenze
incompatibili con il formato sono rifiutati. Le incongruenze che richiedono
una valutazione scientifica vengono segnalate senza correggere i dati.
Il menu mostra gli avvisi anche dopo un completamento tecnico riuscito.
Checksum integrali degli input e limiti di risorse sono configurabili;
le esecuzioni incomplete possono essere consultate senza riscrivere i risultati.

Windows 10 22H2 x64 (build 19045) e Windows 11 x64 usano un singolo
`NIPAT-Setup.exe`. Il setup rileva WSL, prepara i componenti mancanti e può
richiedere Internet, autorizzazione amministrativa e riavvio. Il collegamento
**NIPAT Experimental08** apre il menu. Applicazione, ambiente WSL, cache,
dati e risultati hanno cartelle configurabili, separate dal canale stabile.

macOS 14 o successivo usa un `.pkg` specifico per Intel oppure Apple Silicon.
L'applicazione **NIPAT Experimental08** si apre da Applicazioni e avvia la CLI
nel Terminale. Python e Lima sono inclusi; il primo avvio richiede Internet
per preparare la VM e il motore. Non occorre installare Homebrew o Docker Desktop.
Le protezioni di Windows e macOS possono bloccare i pacchetti non firmati;
questa distribuzione sperimentale non promette un avvio autorizzato su ogni PC.

Gli installatori provengono dalla build sperimentale del repository o da una
pre-release dedicata. Usano l'identità `experimental08`; non sostituiscono
NIPAT Desktop e non vengono proposti dal suo aggiornamento automatico.
Il pacchetto Ubuntu stabile rimane 0.7.2; su Linux la 0.8 è utilizzabile
per sviluppo da sorgenti con Docker Engine locale.

Per utilizzare NIPAT si sceglie il workflow, si indicano file e parametri e
si conferma il riepilogo con **Avvia analisi**. Le indicazioni nei campi
spiegano formati, valori predefiniti e comandi di navigazione. **Configura**
conserva cartelle e impostazioni del menu fra gli avvii; ogni analisi consente
di correggere i valori proposti. Campioni, coppie e nome del run si scelgono
sempre per la singola analisi. **Guida e informazioni** e **Verifica ambiente**
sono funzioni separate. **W — Workflow automatici** configura le analisi
successive a DNPcall e SNPcall su più campioni; per CPI si indicano
esplicitamente le coppie e i ruoli cfDNA materno e paterno. Le preferenze non cambiano la CLI diretta. Gli input
possono restare nelle cartelle originali e vengono letti senza modificarli.
Su Windows sono supportati dischi locali fissi. I percorsi relativi partono
dalla cartella corrente indicata nell'interfaccia, non automaticamente da
**Dati**. Per il riferimento si sceglie il file FASTA, accompagnato dai suoi indici.

`:annulla` nei campi testuali e Ctrl+C anche durante il calcolo riportano al
menu principale. Durante un'analisi NIPAT esegue prima la procedura di arresto,
conservando log e risultati già prodotti. Le impostazioni non salvate vengono
scartate; quelle già salvate restano disponibili.

La verifica degli aggiornamenti è disabilitata nel profilo sperimentale.
Per provare una nuova build si scarica esplicitamente il relativo installatore,
controllando versione e commit nelle sue note.

Ogni analisi crea un nuovo run con risultati in `output`, intermedi conservati
in `work`, metadati in `run.json` e messaggi in `execution.log`. Le cartelle
esistenti non vengono sovrascritte. Il workflow automatico conserva in
`output/workflow` lo stato complessivo, gli output e i log di ogni passaggio.
DNPcall produce una volta sola le tabelle individuali utilizzate da
Contamination e CPI. Un campione condiviso fra coppie viene elaborato una sola
volta, mantenendo il ruolo dichiarato. Se un passaggio fallisce, quelli
successivi non vengono avviati. Contamination non modifica i conteggi DNPcall
e non produce tabelle «decontaminate».

CPI richiede frequenze di popolazione appropriate e può usare tutti i siti
disponibili o pannelli selezionati. I risultati comprendono un CSV riepilogativo,
un PDF per coppia e un PDF complessivo; il record conserva l'associazione
con gli identificatori delle coppie. SNPcall usa un proprio pannello e produce
una tabella SNP per campione, che non è un input diretto di Contamination o
CPI. In modalità BAM conserva anche BED, pileup e log della preparazione;
i pileup importati vengono letti senza rigenerarli.

La verifica degli strumenti controlla l'ambiente di esecuzione; gli autotest
confrontano casi noti. Il completamento di un run non sostituisce la
validazione scientifica sui campioni e sullo scenario d'uso.

La [guida per l'utilizzo](docs/GUIDA_UTILIZZO.md) descrive la procedura operativa;
la [scheda di validazione](docs/VALIDAZIONE.md) aiuta a documentare le prove.
Il [piano di sviluppo](docs/ROADMAP.md) descrive la valutazione dei workflow,
il supporto italiano/inglese e la futura interfaccia grafica.
Il codice originale è distribuito con licenza [GPL-3.0-or-later](LICENSE).

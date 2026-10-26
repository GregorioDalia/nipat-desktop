# NIPAT in sintesi

**NIPAT Desktop 0.7.0a1, in sviluppo**, è un'applicazione locale per eseguire quattro workflow
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
La release ufficiale per l'installazione rimane la 0.6.0.
Le [note della candidata 0.7.0a1](docs/RELEASE_0.7.0a1.md) descrivono
installazione di verifica e collaudo dei workflow automatici.

| Workflow | Funzione |
| --- | --- |
| DNPcall | Conteggi e genotipi di dinucleotidi da uno o più BAM. |
| SNPcall | Conteggi SNP da BAM o pileup con nomi delle letture. |
| Contamination | Stima della contaminazione da tabelle di conteggi compatibili. |
| CPI | Stima della frazione fetale e calcolo dell'indice di paternità. |

Il client Python gestisce selezione degli input, parametri e registrazione
delle esecuzioni. Un'immagine scientifica autonoma contiene la preparazione
degli input, l'esecuzione dei piani, gli script R, samtools e le dipendenze. Su Windows l'immagine
viene eseguita in un ambiente WSL2 dedicato; su Ubuntu tramite Docker Engine
nativo. I calcoli e i dati rimangono sul computer.

Il pacchetto Windows è un singolo `NIPAT-Setup.exe`, con
installazione con doppio clic e avvio dal collegamento **NIPAT Desktop**
sul desktop o nel menu Start. Il setup consente di scegliere cinque cartelle
separate per applicazione, ambiente WSL, cache, dati e risultati e ricorda le
scelte nelle reinstallazioni. L'aggiornamento e la riparazione riutilizzano
la cartella di NIPAT Desktop riconosciuta. La rimozione dell'applicazione conserva
dati e risultati; eliminare l'ambiente NIPAT e la cache è facoltativo. Non richiede
l'installazione separata degli strumenti scientifici.
Ubuntu 24.04 x86_64 utilizza un singolo
pacchetto `.deb`, con lo stesso archivio scientifico e avvio dal collegamento
**NIPAT Desktop** o dal comando `nipat`. APT installa
automaticamente le dipendenze mancanti, inclusi Docker Engine e Compose v2;
l’accesso dell’utente a Docker richiede autorizzazione amministrativa.
Le versioni pubblicate e i relativi pacchetti sono elencati nella pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases); gli
artefatti GitHub Actions sono invece destinati alla revisione tecnica.

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
Su Windows sono supportati dischi locali fissi.

**Verifica aggiornamenti** propone gli installatori completi delle versioni
pubblicate e approvate su GitHub. Download e installazione sono scelte esplicite;
si può rimandare e continuare a lavorare. Il canale iniziale è `testing`, che
include pre-release e versioni stabili; `stable` considera solo le stabili.
L'eventuale verifica all'avvio è disattivata inizialmente e mostra solo un avviso.

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
Il [piano di sviluppo](docs/ROADMAP.md) descrive i workflow automatici previsti
per la 0.7, la trasparenza delle impostazioni e il supporto italiano/inglese.
Il codice originale è distribuito con licenza [GPL-3.0-or-later](LICENSE).

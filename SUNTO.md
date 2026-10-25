# NIPAT in sintesi

**NIPAT Desktop 0.6.0** è un'applicazione locale per eseguire quattro workflow
scientifici da un menu testuale guidato o dalla riga di comando. Ogni avvio
elabora un'analisi; la versione 0.6.0 non include una GUI grafica né il
concatenamento automatico dei workflow.

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
sono funzioni separate. Le preferenze non cambiano la CLI diretta. Gli input
possono restare nelle cartelle originali e vengono letti senza modificarli.
Su Windows sono supportati dischi locali fissi.

**Verifica aggiornamenti** propone gli installatori completi delle versioni
pubblicate e approvate su GitHub. Download e installazione sono scelte esplicite;
si può rimandare e continuare a lavorare. Il canale iniziale è `testing`, che
include pre-release e versioni stabili; `stable` considera solo le stabili.
L'eventuale verifica all'avvio è disattivata inizialmente e mostra solo un avviso.

Ogni analisi crea un nuovo run con risultati in `output`, intermedi conservati
in `work`, metadati in `run.json` e messaggi in `execution.log`. Le cartelle
esistenti non vengono sovrascritte. Per concatenare analisi si selezionano i
risultati compatibili del run precedente: le tabelle individuali DNPcall
alimentano Contamination e, con campioni materni/paterni appropriati e frequenze
di popolazione, CPI. SNPcall usa un proprio pannello e produce una tabella SNP,
che non è un input diretto degli altri due workflow.

La verifica degli strumenti controlla l'ambiente di esecuzione; gli autotest
confrontano casi noti. Il completamento di un run non sostituisce la
validazione scientifica sui campioni e sullo scenario d'uso.

La [guida per l'utilizzo](docs/GUIDA_UTILIZZO.md) descrive la procedura operativa;
la [scheda di validazione](docs/VALIDAZIONE.md) aiuta a documentare le prove.
Il codice originale è distribuito con licenza [GPL-3.0-or-later](LICENSE).

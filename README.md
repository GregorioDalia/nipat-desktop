<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/branding/nipat-logo-dark.svg">
  <img src="assets/branding/nipat-logo.svg" alt="NIPAT" width="335">
</picture>

# NIPAT Desktop

NIPAT esegue analisi locali DNPcall, SNPcall, Contamination e CPI attraverso
un'interfaccia testuale guidata o comandi riproducibili. Il client Python
raccoglie gli input e registra le esecuzioni; un'immagine scientifica autonoma
contiene gli script R, samtools, le dipendenze e la preparazione degli input.

**Versione documentata: NIPAT Desktop 0.8.2.**
Scaricare il pacchetto del proprio sistema da
[GitHub Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
La [guida di distribuzione](docs/DISTRIBUZIONE.md) descrive requisiti e installazione;
le [note della versione](docs/RELEASE_0.8.2.md) identificano le verifiche effettuate.

I risultati per la consultazione conservano i nomi originali dei campioni
nelle tabelle e nei grafici. Ogni run registra l'associazione con gli
identificativi interni, i parametri effettivi e gli esiti delle fasi.
Il menu **Configura** distingue risorse del computer, della VM e del container,
con anteprima delle modifiche e indicazione di quelle ancora da applicare.

## Analisi disponibili

| Workflow | Input | Risultati principali |
| --- | --- | --- |
| DNPcall | Uno o più BAM, FASTA indicizzato e pannello DNP | Conteggi, genotipi, riepiloghi e grafici. |
| SNPcall | BAM e FASTA indicizzato, oppure pileup con QNAME; pannello SNP | Tabella dei conteggi SNP. |
| Contamination | Tabelle individuali compatibili con DNPcall e pannello di coordinate | Stime per sito e riepilogo per campione. |
| CPI | Tabelle cfDNA materne e paterne, coppie, frequenze di popolazione ed eventuali pannelli | Frazione fetale, CPI e grafici. |

Gli input selezionati sono montati in sola lettura. Ogni analisi crea una
cartella distinta con risultati, intermedi conservati, metadati e log.
I run esistenti non vengono sovrascritti. Le quattro analisi sono disponibili
sia nel menu sia nella CLI diretta. I workflow automatici collegano
**DNPcall → Contamination**, **DNPcall → CPI** oppure **DNPcall → Contamination
e CPI**. DNPcall produce una sola volta le tabelle individuali per le analisi
selezionate. CPI richiede l'assegnazione esplicita delle coppie cfDNA materne/paterne.
Si può aggiungere SNPcall sugli stessi BAM, con un pannello SNP scelto
esplicitamente, oppure eseguire SNPcall su più BAM o pileup in un unico run.
Ogni passaggio conserva risultati e stato distinti.
Il livello Python condiviso controlla gli input prima di avviare R e gli
output prima di registrare il completamento. I pannelli SNP e DNP vengono
normalizzati in copie di lavoro; gli originali rimangono invariati.
Il [contratto degli input](docs/INPUT_VALIDATION.md) distingue controlli
tecnici, segnalazioni di qualità e valutazione scientifica.
L'interfaccia è testuale. Il catalogo scientifico è consultabile in italiano
e inglese con `nipat parameters` o da **Guida e informazioni → Catalogo
scientifico**. Descrive parametri pubblici, regole fisse e preparazione degli
input senza modificare gli algoritmi o avviare analisi.

Il [contratto dei piani](docs/WORKFLOW_CONTRACT.md) identifica campioni,
dipendenze e risultati. Validatore ed esecutore supportano le quattro analisi
in ordine sequenziale. SNPcall è un'attività indipendente: legge il BAM o il
pileup selezionato e non fornisce tabelle compatibili con Contamination o CPI.
Il [catalogo scientifico](docs/CATALOGO_SCIENTIFICO.md) descrive
modalità di consultazione e significato delle informazioni esposte.

## Piattaforme e installazione

| Sistema | Ambiente scientifico | Pacchetto |
| --- | --- | --- |
| Windows 10 22H2 x64, build 19045, o Windows 11 x64 | WSL2 e Docker Engine gestiti da NIPAT | `NIPAT-Setup.exe` |
| macOS 14 o successivo, Intel | VM Lima e container AMD64 | `NIPAT-0.8.2-macos-x86_64.pkg` |
| macOS 14 o successivo, Apple Silicon | VM Lima ARM64, Rosetta e container AMD64 | `NIPAT-0.8.2-macos-arm64.pkg` |
| Ubuntu 24.04 LTS x86_64 | Docker Engine locale | `nipat-desktop_0.8.2_amd64.deb` |

Windows e macOS includono Python e i componenti NIPAT. Docker Desktop, R e
samtools installati separatamente non sono necessari. Il setup Windows
prepara WSL e può richiedere consenso amministrativo e riavvio; il primo
avvio Mac prepara Lima. Queste operazioni possono richiedere Internet.
Ubuntu usa APT per le dipendenze e richiede accesso autorizzato al daemon Docker.
Dopo la preparazione, aprire **NIPAT Desktop** per accedere al menu.

Le guide [Windows](docs/INSTALLATORE_WINDOWS.md), [macOS](docs/INSTALLATORE_MACOS.md)
e [Ubuntu](docs/INSTALLATORE_LINUX.md) descrivono requisiti, aggiornamento e rimozione.
I pacchetti non hanno una firma NIPAT riconosciuta dai sistemi; macOS non dispone
di notarizzazione Apple. La guida Mac spiega l'autorizzazione specifica in
Privacy e sicurezza. Il setup non disattiva le protezioni del dispositivo.

## Utilizzo

1. Aprire NIPAT e scegliere il workflow.
2. Selezionare la modalità di input e inserire file e parametri richiesti.
3. Verificare il riepilogo e la destinazione dei risultati.
4. Confermare **Avvia analisi** per eseguire il calcolo scientifico.
5. Consultare risultati e log dalla schermata finale.

Le indicazioni contestuali spiegano ogni campo. `:indietro` corregge il campo
precedente e `:vuoto` svuota un campo facoltativo. Nei campi di testo e nei
menu a inserimento testuale, `:annulla` torna direttamente al menu principale.
**Ctrl+C** annulla l'operazione corrente anche durante un'analisi: NIPAT
esegue la procedura di arresto prima di tornare al menu, conservando log e
risultati già prodotti e segnalando eventuali problemi di arresto. Le modifiche
di configurazione non ancora salvate vengono scartate.
Per chiudere il programma scegliere **0 — Esci** nel menu principale.
**5 — Configura** salva cartelle dati e risultati, riferimenti, modalità e
parametri predefiniti dei workflow per gli avvii successivi del menu.
Ogni analisi permette di modificarli prima della conferma; campioni, coppie
e nome del run vengono scelti ogni volta. Le preferenze non alterano i comandi
CLI diretti. **6 — Ultima esecuzione** riapre il run più recente della sessione;
**7 — Guida e informazioni** e **8 — Verifica ambiente** separano consultazione
e diagnostica. **9 — Verifica aggiornamenti** consulta le release compatibili
e verifica il download del pacchetto. Le installazioni sperimentali conservano
identità e dati separati e non vengono adottate automaticamente.
Dopo la preparazione l'applicazione esegue le analisi offline.
**W — Workflow automatici** offre le tre composizioni DNPcall e SNPcall su più
campioni, con un unico riepilogo e una sola conferma. Per spostare applicazione, ambiente WSL o cache
usare il setup.

Su Windows sono supportati input su dischi locali fissi, anche fuori dalla
cartella dell'applicazione; condivisioni UNC e unità di rete non sono supportate.
I percorsi possono contenere spazi. I percorsi relativi partono dalla cartella
corrente indicata nel campo: la cartella configurata come **Dati** non è una
base di ricerca automatica. Per il riferimento scegliere il file FASTA delle
sequenze, ad esempio `genome.fa`; `.fai` e `.gzi` sono indici associati e non
vanno selezionati al suo posto. Nel workflow automatico non occorre copiare
o riselezionare le tabelle fra i passaggi. Le altre sequenze si
compongono selezionando gli output compatibili di un run come input del successivo.

### CLI diretta

Nella cartella dell'applicazione Windows, `nipat.cmd` accetta gli stessi
workflow del menu. Sostituire i percorsi relativi di esempio con i propri:

```powershell
.\nipat.cmd --runs-dir "..\risultati" dnp-call `
  --bam "..\campioni\campione.bam" `
  --reference "..\riferimenti\genome.fa" --panel "..\pannelli\DNP_list.txt"

.\nipat.cmd snp-call `
  --pileup "..\campioni\campione.pileup" --panel "..\pannelli\SNPlist.txt"

.\nipat.cmd contamination `
  --input-dir "..\risultati\run-dnp\output\individual_outputs" `
  --panel "..\pannelli\DNP_list.txt"

.\nipat.cmd cpi --input-dir "..\campioni\cpi" --pairs "A1:A1" `
  --popfreq "..\pannelli\pop_allFreq.txt" --panel "..\pannelli\DNP_list.txt"
```

Per eseguire DNPcall e poi Contamination nella stessa esecuzione:

```powershell
.\nipat.cmd --runs-dir "..\risultati" workflow dnp-contamination `
  --bam "..\campioni\campione.bam" `
  --reference "..\riferimenti\genome.fa" --panel "..\pannelli\DNP_list.txt"
```

`--bam` è ripetibile; `--bamlist` accetta un elenco di BAM. Contamination usa
il pannello DNP selezionato, oppure quello indicato con `--contamination-panel`.
`--parallel` riguarda soltanto il calcolo DNPcall sui campioni: le analisi
successive iniziano dopo il completamento e la verifica degli output DNPcall.

Per calcolare CPI dopo DNPcall, assegnare esplicitamente il BAM cfDNA materno
e quello paterno a ogni coppia:

```powershell
.\nipat.cmd workflow dnp-cpi `
  --pair coppia_a "..\campioni\cfdna-a.bam" "..\campioni\padre-a.bam" `
  --reference "..\riferimenti\genome.fa" --panel "..\pannelli\DNP_list.txt" `
  --popfreq "..\pannelli\pop_allFreq.txt"
```

`--pair` è ripetibile. Per includere anche Contamination, usare
`workflow dnp-contamination-cpi` con le stesse coppie. `--panel` seleziona
sempre i loci DNPcall; CPI usa tutti i siti disponibili salvo scelta esplicita
di `--cpi-panel`, `--cutoff` o `--cutoff-map`. Le tabelle non devono essere
copiate o rinominate: il motore conserva la corrispondenza fra coppie e risultati.
Contamination non modifica i conteggi utilizzati da CPI.

L'opzione `--snp-panel PATH` aggiunge a ciascuno dei tre workflow un passaggio
SNPcall per ogni BAM distinto, usando lo stesso FASTA. Il pannello SNP deve
essere selezionato esplicitamente. Per eseguire soltanto SNPcall su più campioni:

```powershell
.\nipat.cmd workflow snp-batch `
  --bam "..\campioni\campione-a.bam" --bam "..\campioni\campione-b.bam" `
  --reference "..\riferimenti\genome.fa" --panel "..\pannelli\SNPlist.txt"

.\nipat.cmd workflow snp-batch `
  --pileup "..\campioni\campione-a.pileup" --pileup "..\campioni\campione-b.pileup" `
  --panel "..\pannelli\SNPlist.txt"
```

`--bamlist` è un'alternativa ai BAM ripetuti; i percorsi nel file sono relativi
alla cartella della lista. La modalità pileup non accetta un FASTA e richiede
file con QNAME. Le due modalità non si mescolano nello stesso comando.

Le opzioni globali, come `--runs-dir` e `--dry-run`, precedono il sottocomando.
`--dry-run` valida gli input e registra un'esecuzione `planned`, senza eseguire
il motore scientifico. `nipat.cmd --help` e `nipat.cmd <workflow> --help`
elencano le opzioni. La [guida](docs/GUIDA_UTILIZZO.md) documenta formati,
modalità alternative e parametri.

Su Ubuntu installato dal pacchetto `.deb`, usare `nipat` al posto
di `.\nipat.cmd`, percorsi Linux e `\` per continuare un comando su più righe.
Le opzioni e i workflow sono gli stessi. Per esempio:

```bash
nipat --runs-dir "$HOME/risultati-nipat" contamination \
  --input "$HOME/campioni/sample.txt" --panel "$HOME/pannelli/DNPpanel.txt"
```

### Ubuntu: esecuzione da sorgenti

Servono Python 3.12 con `venv`, Docker Engine e Compose v2, accessibili
all'utente che esegue NIPAT. Dalla radice del repository:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
nipat build-runtime
nipat doctor --runtime
nipat self-test
nipat wizard
```

La costruzione dell'immagine richiede una connessione Internet. I calcoli
usano l'immagine locale. Il pacchetto Python da solo non contiene il runtime:
conservare il checkout completo e seguire i requisiti della
[distribuzione](docs/DISTRIBUZIONE.md).

## Risultati e verifiche

Ogni run contiene `output`, `work`, `run.json` ed `execution.log`.
Nel workflow automatico, `output/workflow` conserva il piano, lo stato
complessivo e le sottocartelle dei passaggi selezionati: `steps/dnp`,
`steps/contamination`, `steps/cpi` e, quando richiesti, `steps/snp_0001` e
successivi. Ogni passaggio conserva risultati, preparazione e log. Un errore impedisce l'avvio dei passaggi
successivi; le evidenze già prodotte restano disponibili. Non è prevista
la ripresa del run: una nuova prova usa una nuova cartella.
Il record identifica input, parametri e immagine effettivamente usata;
la [guida alle esecuzioni](docs/ESECUZIONI.md) ne descrive significato e limiti.
Lo stato `succeeded` indica il completamento tecnico del workflow. La
concordanza scientifica richiede il confronto con risultati attesi appropriati.
Gli avvisi di validazione restano visibili anche dopo un completamento riuscito.
`--input-hashes full` abilita la verifica SHA-256 integrale degli input;
`--cpus`, `--memory-mb` e `--pids-limit` impostano limiti facoltativi del
container. **Guida e informazioni** permette di consultare le esecuzioni
incomplete e, su Windows, l'inventario dell'installazione con manutenzione
selettiva confermata dall'utente.

`doctor --runtime` verifica l'ambiente e il motore scientifico incorporato.
`self-test` confronta i casi distribuiti di SNPcall, CPI e Contamination e le
modalità di input esterno. Il collaudo DNPcall da BAM richiede un caso distinto.
La CI esegue inoltre regressioni DNPcall sintetiche e confronti fra workflow
automatici e analisi separate, compresi CPI e le sue modalità di selezione dei siti,
SNPcall da BAM o pileup e l'uso dello stesso BAM per DNPcall e SNPcall;
la [documentazione CI/CD](docs/CI_CD.md) distingue copertura automatica,
verifica degli installatori e pubblicazione. La
[scheda di validazione](docs/VALIDAZIONE.md) permette di registrare prove
indipendenti e problemi riproducibili.

## Documentazione e licenza

- [Sintesi del prodotto](SUNTO.md)
- [Risorse e memoria](docs/RISORSE.md)
- [Diagnostica delle prestazioni e benchmark](docs/PERFORMANCE.md)
- [Note della versione 0.8.2](docs/RELEASE_0.8.2.md)
- [Guida per l'utilizzo](docs/GUIDA_UTILIZZO.md)
- [Controlli degli input e dei risultati](docs/INPUT_VALIDATION.md)
- [Distribuzione e requisiti](docs/DISTRIBUZIONE.md)
- [Installazione Windows](docs/INSTALLATORE_WINDOWS.md) e [macOS](docs/INSTALLATORE_MACOS.md)
- [Installatore Ubuntu](docs/INSTALLATORE_LINUX.md)
- [Architettura](docs/ARCHITECTURE.md)
- [Piano di sviluppo: workflow e lingue](docs/ROADMAP.md)
- [Controlli CI/CD](docs/CI_CD.md)
- [Accettazione degli installatori](docs/ACCETTAZIONE_INSTALLATORI.md)
- [Componenti scientifici](scientific/README.md)

Il codice originale NIPAT è distribuito con licenza
[GPL-3.0-or-later](LICENSE). Le licenze e le attribuzioni dei componenti inclusi
sono descritte in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/branding/nipat-logo-dark.svg">
  <img src="assets/branding/nipat-logo.svg" alt="NIPAT" width="335">
</picture>

# NIPAT Desktop

NIPAT esegue analisi locali DNPcall, SNPcall, Contamination e CPI attraverso
un'interfaccia testuale guidata o comandi riproducibili. Il client Python
raccoglie gli input e registra le esecuzioni; un'immagine scientifica autonoma
contiene gli script R, samtools, le dipendenze e la preparazione degli input.

**Versione documentata: NIPAT Desktop 0.7.0a1, in sviluppo.** La release
ufficiale disponibile è la 0.6.0. Consultare la pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases) per le
versioni effettivamente pubblicate, gli installatori e le rispettive note.
Gli artefatti GitHub Actions sono pacchetti di verifica tecnica, distinti dalle
release. NIPAT è software per la ricerca: gli autotest verificano casi noti,
mentre la validazione scientifica dipende dai dati e dall'impiego previsto.

## Analisi disponibili

| Workflow | Input | Risultati principali |
| --- | --- | --- |
| DNPcall | Uno o più BAM, FASTA indicizzato e pannello DNP | Conteggi, genotipi, riepiloghi e grafici. |
| SNPcall | BAM e FASTA indicizzato, oppure pileup con QNAME; pannello SNP | Tabella dei conteggi SNP. |
| Contamination | Tabelle individuali compatibili con DNPcall e pannello di coordinate | Stime per sito e riepilogo per campione. |
| CPI | Tabelle cfDNA materne e paterne, coppie, frequenze di popolazione ed eventuali pannelli | Frazione fetale, CPI e grafici. |

Gli input selezionati sono montati in sola lettura. Ogni analisi crea una
cartella distinta con risultati, intermedi conservati, metadati e log.
I run esistenti non vengono sovrascritti. I quattro workflow sono disponibili
sia nel menu sia nella CLI diretta. Ogni avvio esegue una singola analisi;
le sequenze si compongono selezionando gli output compatibili del run precedente.
L'interfaccia è testuale. Il catalogo scientifico è consultabile in italiano
e inglese con `nipat parameters` o da **Guida e informazioni → Catalogo
scientifico**. Descrive parametri pubblici, regole fisse e preparazione degli
input senza modificare gli algoritmi o avviare analisi.

Il motore convalida inoltre il [contratto dei piani](docs/WORKFLOW_CONTRACT.md)
per le composizioni compatibili. Questo incremento verifica struttura,
riferimenti e ordine dei passaggi; l'esecuzione automatica dei piani non è
ancora disponibile. Il [catalogo scientifico](docs/CATALOGO_SCIENTIFICO.md)
descrive modalità di consultazione e significato delle informazioni esposte.

## Piattaforme e installazione

| Piattaforma | Ambiente di esecuzione | Installatore |
| --- | --- | --- |
| Windows 11 x64 | WSL2 con distribuzione NIPAT dedicata e Docker Engine gestito dall'applicazione | Unico file `NIPAT-Setup.exe`. |
| Ubuntu 24.04 LTS x86_64 | Docker Engine locale e Compose v2, accessibili all’utente | Unico pacchetto `.deb`. |

Il pacchetto Windows contiene Python portabile, l'ambiente Linux e l'immagine
scientifica. Non richiede installazioni separate di Python, R, samtools o
Docker Desktop. WSL2 e la virtualizzazione devono essere disponibili sul
computer; la loro attivazione può richiedere Internet, autorizzazione
amministrativa e riavvio.

L'installazione Windows usa il nome **NIPAT Desktop**. Avviare
`NIPAT-Setup.exe` con doppio clic dal proprio account, senza scegliere
«Esegui come amministratore»;
la configurazione deve terminare con `NIPAT: ready`. Per ogni utilizzo
successivo, aprire con doppio clic il collegamento **NIPAT Desktop**
sul desktop o selezionarlo dal menu Start. Non occorre spostare archivi o aprire
manualmente PowerShell. Il setup permette di scegliere separatamente le
cartelle dell'applicazione, dell'ambiente WSL, della cache, dei dati e dei
risultati, anche su dischi locali fissi diversi. Le scelte vengono riproposte
alla reinstallazione. Un’installazione NIPAT Desktop riconosciuta può essere aggiornata o riparata
nella stessa cartella, conservando i file estranei ai componenti installati.
La disinstallazione conserva sempre dati e risultati;
la rimozione dell'ambiente NIPAT e della cache è facoltativa.
Requisiti, percorsi e gestione dell'installazione sono nella
[guida per l'utilizzo](docs/GUIDA_UTILIZZO.md) e nella
[documentazione di distribuzione](docs/DISTRIBUZIONE.md).

Il pacchetto Windows non è firmato digitalmente da NIPAT. Le protezioni
del computer possono impedirne il download, la preparazione o l'avvio;
l'installazione va verificata sui dispositivi destinati al collaudo. La
[guida Windows](docs/INSTALLATORE_WINDOWS.md#controlli-di-sicurezza-di-windows-e-del-browser)
descrive come documentare un blocco.

Il pacchetto Ubuntu incorpora l’applicazione e lo stesso archivio scientifico
del pacchetto Windows. APT installa anche Python, Docker Engine e Compose v2
se mancano, scaricandoli dai repository configurati. Servono Internet e
autorizzazione amministrativa per queste dipendenze; l’accesso dell’utente
a Docker richiede una configurazione amministrativa distinta. Il collegamento
**NIPAT Desktop** o il comando `nipat` apre il menu.
Requisiti, preparazione iniziale e rimozione
sono descritti nell’[installatore Linux](docs/INSTALLATORE_LINUX.md).

## Utilizzo

1. Aprire NIPAT e scegliere il workflow.
2. Selezionare la modalità di input e inserire file e parametri richiesti.
3. Verificare il riepilogo e la destinazione dei risultati.
4. Confermare **Avvia analisi** per eseguire il calcolo scientifico.
5. Consultare risultati e log dalla schermata finale.

Le indicazioni contestuali spiegano ogni campo. `:indietro` corregge il campo
precedente, `:annulla` torna al menu e `:vuoto` svuota un campo facoltativo.
**5 — Configura** salva cartelle dati e risultati, riferimenti, modalità e
parametri predefiniti dei workflow per gli avvii successivi del menu.
Ogni analisi permette di modificarli prima della conferma; campioni, coppie
e nome del run vengono scelti ogni volta. Le preferenze non alterano i comandi
CLI diretti. **6 — Ultima esecuzione** riapre il run più recente della sessione;
**7 — Guida e informazioni** e **8 — Verifica ambiente** separano consultazione
e diagnostica. **9 — Verifica aggiornamenti** cerca versioni pubblicate e
approvate su GitHub; download e installazione richiedono conferme distinte.
In **Configura → Aggiornamenti** si scelgono il canale e l'eventuale avviso
all'avvio, disattivato inizialmente. L'applicazione resta utilizzabile offline.
Per spostare applicazione, ambiente WSL o cache usare il setup.

Su Windows sono supportati input su dischi locali fissi, anche fuori dalla
cartella dell'applicazione; condivisioni UNC e unità di rete non sono supportate.
I percorsi possono contenere spazi. Le analisi in sequenza si compongono
selezionando gli output compatibili di un run come input del successivo.

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
Il record identifica input, parametri e immagine effettivamente usata;
la [guida alle esecuzioni](docs/ESECUZIONI.md) ne descrive significato e limiti.
Lo stato `succeeded` indica il completamento tecnico del workflow. La
concordanza scientifica richiede il confronto con risultati attesi appropriati.

`doctor --runtime` verifica l'ambiente e il motore scientifico incorporato.
`self-test` confronta i casi distribuiti di SNPcall, CPI e Contamination e le
modalità di input esterno. Il collaudo DNPcall da BAM richiede un caso distinto.
La CI esegue inoltre regressioni DNPcall sintetiche e controlli del motore;
la [documentazione CI/CD](docs/CI_CD.md) distingue copertura automatica,
verifica degli installatori e pubblicazione. La
[scheda di validazione](docs/VALIDAZIONE.md) permette di registrare prove
indipendenti e problemi riproducibili.

## Documentazione e licenza

- [Sintesi del prodotto](SUNTO.md)
- [Note della versione 0.6.0](docs/RELEASE_0.6.0.md)
- [Guida per l'utilizzo](docs/GUIDA_UTILIZZO.md)
- [Distribuzione e requisiti](docs/DISTRIBUZIONE.md)
- [Installazione Windows](docs/INSTALLATORE_WINDOWS.md) e [Ubuntu](docs/INSTALLATORE_LINUX.md)
- [Architettura](docs/ARCHITECTURE.md)
- [Piano di sviluppo: workflow e lingue](docs/ROADMAP.md)
- [Controlli CI/CD](docs/CI_CD.md)
- [Accettazione degli installatori](docs/ACCETTAZIONE_INSTALLATORI.md)
- [Componenti scientifici](scientific/README.md)

Il codice originale NIPAT è distribuito con licenza
[GPL-3.0-or-later](LICENSE). Le licenze e le attribuzioni dei componenti inclusi
sono descritte in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

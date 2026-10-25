<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/branding/nipat-logo-dark.svg">
  <img src="assets/branding/nipat-logo.svg" alt="NIPAT" width="335">
</picture>

# NIPAT

NIPAT esegue analisi locali DNPcall, SNPcall, Contamination e CPI attraverso
un'interfaccia testuale guidata o comandi riproducibili. Il client Python
raccoglie gli input e registra le esecuzioni; un'immagine scientifica autonoma
contiene gli script R, samtools, le dipendenze e la preparazione degli input.

**Versione di questo documento: 0.5.0a1 Preview, per collaudo interno.**
La documentazione descrive il contenuto di questa versione. Consultare la pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases) per le
versioni pubblicate e i relativi installatori. Gli artefatti GitHub Actions
sono pacchetti di revisione tecnica e non equivalgono a una release.
La disponibilità del software e il superamento degli autotest non equivalgono
alla validazione scientifica per uno specifico impiego.

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
sia nel menu sia nella CLI diretta; la GUI grafica non fa parte della 0.5.

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

L'installazione Windows usa il nome **NIPAT 0.5 Preview**. Avviare
`NIPAT-Setup.exe` con doppio clic dal proprio account, senza scegliere
«Esegui come amministratore»;
la configurazione deve terminare con `NIPAT: ready`. Per ogni utilizzo
successivo, aprire con doppio clic il collegamento **NIPAT 0.5 Preview**
sul desktop o selezionarlo dal menu Start. Non occorre spostare archivi o aprire
manualmente PowerShell. Requisiti, percorsi e gestione dell'installazione sono
nella [guida per l'utilizzo](docs/GUIDA_UTILIZZO.md) e nella
[documentazione di distribuzione](docs/DISTRIBUZIONE.md).

La Preview Windows non dispone di una firma Authenticode NIPAT. Le protezioni
del computer possono impedirne il download, la preparazione o l'avvio;
l'installazione va verificata sui dispositivi destinati al collaudo. La
[guida Windows](docs/INSTALLATORE_WINDOWS.md#controlli-di-sicurezza-di-windows-e-del-browser)
descrive come documentare un blocco.

Il pacchetto Ubuntu incorpora l’applicazione e lo stesso archivio scientifico
del pacchetto Windows. APT installa anche Python, Docker Engine e Compose v2
se mancano, scaricandoli dai repository configurati. Servono Internet e
autorizzazione amministrativa per queste dipendenze; l’accesso dell’utente
a Docker richiede una configurazione amministrativa distinta. Il collegamento
**NIPAT 0.5 Preview** o il comando `nipat-05-preview` apre il menu.
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
L'opzione **5 — Cartella risultati** cambia la destinazione per la sessione;
**6 — Ultima esecuzione** riapre l'ultimo run della sessione. La
**Guida all'uso** include la verifica degli strumenti di analisi.

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

Su Ubuntu installato dal pacchetto `.deb`, usare `nipat-05-preview` al posto
di `.\nipat.cmd`, percorsi Linux e `\` per continuare un comando su più righe.
Le opzioni e i workflow sono gli stessi. Per esempio:

```bash
nipat-05-preview --runs-dir "$HOME/risultati-nipat" contamination \
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
`self-test` confronta i risultati dei casi di prova distribuiti; non copre
ogni combinazione possibile di dati e parametri. La
[scheda di validazione](docs/VALIDAZIONE.md) permette di registrare prove
indipendenti e problemi riproducibili.

## Documentazione e licenza

- [Sintesi del prodotto](SUNTO.md)
- [Guida per l'utilizzo](docs/GUIDA_UTILIZZO.md)
- [Distribuzione e requisiti](docs/DISTRIBUZIONE.md)
- [Installazione Windows](docs/INSTALLATORE_WINDOWS.md) e [Ubuntu](docs/INSTALLATORE_LINUX.md)
- [Architettura](docs/ARCHITECTURE.md)
- [Controlli CI/CD](docs/CI_CD.md)
- [Accettazione degli installatori](docs/ACCETTAZIONE_INSTALLATORI.md)
- [Componenti scientifici](scientific/README.md)

Il codice originale NIPAT è distribuito con licenza
[GPL-3.0-or-later](LICENSE). Le licenze e le attribuzioni dei componenti inclusi
sono descritte in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

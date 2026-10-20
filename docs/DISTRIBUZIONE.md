# Distribuzione tramite GitHub

La distribuzione assistita è per **Windows x64**, tramite una versione precisa
su GitHub. La CLI `0.2.0a2` aggiunge la scelta libera dei percorsi e le modalità
di input mancanti; i controlli sul PC Windows di sviluppo sono riportati sotto.
Il tag esistente `v0.2.0a1` identifica la versione precedente
e non va spostato o riutilizzato.

## Verifiche osservate il 20 ottobre 2026

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
gli altri casi scelti dall'esperta. Le precedenti prove SNPcall da BAM non sono
state ripetute in questa revisione.

## Verificare e pubblicare la nuova versione

Per ripetere i controlli o verificare un aggiornamento, dalla cartella del
progetto sul PC Windows con Docker Desktop avviato,
eseguire `1_SETUP.cmd` e verificare che il setup termini correttamente.
Poi aprire PowerShell nella stessa cartella:

```powershell
.\.runtime\python\python.exe -m unittest discover -s tests -v
```

Verificare anche `2_AVVIA.cmd` con input esterni al progetto e scegliere
**5 — Cartella risultati** per provare una destinazione diversa da quella
predefinita. Il nuovo controllo di integrazione
è il quarto gruppo di `self-test`, quindi è già eseguito dal setup. Per ripetere
soltanto questo gruppo durante la diagnosi, usare
`.\.runtime\python\python.exe scripts/verify_input_modes.py`.
Usa piccoli casi per i percorsi esterni e le modalità
aggiunte, senza nuove prove numeriche DNPcall da BAM. Non sostituisce la
validazione scientifica della collega. Registrare gli
esiti effettivamente osservati, inclusi eventuali test saltati.

Dopo aver registrato gli esiti delle prove per la revisione da distribuire:

1. Salvare e pubblicare il commit verificato su GitHub.
2. Creare un nuovo tag `v0.2.0a2` e una release contrassegnata come pre-release,
   indicando modifiche, controlli superati e prove di dominio ancora da fare.
3. Condividere il link alla release. La collega scarica **Source code (zip)**,
   estrae il progetto, esegue `1_SETUP.cmd` e poi `2_AVVIA.cmd`.

Applicare le modifiche locali non pubblica la release. I precedenti risultati
Windows di `0.2.0a1` — 48 test Python superati, uno saltato e tre autotest Docker
superati — restano evidenza per quella versione, non per `0.2.0a2`.

## Prima installazione della collega

Docker Desktop deve essere installato e avviato con container Linux.
Il setup verifica Docker, scarica Python 3.12.10 portabile dal sito ufficiale,
ne controlla il SHA-256 e costruisce il runtime scientifico quando necessario.
Infine esegue gli autotest. Non servono Git, PyCharm o installazioni separate
di Python, R e samtools. Il primo setup richiede Internet.

La costruzione usa il Dockerfile del progetto, ma può risolvere versioni
diverse dei pacchetti R disponibili al momento. Gli autotest e i metadati
registrano l'ambiente effettivo: uno stesso tag Git non garantisce da solo
un'immagine Docker identica. La prova su un altro PC resta necessaria.

Gli input possono risiedere fuori dal progetto; anche la radice dei risultati
è selezionabile. Dati genomici, risultati e ambienti locali non vanno aggiunti
al repository. La procedura d'uso è in [GUIDA_COLLEGA.md](GUIDA_COLLEGA.md).
L'installazione automatica di Docker/WSL e la distribuzione del runtime via
GHCR non sono implementate in questa revisione.

## Utilità facoltativa per un asset di release

`scripts/build_validation_bundle.py` resta disponibile per preparare un
archivio con Python e, facoltativamente, il runtime esportato. Il percorso
scelto rimane **Source code (zip)** da GitHub: questa utilità non è necessaria
e non pubblica autonomamente file.

```powershell
.\.runtime\python\python.exe scripts/build_validation_bundle.py `
    --output "..\nipat-cli-0.2.0a2-windows-x64.zip" `
    --include-runtime
```

Il nome di destinazione deve essere nuovo. Il builder usa l'elenco esplicito
`distribution-files.txt` e registra provenienza e checksum in `release.json`.
Un archivio con runtime può essere voluminoso: non inserirlo tra i normali
file Git. L'eventuale asset richiede una verifica separata di contenuto e dimensione.

## Riferimenti

- [Docker Desktop per Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
- [Python 3.12.10](https://www.python.org/downloads/release/python-31210/)
  e [pacchetto incorporabile](https://docs.python.org/3.12/using/windows.html#the-embeddable-package).

I launcher usano un criterio PowerShell limitato al processo; non modificano
il criterio globale né il PATH del sistema.

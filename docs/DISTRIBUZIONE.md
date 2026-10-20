# Distribuzione tramite GitHub

La prima distribuzione assistita è per **Windows x64**. La versione CLI
`0.2.0a1` è destinata alla validazione con l'esperta di dominio.
Il canale di distribuzione è GitHub: alla collega si passa il link a una
versione precisa, dalla quale scaricare il progetto e le istruzioni.

## Pubblicare una versione da provare

1. Verificare il setup Windows, gli autotest e l'apertura del menu testuale.
2. Salvare le modifiche nel repository e pubblicarle su GitHub.
3. Creare un tag e una release contrassegnata come pre-release, indicando il
   commit verificato, l'esito dei controlli e le prove di dominio ancora da fare.
4. Condividere il link alla release. La collega scarica **Source code (zip)**,
   estrae il progetto, esegue `1_SETUP.cmd` e poi `2_AVVIA.cmd`.

Il tag identifica la versione del codice da provare. Non occorre installare
Git né trasferire personalmente archivi alla collega. La pubblicazione della
release è un passaggio distinto dall'applicazione locale delle modifiche.

## Prima installazione della collega

Nella versione attuale, Docker Desktop deve essere già installato e avviato
con container Linux. Il setup verifica Docker, scarica Python 3.12.10 portabile
dal sito ufficiale e ne controlla il SHA-256, quindi costruisce il runtime
scientifico se non è già disponibile. Infine esegue i tre autotest numerici.
Non servono installazioni separate di Python, R, samtools o PyCharm.

Il primo setup richiede Internet e può durare diversi minuti. La costruzione
usa il Dockerfile del progetto, ma può risolvere versioni diverse dei pacchetti
R disponibili al momento: lo stesso tag Git non garantisce da solo un'immagine
Docker identica. Gli autotest e i metadati delle esecuzioni registrano la
configurazione effettiva. La prima prova su un altro PC resta necessaria.

La procedura per l'utilizzatrice è in [GUIDA_COLLEGA.md](GUIDA_COLLEGA.md).
I dati genomici e i risultati restano nelle cartelle locali `data` e `runs`,
esterne al repository; non vanno inclusi nella pubblicazione.

## Evoluzioni previste

- Estendere `1_SETUP.cmd` con un elenco dei prerequisiti e uno script che
  controlli e installi WSL/Docker quando mancanti. WinGet supporta elenchi JSON
  per l'installazione di applicazioni; uno script aggiuntivo deve gestire i
  controlli, gli eventuali permessi, il riavvio richiesto e la ripresa del setup.
  L'abilitazione della virtualizzazione nel firmware e i vincoli amministrativi
  del PC possono richiedere interventi dell'utente o dell'IT.
- Distribuire un'immagine scientifica già verificata, identificata da un digest,
  tramite GitHub Container Registry e scaricarla dal setup. Questo percorso
  deve ancora essere implementato e verificato: il setup attuale non usa GHCR.

L'installazione automatica dei prerequisiti non è presente nella CLI `0.2.0a1`.

## Utilità facoltativa per preparare un archivio completo

`scripts/build_validation_bundle.py` resta disponibile per preparare un
eventuale asset di release, con Python e, facoltativamente, il runtime esportato.
Non è necessario per il percorso attuale basato su **Source code (zip)** e
non pubblica autonomamente alcun file su GitHub.

```powershell
& ".\.venv\Scripts\python.exe" scripts/build_validation_bundle.py `
    --output "..\nipat-cli-0.2.0a1-windows-x64.zip" `
    --include-runtime
```

Il nome di destinazione deve essere nuovo. Il builder usa esclusivamente
`distribution-files.txt`, esclude dati e risultati locali e registra provenienza
e checksum in `release.json`. Un archivio con runtime può essere voluminoso:
non inserirlo tra i normali file del repository Git. L'eventuale pubblicazione
come asset va valutata separatamente, verificandone dimensione e contenuto.

## Riferimenti

- [Installazione Docker Desktop per Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
- [Installazione WSL](https://learn.microsoft.com/en-us/windows/wsl/install).
- [Importazione di un elenco di applicazioni con WinGet](https://learn.microsoft.com/en-us/windows/package-manager/winget/import).
- [Python 3.12.10](https://www.python.org/downloads/release/python-31210/)
  e [pacchetto incorporabile](https://docs.python.org/3.12/using/windows.html#the-embeddable-package).

I launcher usano un criterio PowerShell limitato al processo; non modificano
il criterio globale né il PATH del sistema.

# NIPAT Experimental08 0.8.0a1

**Versione sperimentale di portabilità, distinta da NIPAT Desktop 0.7.2.**
Windows 10 e macOS sono nuovi obiettivi di collaudo. Questo documento non
attesta un'installazione o un'analisi già riuscita su un dispositivo Windows 10,
Mac Intel o Apple Silicon: gli esiti appartengono alla build e alle prove
identificate nei relativi rapporti.

## Funzionalità

La versione mantiene il menu testuale, la CLI diretta e i quattro workflow
scientifici DNPcall, SNPcall, Contamination e CPI. Le composizioni automatiche,
i parametri, il catalogo scientifico, i controlli degli input e i record dei
run conservano i propri contratti. Il core scientifico resta in R, incorporato
nell'immagine insieme a samtools, dipendenze e orchestrazione. Non include GUI.

## Piattaforme e pacchetti

| Piattaforma sperimentale | Pacchetto |
| --- | --- |
| Windows 10 22H2 x64, build 19045, e Windows 11 x64 | `NIPAT-Setup.exe` |
| macOS 14 o successivo, Apple Silicon | `NIPAT-Experimental-0.8.0a1-macos-arm64.pkg` |
| macOS 14 o successivo, Intel | `NIPAT-Experimental-0.8.0a1-macos-x86_64.pkg` |

Windows usa una distribuzione WSL2 dedicata con rilevamento automatico dei
prerequisiti. Non sono supportati Windows Server, ARM o 32 bit. La preparazione
può richiedere Internet, consenso amministrativo e riavvio.
Windows 10 Pro 22H2 build `19045.6466` soddisfa il requisito di versione;
la revisione dell'aggiornamento cumulativo non è vincolata a `6466`.
L'installazione e il funzionamento WSL su questa configurazione restano da
collaudare su un dispositivo reale.

macOS usa Lima con Python e strumenti nativi inclusi nel pacchetto. Il primo
avvio richiede Internet per preparare il guest. I due tipi di Mac usano la
stessa immagine scientifica Linux AMD64; su Apple Silicon l'esecuzione passa
attraverso Rosetta in una VM ARM64. Prestazioni e risultati su questa
combinazione devono essere verificati sul runtime reale.

L'esperimento non produce un nuovo `.deb`. La distribuzione Ubuntu stabile
rimane 0.7.2; Linux resta l'ambiente di sviluppo e regressione del motore.

## Separazione dalla versione stabile

Il profilo `experimental08` usa il nome **NIPAT Experimental08**, proprie
cartelle e un proprio runtime. Il setup non adotta l'installazione stabile.
Gli aggiornamenti automatici del canale desktop non distribuiscono la 0.8;
la verifica degli aggiornamenti è disabilitata nel profilo sperimentale.

I pacchetti sono disponibili come artefatti della build dedicata del branch
`experiment/0.8-portability` o, se pubblicati, come pre-release sperimentale.
La build non modifica `main`, `Latest` o gli asset 0.7.2. Consultare il rapporto
della specifica build per commit, checksum e controlli realmente eseguiti.

## Verifiche e limiti

La CI estende le prove del client a macOS Intel/Apple Silicon e controlla
rilevamento Windows, isolamento del profilo, contratti del trasporto e
confezionamento. Le regressioni scientifiche Linux verificano i casi noti.
I job Lima reali sono facoltativi e distinti dai controlli macOS ospitati;
una prova non avviata rimane non eseguita.

I test automatici non sostituiscono prima installazione e uso sui computer
dei ricercatori. Rimangono da registrare le osservazioni relative a WSL
inizialmente assente, riavvio, permessi dei file, avvio e arresto Lima,
Rosetta, reinstallazione e conservazione dei dati. Il collaudo può procedere
in modo incrementale senza dichiarare completati questi scenari.

I pacchetti non dispongono di firma NIPAT riconosciuta; l'applicazione Mac
non è notarizzata. Le protezioni del sistema possono bloccarli. Nessun
installer modifica le policy di sicurezza per autorizzare la propria esecuzione.
La valutazione scientifica su campioni rappresentativi rimane separata dalle
prove di installazione e portabilità.

## Documentazione

- [Guida per l'utilizzo](GUIDA_UTILIZZO.md)
- [Distribuzione e requisiti](DISTRIBUZIONE.md)
- [Installatore Windows](INSTALLATORE_WINDOWS.md)
- [Installatore macOS](INSTALLATORE_MACOS.md)
- [CI/CD e livelli di prova](CI_CD.md)
- [Scheda di validazione](VALIDAZIONE.md)

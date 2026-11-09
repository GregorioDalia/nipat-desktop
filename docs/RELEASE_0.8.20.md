# NIPAT Desktop 0.8.20

NIPAT Desktop 0.8.20 rafforza il confezionamento Windows, i test degli
installatori e i controlli sulla concorrenza scientifica. Conserva le quattro
analisi e la coda DNP comune a un numero generico di BAM introdotta nella
0.8.14. Le formule scientifiche e il riferimento congelato 0.8.5 restano invariati.

## Correzioni e verifiche

- **Windows:** il componente nativo che coordina installazione, aggiornamento
  e rimozione viene compilato durante la build. La preparazione non compila
  più una DLL temporanea sul computer dell'utente. Il componente distribuito
  viene identificato dall'inventario del pacchetto e verificato prima del caricamento.
- **Build dei componenti Windows:** compilazione deterministica e prova di
  ripetibilità dei componenti NIPAT. Questo controllo riguarda i binari
  indicati nel rapporto, non la riproducibilità dell'intero installer o dell'immagine.
- **Firme Windows:** un rapporto conserva hash e stato Authenticode dei
  componenti esaminati. Una firma assente rimane esplicita e non viene
  interpretata come un esito positivo di Smart App Control.
- **Installazione:** prove su una fixture compilata dalla definizione Inno
  verificano copia, aggiornamento, rimozione e conservazione dei file utente.
  Il bootstrap WSL e i requisiti desktop sono sostituiti nella sola fixture;
  il setup distribuito conserva tutti i propri controlli.
- **macOS:** Ctrl+C raggiunge il client senza farlo terminare prematuramente
  dal processo di avvio. Il lock dell'installazione rimane acquisito finché
  il client è attivo, anche quando ritorna al menu dopo un annullamento.
- **Aggiornamento Linux:** il riavvio finale passa direttamente al launcher,
  evitando la terminazione involontaria del client con Ctrl+C.
- **Validazione DNP:** la prima posizione deve consentire la finestra
  precedente al sito. Il valore 1 viene rifiutato prima di creare output,
  evitando un successivo intervallo BED negativo in samtools.
- **DNP e CI:** i confronti con 2, 3 e 6 BAM e le verifiche dei relativi helper
  diventano requisiti espliciti di pubblicazione. La verifica del parallelismo
  controlla la sovrapposizione effettiva delle attività e il loro esito,
  oltre ai limiti dichiarati.

L'[audit della 0.8.20](AUDIT_0.8.20.md) descrive perimetro, evidenze e limiti.

## Smart App Control

Il pacchetto non dispone di una firma Authenticode NIPAT riconosciuta.
**Questa versione non garantisce la rimozione del blocco di Smart App Control.**
L'eliminazione della compilazione temporanea riduce i componenti generati sul
dispositivo, ma non attribuisce una firma attendibile al setup, agli script
o agli altri eseguibili. La qualificazione richiede una firma riconosciuta
dei componenti pertinenti e prove su Windows 11 con la protezione attiva.

Il riuso del numero 0.8.14 fra una candidata e la successiva release ha impedito
all'aggiornatore di distinguerle; non costituisce una causa dimostrata del blocco
di Windows. La 0.8.20 ha un numero superiore e viene riconosciuta come aggiornamento.
I pacchetti pubblicati rimangono immutabili. La
[guida Windows](INSTALLATORE_WINDOWS.md#controlli-di-sicurezza-di-windows-e-del-browser)
descrive come identificare il componente bloccato senza modificare le protezioni.

## Installazione e limiti

Scaricare il pacchetto del proprio sistema dalla
[release 0.8.20](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.20):

| Sistema | Pacchetto |
| --- | --- |
| Windows 10 22H2 x64 / Windows 11 x64 | `NIPAT-Setup.exe` |
| macOS 14 o successivo, Apple Silicon | `NIPAT-0.8.20-macos-arm64.pkg` |
| macOS 14 o successivo, Intel | `NIPAT-0.8.20-macos-x86_64.pkg` |
| Ubuntu 24.04 LTS x86_64 | `nipat-desktop_0.8.20_amd64.deb` |

Chiudere le analisi prima dell'aggiornamento. Il setup conserva dati,
preferenze e risultati delle installazioni riconosciute. È disponibile
**Verifica aggiornamenti** anche dalle candidate già denominate 0.8.14.

I controlli Windows su Server 2022 non qualificano Smart App Control né
un'installazione completa con WSL su Windows 10/11. I pacchetti Mac non sono
notarizzati; i controlli nativi non sostituiscono le prove Lima sui dispositivi
finali. Le misure sui dati reali della candidata precedente mantengono la
propria identità: non sono benchmark della 0.8.20. La validazione scientifica
di dominio rimane distinta dalla regressione automatica.

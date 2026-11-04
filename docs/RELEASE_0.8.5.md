# NIPAT Desktop 0.8.5

NIPAT Desktop 0.8.5 è la versione stabile per le analisi locali su Windows,
macOS e Ubuntu. Aggiunge una diagnostica delle prestazioni facoltativa al client
e al motore scientifico, disattivata per impostazione predefinita. **Avvia analisi**
esegue il normale workflow senza monitoraggio delle prestazioni. Gli script R,
i parametri scientifici e gli algoritmi distribuiti restano invariati.

## Funzionalità

- Avvio con diagnostica dal riepilogo del menu oppure con l'opzione CLI
  `--performance-diagnostics`. La scelta riguarda una sola analisi e non viene
  salvata nelle preferenze.
- Osservatore esterno del container e monitor interno del motore per raccogliere
  CPU, memoria, I/O e informazioni sui processi disponibili nel sistema.
- Eventi delle fasi di preparazione, esecuzione R, controllo degli output e
  presentazione, con tempi monotoni.
- Sezione dedicata in `run-report.html`, riepiloghi JSON e campioni JSONL
  conservati nella cartella `performance` del run.
- Scrittura progressiva e indicazione esplicita di dati parziali o non disponibili.
  Un problema di monitoraggio non sostituisce l'esito dell'analisi scientifica.
- Supervisore dei benchmark con raccolta diagnostica facoltativa e registrazione
  delle risorse, degli input e delle singole ripetizioni.

## Download e installazione

Scaricare un solo installer dalla
[release 0.8.5](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.5):

| Sistema | Download |
| --- | --- |
| Windows 10 22H2 x64 / Windows 11 x64 | [NIPAT-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.5/NIPAT-Setup.exe) |
| macOS 14 o successivo, Apple Silicon | [NIPAT-0.8.5-macos-arm64.pkg](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.5/NIPAT-0.8.5-macos-arm64.pkg) |
| macOS 14 o successivo, Intel | [NIPAT-0.8.5-macos-x86_64.pkg](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.5/NIPAT-0.8.5-macos-x86_64.pkg) |
| Ubuntu 24.04 LTS x86_64 | [nipat-desktop_0.8.5_amd64.deb](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.5/nipat-desktop_0.8.5_amd64.deb) |

La 0.8.5 usa l'identità **NIPAT Desktop** e aggiorna un'installazione desktop
esistente; non crea un'applicazione diagnostica separata. I requisiti e le
procedure di installazione,
aggiornamento e rimozione sono descritti nelle guide
[Windows](INSTALLATORE_WINDOWS.md), [macOS](INSTALLATORE_MACOS.md) e
[Ubuntu](INSTALLATORE_LINUX.md).

I pacchetti non hanno una firma NIPAT riconosciuta dai sistemi;
macOS non dispone di notarizzazione Apple. Le guide riportano le procedure
applicabili senza disattivare le protezioni del dispositivo.

## Prima misura

1. Preparare BAM e indice, FASTA indicizzato della stessa assembly e pannello DNP.
2. Aprire NIPAT, verificare la versione `0.8.5` e scegliere **1 — DNPcall**.
3. Eseguire una prova con **Avvia analisi** e una con
   **Avvia analisi con diagnostica prestazioni**, mantenendo identici input,
   parametri e limiti delle risorse.
4. Aprire `run-report.html` nel run diagnostico e conservare entrambe le
   cartelle dei risultati.

La [guida alle prestazioni](PERFORMANCE.md) contiene la procedura completa,
il significato delle misure e il protocollo per ripetere il confronto.

## Evidenze e limiti

La CI verifica la raccolta sul motore scientifico, il confronto degli output
DNPcall con e senza diagnostica, casi sintetici con risultati attesi e la
conservazione delle misure durante una terminazione per esaurimento di memoria.
Le evidenze della build identificano il commit, gli hash dei pacchetti e gli
esiti delle verifiche degli installer.

Questa versione introduce misurazioni, non miglioramenti di velocità. Il
monitoraggio ha un costo: le prestazioni ordinarie si stimano sui run senza
diagnostica. Le letture periodiche possono perdere picchi; contatori del
kernel, statistiche Docker e memoria dei processi misurano grandezze diverse.
Le fasi non distinguono tutte le operazioni interne agli script R.

La disponibilità dei contatori dipende da kernel, runtime e filesystem. La CI
non sostituisce una misura su BAM grandi e non applica soglie di velocità ai
runner condivisi. Le build Mac ospitate verificano client e pacchetti; la prova
completa con Lima e Rosetta richiede un ambiente che esponga la virtualizzazione.

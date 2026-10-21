# NIPAT CLI 0.4.0 — pre-release per le prove di dominio

Questa versione è destinata ai ricercatori che devono valutare NIPAT con
input e risultati attesi del proprio dominio. **Pronto per il testing** non
significa che la validazione scientifica sia completata.

## Download e avvio

| Pacchetto | Procedura |
| --- | --- |
| [NIPAT-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.0/NIPAT-Setup.exe) | Scaricare il solo EXE, fare doppio clic, attendere `NIPAT: ready`, poi aprire l'icona **NIPAT**. |
| [NIPAT-DockerDesktop-0.4.0-windows-x64.zip](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.0/NIPAT-DockerDesktop-0.4.0-windows-x64.zip) | Con Docker Desktop attivo in modalità Linux, estrarre tutto lo ZIP, aprire `1_SETUP.cmd` una volta, poi `NIPAT.exe`. |

L'installatore contiene l'ambiente Linux interno e il runtime scientifico;
non richiede archivi separati o Docker Desktop. Il perimetro iniziale è
**Windows 11 x64 con WSL2 già funzionante**. L'attivazione iniziale di WSL può
richiedere Internet, autorizzazioni e riavvio e resta una verifica separata.

## Contenuto

- Interfaccia guidata con indicazioni contestuali, controllo e correzione degli
  input, riepilogo modificabile e conferma esplicita dell'avvio.
- Launcher `NIPAT.exe` comune ai due pacchetti; apertura di risultati e log dal menu.
- DNPcall, SNPcall, Contamination e CPI, con le modalità di input già integrate.
  La conferma **Avvia analisi** esegue gli script scientifici reali.
- Preparazione riprendibile dell'ambiente interno, con controlli prima
  dell'attivazione e conservazione di dati, risultati e ambiente precedente.
- Codice originale NIPAT sotto GPL-3.0-or-later; licenze dei componenti conservate.

## Perimetro delle prove

Per queste prove si assume WSL2 funzionante. Registrare separatamente
installazione e analisi per ciascun pacchetto nella
[scheda di validazione](VALIDAZIONE.md), che include la
[prima prova con Docker Desktop](VALIDAZIONE.md#prima-prova-con-docker-desktop).

La [guida per l’utilizzo](GUIDA_UTILIZZO.md) accompagna questa versione.
Le verifiche tecniche storiche sono conservate separatamente e non attestano
la correttezza scientifica di nuovi casi. Per WSL sono supportati dischi locali
fissi; unità di rete e condivisioni UNC non sono incluse. Concatenamento
automatico dei workflow, cronologia persistente, scelta della lingua e GUI
restano fuori da questa versione.

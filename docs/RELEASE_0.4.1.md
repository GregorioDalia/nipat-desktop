# NIPAT CLI 0.4.1 — installazione e avvio semplificati

Pre-release per le prove di dominio su Windows 11 x64. Questa revisione
semplifica la distribuzione Docker Desktop: un solo installatore e la stessa
icona per preparare l'ambiente, aprire NIPAT o riprovare dopo un errore.
Non modifica gli algoritmi scientifici né completa la validazione di dominio.

## Download e avvio

| Pacchetto | Procedura |
| --- | --- |
| [NIPAT-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-Setup.exe) | Doppio clic per installare l'ambiente WSL dedicato; attendere `NIPAT: ready`, poi aprire l'icona **NIPAT**. Il perimetro iniziale assume WSL2 funzionante. |
| [NIPAT-DockerDesktop-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-DockerDesktop-Setup.exe) | Con Docker Desktop avviato in modalità Linux, installare con doppio clic e aprire **NIPAT (Docker Desktop)**. La preparazione e gli autotest precedono automaticamente il menu. |

Entrambi sono installatori completi: non occorre estrarre archivi o eseguire
script di preparazione separati. Docker Desktop rimane un prerequisito della
seconda modalità. Dopo un errore di preparazione, riaprire la stessa icona
Docker Desktop per riprovare; gli avvii successivi riutilizzano la preparazione
completata. Le due copie possono coesistere e usano cartelle predefinite distinte.

Il percorso WSL resta quello con ambiente Linux interno incorporato nel setup.
L'eventuale attivazione iniziale di WSL può richiedere Internet, autorizzazioni
e riavvio e resta una prova separata.

## Verifica dell'utilizzo

La [guida per l'utilizzo](GUIDA_UTILIZZO.md) descrive il menu e i quattro workflow.
La [prima prova Docker Desktop](VALIDAZIONE.md#prima-prova-con-docker-desktop)
comprende preparazione e una sequenza reale DNPcall → Contamination, con log,
risultati attesi e osservati. Registrare gli esiti per il pacchetto effettivamente
utilizzato: queste note non attestano una nuova prova manuale su Windows.

Il launcher continua a utilizzare PowerShell internamente. Questa revisione
non introduce la firma del codice e non attesta il superamento di eventuali
controlli antivirus o SmartScreen.

Le [note 0.4.0](RELEASE_0.4.0.md) conservano il precedente percorso con ZIP e
setup separato; quel percorso non è più quello ordinario di questa versione.
Il codice originale NIPAT resta GPL-3.0-or-later, con le licenze dei componenti
incluse nei pacchetti.

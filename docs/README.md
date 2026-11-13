# Documentazione NIPAT Desktop

NIPAT permette di eseguire analisi scientifiche sul proprio computer dal menu guidato o da riga di comando. Per individuare la guida giusta, partire dall'operazione da svolgere.

## Installare

| Operazione | Guida |
| --- | --- |
| Scegliere pacchetto e piattaforma | [Distribuzione e requisiti](DISTRIBUZIONE.md) |
| Installare, aggiornare o riparare su Windows | [Windows e WSL2](INSTALLATORE_WINDOWS.md) |
| Installare o aggiornare su Ubuntu | [Ubuntu e Docker Engine](INSTALLATORE_LINUX.md) |
| Installare o aggiornare su macOS | [macOS e Lima](INSTALLATORE_MACOS.md) |
| Collaudare un'installazione Windows con dati sintetici | [Collaudo automatico](COLLAUDO_INSTALLAZIONE.md) |

## Usare

| Operazione | Guida |
| --- | --- |
| Avviare analisi singole e workflow dal menu o dalla CLI | [Guida per l'utilizzo](GUIDA_UTILIZZO.md) |
| Preparare BAM, pileup, pannelli, tabelle e frequenze | [Controlli degli input e dei risultati](INPUT_VALIDATION.md) |
| Consultare formule, costanti e valori configurabili | [Catalogo scientifico](CATALOGO_SCIENTIFICO.md) |
| Leggere output, log e provenienza di un run | [Esecuzioni e risultati](ESECUZIONI.md) |
| Impostare CPU, memoria e numero di processi | [Risorse e memoria](RISORSE.md) |
| Misurare durata, memoria e concorrenza | [Prestazioni e diagnostica](PERFORMANCE.md) |

## Verificare e contribuire

| Operazione | Guida |
| --- | --- |
| Registrare prove su un dispositivo o dati rappresentativi | [Validazione tecnica e di dominio](VALIDAZIONE.md) |
| Trovare il componente da esaminare o modificare | [Architettura](ARCHITECTURE.md) |
| Consultare schema dei piani e interfaccia del motore | [Contratto dei piani](WORKFLOW_CONTRACT.md) · [Interfaccia del motore](../engine/README.md) |
| Individuare sorgenti R, riferimenti di test e attribuzioni | [Componenti scientifici](../scientific/README.md) · [Attribuzioni e licenze](../THIRD_PARTY_NOTICES.md) |
| Preparare build, accettazione e pubblicazione | [CI/CD](CI_CD.md) · [Accettazione installatori](ACCETTAZIONE_INSTALLATORI.md) · [Procedura di pubblicazione](../.github/RELEASE.md) |
| Orientarsi fra le priorità di sviluppo | [Sviluppo e validazione](ROADMAP.md) · [Audit per la 0.8.70](AUDIT_0.8.70.md) |

## Evidenze storiche

Le note di rilascio, le misure e gli audit datati sono raccolti nell'[archivio](archive/README.md). Per sapere quali pacchetti sono distribuiti e quali prove li riguardano, consultare le [release pubblicate](https://github.com/GregorioDalia/nipat-desktop/releases).

# NIPAT Desktop 0.8.2

NIPAT Desktop 0.8.2 offre la CLI e i workflow automatici su Windows 10/11,
macOS Intel/Apple Silicon e Ubuntu 24.04 x86_64. Gli algoritmi R distribuiti
restano invariati; gli interventi riguardano presentazione, tracciabilità,
risorse e distribuzione.

## Funzionalità

- Risultati per la consultazione con i nomi originali dei campioni nei file,
  nelle tabelle e nei grafici, mantenendo gli identificativi interni per
  collegare senza ambiguità le fasi.
- Mappa dei campioni e resoconto leggibile di ogni run, accanto ai metadati
  strutturati e ai log.
- Configurazione delle risorse con distinzione fra computer, VM e container;
  anteprima, backup e conferma per le modifiche Lima e WSL2.
- Indicazione delle modifiche salvate che richiedono ancora un riavvio.
- Diagnostica persistente dello stato del container, quando acquisibile,
  per distinguere memoria esaurita da una terminazione di causa non accertata.
- Un installer Windows, un pacchetto Ubuntu e due pacchetti Mac, costruiti
  dallo stesso commit e con lo stesso archivio scientifico.

## Installazione e aggiornamento

Scaricare il pacchetto appropriato dalla pagina
[Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
Windows e Ubuntu conservano l'identità desktop. Su Mac l'applicazione è
**NIPAT Desktop** e usa un ambiente Lima dedicato. Le installazioni
sperimentali rimangono separate; non vengono rimosse o convertite automaticamente.

I pacchetti non dispongono di firma NIPAT riconosciuta dal sistema;
macOS non ha notarizzazione Apple. La [guida di distribuzione](DISTRIBUZIONE.md)
riporta le procedure di installazione e i collegamenti alle guide per sistema.

## Evidenze e limiti

I risultati dei controlli sono associati al commit e agli hash dei pacchetti
nella build e nella pagina della release. La CI verifica contratti, nomi,
risorse, regressioni numeriche, installer e provenienza comune degli archivi.
Una prova simulata di errore non è una misura di memoria su dati reali.

Le build Mac ospitate verificano client e pacchetti; l'esecuzione della VM
Lima e del container tramite Rosetta richiede un ambiente che esponga la
virtualizzazione. Gli esiti desktop non eseguiti restano indicati come tali.
La pubblicazione per ricerca pre-1.0 non costituisce validazione scientifica
sui campioni delle ricercatrici.

- [Guida per l'utilizzo](GUIDA_UTILIZZO.md)
- [Risultati e tracciabilità](ESECUZIONI.md)
- [Risorse e memoria](RISORSE.md)
- [CI e distribuzione](CI_CD.md)
- [Scheda di validazione](VALIDAZIONE.md)

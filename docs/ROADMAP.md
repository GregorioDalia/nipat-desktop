# Sviluppo e validazione

NIPAT Desktop 0.8.5 mantiene il core scientifico R, una CLI guidata e workflow
automatici su Windows, macOS e Ubuntu. Il perimetro corrente è descritto nelle
[note della versione](RELEASE_0.8.5.md) e nella [guida per l'utilizzo](GUIDA_UTILIZZO.md).

## Priorità

| Area | Obiettivo |
| --- | --- |
| Validazione di dominio | Confrontare risultati e parametri su casi rappresentativi degli utilizzi scientifici previsti. |
| Tracciabilità | Collegare senza ambiguità nomi originali, identità interne, fasi e risultati. |
| Uso delle risorse | Rendere leggibili e configurabili i limiti dell'ambiente e dell'analisi, conservando diagnosi e configurazione effettiva. |
| Prestazioni | Sviluppare la revisione R 0.8.9 mediante confronti differenziali con la 0.8.5 e benchmark riproducibili, distinguendo equivalenza dei risultati e prestazioni. |
| Portabilità | Raccogliere prove reali Windows 10/11, Ubuntu e Mac Intel/Apple Silicon oltre ai controlli automatici. |
| Interfaccia | Preparare una GUI sugli stessi contratti della CLI, dopo il consolidamento delle analisi. |
| Lingue | Estendere italiano e inglese dal catalogo scientifico all'interfaccia e alla documentazione, senza duplicare le regole applicative. |

## Metodo di verifica

La [revisione 0.8.9](OPTIMIZATION_0.8.9.md) è sperimentale. La versione
ufficiale rimane la 0.8.5; il completamento dei test di sviluppo non pubblica
automaticamente un aggiornamento o un installatore.

Ogni difetto riproducibile aggiunge una regressione al livello appropriato.
I test distinguono input e parametri, calcoli numerici, trasporto, installer,
aggiornamenti e presentazione. Le modifiche di etichetta devono lasciare invariati
i risultati numerici e le associazioni biologiche dichiarate.

Il collaudo dei pacchetti procede per scenari documentati: installazione,
aggiornamento, riavvio, percorsi personalizzati, riparazione e rimozione.
Le evidenze automatiche e quelle desktop rimangono distinte; la distribuzione
pre-1.0 non trasforma i casi non eseguiti in casi superati.

La [scheda di validazione](VALIDAZIONE.md) raccoglie attese, osservazioni,
versioni e materiale necessario a riprodurre i problemi. Le decisioni sulle
interpretazioni scientifiche richiedono una valutazione di dominio.

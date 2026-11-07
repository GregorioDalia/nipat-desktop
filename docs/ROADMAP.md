# Sviluppo e validazione

NIPAT Desktop 0.8.9 mantiene il core scientifico R, una CLI guidata e workflow
automatici su Windows, macOS e Ubuntu. Il perimetro corrente è descritto nelle
[note della versione](RELEASE_0.8.9.md) e nella [guida per l'utilizzo](GUIDA_UTILIZZO.md).

## Priorità

| Area | Obiettivo |
| --- | --- |
| Validazione di dominio | Confrontare risultati e parametri su casi rappresentativi degli utilizzi scientifici previsti. |
| Tracciabilità | Collegare senza ambiguità nomi originali, identità interne, fasi e risultati. |
| Uso delle risorse | Conservare la distinzione fra configurazione salvata, risorse effettive, suggerimenti e modifiche; Invio mantiene i valori correnti. |
| Prestazioni | Integrare nel prototipo 0.8.10 accesso al BAM e gestione dei dati più efficienti, verificando prima l'equivalenza scientifica. |
| Portabilità | Raccogliere prove reali Windows 10/11, Ubuntu e Mac Intel/Apple Silicon oltre ai controlli automatici. |
| Interfaccia | Esporre fase, campione, tempo trascorso e attività anche senza diagnostica; usare avanzamento e tempo residuo solo quando misurabili o stimabili con dati sufficienti. |
| GUI | Riutilizzare i contratti della CLI e gli eventi di avanzamento in una futura interfaccia grafica. |
| Lingue | Estendere italiano e inglese dal catalogo scientifico all'interfaccia e alla documentazione, senza duplicare le regole applicative. |

## Prototipo 0.8.10

La 0.8.10 è un unico prototipo integrato, sviluppato in commit distinti e
verificabili. Non sostituisce automaticamente la release ufficiale 0.8.9.
Le direzioni da valutare comprendono accesso indicizzato alle regioni BAM,
elaborazione incrementale per finestre DNP, rappresentazioni compatte,
intermedi su disco Linux e parallelismo per blocchi entro un budget di memoria.
Gli eventuali costi di copia fanno parte dei benchmark; la RAM non sostituisce
il disco per nasconderli.

Formule, soglie, filtri e significato dei risultati rimangono vincoli del
confronto. Profondità massima, BAQ e letture considerate non vengono modificati
per ridurre il lavoro. I test includono pileup, finestre sovrapposte, bordi dei
blocchi, QNAME ripetuti, indel, alta copertura, ordine dei risultati e annullamento.
Il core scientifico resta R; Windows conserva WSL2, macOS Lima e Linux Docker
Engine.

SNP 2.0 e un ulteriore modulo scientifico sono attesi come nuovi sorgenti.
La loro integrazione e ottimizzazione saranno definite dopo averne esaminato
script e contratti. L'attuale preparazione SNPcall da BAM non determina le
scelte sulla futura versione del modulo.

## Metodo di verifica

La [revisione 0.8.9](OPTIMIZATION_0.8.9.md) usa i sorgenti congelati della 0.8.5
come riferimento. I controlli distinguono equivalenza dei risultati,
misure delle prestazioni e funzionamento sulle piattaforme finali.
Le build di sviluppo sono identificate da commit e build; il completamento
dei test non pubblica automaticamente un aggiornamento.

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

# Sviluppo e validazione

La versione stabile di NIPAT Desktop è la **0.8.50**, con DNPcall, SNPcall 2.0,
Contamination, CPI prenatale e CPIN postnatale. Le [note 0.8.50](RELEASE_0.8.50.md)
distinguono modifiche e verifiche. Il prodotto mantiene una CLI guidata e
workflow automatici su Windows, macOS e Ubuntu. DNP e SNP conservano i
rispettivi riferimenti 0.8.5 e upstream 2.0; CPI, Contamination e CPIN usano
il riferimento NEWPAT congelato il 13 novembre 2026.

La 0.8.50 collega i conteggi di entrambi i caller a tutte le combinazioni dei
tre moduli successivi, con rami indipendenti, ruoli espliciti e parametri
configurabili. Le costanti del modello sono consultabili e i valori effettivi
sono registrati in ogni run. Il modulo fetal sex resta fuori da questa versione.

## Priorità

| Area | Obiettivo |
| --- | --- |
| Validazione di dominio | Confrontare risultati e parametri su casi rappresentativi degli utilizzi scientifici previsti. |
| Tracciabilità | Collegare senza ambiguità nomi originali, identità interne, fasi e risultati. |
| Uso delle risorse | Conservare la distinzione fra configurazione salvata, risorse effettive, suggerimenti e modifiche; Invio mantiene i valori correnti. |
| Prestazioni | Misurare la 0.8.50 su BAM reali con risorse e alimentazione del computer comparabili, includendo più di due BAM e tutti i moduli; mantenere un unico budget di calcolo e confrontare tempi e RAM a parità di parametri. I blocchi DNP iniziali da 32 MiB / 64 loci restano configurabili. |
| Portabilità | Raccogliere prove reali Windows 10/11, Ubuntu e Mac Intel/Apple Silicon oltre ai controlli automatici. |
| Interfaccia | Esporre fase, campione, tempo trascorso e attività anche senza diagnostica; usare avanzamento e tempo residuo solo quando misurabili o stimabili con dati sufficienti. |
| GUI | Riutilizzare i contratti della CLI e gli eventi di avanzamento in una futura interfaccia grafica. |
| Lingue | Estendere italiano e inglese dal catalogo scientifico all'interfaccia e alla documentazione, senza duplicare le regole applicative. |

## Parallelismo introdotto nella 0.8.12

La modalità iniziale è automatica, con scelta seriale e massimo manuale dei
processi R di calcolo. CPU della VM, quota del container e memoria disponibile
limitano il numero effettivo; campioni, blocchi e altri livelli interni non
moltiplicano i pool. Il coordinatore in attesa è distinto dai processi di
calcolo, e il massimo manuale non è un limite ai PID totali del container.

Menu e CLI espongono gli stessi parametri. Le preferenze del menu valgono
per gli avvii guidati successivi; il riepilogo permette un override per la
singola analisi. I MiB del blocco misurano input grezzo, non RAM residente:
dimensioni e stime di memoria devono essere verificate con il parallelismo.

Per ciascun modulo la qualificazione confronta seriale e parallelo con il
rispettivo riferimento scientifico e gli stessi parametri, distinguendo i
cambiamenti intenzionali di modello dalle ottimizzazioni. Include determinismo
delle ripetizioni e prova di processi realmente contemporanei entro il budget. Il
[protocollo prestazioni](PERFORMANCE.md#collaudo-del-parallelismo-0812) richiede
poi gli stessi input reali e risorse fisse per confrontare tempi e RAM.
I test di sviluppo non sostituiscono questo collaudo o le prove dei pacchetti
sulle piattaforme finali. La pubblicazione richiede inoltre i gate della release
descritti in [CI/CD](CI_CD.md).

## Prototipo 0.8.10 — contesto precedente

La 0.8.10 ha costituito il prototipo integrato per le prove precedenti,
sviluppato in commit distinti e verificabili. La
[guida dedicata](PROTOTYPE_0.8.10.md) conserva identità e procedura di collaudo.
Le direzioni considerate comprendevano accesso indicizzato alle regioni BAM,
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

La 0.8.30 integra SNPcall 2.0 dopo l'esame del nuovo sorgente e del suo
contratto: qualità, likelihood, genotipi, raggruppamento per SNP e QNAME,
statistiche degli indel e riepiloghi. La successiva 0.8.50 integra CPIN e i
nuovi modelli CPI e Contamination; i riferimenti storici restano congelati.

## Metodo di verifica

La [revisione 0.8.9](OPTIMIZATION_0.8.9.md) documenta i confronti storici con
la 0.8.5. Per la versione corrente, i sorgenti indipendenti sotto
`tests/reference_r/` identificano il riferimento appropriato a ogni modulo;
le differenze intenzionali, come la nuova quota Contamination, non vengono
forzate a riprodurre il modello precedente. I controlli distinguono equivalenza dei risultati,
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

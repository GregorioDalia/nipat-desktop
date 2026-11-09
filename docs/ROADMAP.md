# Sviluppo e validazione

La versione stabile di NIPAT Desktop è la 0.8.9; il candidato corrente di
sviluppo è la **0.8.12**, con parallelismo interno ai quattro programmi R e
blocchi DNP configurabili. La [guida 0.8.12](PARALLELISMO_0.8.12.md) descrive
impostazioni e limiti. Il prodotto mantiene una CLI guidata e workflow
automatici su Windows, macOS e Ubuntu; la baseline scientifica resta la
0.8.5 congelata, non l'ultimo candidato di prestazioni.

## Priorità

| Area | Obiettivo |
| --- | --- |
| Validazione di dominio | Confrontare risultati e parametri su casi rappresentativi degli utilizzi scientifici previsti. |
| Tracciabilità | Collegare senza ambiguità nomi originali, identità interne, fasi e risultati. |
| Uso delle risorse | Conservare la distinzione fra configurazione salvata, risorse effettive, suggerimenti e modifiche; Invio mantiene i valori correnti. |
| Prestazioni | Qualificare il parallelismo R della 0.8.12 su tutti i moduli, con un unico budget di calcolo e blocchi DNP iniziali da 32 MiB / 64 loci; misurare tempi e RAM senza modificare i risultati. |
| Portabilità | Raccogliere prove reali Windows 10/11, Ubuntu e Mac Intel/Apple Silicon oltre ai controlli automatici. |
| Interfaccia | Esporre fase, campione, tempo trascorso e attività anche senza diagnostica; usare avanzamento e tempo residuo solo quando misurabili o stimabili con dati sufficienti. |
| GUI | Riutilizzare i contratti della CLI e gli eventi di avanzamento in una futura interfaccia grafica. |
| Lingue | Estendere italiano e inglese dal catalogo scientifico all'interfaccia e alla documentazione, senza duplicare le regole applicative. |

## Candidato 0.8.12

La modalità iniziale è automatica, con scelta seriale e massimo manuale dei
processi R di calcolo. CPU della VM, quota del container e memoria disponibile
limitano il numero effettivo; campioni, blocchi e altri livelli interni non
moltiplicano i pool. Il coordinatore in attesa è distinto dai processi di
calcolo, e il massimo manuale non è un limite ai PID totali del container.

Menu e CLI espongono gli stessi parametri. Le preferenze del menu valgono
per gli avvii guidati successivi; il riepilogo permette un override per la
singola analisi. I MiB del blocco misurano input grezzo, non RAM residente:
dimensioni e stime di memoria devono essere verificate con il parallelismo.

I requisiti di qualificazione sono equivalenza con la 0.8.5 in seriale,
automatico, massimo 2 e massimo 4, determinismo delle ripetizioni e prova
di processi realmente contemporanei entro il budget. Il
[protocollo prestazioni](PERFORMANCE.md#collaudo-del-parallelismo-0812) richiede
poi gli stessi input reali e risorse fisse per confrontare tempi e RAM.
I test di sviluppo non sostituiscono questo collaudo o le prove dei pacchetti
sulle piattaforme finali; non costituiscono autorizzazione alla pubblicazione.

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

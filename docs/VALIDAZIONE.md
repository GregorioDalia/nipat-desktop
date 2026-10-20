# Scheda per le prove dell'esperta di dominio

Il successo degli autotest verifica la riproduzione dei casi inclusi. Questa
scheda serve a valutare il comportamento con altri input e a distinguere
problemi di utilizzo, problemi tecnici e discrepanze scientifiche.

Per ciascuna prova registrare:

| Campo | Da compilare |
| --- | --- |
| Identificativo del caso, senza dati identificativi personali | |
| Versione del pacchetto e nome del run | |
| Workflow | |
| Modalità di input: BAM/lista, pileup, file/cartella, pannello/cutoff/ALL | |
| Tipologia e provenienza degli input; pannello e riferimento | |
| Percorsi esterni al progetto e destinazione dei risultati utilizzati | |
| Parametri modificati rispetto ai valori predefiniti | |
| Risultato atteso e sua fonte: analisi indipendente, caso noto, altro | |
| Risultato osservato: conteggi, stime, grafici pertinenti | |
| Esito: concordante, discordante, non valutabile | |
| Difficoltà di utilizzo o messaggi poco chiari | |
| File condivisibili per riprodurre la prova | |

La selezione dei casi spetta all'esperta. Sono particolarmente utili campioni
con risultati noti, coperture differenti, siti con letture inattese, casi
senza siti informativi e input con intestazioni o percorsi non validi.
Per CPI servono coppie e frequenze appropriate; per DNPcall/SNPcall un confronto
indipendente dei conteggi consente di andare oltre la verifica dell'esecuzione.

Per `0.2.0a2`, verificare anche l'utilizzo di input nelle loro cartelle originali,
percorsi con spazi e una destinazione dei risultati diversa da quella predefinita.
Per DNPcall controllare la corrispondenza fra gli alias e i BAM originali nelle
prove con più campioni. Quando possibile, confrontare modalità equivalenti:
elenco BAM e singoli argomenti; SNPcall da BAM e dal relativo pileup; singoli
input Contamination e una cartella contenente gli stessi file; un pannello CPI
e lo stesso pannello passato come cutoff. I casi con più cutoff devono riportare
risultati distinti per le etichette selezionate.

Le verifiche Windows di `0.2.0a2`, incluso `scripts/verify_input_modes.py` e
un confronto DNPcall da BAM reale con un run precedente, sono descritte in
[DISTRIBUZIONE.md](DISTRIBUZIONE.md). Coprono i casi riportati sul PC di sviluppo;
le prove dell'esperta devono estendere la copertura e valutare i risultati
scientifici su riferimenti indipendenti quando disponibili.

Annotare separatamente un errore del programma e un risultato scientifico
inatteso. Per esempio, una stima `NA` in assenza di siti informativi può essere
l'esito previsto. Un run che termina correttamente non implica, da solo,
che il risultato sia scientificamente corretto per quel caso.

Conservare `run.json`, `execution.log` e `work/input-mounts.json` insieme ai risultati. Condividere
input o risultati solo tramite un canale appropriato al contenuto; i nomi
dei campioni nei metadati non sono anonimizzati automaticamente.

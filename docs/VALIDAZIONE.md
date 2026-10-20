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
| Tipologia e provenienza degli input; pannello e riferimento | |
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

Annotare separatamente un errore del programma e un risultato scientifico
inatteso. Per esempio, una stima `NA` in assenza di siti informativi può essere
l'esito previsto. Un run che termina correttamente non implica, da solo,
che il risultato sia scientificamente corretto per quel caso.

Conservare `run.json` ed `execution.log` insieme ai risultati. Condividere
input o risultati solo tramite un canale appropriato al contenuto; i nomi
dei campioni nei metadati non sono anonimizzati automaticamente.

# Scheda per le prove di validazione di dominio

Il successo degli autotest verifica la riproduzione dei casi inclusi. Questa
scheda serve a valutare il comportamento con altri input e a distinguere
problemi di utilizzo, problemi tecnici e discrepanze scientifiche.

La pre-release **0.4.1** è destinata alle prove di dominio su Windows 11 x64.
Il percorso WSL assume WSL2 già funzionante; l’installatore alternativo
richiede Docker Desktop installato e avviato con container Linux.
Registrare separatamente installazione e analisi per ciascun pacchetto,
riportando il comportamento osservato.

Prima delle analisi registrare una sola volta:

| Ambiente e preparazione | Da compilare |
| --- | --- |
| Versione Windows; versione WSL o Docker Desktop, secondo il pacchetto scelto | |
| Versione NIPAT, pacchetto e pagina della release | |
| Prima installazione o aggiornamento di una copia esistente | |
| Configurazione e autotest completati senza errori | |
| Apertura del menu NIPAT e cartella risultati scelta | |

Per il setup WSL, lo stato e il log si trovano in
`%LOCALAPPDATA%\Programs\NIPAT\.runtime\installer` (`state.json` e `setup.log`).
Per Docker Desktop, conservare `setup.log` (riepilogo della preparazione) e
`setup-checks.log` (dettagli di `doctor` e autotest) nella cartella
`%LOCALAPPDATA%\Programs\NIPAT-DockerDesktop\.runtime`.
In caso di errore conservare entrambi e registrare l'impedimento prima
di passare ai test scientifici. L'abilitazione iniziale di WSL e la ripresa
dopo riavvio Windows sono prove separate, ancora aperte.

## Prima prova con Docker Desktop

1. Avviare Docker Desktop in modalità **container Linux**. Scaricare
   [NIPAT-DockerDesktop-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.4.1/NIPAT-DockerDesktop-Setup.exe)
   ed eseguirlo con doppio clic. La copia WSL già installata può restare presente.
2. Aprire **NIPAT (Docker Desktop)** dal desktop o dal menu Start. Attendere la
   preparazione automatica e gli autotest, dopo i quali compare il menu. Non
   occorre eseguire script separati. In caso di errore conservare
   `setup.log` e `setup-checks.log`,
   verificare Docker Desktop e riaprire la stessa icona per riprovare.
3. Verificare versione `0.4.1` e menu; con **5 — Cartella risultati** scegliere
   una destinazione per questa prova. Usare l'icona Docker Desktop, non quella
   dell'installazione WSL; l'avvio normale esegue analisi reali, senza `--dry-run`.
4. Scegliere **1 — DNPcall** e inserire un BAM di un caso noto, il FASTA con
   indice `.fai` e il pannello DNP appropriati. Controllare il riepilogo e
   confermare **Avvia analisi**. Attendere il completamento, aprire i risultati
   e confrontare conteggi/genotipi con il riferimento disponibile per quel caso.
5. Tornare al menu e scegliere **3 — Contamination**. Come input selezionare
   la tabella `full_output_*.txt` in `output\individual_outputs` del run DNPcall
   appena concluso, usando il pannello corrispondente. Confermare l'analisi e
   verificare riepilogo e risultati per sito, registrando valori attesi e osservati.

Questa sequenza esegue calcoli reali. Ogni analisi ha una propria cartella del
run con `output`, `work`, `run.json` ed `execution.log`; si possono aprire dalla
schermata finale. Annotare separatamente il successo tecnico e la concordanza
scientifica. Per SNPcall e CPI proseguire con casi appropriati secondo la
[guida per l'utilizzo](GUIDA_UTILIZZO.md#input-dei-quattro-workflow).

## Registrazione delle analisi

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

La selezione dei casi richiede competenze di dominio. Sono particolarmente utili campioni
con risultati noti, coperture differenti, siti con letture inattese, casi
senza siti informativi e input con intestazioni o percorsi non validi.
Per CPI servono coppie e frequenze appropriate; per DNPcall/SNPcall un confronto
indipendente dei conteggi consente di andare oltre la verifica dell'esecuzione.

Verificare anche l'utilizzo di input nelle loro cartelle originali,
percorsi con spazi e una destinazione dei risultati diversa da quella predefinita.
Per DNPcall controllare la corrispondenza fra gli alias e i BAM originali nelle
prove con più campioni. Quando possibile, confrontare modalità equivalenti:
elenco BAM e singoli argomenti; SNPcall da BAM e dal relativo pileup; singoli
input Contamination e una cartella contenente gli stessi file; un pannello CPI
e lo stesso pannello passato come cutoff. I casi con più cutoff devono riportare
risultati distinti per le etichette selezionate.

Le verifiche Windows di `0.2.0a2`, incluso `scripts/verify_input_modes.py` e
un confronto DNPcall da BAM reale con un run precedente, sono descritte in
[DISTRIBUZIONE.md](DISTRIBUZIONE.md). Coprono i casi riportati sul PC di sviluppo.
Le ulteriori prove sul candidato WSL del 21 ottobre sono riportate in
[INSTALLATORE_WINDOWS.md](INSTALLATORE_WINDOWS.md). Le prove di dominio devono estendere la copertura e valutare i risultati
scientifici su riferimenti indipendenti quando disponibili.

Annotare separatamente un errore del programma e un risultato scientifico
inatteso. Per esempio, una stima `NA` in assenza di siti informativi può essere
l'esito previsto. Un run che termina correttamente non implica, da solo,
che il risultato sia scientificamente corretto per quel caso.

Conservare `run.json`, `execution.log` e `work/input-mounts.json` insieme ai risultati. Condividere
input o risultati solo tramite un canale appropriato al contenuto; i nomi
dei campioni nei metadati non sono anonimizzati automaticamente.

# Parallelismo e blocchi — sviluppo 0.8.12

La 0.8.12 introduce un'impostazione comune per distribuire il calcolo nei
quattro programmi R. È un candidato di sviluppo: questa guida non dichiara
completati il collaudo sui dati reali o la validazione dei pacchetti finali.
I requisiti di equivalenza restano quelli del [riferimento 0.8.5](#equivalenza-e-collaudo).

## Impostazioni

| Impostazione | Valore iniziale | Significato |
| --- | --- | --- |
| Modalità di calcolo R | Automatica (`auto`) | Sceglie quanti processi di calcolo usare entro le risorse e il lavoro disponibili. Può scegliere un solo processo. |
| Massimo processi R di calcolo | Automatico, senza un ulteriore massimo manuale | Un numero esplicito limita la scelta automatica; non impone di raggiungerlo. |
| Dimensione obiettivo blocchi DNP | 32 MiB | Quantità obiettivo di pileup grezzo per blocco, non RAM occupata dal processo. |
| Massimo obiettivo loci per blocco DNP | 64 | Numero obiettivo di loci completi per blocco. |

La modalità `serial` mantiene un solo processo R di calcolo, anche se è
salvato un massimo maggiore. I valori dei blocchi si applicano a DNPcall;
modalità e massimo di processi valgono per tutti e quattro i moduli e per
le analisi dei workflow automatici.

I limiti accettati sono interi: 1–1024 processi di calcolo, 1–4096 MiB e
1–1.000.000 loci. Sono intervalli di configurazione, non raccomandazioni sui
valori più alti. Finestre complete, QNAME condivisi e gruppi necessari alla
compatibilità non vengono spezzati: un blocco indivisibile può superare gli
obiettivi di MiB o loci. I valori 32 MiB / 64 loci sono un punto di partenza
per il collaudo, non un optimum dimostrato per ogni dataset.

## Un unico budget di calcolo

Il massimo conta i **processi R che svolgono il calcolo in parallelo**.
Un coordinatore R in attesa può aggiungersi: massimo 4 non significa che
il sistema operativo mostrerà al più quattro PID R. Anche samtools, il
motore Python e il monitoraggio hanno processi propri. Il limite globale
dei PID del container (`--pids-limit`) è un'altra impostazione.

Con un massimo di 4, DNPcall può distribuire quattro campioni, oppure i
blocchi di un campione. Un campione già eseguito da un processo figlio
elabora i propri blocchi in serie: quattro campioni non aprono altri quattro
processi ciascuno. Lo stesso criterio impedisce pool annidati negli altri
moduli; le librerie numeriche sono limitate a un thread per processo.
I passaggi di un workflow composto restano sequenziali.

| Modulo | Lavoro distribuito quando utile e compatibile con il budget |
| --- | --- |
| DNPcall | Campioni; se il livello campioni non usa processi figli, blocchi completi del campione corrente. |
| SNPcall | Gruppi completi di letture per QNAME, anche quando attraversano più loci. |
| Contamination | Campioni distinti; per un singolo campione grande, porzioni contigue delle righe. |
| CPI | Coppie; se il livello superiore resta seriale, pannelli/cutoff o intervalli di soglie. |

La raccolta ripristina l'ordine previsto prima delle aggregazioni e della
scrittura. Formule, filtri, soglie scientifiche e ordine delle riduzioni
numeriche devono rimanere equivalenti al riferimento; il parallelismo non
implica che lettura, preparazione, grafici e ogni istruzione R siano paralleli.

## Come viene scelto il numero di processi

La scelta automatica considera il minimo fra lavoro indipendente disponibile,
CPU accessibili al processo, quota CPU del container, massimo manuale,
disponibilità di PID e stima della memoria. Su Windows il calcolo avviene
nel runtime Linux di WSL2; su macOS in Lima. Aumentare le CPU della VM può
rendere disponibili più processi, senza obbligare NIPAT a usarli tutti.
Una quota CPU frazionaria viene arrotondata per difetto, con almeno un
processo di calcolo.

La stima usa la memoria ancora disponibile, considerando i limiti effettivi
del container, e ne lascia il 20% come margine. Riserva almeno **2 GiB per
processo di calcolo**. Per DNPcall aumenta questa stima se necessario in
base al blocco grezzo più grande effettivamente pianificato:
`max(2048, 512 + 48 × MiB del blocco più grande)`, in MiB e arrotondato per
eccesso. Quindi conta anche un blocco indivisibile oltre il target configurato.
Se la memoria disponibile non è rilevabile, la scelta è seriale.

Questi numeri sono **euristiche di pianificazione, non limiti RAM garantiti**.
Espansione delle osservazioni, join, copie e oggetti R possono richiedere più
memoria. La scelta conserva almeno un processo anche con poca RAM: ciò non
garantisce che il dataset sia elaborabile. `--memory-mb` imposta invece il
limite del container e può provocarne l'arresto se insufficiente; non aumenta
la memoria assegnata a WSL o Lima. Vedere [Risorse e memoria](RISORSE.md).

## Menu e preferenze

Per i valori predefiniti delle prossime analisi guidate:

1. **5 — Configura → 9 — Risorse, prestazioni e provenienza →
   6 — Parallelismo e blocchi**.
2. Scegliere **1 — Modalità di calcolo R**, **2 — Massimo processi R di
   calcolo**, **3 — Dimensione obiettivo blocchi DNP (MiB)** oppure
   **4 — Massimo obiettivo loci per blocco DNP**.
3. **9 — Applica questi valori** torna al menu precedente; scegliere ancora
   **9 — Salva modifiche** per conservarli nelle preferenze.

Invio mantiene il valore corrente. Nel massimo di processi, `:vuoto`
ripristina la scelta automatica senza massimo manuale. **0 — Annulla
modifiche** scarta le modifiche non confermate nel menu corrente.

Per una sola analisi, nel riepilogo finale scegliere **4 — Parallelismo e
blocchi**, modificare e applicare i valori, poi avviare l'analisi. Questa
scelta non cambia le preferenze salvate. Le preferenze esistenti che non
contengono questi campi ricevono i nuovi valori iniziali.

Le opzioni esplicite passate a `wizard` prevalgono sulle preferenze salvate;
il riepilogo permette ancora una modifica per il singolo run. I comandi CLI
diretti non leggono le preferenze del menu e usano i propri argomenti o i
valori iniziali. La diagnostica delle prestazioni rimane facoltativa e non
viene salvata come preferenza.

## CLI

Le quattro opzioni sono **globali e precedono il sottocomando**:
`--execution-mode auto|serial`, `--max-workers N`, `--dnp-block-mib N`,
`--dnp-block-loci N`. Il vecchio `--parallel` di DNPcall rimane accettato
per compatibilità, ma la politica comune determina il parallelismo:
`--execution-mode serial` resta seriale anche in presenza di `--parallel`.
Non occorre aggiungere `--parallel` per usare la modalità automatica.

Esempi PowerShell, dalla cartella applicativa del candidato 0.8.12 contenente
`nipat.cmd`. Sostituire i percorsi con quelli dei propri input; ogni comando
crea un nuovo run. Controllare prima la versione con `.\nipat.cmd --version`.

```powershell
.\nipat.cmd --execution-mode auto --max-workers 4 --dnp-block-mib 32 --dnp-block-loci 64 dnp-call --bam "C:\Dati\campione.bam" --reference "C:\Dati\genome.fa" --panel "C:\Dati\DNP_list.txt" --run-name dnp-max4
.\nipat.cmd --execution-mode serial snp-call --pileup "C:\Dati\snp-pileup.txt" --panel "C:\Dati\SNP_list.txt" --run-name snp-seriale
.\nipat.cmd --execution-mode auto --max-workers 2 contamination --input "C:\Dati\campione-individual.txt" --panel "C:\Dati\DNP_list.txt" --run-name contamination-max2
.\nipat.cmd --execution-mode auto --max-workers 4 cpi --input-dir "C:\Dati\cpi" --pairs "A1:A1" --popfreq "C:\Dati\frequenze.tsv" --run-name cpi-max4
```

Per aprire il menu con un massimo temporaneo:

```powershell
.\nipat.cmd --execution-mode auto --max-workers 2 wizard
```

Su Linux usare `nipat` e percorsi POSIX; su macOS il launcher
`"/Applications/NIPAT Desktop.app/Contents/Resources/NIPAT.command"` con gli
stessi argomenti. Sono disponibili gli stessi parametri anche prima di
`workflow`. La [guida CLI](GUIDA_UTILIZZO.md#comandi-diretti) descrive i launcher.

## Controllare il lavoro effettivo

Ogni invocazione scientifica registra le decisioni in `work/parallel/*.jsonl`;
nei workflow composti la cartella appartiene al singolo passaggio,
`steps/<id>/work/parallel/`. Questi eventi sono prodotti anche senza attivare
la diagnostica delle prestazioni.

Gli eventi `plan`, `task-start` e `task-end` riportano modalità, massimo
richiesto, processi scelti (`workers`), disponibilità stimata, motivazione,
PID, indice dell'attività e tempi. Per dimostrare calcolo simultaneo occorrono
intervalli di attività sovrapposti in PID distinti: il valore richiesto o
il solo numero totale di PID osservati non bastano. Per DNPcall,
`work/dnp-blocks.json` registra inoltre il piano e le misure dei blocchi.

Tempi complessivi, CPU e picco RAM del container richiedono la
[diagnostica delle prestazioni](PERFORMANCE.md); gli eventi di parallelismo
non sostituiscono queste misure.

## Equivalenza e collaudo

Il riferimento è **NIPAT v0.8.5**, commit
`eafadf7002a9c7d7c1b9af9ccafc47d698a059e5`, con copie congelate e checksum in
[`tests/reference_r/0.8.5`](../tests/reference_r/0.8.5/README.md). Include le
modifiche di compatibilità già distribuite in quella versione: non coincide
con una dichiarazione di sorgenti upstream mai modificati. La baseline non
viene aggiornata per far passare un candidato.

La qualificazione deve confrontare tutti e quattro i moduli contro questa
stessa baseline: seriale, automatico, massimo 2, massimo 4 e ripetizione delle
condizioni parallele. Il [contratto dei test R](../tests/r_optimization/README.md)
richiede tabelle identiche anche nell'ordine, valori R non arrotondati identici,
PDF equivalenti nelle pagine renderizzate e input invariati. I test paralleli
devono dimostrare processi di calcolo realmente sovrapposti, senza superare
il budget effettivo. I casi sintetici non dimostrano un aumento delle
prestazioni sui dati reali o il funzionamento di ogni installer.

Il [protocollo 0.8.12](PERFORMANCE.md#collaudo-del-parallelismo-0812) separa
equivalenza, determinismo e misure di velocità/RAM. Restano necessari il
confronto sul dataset reale concordato, prove ripetute a risorse fisse e il
collaudo delle piattaforme finali prima di una release. I dati grezzi e i
risultati identificativi non vanno pubblicati nel repository.

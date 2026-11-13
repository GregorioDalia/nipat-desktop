# Diagnostica delle prestazioni

NIPAT può registrare tempi, processi, CPU, memoria e I/O durante un'analisi.
La raccolta è facoltativa e introduce un costo di monitoraggio. Per misurare
il tempo d'uso ordinario, eseguire prove senza diagnostica. Per individuare
la fase che pesa di più o interpretare un arresto, ripetere la prova con
diagnostica mantenendo gli stessi input e parametri.

## Prima misura dal menu

1. Aprire **NIPAT Desktop** e annotare la versione mostrata nel banner.
   Eseguire **8 — Verifica ambiente** prima di iniziare.
2. Scegliere l'analisi da misurare. Per DNPcall usare un BAM, un FASTA
   indicizzato dello stesso assemblaggio e il pannello DNP. Un indice
   BAM accanto al file consente il percorso indicizzato quando applicabile.
3. Nel riepilogo controllare input, parametri, destinazione e modalità.
   Assegnare un nome nuovo al run e selezionare **Avvia analisi**.
4. Ripetere l'analisi con un altro nome e scegliere **Avvia analisi con
   diagnostica prestazioni**. La scelta vale per quel run.
5. Nella cartella del secondo run aprire `run-report.html` e vedere
   **Diagnostica delle prestazioni**. Confrontare anche le tabelle ottenute.

Una coppia di prove consente di controllare la raccolta. Per confrontare
due modalità di esecuzione usare il
[protocollo di ripetizione](#protocollo-per-input-reali). I
[requisiti dei file](GUIDA_UTILIZZO.md#input-dei-cinque-moduli)
valgono anche per il benchmark.

## Attivazione per una singola analisi

La CLI accetta `--performance-diagnostics` prima del comando di
analisi singola o del workflow. Esempio su Ubuntu:

```sh
nipat --performance-diagnostics dnp-call \
  --bam "/dati/campione.bam" --reference "/dati/genome.fa" \
  --panel "/dati/DNP_list.txt" --run-name dnp-diagnostica-01
```

Per Windows o macOS usare il
[launcher del pacchetto](GUIDA_UTILIZZO.md#comandi-diretti).
Con `nipat --performance-diagnostics wizard` il menu propone
la diagnostica per l'analisi successiva; il riepilogo permette di scegliere
l'avvio ordinario. Il flag richiede un motore che dichiari l'interfaccia
`performance-diagnostics-v1`.

## Confrontare seriale e automatico

| Modalità | Opzioni globali prima del comando |
| --- | --- |
| Seriale | `--execution-mode serial` |
| Automatica | `--execution-mode auto` |
| Automatica con massimo di due processi di calcolo | `--execution-mode auto --max-workers 2` |

Il massimo richiesto è un limite. Quota CPU, memoria disponibile e quantità
di lavoro possono ridurre i worker effettivi. I processi di coordinamento
si osservano a parte. Il budget si applica alle attività di calcolo senza
moltiplicare pool interni. In DNPcall l'acquisizione del pileup, eventualmente
in parallelo per cromosoma, precede il calcolo R. Per un primo confronto
mantenere fissi i valori iniziali di **32 MiB** di input grezzo e **64
loci** per blocco. La dimensione obiettivo in MiB descrive i dati del blocco;
la RAM effettiva dipende dal calcolo.

Dal menu usare **Parallelismo e blocchi** nel riepilogo per cambiare la
modalità del singolo run. Le impostazioni comuni si conservano in
**Configura → Risorse, prestazioni e provenienza**. In CLI, ad esempio
su Windows dopo [aver individuato il launcher](GUIDA_UTILIZZO.md#comandi-diretti):

```powershell
& $nipat --execution-mode serial dnp-call --bam ".\campione.bam" --reference ".\genome.fa" --panel ".\DNP_list.txt" --run-name dnp-seriale-01
& $nipat --execution-mode auto dnp-call --bam ".\campione.bam" --reference ".\genome.fa" --panel ".\DNP_list.txt" --run-name dnp-auto-01
```

Per verificare lavoro in parallelo, cercare intervalli sovrapposti degli
eventi dei worker in `work/parallel/*.jsonl`, oppure nel `work` del
singolo passaggio. L'acquisizione DNP riporta anche processi osservati
in `dnp-pileup.json`.

## Misure e significato

| Misura | Che cosa include |
| --- | --- |
| Tempo totale | Avvio del client e dell'ambiente, preparazione, calcolo e finalizzazione; misurato dal supervisore. |
| Tempo del run | Intervallo fra `started_at` e `finished_at` in `run.json`. |
| Tempo di un passaggio | Intervallo del passaggio in `workflow-state.json`, con preparazione, calcolo e verifica. Passaggi paralleli possono sovrapporsi. |
| Durata delle fasi | Confini registrati dal motore con orologio monotono. La fase R può comprendere samtools, calcolo e grafici. Le fasi annidate si sovrappongono. |
| Memoria Docker | Misura dell'osservatore esterno. Su Linux la CLI Docker riduce il valore della cache inattiva. |
| Memoria cgroup | Memoria contabilizzata dal kernel per il gruppo, incluse quote di cache. Il picco è disponibile quando il contatore è esposto e letto. |
| RSS dei processi | Memoria residente di R, samtools o supervisore. Pagine condivise possono comparire in più RSS. |
| CPU e I/O | Contatori disponibili al container. Cache, filesystem condiviso e virtualizzazione possono limitare l'attribuzione delle operazioni. |

Usare la stessa fonte per confrontare la RAM. Il massimo delle
rilevazioni periodiche può perdere un picco fra due campioni. Anche il
picco del kernel si riferisce all'ultimo campione riuscito. Una misura
mancante rimane **non disponibile**. Il codice di uscita 137 indica una
terminazione: per attribuirla alla memoria controllare l'indicatore
`OOMKilled` e [la diagnostica delle risorse](RISORSE.md#errori-di-memoria-e-codice-137).

## Consultazione dei risultati

| File | Contenuto |
| --- | --- |
| `run-report.html` | Riepilogo leggibile e collegamenti alle misure. |
| `performance/summary.json` | Riepilogo della raccolta esterna Docker. |
| `performance/container-samples.jsonl` | Campioni delle risorse del container. |
| `performance/engine/summary.json` | Disponibilità e riepilogo delle misure raccolte nel motore. |
| `performance/engine/samples.jsonl` | Campioni cgroup e dei processi. |
| `performance/engine/phases.jsonl` | Inizio, fine e durata delle fasi osservate. |
| `work/parallel/*.jsonl` | Budget ed eventi dei worker. |
| `work/dnp-acquisition-budget.json` | Budget per l'acquisizione del pileup DNP. |
| `work/dnp-pileup.json` | Strategia di acquisizione DNP, tempi e processi osservati. |
| `work/dnp-blocks.json` | Acquisizione, indicizzazione e calcolo DNP, con lavoro dei blocchi. |

Per un workflow composto gli ultimi quattro percorsi sono relativi ai
passaggi che li producono, sotto `output/workflow/steps/<id>/`. Usare
la durata osservata della fase come tempo trascorso. La somma dei tempi
di task concorrenti descrive lavoro aggregato.

La raccolta può essere incompleta se il run è breve, viene interrotto
o raggiunge i limiti dei file diagnostici. Verificare lo stato della
raccolta insieme allo stato scientifico del run. I log e i rapporti
possono contenere nomi e percorsi originali dei campioni.

<a id="protocollo-per-un-bam-grande"></a>

## Protocollo per input reali

1. Preparare gli stessi file, indici, pannelli, frequenze, ruoli e ordine
   dei campioni. Annotare versione, immagine scientifica, parametri
   effettivi e politica dei checksum.
2. Tenere fissi computer, dischi, alimentazione, profilo energetico,
   risorse WSL/Lima e limiti del container. Annotare eventuale carico
   concorrente. La prima lettura e le seguenti possono usare le cache in
   modo diverso. Anche il calcolo degli hash completi legge tutti i byte.
3. Alternare le condizioni e, se sostenibile, ripetere almeno tre
   volte. Usare nomi dei run distinti. Riportare mediana, variabilità
   e condizioni di misura. Conservare anche fallimenti e interruzioni.
4. Verificare risultati e identità dei campioni oltre ai tempi. Tener
   distinte le prove su BAM reali dalle fixture sintetiche. Per CPI e
   CPIN fissare coppie o terne, pannelli, cutoff e frequenze.
5. Modificare una scelta alla volta. Per DNP separare acquisizione,
   indice e calcolo dei blocchi. Per i workflow misurare il totale e i
   passaggi, considerando le possibili sovrapposizioni.

Dal checkout si può usare il supervisore
[`scripts/benchmark_workflows.py`](../scripts/benchmark_workflows.py)
nell'ambiente configurato per il progetto. Esempio con un BAM, espresso
da un elenco di una riga, per DNPcall con diagnostica:

```sh
python scripts/benchmark_workflows.py \
  --bamlist /dati/un-campione.txt --reference /dati/genome.fa \
  --panel /dati/DNP_list.txt --output-dir /risultati/benchmark-dnp \
  --sample-counts 1 --repeats 3 --workflow dnp-call --performance-diagnostics
```

Il supervisore misura DNPcall o DNPcall → Contamination con campioni
distinti. Salvare ogni condizione in una nuova directory. Per una prova
ordinaria omettere `--performance-diagnostics`. In `benchmark.json`
rimangono tempi, risorse, input e riepiloghi disponibili. I risultati
del [collaudo sintetico installato](COLLAUDO_INSTALLAZIONE.md) riguardano
i casi noti; i tempi attesi per altri dataset richiedono misure sul
computer e sui file di interesse.

## Riferimenti tecnici

- [Risorse e memoria](RISORSE.md)
- [Registri delle esecuzioni](ESECUZIONI.md)
- [Statistiche Docker](https://docs.docker.com/reference/cli/docker/container/stats/)
- [Contatori cgroup v2 del kernel Linux](https://docs.kernel.org/admin-guide/cgroup-v2.html)

## Archivio dei collaudi

Questi riferimenti preservano i protocolli e le evidenze associati alle versioni
indicate nei relativi documenti. Per nuovi benchmark seguire
il [protocollo corrente](#protocollo-per-input-reali).

<a id="collaudo-dei-cinque-moduli-nella-0850"></a>
<a id="collaudo-del-parallelismo-0812"></a>
<a id="collaudo-del-pileup-parallelo-0813"></a>
<a id="collaudo-delle-ottimizzazioni-0814"></a>

- [Evidenze dei cinque moduli](DEVELOPMENT_0.8.50.md#verifica-prima-di-una-distribuzione)
- [Protocollo di equivalenza e parallelismo](PARALLELISMO_0.8.12.md#equivalenza-e-collaudo)
- [Preparazione parallela del pileup](PILEUP_0.8.13.md#collaudo-windows)
- [Ottimizzazioni e misure su input reali](OPTIMIZATIONS_0.8.14.md#collaudo-sugli-input-reali)

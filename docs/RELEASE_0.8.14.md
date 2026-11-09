# NIPAT Desktop 0.8.14

NIPAT Desktop 0.8.14 introduce la scelta tra esecuzione seriale e automatica,
il limite configurabile dei processi e il pileup DNP parallelo per cromosoma.
La distribuzione del calcolo DNP usa un budget comune ai blocchi di tutti i
campioni: il miglioramento riguarda un numero generico di BAM, anche quando
è maggiore del numero di processi disponibili.

## Modifiche

- **DNP con più BAM:** una coda comune di attività campione/blocco sostituisce
  l'alternativa fra parallelismo sui campioni e sui blocchi. I processi liberi
  possono elaborare altri blocchi senza aspettare la fine di un intero campione.
  La ricomposizione conserva ordine dei campioni, loci e risultati.
- **Budget unico:** seriale, massimo di processi e limiti di memoria si
  applicano alla coda complessiva. Non vengono avviati pool scientifici annidati.
  Le unità che richiedono compatibilità globale rimangono indivisibili.
- **Pileup:** la preparazione per cromosoma conserva l'ordine canonico e il
  percorso seriale di ripiego. Preparazione e calcolo R sono fasi successive.
- **Altri moduli:** parallelismo controllato per SNPcall, Contamination e CPI;
  riuso delle righe informative già calcolate nel riepilogo CPI. Le formule
  scientifiche e i filtri restano invariati.
- **Thread interni:** lettori e librerie numeriche rispettano il budget senza
  aggiungere autonomamente altri gruppi di thread, anche in modalità seriale.
- **Metriche Docker:** la raccolta distingue la normale fine del container
  dagli errori di parsing. Gli errori reali restano espliciti; una prova troppo
  breve può non produrre campioni esterni, senza trasformarli in misure nulle.

Le opzioni globali della CLI precedono il nome dell'analisi:

```powershell
.\nipat.cmd --execution-mode serial dnp-call --bam campione.bam --reference genome.fa --panel DNP_list.txt
.\nipat.cmd --execution-mode auto --max-workers 4 dnp-call --bam campione-a.bam --bam campione-b.bam --bam campione-c.bam --reference genome.fa --panel DNP_list.txt
```

`--bam` è ripetibile; `--bamlist` accetta un elenco di file. Il massimo di
processi è un limite, non un numero garantito. Nel menu le stesse opzioni sono
disponibili nel riepilogo dell'analisi. I blocchi iniziali sono 32 MiB di input
grezzo e 64 loci; non rappresentano un limite rigido della RAM del processo R.

## Evidenze e limiti

Le [misure del precedente candidato 0.8.14](https://github.com/GregorioDalia/nipat-desktop/blob/main/docs/validation/0.8.14-observed-benchmarks.json),
commit `e04ff883fc6417748174d2a7c3b49cadad989308`, comprendono 42 esecuzioni
Windows/WSL. DNP e Contamination usano dati reali; SNP e CPI esempi piccoli.
Le tabelle DNP, SNP e Contamination coincidono fra seriale e automatico;
il controllo CPI informativo verifica anche risultati numerici attesi.

Su quel candidato, i tempi mediani DNP seriale/automatico erano 377,649/122,849
secondi e 191,161/68,071 secondi per i due BAM separati; l'elaborazione congiunta
richiedeva 623,327/291,771 secondi. La fase R congiunta usava due processi,
contro cinque nel caso singolo. Questa osservazione ha guidato la nuova coda
comune; **non misura l'accelerazione della nuova implementazione**.
Gli input reali non sono inclusi nel repository e il nuovo installer non
eredita automaticamente il collaudo manuale del candidato precedente.

Il riferimento scientifico dei confronti automatici rimane la 0.8.5 congelata.
Le verifiche differenziali controllano tabelle, quantità R non arrotondate e
PDF nei casi coperti, insieme a test specifici del budget, di più campioni e
della terminazione del monitoraggio. Le evidenze della build identificano
il commit e l'immagine realmente distribuiti. Gli esempi SNP/CPI non stimano
la scalabilità su dataset grandi; l'indicizzazione globale DNP resta una
fase separata da profilare.

## Installazione e aggiornamento

Scaricare un solo pacchetto dalla
[release 0.8.14](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.14):

| Sistema | Pacchetto |
| --- | --- |
| Windows 10 22H2 x64 / Windows 11 x64 | `NIPAT-Setup.exe` |
| macOS 14 o successivo, Apple Silicon | `NIPAT-0.8.14-macos-arm64.pkg` |
| macOS 14 o successivo, Intel | `NIPAT-0.8.14-macos-x86_64.pkg` |
| Ubuntu 24.04 LTS x86_64 | `nipat-desktop_0.8.14_amd64.deb` |

Da una versione stabile precedente è disponibile **Verifica aggiornamenti**.
Chi ha installato un candidato già denominato 0.8.14 deve invece scaricare
manualmente l'installer ufficiale: l'aggiornatore confronta le versioni, non
i commit. Chiudere le analisi prima dell'aggiornamento; dati, preferenze e
risultati precedenti vengono conservati.

Windows usa WSL2 con Docker Engine gestito dall'applicazione; macOS usa Lima
e, su Apple Silicon, Rosetta; Ubuntu usa Docker Engine locale. Docker Desktop
non è un prerequisito. I pacchetti non hanno una firma NIPAT riconosciuta
dai sistemi e macOS non dispone di notarizzazione Apple. Le verifiche dei
pacchetti Mac non sostituiscono un collaudo completo della VM sui dispositivi
finali. La validazione di dominio resta distinta dai controlli automatici.

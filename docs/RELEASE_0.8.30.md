# NIPAT Desktop 0.8.30

Questa versione integra SNPcall 2.0 e corregge la presentazione dei risultati
scientifici. Gli installer sono pubblicati dopo la qualificazione del codice,
dei pacchetti e delle rispettive evidenze.

## SNPcall 2.0

Il riferimento scientifico è [NEWPAT, commit ce59f4be](https://github.com/lpistacchia/NEWPAT/tree/ce59f4beeeec710b1b42d425cb87d7aad729f71d/SNPcall).
Il sorgente originale è conservato senza modifiche in
[`tests/reference_r/2.0/SNPcall.R`](../tests/reference_r/2.0/SNPcall.R).

- Pannelli `chr, pos, ref, alt`, con compatibilità per i precedenti pannelli
  `pos, ref, alt` dove la posizione è scritta come `chr:pos`.
- Input BAM e pileup con nomi delle letture e qualità; generazione del pileup
  senza il precedente limite predefinito di profondità (`samtools -d 0`).
- Raggruppamento per SNP e nome della lettura, incluse finestre sovrapposte.
- Tabella completa di 17 colonne: conteggi REF/ALT/Other, rapporto REF,
  likelihood GL0/GL1/GL2, genotipo, statistiche sugli indel e conteggi per base.
- Grafici per campione, genotipi aggregati, conteggio dei genotipi non assegnati,
  UpSet per più campioni e misure di tempo e memoria residente.

`ratio` è REF/(REF+ALT), non la frequenza dell'allele alternativo. Le GL sono
logaritmi naturali. Il genotipo resta mancante quando la frazione di Other è
almeno il 10%; i conteggi e le GL restano disponibili. La statistica degli
indel conta la base centrale, mentre l'esclusione della lettura considera
l'intera finestra. Copertura zero e stima mancante sono rappresentate
distintamente.

Le ottimizzazioni mantengono il modello scientifico originale: lettura delle sole
colonne necessarie, aggregazione delle osservazioni e processi entro il budget
CPU/memoria. La modalità seriale resta disponibile. I risultati possono
differire dal vecchio SNP di NIPAT perché il modello scientifico è cambiato;
il confronto di riferimento è ora SNPcall 2.0.

## Presentazione dei quattro moduli

Gli istogrammi di DNP e SNP includono una classe `0`, seguita da `1–5`, `6–10`
e così via. Le etichette corrispondono ai valori effettivi. I pannelli lunghi
sono paginati e le dimensioni dei PDF sono limitate. I grafici CPI sono
suddivisi in pagine leggibili. Riepiloghi e descrizioni chiariscono unità,
genotipi mancanti e significato delle statistiche di Contamination e CPI.

Questi interventi di presentazione non modificano le formule o i risultati
tabellari di DNPcall, Contamination e CPI.

## Verifiche

La qualificazione confronta i risultati di SNP con l'originale 2.0 e mantiene
il riferimento immutabile 0.8.5 per gli altri tre moduli. Sono richiesti
confronti esatti di tabelle e valori R non arrotondati, casi con qualità
diverse, finestre sovrapposte e copertura assente, verifiche delle classi
degli istogrammi e determinismo tra esecuzioni seriali e parallele.

I PDF corretti non devono riprodurre i difetti grafici della vecchia versione:
si verificano contenuto, dimensioni, renderizzabilità e uguaglianza tra le
modalità di esecuzione della nuova versione. Le procedure di pubblicazione
richiedono riferimenti e verifiche specifici per la 0.8.30 e conservano i
vincoli delle release precedenti.

I test locali con R 4.5.0 sono un controllo aggiuntivo. La qualificazione
distributiva usa R 4.4.2 e le dipendenze fissate nell'immagine scientifica.
I BAM reali del collaudo 0.8.20 non sono inclusi nel repository: i relativi
tempi non costituiscono un benchmark della 0.8.30.

## Installazione e aggiornamento

Scaricare un solo pacchetto dalla
[release 0.8.30](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.30),
scegliendo sistema e architettura:

| Sistema | Pacchetto |
| --- | --- |
| Windows 10 22H2 x64 / Windows 11 x64 | [NIPAT-Setup.exe](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.30/NIPAT-Setup.exe) |
| macOS 14 o successivo, Apple Silicon | [NIPAT-0.8.30-macos-arm64.pkg](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.30/NIPAT-0.8.30-macos-arm64.pkg) |
| macOS 14 o successivo, Intel | [NIPAT-0.8.30-macos-x86_64.pkg](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.30/NIPAT-0.8.30-macos-x86_64.pkg) |
| Ubuntu 24.04 LTS x86_64 | [nipat-desktop_0.8.30_amd64.deb](https://github.com/GregorioDalia/nipat-desktop/releases/download/v0.8.30/nipat-desktop_0.8.30_amd64.deb) |

Chi usa la 0.8.20 o una precedente versione compatibile può scegliere
**Verifica aggiornamenti** oppure scaricare il pacchetto dalla release.
Chiudere le analisi prima dell'aggiornamento. Le installazioni riconosciute
conservano percorsi, preferenze, dati e risultati; i run precedenti non vengono
ricalcolati o sovrascritti. I nuovi run SNP usano il modello 2.0, per cui
non devono essere confrontati con il vecchio SNP aspettandosi risultati identici.

Il setup Windows resta privo di firma Authenticode NIPAT: questa versione
non garantisce l'accettazione da parte di Smart App Control. I pacchetti Mac
non sono notarizzati; i controlli automatici non sostituiscono le prove Lima
sui dispositivi finali. Le guide [Windows](INSTALLATORE_WINDOWS.md),
[macOS](INSTALLATORE_MACOS.md) e [Ubuntu](INSTALLATORE_LINUX.md) descrivono
installazione, requisiti e limiti delle rispettive piattaforme.

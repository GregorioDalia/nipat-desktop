# Archivio della documentazione

Questi documenti descrivono release, revisioni e prove identificabili. I relativi file restano ai loro percorsi originali per conservare le citazioni. Per installare o utilizzare NIPAT, partire dalle [guide correnti](../README.md).

## Note di rilascio

| Serie | Note |
| --- | --- |
| 0.8 | [0.8.80](../RELEASE_0.8.80.md) · [0.8.70](../RELEASE_0.8.70.md) · [0.8.60](../RELEASE_0.8.60.md) · [0.8.50](../RELEASE_0.8.50.md) · [0.8.35](../RELEASE_0.8.35.md) · [0.8.30](../RELEASE_0.8.30.md) · [0.8.20](../RELEASE_0.8.20.md) · [0.8.14](../RELEASE_0.8.14.md) · [0.8.9](../RELEASE_0.8.9.md) · [0.8.5](../RELEASE_0.8.5.md) · [0.8.2](../RELEASE_0.8.2.md) · [0.8.0a1](../RELEASE_0.8.0a1.md) |
| 0.7 e 0.6 | [0.7.2](../RELEASE_0.7.2.md) · [0.7.1](../RELEASE_0.7.1.md) · [0.7.0a1](../RELEASE_0.7.0a1.md) · [0.6.0](../RELEASE_0.6.0.md) |
| 0.5, 0.4 e 0.3 | [0.5.0a1](../RELEASE_0.5.0a1.md) · [0.4.1](../RELEASE_0.4.1.md) · [0.4.0](../RELEASE_0.4.0.md) · [0.3.0a2](../RELEASE_0.3.0a2.md) · [0.3.0a1](../RELEASE_0.3.0a1.md) |

## Audit, prove e decisioni

- Audit [0.8.60](../AUDIT_0.8.60.md), [0.8.50](../AUDIT_0.8.50.md) e [0.8.20](../AUDIT_0.8.20.md).
- [Sviluppo 0.8.50](../DEVELOPMENT_0.8.50.md) e [collaudo dell'installazione 0.8.50](../COLLAUDO_INSTALLAZIONE_0850.md).
- Studi sulle prestazioni: [0.8.14](../OPTIMIZATIONS_0.8.14.md), [pileup 0.8.13](../PILEUP_0.8.13.md), [parallelismo 0.8.12](../PARALLELISMO_0.8.12.md), [prototipo 0.8.10](../PROTOTYPE_0.8.10.md) e [ottimizzazioni 0.8.9](../OPTIMIZATION_0.8.9.md).
- Rapporti strutturati: [0.8.50](../validation/0.8.50-development.json), [microbenchmark 0.8.14](../validation/0.8.14-microbenchmarks.json), [benchmark osservati 0.8.14](../validation/0.8.14-observed-benchmarks.json), prove rootless [0.8.14](../validation/0.8.14-rootless.json), [0.8.13](../validation/0.8.13-rootless.json) e [0.8.12](../validation/0.8.12-rootless.json).
- [Record di accettazione e relativi rapporti](../../.github/release-acceptance).
- [Decisioni iniziali](DECISIONS.md) e [piano 0.5](PIANO_0.5.md).

## Profilo storico della build degli installatori

La [build 43430275209](https://github.com/GregorioDalia/nipat-desktop/actions/runs/43430275209)
del 13 novembre 2026 permette di distinguere il costo di un ciclo dai tentativi
ripetuti. Queste sono misure di quella esecuzione, non soglie garantite:

| Fase sul percorso critico | Durata |
| --- | --- |
| Identificazione sorgente | 21 s |
| Controlli Windows | 3 min 34 s |
| Runtime Linux, regressioni ed esportazione | 19 min 54 s |
| Quattro installer in parallelo | 5 min 48 s |
| Raccolta e controllo finale | 2 min 32 s |
| Avvio dei job e intervalli | 16 s |
| **Totale** | **32 min 25 s** |

Nel job Linux, i controlli scientifici richiedevano 13 min 55 s, i test Python
53 s e le guardie della release 3 s. Il fallimento finale riguardava il limite
dei file delle evidenze, dopo il completamento dei quattro installer. I sette
tentativi di build della candidata precedenti alla correzione finale totalizzavano
75 min 45 s di esecuzione; le CI parallele non vanno sommate a questo valore
come attesa dell'operatore.

Il preflight delle evidenze scientifiche usa lo stesso lettore e gli stessi
limiti dell'archivio finale, prima dell'esportazione e del packaging. Non attesta
gli installer ancora da costruire: il controllo completo finale resta richiesto.
Sulle evidenze reali del tentativo fallito ha letto 3.602 file in 1,34 s e avrebbe
intercettato il precedente limite circa 12 minuti prima. Non riduce in modo
significativo la durata di una build già corretta.


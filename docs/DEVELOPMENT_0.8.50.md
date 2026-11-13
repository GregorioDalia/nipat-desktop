# NIPAT 0.8.50 — guida ai cinque moduli

La revisione integra cinque moduli: DNPcall, SNPcall 2.0, Contamination,
CPI prenatale e CPIN (CPI postnatale). Non include fetal sex.
Il codice richiede il motore scientifico di questa revisione: il client verifica esplicitamente
contratti, moduli e registro dei parametri del runtime.

## Analisi e associazioni

| Origine | Contamination | CPI prenatale | CPIN postnatale |
| --- | --- | --- | --- |
| BAM → DNPcall | Sì | Sì | Sì |
| BAM o pileup → SNPcall | Sì | Sì | Sì |
| Tabelle DNP già disponibili | Sì | Sì | Sì |
| Tabelle SNP già disponibili | Sì | Sì | Sì |

`workflow analyze` permette qualsiasi sottoinsieme delle tre analisi a valle,
compresa la loro esecuzione congiunta, e può eseguire entrambi i caller.
I risultati SNP e DNP rimangono distinti. I conteggi vengono prodotti una
sola volta per campione/caller e poi riutilizzati.

CPI richiede coppie **cfDNA materno–padre**; CPIN richiede terne
**madre–padre–figlio**. Gli identificativi e i ruoli sono espliciti. Lo stesso
padre può comparire in più famiglie. Non viene inferita l'equivalenza fra
cfDNA materno e DNA genomico della madre. Le associazioni devono riferirsi a
campioni distinti all'interno di ciascuna coppia o terna.

Nel menu: **N** apre CPIN; **W → 5** apre la composizione completa. Restano
utilizzabili i comandi diretti dei singoli moduli.

## Parametri e costanti

Il registro `src/nipat_scientific/settings_data.json` contiene un'unica
fonte di valori predefiniti, tipi, limiti, descrizioni e costanti del modello,
letta da Python e R. Sono configurabili:

- acquisizione pileup: qualità minima di basi e mappatura, copertura massima,
  aggiustamento della qualità di mappatura, BAQ, sovrapposizioni, coppie
  anomale e flag esclusi;
- soglia delle altre basi per l'assegnazione del genotipo nei caller;
- filtri di qualità e soglie genotipiche di Contamination, CPI e CPIN;
- inclusione degli zeri in Contamination;
- costanti d'errore distinte SNP/DNP, letture minime fetali o del figlio,
  selezione dell'analisi CPIN e linee guida dei grafici CPI;
- file, pannelli, frequenze, campioni, coppie e terne tramite i comandi e il menu;
- processi, modalità seriale e dimensioni dei blocchi tramite i controlli
  di esecuzione già disponibili.

Le regole strutturali del modello — diploidia, codifica Phred, formule PI,
interpretazione delle colonne — sono consultabili. Non sono parametri
liberamente modificabili: cambiarle definirebbe un modello diverso.
Variabili interne e indici dei cicli non vengono esposti come opzioni.

```powershell
python -m nipat settings
python -m nipat settings cpin
python -m nipat settings --export .\parametri-nipat.json
python -m nipat parameters cpin
```

Le opzioni globali precedono il comando. Un file JSON può contenere solo
le modifiche richieste, suddivise per modulo:

```json
{
  "snp-call": {"min_base_quality": 20},
  "contamination": {"include_zero": false},
  "cpi": {"min_fetal_reads": 3},
  "cpin": {"min_child_reads": 3, "site_selection": "both"}
}
```

```powershell
python -m nipat --scientific-config .\parametri-nipat.json --set cpin.min_child_reads=4 settings cpin
```

La configurazione esplicita è validata prima dell'analisi: chiavi sconosciute,
valori non finiti, tipi errati e soglie genotipiche sovrapposte sono rifiutati.
Le modifiche `--set` prevalgono sul file. Il menu permette di consultare e
modificare i valori per il run e di salvare preferenze in **Configura → S**.
La CLI diretta usa le opzioni esplicite e i default distribuiti.

Ogni esecuzione scientifica conserva `work/effective-scientific-settings.json`
con valori effettivi e costanti. Nei workflow il file appartiene al singolo
passaggio. `run.json`, `workflow-state.json` e la presentazione dei risultati
permettono di risalire a input, associazioni e configurazione.
I parametri di acquisizione non possono cambiare un pileup già prodotto:
se si seleziona un pileup importato, eventuali variazioni sono segnalate.

## Modello aggiornato e prestazioni

CPI, Contamination e CPIN derivano da NEWPAT commit
`9c2a8be60afcb944153710da6a61cd0559e2b4cf` (copie originali congelate in
`tests/reference_r/NEWPAT_20261113`).

Contamination usa il filtro `Other/(REF+ALT+Other)`; la stima per sito resta
`unexpected/(REF+ALT)`. Gli zeri sono inclusi di default e la media è la
media aritmetica dei siti informativi. Il conteggio nel riepilogo si chiama
`informative_sites`.

CPI seleziona automaticamente il modello SNP/DNP, usa costanti d'errore
specifiche e una soglia configurabile di letture fetali. Conserva cache,
pannelli multipli e curve calcolate per intervalli. Colonne accessorie con
valori mancanti non eliminano siti scientificamente validi.

CPIN conserva il modello upstream, comprese le modalità `other_allele`,
`all` e `both`. Esporta siti con motivi di esclusione, curve con intervalli
esatti, riepiloghi e PDF. I campioni condivisi vengono letti una volta;
le curve evitano di ripercorrere ogni singola soglia fino alla copertura
massima. Le terne indipendenti possono essere eseguite in parallelo.

Il budget comune limita i processi senza pool annidati. Anche nei piani
misti le chiamate SNP indipendenti possono essere eseguite in parallelo.
La modalità seriale resta disponibile per controlli riproducibili.

## Verifica prima di una distribuzione

I test confrontano le analisi aggiornate con le copie upstream congelate e
con risultati analitici indipendenti; i caller mantengono i loro riferimenti
immutabili. La CI include una verifica obbligatoria dei nuovi modelli
nell'immagine costruita, compresi batch da 2, 3 e 5 elementi in modalità
seriale, automatica e con limite di due processi.

```bash
python -m pytest tests
python -m unittest discover -s .github/scripts
python scripts/verify_five_modules.py --output build/qualification-0850 --full
python scripts/verify_five_modules.py --image IMAGE_ID --output build/qualification-image-0850 --full
```

Le prove locali con R e quelle del client non attestano l'installazione su
Windows/WSL o sugli altri sistemi finali. La build verifica il runtime
distribuito e i pacchetti; il record di accettazione distingue queste
evidenze dalle prove desktop e di dominio.

## Esempio: analisi diverse sui due rami

Il parametro `--analyses` propone le stesse analisi per ogni ramo attivo.
`--dnp-analyses` e `--snp-analyses` permettono di selezionarle separatamente;
una stringa vuota esclude le analisi successive da quel ramo. Per esempio,
DNP → CPI prenatale e SNP → Contamination:

```powershell
python -m nipat workflow analyze --caller both `
  --sample Plasma .\plasma.bam --sample Padre .\padre.bam `
  --reference .\genoma.fa --dnp-panel .\dnp.tsv --snp-panel .\snp.tsv `
  --dnp-analyses cpi --snp-analyses contamination `
  --pair Famiglia1 Plasma Padre --dnp-popfreq .\frequenze-dnp.tsv
```

Il pannello di calling viene usato anche per Contamination quando non si
indica un pannello dedicato. Le frequenze SNP non sono richieste nell'esempio,
perché il ramo SNP non esegue analisi di paternità. Nel menu **W → 5**, la
scelta **Analisi successive → 8** permette la stessa composizione guidata.

Per iniziare da tabelle esistenti usare `--caller tables` e le opzioni
ripetibili `--dnp-table ID PATH` / `--snp-table ID PATH`. Per SNPcall da pileup
usare `--caller snp --pileup ID PATH --snp-panel PATH`, senza FASTA. Gli ID
indicati da `--pair` e `--trio` si riferiscono esplicitamente a questi campioni.

La qualificazione iniziale dello sviluppo comprendeva 1.182 test Python
(4 saltati), 253 test dei contratti CI,
86 esecuzioni R e due workflow completi da tre BAM superati. Le 30 tabelle
scientifiche dei workflow seriale e con limite 2 sono identiche.
Il [resoconto iniziale](validation/0.8.50-development.json) conserva hash,
runtime, copertura e verifiche non eseguite nell’ambiente finale.
La [revisione successiva](AUDIT_0.8.50.md) e le
[note di versione](RELEASE_0.8.50.md) descrivono le ulteriori correzioni e
la qualificazione per la distribuzione.

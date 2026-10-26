# Catalogo scientifico

Il catalogo descrive le interfacce pubbliche e le regole interne dei quattro
script R distribuiti con NIPAT. È consultabile in italiano e inglese, senza
avviare l'ambiente scientifico o elaborare campioni.

Nel menu scegliere **7 — Guida e informazioni → 6 — Catalogo scientifico**,
poi l'analisi e la sezione. **L — Lingua / Language** cambia la lingua della
consultazione. Non modifica la lingua del resto del menu né salva una
preferenza generale.

Dalla CLI:

```sh
nipat parameters cpi
nipat parameters dnp-call --section rules
nipat parameters snp-call --section preparation --lang en
nipat parameters --json
```

In un checkout di sviluppo si può usare `python -m nipat` al posto di
`nipat`. Su Windows il wrapper `nipat.cmd` accetta gli stessi argomenti.
Il JSON contiene entrambe le lingue; `--lang` e `--section` riguardano
soltanto la presentazione testuale. Il comando non cambia configurazione,
non crea run e non richiede Docker o WSL.

## Contenuto e significato

| Sezione | Significato |
| --- | --- |
| Opzioni pubbliche R | Argomenti accettati dallo script, obbligatorietà, default R e corrispondenza con CLI e richiesta al motore. |
| Regole interne R | Soglie fisse, formule, filtri, assunzioni di formato e impostazioni di presentazione, consultabili in sola lettura. |
| Preparazione degli input | Trasformazioni NIPAT e impostazioni delle dipendenze, con origine e ambito di applicazione. |

Una corrispondenza **diretta** conserva il significato del parametro nativo.
Una corrispondenza **adattata** prepara il formato richiesto da R, per esempio
la directory interna dei campioni CPI. Una destinazione **gestita da NIPAT**
usa cartelle e nomi standardizzati nel run: non equivale a permettere qualsiasi
nome di output accettato dallo script.

Il catalogo non è il resoconto di un'esecuzione. I valori effettivamente scelti
sono nei parametri del relativo `run.json`; i default del catalogo non
prevalgono sulle opzioni dell'utente. I default aggiunti dal client sono
distinti da quelli dichiarati da R. Per un pileup importato, le impostazioni
samtools applicate a monte possono non essere ricostruibili: il catalogo
non attribuisce a quel file le impostazioni della preparazione BAM di NIPAT.

Le costanti interne non sono nuove opzioni modificabili. Renderle visibili
non cambia il modello scientifico e non autorizza automaticamente a modificarlo.
I pannelli CPI chiamati *cutoff* selezionano coordinate; i loro nomi non
applicano soglie numeriche ai campioni.

I [controlli degli input e dei risultati](INPUT_VALIDATION.md) sono applicati
dagli adattatori Python. Il catalogo distingue questi controlli dalle
assunzioni e dalle formule R: una normalizzazione del pannello o un errore
preliminare non modifica lo script scientifico. Le segnalazioni sui valori
mantengono disponibili i dati originali per la valutazione di dominio.

## Provenienza e verifiche

Ogni scheda identifica il percorso e lo SHA-256 del sorgente R, i riferimenti
alle righe e la copertura dell'intero script. Una modifica del sorgente rende
necessaria la revisione della scheda; la CI verifica questa corrispondenza.
I testi tradotti conservano gli stessi identificatori e valori scientifici.
Anche i riferimenti alla preparazione sono associati allo SHA-256 dei file
citati. Nel checkout la CI controlla questi sorgenti, compreso il Dockerfile
che identifica la versione samtools. Nell'immagine vengono ricontrollati gli
adapter incorporati; i riferimenti al client e ai file di build assenti
restano evidenze verificate durante la CI, non nuove verifiche sull'host.

La consultazione ordinaria usa il catalogo incluso nell'applicazione. Il
motore include la stessa struttura nell'immagine e permette di interrogare
il catalogo associato ai propri sorgenti:

```sh
python3 /opt/nipat/engine/main.py catalog cpi --json
```

L'identità del motore registra anche gli hash dei file del catalogo e del
validatore dei piani. Un hash identifica una revisione: non dimostra da solo
la correttezza scientifica della descrizione o dell'algoritmo. Le prove
numeriche e la valutazione di dominio restano distinte dalla copertura del
catalogo.

Il [contratto dei piani](WORKFLOW_CONTRACT.md) descrive la validazione delle
relazioni fra analisi. La validazione di un piano non avvia i suoi passaggi.

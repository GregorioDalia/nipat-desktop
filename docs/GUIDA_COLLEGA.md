# Guida alla prova della CLI

La CLI `0.2.0a2` serve a verificare i quattro workflow con input scelti
dall'esperta di dominio. Si può usare un menu testuale oppure la riga di
comando. Setup, autotest e una regressione DNPcall da BAM reale sono riusciti
sul PC Windows di sviluppo; gli [esiti](DISTRIBUZIONE.md) non sostituiscono
le prove con i propri input e sul proprio computer.

## Preparazione su Windows a 64 bit

1. Installa e avvia [Docker Desktop](https://docs.docker.com/desktop/setup/install/windows-install/)
   con container Linux. Completa gli eventuali passaggi WSL richiesti da Docker.
2. Dalla release GitHub indicata per la validazione, scarica **Source code (zip)**
   ed estrai interamente il progetto in una cartella locale scrivibile.
   Non avviare i file direttamente dalla finestra dello ZIP.
3. Nella cartella che contiene `README.md`, avvia `1_SETUP.cmd`. Il setup
   prepara Python locale e il runtime scientifico, poi esegue gli autotest.
4. Dopo il completamento del setup, avvia `2_AVVIA.cmd`.

Non servono Git, PyCharm o installazioni separate di Python, R e samtools.
Il primo setup richiede Internet e può durare diversi minuti. I successivi
avvii riusano l'ambiente locale. Docker rimane un prerequisito manuale.

## Dove tenere input e risultati

Gli input possono restare nelle loro cartelle originali: selezionarli con il
percorso completo, anche su un'altra unità accessibile a Docker. Non occorre
copiare BAM e FASTA nel progetto. Sono ammessi percorsi contenenti spazi;
il programma assegna ai file nomi interni compatibili con gli script R.

Il setup crea per comodità `data` e `runs` accanto al progetto. `data` non è
un vincolo: i file selezionati possono trovarsi altrove. La cartella dei
risultati si sceglie con **5 — Cartella risultati** nel menu: la scelta vale
per le analisi successive nella sessione corrente e Invio mantiene il percorso
mostrato. La nuova cartella viene controllata e creata; non può sovrapporsi
al progetto o alla cartella dati. `:annulla` torna al menu senza cambiarla.
Per configurare l'avvio si possono usare `--runs-dir` e `--data-dir`, oppure
`NIPAT_RUNS_DIR` e `NIPAT_DATA_DIR`; le opzioni CLI prevalgono sulle variabili
di ambiente. La scelta fatta nel menu non viene salvata per l'avvio successivo.

Nei comandi CLI le opzioni globali vanno **prima del workflow**. I percorsi
relativi partono dalla cartella corrente del terminale; quelli dentro una
lista BAM partono dalla cartella della lista stessa. Nell'esempio seguente,
eseguito dalla cartella del progetto, sostituire le cartelle con le proprie:

```powershell
.\nipat.cmd --data-dir "..\miei-dati" --runs-dir "..\miei-risultati" wizard
```

Ogni analisi crea una nuova sottocartella sotto la destinazione scelta,
conservando i nomi degli output scientifici. Non è necessario rinominare
manualmente i risultati e un run esistente non viene sovrascritto.

## Input dei quattro workflow

**DNPcall.** Selezionare uno o più BAM, oppure una lista di BAM: un percorso
per riga, senza intestazione. CLI: ripetere `--bam` oppure usare `--bamlist`,
senza combinare le due modalità. Il FASTA richiede il relativo indice
`.fai`; se compresso in BGZF richiede anche `.gzi`. Gli indici BAM sono
facoltativi per l'attuale percorso `samtools mpileup -l`.
Il pannello DNP è tabulato, senza intestazione, con cinque colonne:
`chr`, `pos1`, `pos2`, `REF`, `ALT`. Le posizioni devono essere adiacenti e
REF/ALT devono essere dinucleotidi.
Il programma prepara in `work` una piccola copia del pannello con gli alleli
REF/ALT in maiuscolo, lasciando invariato l'originale.
L'esecuzione è seriale per impostazione predefinita; il menu e `--parallel`
consentono quella parallela. DNPcall usa alias `sample_0001.bam`, ecc.:
consultare la corrispondenza nei metadati del run per risalire ai campioni
originali. Con un solo campione il grafico UpSet è intenzionalmente omesso.

**SNPcall.** Scegliere BAM e FASTA indicizzato, per generare automaticamente
il pileup, oppure fornire un pileup già pronto. In CLI: `--bam` con
`--reference`, oppure `--pileup`. Il pileup deve avere almeno sette colonne
samtools, con i nomi delle letture (QNAME) nella settima; le eventuali colonne
successive sono ignorate da R. Un pileup standard senza QNAME non è equivalente.
La lista SNP è tabulata, con intestazione
`pos`, `ref`, `alt`, dove `pos` ha forma `chr1:1770788`.
Il totale dei conteggi include le letture “altre”; il rapporto REF usa
soltanto REF e ALT nel denominatore.

**Contamination.** Selezionare singole tabelle oppure una cartella.
La modalità cartella cerca ricorsivamente file `.txt` e `.tsv`, senza
distinguere maiuscole e minuscole, ed esclude il pannello selezionato.
Le tabelle devono contenere `chr`, `pos1`, `pos2`, `N_REF`, `N_ALT`,
`N_Other`; gli output individuali DNPcall sono compatibili. Una cartella
con riepiloghi o altri TXT/TSV non compatibili va filtrata scegliendo
esplicitamente i singoli file. Nomi che collidono dopo l'adattamento per R
sono segnalati e non vengono sovrascritti.
Se presente, `ratio_REF_ALT` viene usato dallo script; altrimenti viene
calcolato dai conteggi. Le stime sono frazioni: `0.025` significa 2.5%.
Il pannello può essere il precedente DNP a cinque colonne oppure una tabella
di coordinate: con intestazione deve includere `chr`, `pos1`, `pos2`;
senza intestazione queste devono essere le prime tre colonne, in tale ordine.

**CPI.** Selezionare la cartella delle tabelle della componente cfDNA materna
e del presunto padre, le coppie e le frequenze di popolazione. Con i prefissi
predefiniti, `A1:A1` individua `MotherA1.txt` e `FatherA1.txt`; più coppie si
separano con virgole. Le frequenze richiedono `chr`, `pos1`, `pos2`,
`Ref_f.pop`, `Alt_f.pop`. La scelta deve essere coerente con i campioni e
il riferimento genomico; i nomi dei file non determinano il ruolo biologico.

Per CPI si può usare un solo pannello (`--panel`), più pannelli etichettati
(`--cutoff LABEL PATH`, ripetibile), una mappa nativa (`--cutoff-map`) oppure
tutti i siti, omettendo i filtri. Le tre opzioni di filtro sono alternative.
Sono accettati il pannello DNP a cinque colonne e i pannelli di coordinate
native. Le etichette dei cutoff devono essere uniche e non contenere virgole
né `=`. Preferire `--cutoff` per indicare separatamente etichetta e percorso,
soprattutto se i nomi dei file contengono delimitatori della mappa nativa.
Il parametro `err_const` è modificabile nel menu e tramite `--err-const`:
il valore predefinito rimane `0.0000892303778101497`.

## Esecuzione e controlli

`2_AVVIA.cmd` mostra la destinazione dei risultati e chiede workflow, modalità
di input e parametri. L'opzione 5 consente di cambiare la destinazione prima
della prossima analisi. È possibile incollare percorsi completi tra virgolette.
Scegliere un nome nuovo per il run oppure lasciare quello automatico.
Per i comandi diretti, aprire PowerShell nella cartella di `nipat.cmd`:

```powershell
.\nipat.cmd --help
.\nipat.cmd dnp-call --help
.\nipat.cmd --runs-dir "..\risultati" --dry-run contamination `
    --input "..\campioni\sample.txt" --panel "..\pannelli\DNPpanel.txt"
```

`--dry-run` controlla e prepara l'esecuzione senza avviare l'analisi
scientifica; anche la successiva prova reale richiede un nuovo run.
Il setup esegue quattro gruppi di controlli: l'esempio SNPcall, i casi sintetici
CPI e Contamination e le nuove modalità con input esterni. Quest'ultimo gruppo
prova SNPcall da pileup, Contamination da cartella e CPI con due cutoff oppure
con tutti i siti. Per ripetere i controlli:

```powershell
.\nipat.cmd doctor --runtime
.\nipat.cmd self-test
.\.runtime\python\python.exe scripts/verify_input_modes.py
```

Attendere l'esito finale di ciascun comando. Nei test CPI e Contamination
il confronto numerico segue il completamento del workflow: un `run.json`
positivo non basta a dimostrare il superamento dell'autotest. Il controllo
aggiuntivo usa piccoli input di prova in percorsi esterni al progetto ed è
già incluso in `self-test`; il comando separato ripete soltanto quel gruppo.
Non aggiunge una verifica numerica DNPcall da BAM. La valutazione scientifica
sui propri campioni rimane distinta.

Ogni run conserva `run.json`, `execution.log`, `work` e `output`.
`work/input-mounts.json` e i metadati del run permettono di collegare i percorsi
originali a quelli usati nel container. L'esito positivo indica che i comandi
sono terminati correttamente; `NA` può essere un risultato atteso in assenza
di siti informativi. Una cartella di output parziale non prova il completamento.

## Problemi e feedback

- Se Docker non risponde, avviarlo e attendere che il motore Linux sia pronto.
- Se un file esterno non è accessibile al container, verificare la disponibilità
  dell'unità e i permessi di accesso in Docker Desktop.
- Se manca l'indice FASTA, fornire quello corrispondente al riferimento scelto.
- Se il nome del run esiste già, sceglierne uno nuovo.
- Per una prova fallita, conservare il run e compilare la
  [scheda di validazione](VALIDAZIONE.md) con atteso e osservato.

Nomi e percorsi dei campioni compaiono nei metadati e non sono anonimizzati.
Verificare i contenuti prima di allegarli a segnalazioni pubbliche; non
caricare su GitHub dati genomici o risultati dei campioni.

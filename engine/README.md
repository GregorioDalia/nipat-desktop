# Interfaccia del motore scientifico

L'immagine NIPAT installa il motore in `/opt/nipat/engine`, gli script R in
`/opt/nipat/scientific` e la libreria di preparazione in
`/opt/nipat/lib/nipat_scientific`. Il motore non dipende dalla directory
corrente, dai sorgenti del client o dalla cartella dell’applicazione installata.
Python usa la sola libreria standard; R, samtools e le dipendenze sono inclusi
nell'immagine.

Questo riferimento descrive il contratto tecnico. Per l'utilizzo ordinario
usare la [CLI o il menu guidato](../docs/GUIDA_UTILIZZO.md), che preparano
richieste e mount e conservano i metadati dell'esecuzione.

## Comandi e identificazione

```sh
python3 /opt/nipat/engine/main.py describe --json
python3 /opt/nipat/engine/main.py verify
python3 /opt/nipat/engine/main.py catalog cpi --json
python3 /opt/nipat/engine/main.py validate-plan --plan /inputs/plan.json
python3 /opt/nipat/engine/main.py execute dnp-call --request /run/work/request.json
python3 /opt/nipat/engine/main.py execute snp-call --request /run/work/request.json
python3 /opt/nipat/engine/main.py execute contamination --request /run/work/request.json
python3 /opt/nipat/engine/main.py execute cpi --request /run/work/request.json
```

`execute` convalida la richiesta, prepara i file e avvia il programma R.
Per un'invocazione tecnica con argomenti R nativi è disponibile anche `run`:

```sh
python3 /opt/nipat/engine/main.py run snp-call -- \
  --pileup /inputs/pileup.txt --snplist /inputs/SNPlist.txt --out /outputs/output.txt
```

Solo `run` passa direttamente a R gli argomenti dopo il nome del workflow,
rimuovendo un eventuale `--` iniziale. Questa modalità non esegue la
preparazione prevista da `execute`.

Prima di eseguire un workflow, tutti e quattro i sorgenti R devono corrispondere
al manifest scientifico incluso. `describe --json` restituisce:

| Campo | Contratto |
| --- | --- |
| `schema_version` | `1` |
| `interface` | `native-r-v1` |
| `workflow_interfaces` | `dnp-call-v1`, `snp-call-v1`, `contamination-v1`, `cpi-v1`, associati ai rispettivi workflow |
| `preparation.interface` | `workflow-preparation-v1` |
| Identità scientifica | Hash del manifest e percorso/hash dei quattro script R |
| `preparation.file_sha256` | Hash dell'ingresso del motore, dei dieci moduli Python condivisi e delle quattro schede JSON del catalogo |

Moduli mancanti e percorsi esterni al bundle sono rifiutati. Gli hash della
preparazione identificano i byte nell'immagine; gli hash R vengono inoltre
confrontati con il manifest. La descrizione non identifica da sola una release:
commit, archivio distribuito e ID immagine appartengono alle evidenze di build
e ai metadati del run.

L'avvio di R sostituisce il processo del motore con `Rscript`, preservandone
codice di uscita e ricezione dei segnali. Gli errori di verifica o avvio
restituiscono 2. Nella preparazione SNPcall da BAM, i segnali sono inoltrati
anche al processo samtools; un suo errore impedisce l'avvio di R.
Nessun comando del motore scarica o installa dipendenze.

`catalog` espone le schede scientifiche bilingui e verifica la corrispondenza
con i sorgenti R nell'immagine. `validate-plan` legge un documento JSON e
restituisce il piano canonico e l'ordine derivato dalle dipendenze. Non legge
i campioni, non crea risultati e non avvia R o samtools. Il
[contratto dei piani](../docs/WORKFLOW_CONTRACT.md) specifica campi e limiti;
il [catalogo scientifico](../docs/CATALOGO_SCIENTIFICO.md) ne descrive la
consultazione. L'esecuzione dei piani concatenati è un incremento distinto.

## Regole comuni delle richieste

Ogni richiesta usa `schema_version: 1` e il nome del workflow. I percorsi
identificano file e destinazioni **dentro il container**, non percorsi host
Windows. Gli input devono essere esterni alle directory di lavoro e di output,
che devono essere distinte. L'output deve essere vuoto e i file di staging
previsti non devono già esistere. La validazione precede la preparazione;
nessun file generato viene sovrascritto automaticamente.

Il client monta soltanto gli input selezionati in sola lettura e il run corrente
in scrittura. Il filesystem dell'immagine è in sola lettura, con directory
temporanea dedicata e rete disabilitata. Non montare sorgenti o cartelle
applicative sopra `/opt/nipat`. Il Dockerfile consente comandi espliciti per
le sonde e per le analisi, senza imporre un `ENTRYPOINT`.

I file parzialmente preparati dopo un errore di I/O rimangono nel run per la
diagnosi. Una nuova analisi deve usare una nuova directory.

## Contamination

```json
{
  "schema_version": 1,
  "workflow": "contamination",
  "panel": "/inputs/panel.txt",
  "samples": [
    {"path": "/inputs/sample_001.tsv", "name": "Original_sample.txt"}
  ],
  "work_dir": "/run/work",
  "out_dir": "/run/output"
}
```

Il motore convalida pannello e tabelle, copia le tabelle byte per byte in
`work/inputs` e scrive il pannello R in `work/DNPpanel.txt`. I nomi mantengono
lo stem originale e usano l'estensione `.txt`. Sono ammessi spazi e Unicode,
ma non separatori di directory o caratteri di controllo. Collisioni di nome,
anche limitate alle maiuscole, vengono rifiutate prima dello staging.
Il client può selezionare singoli file o espandere ricorsivamente una cartella;
la richiesta contiene l'elenco finale dei soli file selezionati.

## SNPcall

```json
{
  "schema_version": 1,
  "workflow": "snp-call",
  "mode": "bam",
  "panel": "/inputs/SNPlist.txt",
  "bam": "/inputs/sample.bam",
  "pileup": null,
  "reference": "/inputs/genome.fa",
  "work_dir": "/run/work",
  "out_dir": "/run/output"
}
```

Con `mode: "pileup"`, `bam` e `reference` devono essere `null`; `pileup`
identifica il file con la settima colonna QNAME. Sono ammesse ulteriori colonne.
Questa modalità non esegue samtools e non genera i file di preparazione BAM.

Con `mode: "bam"`, `pileup` deve essere `null` e il riferimento deve avere
l'indice adiacente `.fai`; un riferimento BGZF richiede anche `.gzi`.
L'indice BAM è facoltativo perché samtools usa `-l`, senza accesso indicizzato
per regione. Il motore conserva i nomi dei cromosomi del pannello, genera le
finestre BED di tre basi in `work/snp_regions.bed` ed esegue samtools,
conservando `work/pileup.txt`. Entrambe le modalità producono
`output/SNPcall_output.txt`.

## DNPcall

```json
{
  "schema_version": 1,
  "workflow": "dnp-call",
  "panel": "/inputs/DNP_list.txt",
  "samples": [
    {"path": "/inputs/bams/sample_0001.bam", "sample_id": "sample_0001"}
  ],
  "reference": "/inputs/genome.fa",
  "parallel": false,
  "work_dir": "/run/work",
  "out_dir": "/run/output"
}
```

Il client accetta BAM singoli, multipli o una lista; le voci della lista sono
relative alla directory che la contiene. I BAM ricevono alias progressivi
`sample_0001.bam`; `run.json` conserva l'associazione con gli originali.
BAM e riferimento sono montati in sola lettura. Il riferimento richiede `.fai`
e, se BGZF, `.gzi`; gli indici BAM sono facoltativi.

Il motore convalida alias e pannello, poi scrive `work/DNP_list.txt` e
`work/bamlist.txt`. Le directory devono essere sorelle e chiamarsi `work` e
`output`. L'esecuzione parte dalla loro directory padre con gli argomenti
relativi `--bamlist=work/bamlist.txt`, `--DNPs=work/DNP_list.txt` e `--out=output`.
Gli alias ASCII interni sono necessari alle chiamate shell di DNPcall, anche
quando i nomi originali contengono spazi o Unicode. `parallel` è booleano
e attiva l'opzione R `--parallel`.

La presenza di staging preesistente, output non vuoto o file `mpileup.txt`
e `bedfile_for_mpileup.bed` nella radice del run impedisce la preparazione.
Lo script R genera e rimuove questi ultimi due file al termine. Richiesta,
pannello normalizzato e lista BAM rimangono disponibili.

DNPcall richiama samtools internamente, ne sopprime lo stderr e non controlla
esplicitamente il codice di uscita. Il motore conserva lo stato restituito da R,
ma non garantisce che ogni errore interno di samtools venga segnalato.
Un processo riuscito non attesta la correttezza scientifica dell'output.

## CPI

```json
{
  "schema_version": 1,
  "workflow": "cpi",
  "samples": [
    {"path": "/inputs/sample_0001.txt", "name": "MotherA.txt"},
    {"path": "/inputs/sample_0002.txt", "name": "FatherB.txt"}
  ],
  "pairs": "A:B",
  "mother_prefix": "Mother",
  "father_prefix": "Father",
  "popfreq": "/inputs/population.tsv",
  "cutoff_mode": "named",
  "cutoffs": [{"label": "Full", "path": "/inputs/panel.tsv"}],
  "err_const": 0.0000892303778101497,
  "work_dir": "/run/work",
  "out_dir": "/run/output"
}
```

Le coppie sono identificate da `madre:padre`, separate da virgole; gli spazi
esterni agli identificatori sono normalizzati. I prefissi possono essere
personalizzati o vuoti. I nomi delle tabelle selezionate devono corrispondere
esattamente a `<prefisso><identificatore>.txt`. Un genitore usato in più coppie
viene preparato una sola volta.

Il client espone soltanto tabelle richieste, frequenze e pannelli. Il motore
convalida nuovamente questi file e copia le tabelle senza cambiarne i byte
in `work/inputs`. I file non selezionati non sono accessibili a R.

| `cutoff_mode` | Richiesta e preparazione |
| --- | --- |
| `all` | Lista `cutoffs` vuota; nessun `--cutoff_map` nativo e nessuna colonna `Cutoff` nell'output. |
| `panel` | Un pannello con etichetta vuota; genera `work/DNPpanel.txt` e usa il suo percorso interno come valore `Cutoff`. |
| `named` | Una o più etichette univoche non vuote; genera `work/cutoff_001.tsv` e successivi. |

Il client offre `--cutoff` ripetuto e `--cutoff-map`. Un percorso senza
etichetta nella mappa diventa anche la sua etichetta. I pannelli accettano
formati testuali a tre colonne, con o senza intestazione, e il formato DNP
a cinque colonne; vengono normalizzati a `chr`, `pos1`, `pos2`. L'interfaccia
non accetta pannelli XLSX.

Le etichette non possono contenere virgole, segni uguale o caratteri di controllo.
I percorsi interni dei cutoff non possono contenere virgole o segni uguale,
perché il parser R non li può codificare; gli alias del client evitano questa
limitazione sui percorsi host. `err_const` deve essere finito e non negativo;
zero è ammesso. Gli argomenti sono passati senza shell, preservando prefissi
vuoti e valori che iniziano con un trattino.

Le etichette delle coppie e i PDF usano `Mother<id>-Father<id>_DNPs`, indipendentemente
dai prefissi degli input. Nomi ambigui dei campioni e collisioni degli output
delle coppie, anche limitate alle maiuscole, sono rifiutati prima dello staging.
Richiesta, tabelle preparate e pannelli rimangono in `work`; CSV e PDF sono
scritti in `output`.

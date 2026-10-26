# Contratto dei piani scientifici

Un piano descrive campioni, analisi e collegamenti fra risultati attraverso
identificatori espliciti. Il contratto `schema_version: 1` appartiene al
motore scientifico `nipat_scientific`, incluso nell'immagine Linux. Non dipende
dal menu Windows, da una GUI o dalla lingua dell'interfaccia.

Il comando del motore `validate-plan --plan FILE` controlla la struttura e
le dipendenze e restituisce JSON. **Questa validazione non esegue il piano**:
non avvia R o samtools, non crea risultati e non controlla esistenza,
contenuto o compatibilità biologica dei file.

Il comando distinto `execute-plan --plan FILE --run-dir DIR` esegue
piani composti dalle quattro analisi. SNPcall è un'attività indipendente,
con un BAM o pileup per passaggio; non produce input per Contamination o CPI.
Le analisi singole restano disponibili tramite `execute`. Il menu e la CLI
desktop offrono DNPcall → Contamination, DNPcall → CPI e DNPcall → Contamination
e CPI, con SNPcall facoltativo sugli stessi BAM, oltre a SNPcall su più campioni.
Queste opzioni non richiedono la scrittura del JSON.

## Struttura della richiesta

La richiesta contiene esattamente `schema_version`, `samples` e `steps`.
Campi sconosciuti o mancanti sono errori; non vengono ignorati. Le opzioni
che possono influire sul comportamento devono essere scritte esplicitamente,
anche quando coincidono con il valore predefinito del singolo script.

Il registro `samples` contiene oggetti con questi tre campi:

| Campo | Contenuto |
| --- | --- |
| `id` | Identità del campione nel piano, indipendente dal nome del file. |
| `kind` | `bam`, `dnp-table` oppure `snp-pileup`. |
| `path` | Percorso assoluto POSIX del file nel container. |

Gli identificatori di campioni, passaggi e coppie usano da 1 a 64 caratteri
ASCII: iniziano con una lettera e proseguono con lettere, numeri, `_` o `-`.
Non sono ammessi duplicati, neppure con differenze di maiuscole/minuscole.
Il riferimento a un identificatore deve conservarne la scrittura esatta.
Lo stesso percorso non può essere registrato come due campioni distinti.
Il confronto è testuale: il validatore non risolve collegamenti simbolici,
hard link o due percorsi che identificano fisicamente lo stesso file.

I percorsi sono quelli assegnati dal client dopo la preparazione dei mount,
per esempio `/workspace/inputs/sample_a.bam`. Un percorso Windows come
`D:\dati\sample.bam` non è un percorso valido in questo contratto. Non sono
ammessi componenti `.` o `..`, barre ripetute, backslash o caratteri di controllo.
I valori sono letterali: non sono espansi variabili, comandi, template o glob.
Il contratto non accetta comandi di shell né programmi arbitrari.

Ogni elemento di `steps` contiene esattamente `id`, `workflow`, `inputs` e
`parameters`. `workflow` identifica una delle quattro analisi supportate.

| Workflow | Campi esatti di `inputs` | Campi esatti di `parameters` |
| --- | --- | --- |
| `dnp-call` | `samples`: lista di ID BAM; `reference`: FASTA; `panel`: pannello DNP | `parallel`: booleano. |
| `snp-call` | `sample`: ID BAM o pileup; `reference`: FASTA oppure `null`; `panel`: pannello SNP | `mode`: `bam` oppure `pileup`. |
| `contamination` | `samples`: lista di riferimenti a tabelle; `panel`: pannello di coordinate | Oggetto vuoto `{}`. |
| `cpi` | `pairs`: coppie esplicite; `popfreq`: frequenze di popolazione; `cutoffs`: pannelli selezionati | `err_const`: numero finito non negativo; `cutoff_mode`: `all`, `panel` o `named`. |

SNPcall in modalità `bam` richiede un campione `bam` e un FASTA. In modalità
`pileup` richiede un campione `snp-pileup` e `reference: null`. Le impostazioni
con cui è stato prodotto un pileup esterno non sono ricostruite né attribuite
automaticamente a NIPAT.

## Riferimenti tipizzati e ruoli CPI

Contamination e CPI accettano due forme di riferimento a una tabella:

- `{"sample": "table_a"}` seleziona un campione registrato come `dnp-table`.
- `{"step": "dnp", "output": "dnp-tables", "sample": "sample_a"}` seleziona
  la tabella individuale che il passaggio DNPcall `dnp` deve produrre per il
  campione `sample_a` presente nei suoi input.

Il secondo riferimento crea una dipendenza. Un risultato SNPcall, un riepilogo
Contamination o un risultato CPI non è una tabella DNP compatibile per questo
collegamento. Non si possono usare percorsi ipotizzati di risultati futuri
per sostituire questi riferimenti.

Ogni coppia CPI contiene `id`, `mother` e `father`:

- `mother` identifica esplicitamente la tabella **cfDNA materna**;
- `father` identifica esplicitamente la tabella del **campione paterno**.

Entrambi sono riferimenti alle tabelle descritti sopra. I ruoli non vengono
dedotti da nomi, prefissi o ordine dei campioni. Lo stesso campione non può
assumere entrambi i ruoli in un passaggio CPI, anche se proviene da due
elaborazioni DNPcall differenti. Sono consentite più coppie che riutilizzano
un campione nello stesso ruolo; coppie duplicate non sono ammesse.
La correttezza biologica dell'assegnazione resta responsabilità di chi prepara
il piano: il contratto controlla la coerenza dichiarata, non il tipo di materiale.

Le modalità cutoff conservano la struttura dell'adattatore CPI:

| `cutoff_mode` | Valore di `cutoffs` |
| --- | --- |
| `all` | Lista vuota `[]`; nessun pannello cutoff. |
| `panel` | Un elemento con `label: ""` e `path` del pannello. |
| `named` | Uno o più elementi con `label` non vuota e `path`. |

Le etichette dei pannelli devono essere univoche e non possono contenere
virgole, `=` o caratteri di controllo, né spazi iniziali o finali. `err_const`
segue l'interfaccia attuale CPI: il contratto richiede un valore finito e non
negativo e non introduce un limite superiore assente nell'adattatore.

## Esempio DNPcall → Contamination e CPI

L'esempio seleziona due BAM, elabora i conteggi una sola volta e riferisce
esplicitamente quei risultati nelle due analisi successive. La stima di
contaminazione non modifica i dati usati dal CPI. Il piano può essere
convalidato senza dati con `validate-plan`; per eseguirlo occorrono gli input
montati nei percorsi indicati, gli indici del FASTA e una destinazione nuova.

```json
{
  "schema_version": 1,
  "samples": [
    {
      "id": "cfDNA_a",
      "kind": "bam",
      "path": "/workspace/inputs/bams/sample_0001.bam"
    },
    {
      "id": "paternal_a",
      "kind": "bam",
      "path": "/workspace/inputs/bams/sample_0002.bam"
    }
  ],
  "steps": [
    {
      "id": "dnp",
      "workflow": "dnp-call",
      "inputs": {
        "samples": ["cfDNA_a", "paternal_a"],
        "reference": "/workspace/inputs/reference.fa",
        "panel": "/workspace/inputs/dnp.tsv"
      },
      "parameters": {"parallel": false}
    },
    {
      "id": "contamination",
      "workflow": "contamination",
      "inputs": {
        "samples": [
          {"step": "dnp", "output": "dnp-tables", "sample": "cfDNA_a"},
          {"step": "dnp", "output": "dnp-tables", "sample": "paternal_a"}
        ],
        "panel": "/workspace/inputs/dnp.tsv"
      },
      "parameters": {}
    },
    {
      "id": "cpi",
      "workflow": "cpi",
      "inputs": {
        "pairs": [
          {
            "id": "pair_a",
            "mother": {"step": "dnp", "output": "dnp-tables", "sample": "cfDNA_a"},
            "father": {"step": "dnp", "output": "dnp-tables", "sample": "paternal_a"}
          }
        ],
        "popfreq": "/workspace/inputs/popfreq.tsv",
        "cutoffs": []
      },
      "parameters": {"err_const": 0.0000892303778101497, "cutoff_mode": "all"}
    }
  ]
}
```

## Risultato della validazione

L'API Python `nipat_scientific.plan.validate_plan(document)` restituisce un
nuovo oggetto, senza modificare quello ricevuto:

- `schema_version: 1` identifica il formato del resoconto;
- `plan` contiene la richiesta canonica;
- `execution_order` elenca gli ID dei passaggi nell'ordine determinato.

Il registro campioni è ordinato per ID. I passaggi sono ordinati rispettando
le dipendenze; fra i passaggi disponibili viene scelto quello con ID
lessicograficamente minore. Per l'esempio l'ordine è `dnp`, `contamination`,
`cpi`. Questo ordinamento non implica che il validatore li abbia eseguiti.
L'ordine dei campioni dentro un passaggio, delle coppie e dei pannelli viene
conservato. Non viene applicato parallelismo fra passaggi.

`report["plan"]` può essere validato nuovamente ottenendo lo stesso resoconto.
Il resoconto completo non è invece una richiesta: l'input non ammette
`execution_order`, perché l'ordine deve derivare dai riferimenti e non può
essere imposto dal chiamante. I cicli e i riferimenti a passaggi, campioni o
tipi di output inesistenti vengono respinti.

Le cartelle `work` e `output` appartengono alla singola esecuzione e non
sono impostate arbitrariamente nel piano. Gli ID del piano identificano i
campioni; non devono essere interpretati come nomi generati dal codice R.
Per CPI, il contratto rappresenta le selezioni di file mediante riferimenti
espliciti alle coppie. L'esecutore traduce questi riferimenti nei nomi interni
CPI e conserva la corrispondenza fra coppie dichiarate, input materni/paterni
e risultati nativi. Non occorre rinominare gli originali.

## Esecuzione dei piani

```sh
python3 /opt/nipat/engine/main.py execute-plan \
  --plan /workspace/run/work/engine-plan.json \
  --run-dir /workspace/run/output/workflow
```

`execute-plan` usa la stessa struttura di richiesta di `validate-plan`, ma
aggiunge i controlli necessari all'esecuzione. Al termine mostra un riepilogo
e il percorso dello stato; `--json` scrive il resoconto completo su stdout,
riservando stderr ai messaggi di avanzamento. Il codice di uscita non dipende
dal formato di presentazione. Il descrittore del motore
espone `plan_execution.interface: workflow-plan-execution-v1`, i workflow
eseguibili `dnp-call`, `snp-call`, `contamination` e `cpi`, la pianificazione `sequential` e
`resume: false`.

La destinazione deve essere nuova, con directory padre già esistente:
una directory già presente, anche vuota, non viene riutilizzata. Il motore
controlla l'intero piano, il sottoinsieme
di analisi supportate e gli input già disponibili prima di creare la
destinazione. Riferimenti, pannelli, indici e alias richiesti devono essere
validi. Le tabelle prodotte da un passaggio sono verificate quando diventano
disponibili, prima di utilizzarle nel passaggio dipendente.

DNPcall richiede BAM esposti con nomi `sample_0001.bam`, `sample_0002.bam` e
successivi, nell'ordine della lista `inputs.samples` del passaggio. I percorsi
interni devono essere compatibili con l'interfaccia R e i suoi comandi samtools.
Il client prepara alias mediante mount in sola lettura, senza copiare i BAM.
Un piano tecnico con più passaggi DNPcall deve rispettare questa associazione
in ciascun passaggio: un ordine diverso che rende gli alias incompatibili
viene rifiutato. Un ID del piano, per esempio `cfDNA_a`, può essere diverso
dall'alias `sample_0001`; la corrispondenza è conservata nei risultati.

Le analisi vengono eseguite una per volta, nell'ordine derivato dalle
dipendenze. `parallel: true` abilita esclusivamente il parallelismo interno
di DNPcall sui campioni; non esegue contemporaneamente i passaggi del piano.
Il motore passa le tabelle individuali DNPcall a Contamination e conserva
il riferimento al campione e al passaggio produttore. Lo staging di
Contamination usa `table_0001.txt`, `table_0002.txt` e successivi nell'ordine
dichiarato dal consumatore. Questi nomi interni non sostituiscono l'identità
dei campioni registrata nello stato.

### Preparazione SNPcall e identità dei campioni

Un passaggio SNPcall seleziona un solo ID da `samples`, un pannello SNP e la
modalità `bam` o `pileup`. Un BAM registrato può essere utilizzato sia da
DNPcall sia da SNPcall: questa condivisione non crea una dipendenza fra i due
passaggi. Il piano può contenere più attività SNPcall con risultati separati.
Le tabelle SNP non sono accettate come riferimenti `dnp-tables`.

Prima di creare la destinazione, il motore verifica i pannelli e gli input
esterni di tutti i passaggi: in modalità BAM richiede il FASTA e i suoi indici;
in modalità pileup controlla il formato con QNAME. Durante l'esecuzione usa
lo stesso adattatore SNPcall delle analisi singole. La modalità BAM genera
`work/snp_regions.bed`, esegue samtools per scrivere `work/pileup.txt` e ne
verifica il formato prima di avviare R. Errori o interruzioni di samtools non
permettono di proseguire con R. La modalità pileup non esegue samtools.

Ogni passaggio produce `output/SNPcall_output.txt`, senza rinominare o
riscrivere i risultati scientifici. La tabella completata è associata all'ID
campione in `artifacts.snp-tables`, con percorso relativo e SHA-256.
I file preparati da NIPAT sono elencati in `artifacts.preparation`, con tipo
`regions-bed` o `pileup`, percorso e SHA-256. Per un pileup importato questa
lista è vuota: l'input non viene presentato come file generato dal motore.

### Preparazione CPI e identità delle coppie

CPI accetta tabelle già registrate come `dnp-table` oppure risultati DNPcall
riferiti esplicitamente dal piano. I ruoli `mother` e `father` sono dichiarati
nelle coppie; il motore non li ricava dai nomi originali dei file. Riferimenti
materni e paterni allo stesso campione vengono respinti dal contratto.

Le tabelle ricevono identificatori `s0001`, `s0002` e successivi, assegnati alla
prima occorrenza nell'ordine delle coppie e dei ruoli materno/paterno. Un
riferimento condiviso nello stesso ruolo viene preparato una sola volta.
Il motore usa i prefissi interni `Mother` e `Father` e scrive le richieste
all'adattatore CPI già disponibile. Questi prefissi servono alla selezione
nativa dei file e non sostituiscono la dichiarazione dei ruoli biologici.

I risultati R restano invariati: il motore non sostituisce gli ID delle coppie
nel CSV e non riscrive i PDF. Lo stato del passaggio associa ogni coppia del
piano al nome nativo, per esempio `Mothers0001-Fathers0002_DNPs`, alle righe
del riepilogo e al PDF corrispondente. Le tre modalità di cutoff conservano
il comportamento dello script:

- `all`: una riga per coppia, senza colonna `Cutoff` nel CSV;
- `panel`: una riga per coppia, con il percorso interno `work/DNPpanel.txt`
  come valore `Cutoff`;
- `named`: una riga per ogni combinazione coppia/etichetta, con le etichette
  dichiarate nel piano.

Lo script produce `Summary_FetalFraction_CPI.csv` e, nella sottocartella
`plots`, un PDF per coppia e `All_CPIplots.pdf`; non salva tabelle di dettaglio per sito o per iterazione.
L'esecutore controlla le colonne del riepilogo, l'insieme atteso di coppie e
cutoff e la presenza e intestazione PDF degli output richiesti. Un CSV
incompleto, righe duplicate o grafici mancanti impediscono di considerare
il passaggio completato. Il controllo della struttura non interpreta la
validità biologica o la plausibilità dei valori scientifici.

### Evidenze e stati

| Percorso relativo alla destinazione `--run-dir` | Contenuto |
| --- | --- |
| `plan.json` | Piano canonico effettivamente eseguito. |
| `workflow-state.json` | Stato complessivo, stati e comandi dei passaggi, associazione degli output ai campioni. |
| `steps/<id>/request.json` | Richiesta concreta preparata per l'adattatore del passaggio. |
| `steps/<id>/command.log` | Output standard e messaggi di errore del processo R. |
| `steps/<id>/preparation.log` | Messaggi samtools, per i passaggi SNPcall da BAM. |
| `steps/<id>/work` | Pannelli, liste e tabelle preparati per R. |
| `steps/<id>/output` | Risultati scientifici del passaggio. |

Lo stato viene aggiornato con sostituzione atomica. Lo stato complessivo può
essere `running`, `succeeded`, `failed` o `cancelled`; i passaggi
possono assumere anche `pending` e `blocked`. I risultati DNPcall sono
identificati come
`dnp-tables`, quelli Contamination come `contamination-tables`, con campione,
nome interno, percorso relativo alla destinazione e SHA-256. Per Contamination
è conservato anche il riferimento alla tabella sorgente; il riepilogo ha un
percorso e un checksum distinti. Questi riferimenti evitano la deduzione
dell'identità dei campioni dai soli nomi dei file.

Per SNPcall da BAM, `preparation_command` e `preparation_log` identificano
il comando samtools e il suo log. Dopo la preparazione valida, il campo
`preparation_artifacts` conserva BED e pileup prima dell'avvio R. Queste
evidenze rimangono consultabili anche se R non completa il passaggio.

Prima di preparare i file o avviare R, il passaggio CPI registra `pair_mapping`,
con `pair`, riferimenti `mother` e `father` e `native_pair`. La mappa rimane
consultabile anche in caso di fallimento o cancellazione, per attribuire gli
output parziali. I riferimenti agli artefatti completati vengono aggiunti dopo
le verifiche degli output.

Il passaggio CPI completato registra in `artifacts`:

| Campo | Contenuto |
| --- | --- |
| `summary` | Percorso e SHA-256 del CSV riepilogativo. |
| `cpi-pairs` | Elenco delle coppie, ciascuna con `pair`, riferimenti `mother` e `father`, `native_pair`, `plot` e `summary_rows`. |
| `combined-plot` | Percorso e SHA-256 di `All_CPIplots.pdf`. |

`pair` mantiene l'ID del piano; `mother` e `father` mantengono i riferimenti
agli input. `plot` contiene percorso e checksum del PDF della coppia.
Ogni elemento di `summary_rows` contiene `row`, a partire da 1 senza contare
l'intestazione del CSV, e `cutoff`: `null` in modalità ALL, il percorso interno
del pannello singolo oppure l'etichetta dichiarata. Questa mappa collega i
risultati nativi alla richiesta senza modificare i file scientifici.

Un errore o un'interruzione arrestano il piano e marcano `blocked` tutti i
passaggi non ancora iniziati, anche se indipendenti. I risultati già prodotti
rimangono disponibili; non vengono presentati come successo dell'intero piano.
Un processo R con codice zero ma privo degli output richiesti non permette
di proseguire. Gli stati tecnici e i controlli delle tabelle non attestano
la validità scientifica del campione o del modello.

La cancellazione viene inoltrata al gruppo di processi scientifici, compresi
i processi figli. Il client concede un intervallo di arresto prima della
rimozione forzata del container. Uno spegnimento o un arresto forzato possono
impedire l'ultimo aggiornamento dello stato: `running` non è un esito positivo
né una prova che il processo sia ancora attivo. Non sono previsti ripresa
o riutilizzo del run; correggere la causa e scegliere una destinazione nuova.

Il codice di uscita è `0` solo quando tutti i passaggi sono completati.
Gli errori di validazione restituiscono `2`; un fallimento scientifico conserva
il codice del processo e un'interruzione usa `128 + numero del segnale`.
Lo stato del piano costituisce l'evidenza dei passaggi eseguiti; il record
`run.json` del client aggiunge input host, immagine e identità dell'applicazione.

## Errori e limiti della verifica

L'API solleva `PlanValidationError`, sottoclasse di `ValidationError`, con
attributo `code` stabile. Il testo diagnostico è separato dall'identificatore
e può essere presentato dall'interfaccia nella lingua selezionata.

| Codice | Significato |
| --- | --- |
| `plan.schema` | Versione del contratto non supportata. |
| `plan.fields` | Oggetto con campi mancanti, sconosciuti o struttura errata. |
| `plan.identifier` | Identificatore non ammesso. |
| `plan.path` | Percorso container non valido. |
| `plan.list` | Lista richiesta mancante, vuota o di tipo errato. |
| `plan.duplicate` | Identità, percorso campione, riferimento o coppia duplicati. |
| `plan.sample_missing` | Campione non presente nel registro. |
| `plan.sample_kind` | Tipo di campione incompatibile o sconosciuto. |
| `plan.workflow` | Analisi non supportata. |
| `plan.step_missing` | Produttore non presente nel piano. |
| `plan.output_kind` | Tipo di output o produttore incompatibile. |
| `plan.output_sample` | Campione non prodotto dal passaggio indicato. |
| `plan.cycle` | Dipendenza ciclica, compreso un riferimento al passaggio stesso. |
| `plan.parameter` | Parametro non valido o incoerente con la modalità scelta. |
| `plan.roles` | Assegnazione CPI materna/paterna incoerente. |
| `plan.cutoff_mode` | Modalità o numero di pannelli cutoff incoerenti. |
| `plan.cutoff_label` | Etichetta cutoff non valida. |

Un piano accettato dal validatore può ancora contenere file inesistenti,
tabelle malformate, un riferimento genomico inappropriato o campioni non
idonei. Queste verifiche appartengono rispettivamente alla preparazione
effettiva degli input e alla valutazione scientifica. La validazione del
contratto non sostituisce le regressioni numeriche né le prove di dominio.

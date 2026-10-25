# Contratto dei piani scientifici

Un piano descrive campioni, analisi e collegamenti fra risultati attraverso
identificatori espliciti. Il contratto `schema_version: 1` appartiene al
motore scientifico `nipat_scientific`, incluso nell'immagine Linux. Non dipende
dal menu Windows, da una GUI o dalla lingua dell'interfaccia.

Il comando del motore `validate-plan --plan FILE` controlla la struttura e
le dipendenze e restituisce JSON. **Questa validazione non esegue il piano**:
non avvia R o samtools, non crea risultati e non controlla esistenza,
contenuto o compatibilità biologica dei file. L'esecuzione automatica dei
piani non è disponibile tramite questo contratto di validazione.

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
contaminazione non modifica i dati usati dal CPI.

```json
{
  "schema_version": 1,
  "samples": [
    {
      "id": "cfDNA_a",
      "kind": "bam",
      "path": "/workspace/inputs/cfdna_a.bam"
    },
    {
      "id": "paternal_a",
      "kind": "bam",
      "path": "/workspace/inputs/paternal_a.bam"
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

La successiva esecuzione dovrà risolvere i riferimenti in file effettivi e
produrre le richieste già supportate dagli adattatori dei quattro script.
I nomi interni e i prefissi CPI `mother_prefix` e `father_prefix` saranno
assegnati durante questa preparazione conservando la mappa delle identità
esplicite. Non sono parametri scientifici rimossi: appartengono alla selezione
dei file nativa R, qui rappresentata dai riferimenti delle coppie. Le cartelle
`work` e `output` appartengono alla singola esecuzione e non sono impostate
arbitrariamente nel piano. Non viene promessa una corrispondenza fra ID
del piano e nomi generati dal codice R.

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

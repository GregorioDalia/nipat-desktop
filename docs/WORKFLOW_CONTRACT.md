# Contratto dei piani scientifici

Un piano descrive campioni, analisi e collegamenti fra risultati attraverso
identificatori espliciti. Il contratto `schema_version: 1` appartiene al
motore scientifico `nipat_scientific`, incluso nell'immagine Linux. Non dipende
dal sistema host, dal menu, da una GUI o dalla lingua dell'interfaccia.

Il comando del motore `validate-plan --plan FILE` controlla la struttura e
le dipendenze e restituisce JSON. **Questa validazione non esegue il piano**:
non avvia R o samtools, non crea risultati e non controlla esistenza,
contenuto o compatibilità biologica dei file.

Il comando distinto `execute-plan --plan FILE --run-dir DIR` esegue
piani composti dai cinque moduli: DNPcall, SNPcall, Contamination, CPI
prenatale e CPIN postnatale. DNPcall e SNPcall producono tabelle tipizzate
utilizzabili da tutti e tre i consumatori. Un passaggio SNPcall seleziona
un solo BAM o pileup; più passaggi possono condividere il pannello.
Le analisi singole restano disponibili tramite `execute`.

La CLI desktop `workflow analyze` e il menu **W → 5** compongono i rami DNP,
SNP o entrambi, anche da tabelle già disponibili. Ogni ramo può eseguire
qualsiasi sottoinsieme di Contamination, CPI e CPIN; i due rami possono
scegliere analisi diverse. Il client genera il JSON a partire dagli input
confermati nel menu o dagli argomenti della CLI.

Prima dell'avvio di ciascun script R, il motore esegue anche i controlli
sul contenuto degli input descritti in [INPUT_VALIDATION.md](INPUT_VALIDATION.md).
Questi controlli appartengono all'esecuzione, non a `validate-plan`, e sono
condivisi con le analisi singole. I pannelli normalizzati e il resoconto
`work/input-validation.json` appartengono alla cartella del passaggio.
Gli output sono verificati prima di essere dichiarati utilizzabili dal
passaggio dipendente. Gli avvisi numerici sono conservati in
`artifacts.quality_warnings`: non trasformano le tabelle R e non attestano
la validità scientifica di un risultato tecnicamente completato.

## Struttura della richiesta

La richiesta contiene `schema_version`, `samples` e `steps` e può aggiungere
il campo opzionale `presentation`.
Campi sconosciuti o mancanti sono errori; non vengono ignorati. Le opzioni
obbligatorie di orchestrazione devono essere scritte esplicitamente.
`scientific_settings` e alcuni campi scientifici sono invece facoltativi:
l'omissione usa i default del registro incluso nel motore. La configurazione
effettiva viene conservata per ciascun passaggio.

Il registro `samples` contiene oggetti con questi tre campi:

| Campo | Contenuto |
| --- | --- |
| `id` | Identità del campione nel piano, indipendente dal nome del file. |
| `kind` | `bam`, `dnp-table`, `snp-table` oppure `snp-pileup`. |
| `path` | Percorso assoluto POSIX del file nel container. |

Gli identificatori di campioni, passaggi, coppie e terne usano da 1 a 64 caratteri
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
`parameters`. `workflow` identifica uno dei cinque moduli supportati.

| Workflow | Campi esatti di `inputs` | Parametri di orchestrazione |
| --- | --- | --- |
| `dnp-call` | `samples`: lista di ID BAM; `reference`: FASTA; `panel`: pannello DNP | `parallel`: booleano. |
| `snp-call` | `sample`: ID BAM o pileup; `reference`: FASTA oppure `null`; `panel`: pannello SNP | `mode`: `bam` oppure `pileup`. |
| `contamination` | `samples`: lista di riferimenti a tabelle; `panel`: pannello di coordinate | Nessun campo obbligatorio specifico. |
| `cpi` | `pairs`: coppie esplicite; `popfreq`: frequenze di popolazione; `cutoffs`: pannelli selezionati | `cutoff_mode`: `all`, `panel` o `named`; `err_const` facoltativo, finito in `(0, 1]`. |
| `cpin` | `trios`: terne esplicite; `popfreq`: frequenze di popolazione; `markers`: pannello con REF/ALT oppure `null` | Nessun campo obbligatorio specifico. |

Tutti i passaggi accettano in `parameters` un oggetto facoltativo
`scientific_settings`, contenente le modifiche per quel modulo. I consumatori
accettano anche `marker_type: "SNP"` oppure `"DNP"`: il validatore lo deduce
se omesso e ne verifica la coerenza se dichiarato. Una singola analisi a valle
non può mescolare tabelle SNP e DNP. Le frequenze e i pannelli devono avere
il tipo di coordinate corrispondente; l'esecutore ne verifica il contenuto.

`nipat settings` mostra default, tipi, limiti, vincoli fra parametri e costanti
consultabili; `nipat settings --export FILE` salva un JSON riutilizzabile con
`--scientific-config FILE`. Le modifiche `--set modulo.parametro=valore`
prevalgono sul file. Sono rifiutate chiavi sconosciute, valori non finiti,
tipi errati e combinazioni di soglie non valide. Il client porta queste
impostazioni nei passaggi e nei metadati del run; Python e R leggono lo stesso
registro. Le formule e le altre invarianti del modello sono documentate,
senza diventare parametri modificabili.

SNPcall in modalità `bam` richiede un campione `bam` e un FASTA. In modalità
`pileup` richiede un campione `snp-pileup` e `reference: null`. Le impostazioni
con cui è stato prodotto un pileup esterno non sono ricostruite né attribuite
automaticamente a NIPAT.

## Riferimenti tipizzati e ruoli familiari

Contamination, CPI e CPIN accettano questi riferimenti:

- `{"sample": "table_a"}` seleziona un campione registrato come `dnp-table`
  oppure `snp-table`.
- `{"step": "dnp", "output": "dnp-tables", "sample": "sample_a"}` seleziona
  la tabella individuale prodotta da DNPcall per quel campione.
- `{"step": "snp_a", "output": "snp-tables", "sample": "sample_a"}` seleziona
  la tabella prodotta dal passaggio SNPcall per quel campione.

Un riferimento a un produttore crea una dipendenza e deve avere il tipo
corretto: SNPcall produce `snp-tables`, DNPcall produce `dnp-tables`.
Riepiloghi Contamination e risultati CPI/CPIN non sostituiscono le tabelle
di conteggi. Non si possono usare percorsi ipotizzati di risultati futuri
al posto dei riferimenti tipizzati.

Ogni coppia CPI contiene `id`, `mother` e `father`:

- `mother` identifica esplicitamente la tabella **cfDNA materna**;
- `father` identifica esplicitamente la tabella del **campione paterno**.

Entrambi sono riferimenti alle tabelle descritti sopra. I ruoli non vengono
dedotti da nomi, prefissi o ordine dei campioni. Lo stesso campione non può
assumere entrambi i ruoli in un passaggio CPI, anche se proviene da due
elaborazioni del caller differenti. Sono consentite più coppie che riutilizzano
un campione nello stesso ruolo; coppie duplicate non sono ammesse.
La correttezza biologica dell'assegnazione resta responsabilità di chi prepara
il piano: il contratto controlla la coerenza dichiarata, non il tipo di materiale.

Ogni terna CPIN contiene `id`, `mother`, `father` e `child`, tutti riferimenti
alle tabelle dello stesso tipo. I tre campioni devono avere identità globali
distinte; lo stesso campione può essere riutilizzato in più terne nello stesso
ruolo. Terne duplicate o ruoli contraddittori vengono respinti. Il ruolo materno
CPIN riguarda il campione della madre: non viene equiparato automaticamente
al cfDNA materno del CPI prenatale.

Negli input nativi delle analisi singole, gli ID locali vengono invece
combinati con i prefissi dei file. `A:A:A` è valido per CPIN con i prefissi
`Mother`, `Father`, `Child` quando indica tre file e campioni distinti.
Il piano usa riferimenti globali e non richiede queste convenzioni di nomi.

Le modalità cutoff conservano la struttura dell'adattatore CPI:

| `cutoff_mode` | Valore di `cutoffs` |
| --- | --- |
| `all` | Lista vuota `[]`; nessun pannello cutoff. |
| `panel` | Un elemento con `label: ""` e `path` del pannello. |
| `named` | Uno o più elementi con `label` non vuota e `path`. |

Le etichette dei pannelli devono essere univoche e non possono contenere
virgole, `=` o caratteri di controllo, né spazi iniziali o finali. `err_const`
è facoltativo: se presente sovrascrive la costante del tipo di marcatori
selezionato e deve appartenere a `(0, 1]`. Se omesso, il registro propone
`err_const_snp = 0.001` e `err_const_dnp = 0.0000892303778101497`, entrambi
configurabili. Zero non è ammesso dal modello aggiornato.

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
conservato. Questo è un ordinamento delle dipendenze, non una promessa di
esecuzione strettamente seriale: l'esecutore può raggruppare passaggi SNP
indipendenti entro il budget comune, anche in piani misti.

`report["plan"]` può essere validato nuovamente ottenendo lo stesso resoconto.
Il resoconto completo non è invece una richiesta: l'input non ammette
`execution_order`, perché l'ordine deve derivare dai riferimenti e non può
essere imposto dal chiamante. I cicli e i riferimenti a passaggi, campioni o
tipi di output inesistenti vengono respinti.

Le cartelle `work` e `output` appartengono alla singola esecuzione e non
sono impostate arbitrariamente nel piano. Gli ID del piano identificano i
campioni; non devono essere interpretati come nomi generati dal codice R.
Per CPI e CPIN, il contratto rappresenta le selezioni di file mediante
riferimenti espliciti a coppie e terne. L'esecutore li traduce nei nomi interni
e conserva la corrispondenza fra famiglie dichiarate, input dei rispettivi
ruoli e risultati nativi. Non occorre rinominare gli originali.

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
espone `plan_execution.interface: workflow-plan-execution-v2`, i workflow
eseguibili `dnp-call`, `snp-call`, `contamination`, `cpi` e `cpin`, la pianificazione
`dependency-order-with-bounded-independent-snp` e
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

I piani eseguono i consumatori dopo la disponibilità delle tabelle richieste.
I passaggi SNPcall indipendenti possono eseguire più campioni contemporaneamente
entro il budget comune anche nei piani misti; i worker campione mantengono
seriali i propri pool R. La modalità `serial` impone un solo processo di
calcolo. Il parametro DNP `parallel` non scavalca la policy comune di esecuzione,
che determina il parallelismo effettivo.
Il motore passa le tabelle individuali SNP o DNP a Contamination e conserva
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

Il pannello normalizzato usa `chr`, `pos`, `ref` e `alt`. L'input può
anche usare tre colonne, con `pos=chr:posizione`, `ref` e `alt`.
Per default samtools usa `-d 0`, come SNPcall 2.0; `max_depth` e gli altri
parametri di acquisizione sono configurabili. R usa riferimento e qualità
del pileup e raggruppa le osservazioni per SNP e QNAME. Una modifica dei
parametri di acquisizione non ricalcola un pileup importato.

Ogni passaggio produce `output/SNPcall_output.txt`, senza rinominare o
riscrivere i risultati scientifici. La tabella completata è associata all'ID
campione in `artifacts.snp-tables`, con percorso relativo e SHA-256.
I file preparati da NIPAT sono elencati in `artifacts.preparation`, con tipo
`regions-bed` o `pileup`, percorso e SHA-256. Per un pileup importato questa
lista è vuota: l'input non viene presentato come file generato dal motore.

La tabella SNP 2.0 comprende conteggi `N_REF`, `N_ALT`, `N_Other`,
log-likelihood `GL0`/`GL1`/`GL2`, `GT` e statistiche degli indel. Il nuovo
schema mantiene coordinate e modello SNP: CPI, Contamination e CPIN lo
consumano come SNP, senza convertirlo artificialmente in DNP.

Per campioni distinti con lo stesso pannello, riferimento e modalità, la
finalizzazione crea `snp_summary/group_0001` e gruppi successivi, con genotipi
uniti, risorse per campione, etichette e grafici dei genotipi mancanti e
delle intersezioni. Analisi ripetute dello stesso campione non diventano
individui aggiuntivi. Le tabelle individuali e i relativi checksum restano
disponibili. L'UpSet considera assegnato un genotipo diverso da `NA`.

### Preparazione CPI e identità delle coppie

CPI accetta tabelle registrate come `dnp-table`/`snp-table` oppure risultati
DNPcall/SNPcall riferiti esplicitamente dal piano. Ogni passaggio usa un solo
tipo di marcatori e le frequenze corrispondenti. I ruoli `mother` e `father` sono dichiarati
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
- `panel`: una riga per coppia, con il percorso del pannello normalizzato
  come valore `Cutoff`;
- `named`: una riga per ogni combinazione coppia/etichetta, con le etichette
  dichiarate nel piano.

Lo script produce `Summary_FetalFraction_CPI.csv` e, nella sottocartella
`plots`, un PDF per coppia e `All_CPIplots.pdf`. Esporta inoltre in `curves`
le curve per coppia/pannello, calcolate per intervalli di soglie equivalenti;
non produce una tabella CPI per ogni sito.
L'esecutore controlla le colonne del riepilogo, l'insieme atteso di coppie e
cutoff e la presenza e intestazione PDF degli output richiesti. Un CSV
incompleto, righe duplicate o grafici mancanti impediscono di considerare
il passaggio completato. Il controllo della struttura non interpreta la
validità biologica o la plausibilità dei valori scientifici.

### Preparazione CPIN e identità delle terne

CPIN riceve tabelle SNP oppure DNP, una frequenza di popolazione coerente
e terne esplicite. `inputs.markers` è `null` per tutti i siti oppure indica
un pannello con coordinate **e alleli REF/ALT**. Un semplice elenco di
coordinate privo di alleli non è sufficiente per questo parametro.

`scientific_settings.site_selection` seleziona `other_allele`, `all` oppure
`both`; sono configurabili anche letture minime del figlio, costanti d'errore
e soglie genotipiche. Le tabelle condivise vengono preparate una volta e
`trio_mapping` collega ID del piano, tre ruoli e identificativo nativo.

Il modulo produce `Summary_Postnatal_CPI.txt`, dettaglio dei siti in `sites`,
curve per intervalli in `curves`, PDF per terna/analisi in `plots` e
`All_CPIplots.pdf` nella radice degli output. La verifica del passaggio
controlla riepilogo, combinazioni attese di terne e analisi, tabelle e PDF;
le associazioni completate sono pubblicate in `artifacts.cpin-trios`.

### Evidenze e stati

| Percorso relativo alla destinazione `--run-dir` | Contenuto |
| --- | --- |
| `plan.json` | Piano canonico effettivamente eseguito. |
| `workflow-state.json` | Stato complessivo, stati e comandi dei passaggi, associazione degli output ai campioni. |
| `steps/<id>/request.json` | Richiesta concreta preparata per l'adattatore del passaggio. |
| `steps/<id>/command.log` | Output standard e messaggi di errore del processo R. |
| `steps/<id>/preparation.log` | Messaggi samtools, per i passaggi SNPcall da BAM. |
| `steps/<id>/work` | Pannelli, liste e tabelle preparati per R. |
| `steps/<id>/work/effective-scientific-settings.json` | Parametri effettivi e costanti del passaggio. |
| `steps/<id>/output` | Risultati scientifici del passaggio. |

Lo stato viene aggiornato con sostituzione atomica. Lo stato complessivo può
essere `running`, `succeeded`, `failed` o `cancelled`; i passaggi
possono assumere anche `pending` e `blocked`. I risultati DNPcall sono
identificati come `dnp-tables`, quelli SNPcall come `snp-tables` e quelli
Contamination come `contamination-tables`, con campione,
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
| `plan.roles` | Assegnazione materna/paterna CPI o madre/padre/figlio CPIN incoerente. |
| `plan.marker_type` | Tipo SNP/DNP dichiarato incoerente o tabelle di tipi diversi nello stesso consumatore. |
| `plan.cutoff_mode` | Modalità o numero di pannelli cutoff incoerenti. |
| `plan.cutoff_label` | Etichetta cutoff non valida. |

Un piano accettato dal validatore può ancora contenere file inesistenti,
tabelle malformate, un riferimento genomico inappropriato o campioni non
idonei. Queste verifiche appartengono rispettivamente alla preparazione
effettiva degli input e alla valutazione scientifica. La validazione del
contratto non sostituisce le regressioni numeriche né le prove di dominio.

## Presentazione dei campioni

`presentation` contiene esattamente `samples` e `pairs`. La prima mappa
associa ogni ID campione a un nome originale senza componenti di percorso;
la seconda associa zero o più ID di coppia CPI o terna CPIN presenti nel
piano a etichette leggibili. Sono rifiutati nomi vuoti, caratteri di controllo, ID estranei e
mappature incomplete dei campioni. Le etichette non cambiano gli ID del piano.

I passaggi producono i propri export in `output/presentation`; l'indice
complessivo è in `presentation` sotto la radice del workflow. Gli output
canonici, le dipendenze e i checksum rimangono distinti. Il
[contratto del motore](../engine/README.md#etichette-leggibili) descrive
la separazione tra calcolo ed esportazione.

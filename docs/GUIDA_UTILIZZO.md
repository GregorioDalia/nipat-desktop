# Guida per l'utilizzo di NIPAT

NIPAT Desktop esegue sul computer dell'utente cinque analisi di dati genetici.
Il menu guidato permette di compilare un'analisi passo per passo. La CLI
accetta gli stessi tipi di input e permette di ripetere un comando da uno script.

- [Installazione e avvio](#requisiti-e-avvio-su-windows)
- [Menu guidato](#menu-guidato)
- [File richiesti dai cinque moduli](#input-dei-cinque-moduli)
- [Comandi diretti](#comandi-diretti) e [parametri scientifici](#parametri-scientifici-valori-effettivi-e-costanti)
- [Workflow automatici](#risultati-e-analisi-in-sequenza)
- [Risultati e risoluzione dei problemi](#problemi-e-segnalazioni)

## Requisiti e avvio su Windows

Scaricare **NIPAT-Setup.exe** dalla [pagina delle release](https://github.com/GregorioDalia/nipat-desktop/releases/latest).
Il pacchetto è per Windows 10 22H2 x64 (build 19045) o Windows 11 x64 con
virtualizzazione e WSL2. Il setup prepara un ambiente dedicato con gli strumenti
scientifici. L'attivazione iniziale di WSL può richiedere Internet, autorizzazione
amministrativa e riavvio.

1. Aprire il file scaricato da Esplora file, dal proprio account.
2. Scegliere le cartelle dell'applicazione, dell'ambiente WSL, della cache,
   dei dati e dei risultati. Si possono mantenere i valori proposti.
3. Attendere **`NIPAT: ready`**, poi aprire **NIPAT Desktop** dal menu Start.
   Se è richiesto un riavvio, completarlo e seguire le indicazioni del setup.

Per riprendere una preparazione incompleta, risolvere l'errore segnalato e aprire
**NIPAT Desktop - completa preparazione** dal menu Start. Se Windows o il
browser blocca il setup, annotare il messaggio e il componente indicato. La
[guida Windows](INSTALLATORE_WINDOWS.md) descrive requisiti, diagnostica,
riparazione e disinstallazione.

## Requisiti e avvio su macOS

Su macOS 14 o successivo scaricare il `.pkg` **arm64** per Apple Silicon
oppure **x86_64** per Intel. Installare il pacchetto e aprire **NIPAT Desktop**
da Applicazioni. Il primo avvio nel Terminale prepara la VM Lima e richiede
Internet. Su Apple Silicon, l'immagine scientifica Linux AMD64 usa Rosetta
nella VM. Per i requisiti, i percorsi e le protezioni del sistema consultare
la [guida macOS](INSTALLATORE_MACOS.md).

## Utilizzo su Ubuntu

Su Ubuntu 24.04 x86_64 installare il pacchetto `.deb` con APT.
L'ambiente scientifico usa Docker Engine locale, che deve essere accessibile
all'utente. Avviare il menu con `nipat`. La
[guida Ubuntu](INSTALLATORE_LINUX.md) descrive installazione e diagnosi.

## Menu guidato

| Tasto | Funzione |
| --- | --- |
| `1` | DNPcall da uno o più BAM. |
| `2` | SNPcall da un BAM o un pileup. |
| `3` | Contamination da tabelle di conteggi. |
| `4` | CPI prenatale da coppie di campioni. |
| `N` | CPIN postnatale da terne di campioni. |
| `W` | Workflow automatici con più passaggi. |
| `5` | Configurazione delle analisi guidate. |
| `6` | Ultima esecuzione della sessione, anche fallita o interrotta. |
| `7` | Guida, catalogo, esecuzioni incomplete e manutenzione. |
| `8` | Verifica dell'ambiente scientifico. |
| `9` | Verifica degli aggiornamenti. |
| `0` | Esci. |

Usare frecce e Invio o il tasto indicato. Se il terminale non supporta le
frecce o la finestra è troppo piccola, la stessa scelta è disponibile in testo.
Invio mantiene il valore proposto o chiude un elenco di file già compilato.
Nei campi usare `:indietro` per tornare al campo precedente, `:vuoto` per
svuotare un valore facoltativo, `:annulla` per tornare al menu principale.

Prima di confermare, verificare file, parametri scientifici, modalità di
esecuzione e destinazione nel riepilogo. La voce **Avvia analisi** avvia
il calcolo ordinario. **Avvia analisi con diagnostica prestazioni** aggiunge
le misure per quel run. Il solo Invio sul riepilogo annulla l'avvio.
Durante il calcolo, Ctrl+C richiede l'arresto e conserva log e output già
prodotti. Attendere il ritorno del controllo e verificare eventuali avvisi
sull'arresto prima di iniziare un altro run. La
[guida alle esecuzioni](ESECUZIONI.md#esecuzioni-incomplete) spiega come
consultare una sessione incompleta.

### Configurazione del menu

Con **5 — Configura** si salvano cartelle, pannelli, riferimenti, impostazioni
scientifiche, limiti di calcolo e canale di aggiornamento. **9 — Salva
modifiche** salva la categoria corrente. **0 — Annulla modifiche** la chiude
scartando le modifiche ancora da salvare. Campioni, coppie, terne e nome
del run vengono indicati a ogni analisi.

I comandi diretti usano le opzioni CLI e i propri valori predefiniti.
Per vedere le impostazioni scientifiche usare **Configura → S** nel menu
oppure [`settings` nella CLI](#parametri-scientifici-valori-effettivi-e-costanti).
Un file delle preferenze illeggibile viene segnalato e blocca le analisi
guidate. **Ripristina impostazioni** azzera le preferenze dopo conferma.

### Percorsi e cartelle

Gli input possono rimanere nella posizione originale. I percorsi relativi
si risolvono dalla cartella corrente mostrata nel menu. Nei file elenco
BAM, invece, partono dalla posizione dell'elenco. Su Windows usare dischi
locali fissi per dati e risultati. Su macOS i percorsi devono essere
accessibili alla VM Lima. Su Ubuntu devono essere accessibili al motore
Docker locale.

| Sistema | Cartella risultati predefinita |
| --- | --- |
| Windows | `%LOCALAPPDATA%\NIPAT-Desktop\runs` |
| macOS | `~/Library/Application Support/NIPAT-Desktop/runs` |
| Ubuntu | `~/.local/share/nipat-desktop/runs`, salvo `XDG_DATA_HOME`. |
| Checkout da sorgenti | `runs` accanto alla cartella del progetto. |

La cartella risultati deve essere scrivibile e separata da applicazione e
cartella dati. **Configura → Cartelle dati e risultati** cambia la destinazione
proposta per il menu. Nella CLI usare `--runs-dir` prima del comando.
I risultati già prodotti restano nella propria cartella. Per un nome automatico
lasciare vuoto il campo del run nel menu o omettere `--run-name`.

### Aggiornamenti e spazio

**9 — Verifica aggiornamenti** consulta le release compatibili con sistema,
architettura e canale. Mostra le note e verifica il pacchetto scaricato.
Chiudere NIPAT prima di sostituire l'applicazione. Su Mac aprire il `.pkg`
verificato al termine del download.

Su Windows, **Guida e informazioni → Installazione e spazio** mostra
ambiente e cache di proprietà dell'installazione. La pulizia riguarda soltanto
i componenti indicati come rimovibili, dopo conferma. **Ripara/riprendi
preparazione** verifica la configurazione corrente, il runtime e gli
autotest. Consultare l'esito finale della finestra di manutenzione e il
[registro dell'installatore](INSTALLATORE_WINDOWS.md).

## Input dei cinque moduli

| Modulo | Input essenziali | Risultato principale |
| --- | --- | --- |
| DNPcall | BAM, FASTA indicizzato e pannello DNP. | Conteggi e genotipi DNP per campione. |
| SNPcall | Pannello SNP e un BAM con FASTA indicizzato, oppure un pileup con QNAME. | Conteggi, likelihood e genotipi SNP per campione. |
| Contamination | Tabelle di conteggi e pannello dello stesso tipo SNP o DNP. | Stime per sito e riepilogo per campione. |
| CPI | Tabelle cfDNA materne e paterne, coppie, frequenze di popolazione e cutoff facoltativi. | Frazione fetale, CPI, curve e grafici. |
| CPIN | Tabelle di madre, padre e figlio, terne, frequenze e pannello facoltativo. | CPI postnatale, dettaglio siti, curve e grafici. |

I pannelli, le tabelle e i riferimenti devono avere coordinate e tipo di
marcatori coerenti. Gli input originali rimangono disponibili. NIPAT prepara
le copie di lavoro necessarie e controlla [formati e segnalazioni](INPUT_VALIDATION.md).

### DNPcall

Fornire i BAM con `--bam` ripetuto oppure un elenco senza intestazione,
un BAM per riga, con `--bamlist`. Indicare il **file FASTA** con
`--reference`. Il FASTA richiede il proprio indice `.fai` e, se compresso
in BGZF, anche `.gzi`. Con un indice BAM valido il motore può scegliere
un percorso di acquisizione indicizzato. L'indice BAM è facoltativo
per l'acquisizione a scansione.

Il pannello usa cinque colonne senza intestazione, separate da spazi o
tabulazioni: `chr pos1 pos2 REF ALT`. Le coordinate sono positive e
adiacenti (`pos2 = pos1 + 1`), ciascun locus è unico e gli alleli sono
dinucleotidi A/C/G/T. Concordare l'assemblaggio e i nomi dei cromosomi
fra riferimento, BAM e pannello.

### SNPcall

Per un BAM usare `--bam` e `--reference` con FASTA indicizzato. Per un
pileup già prodotto usare `--pileup`. Serve un pannello con intestazioni
tabulate `chr`, `pos`, `ref`, `alt`. È ammesso anche `pos`, `ref`,
`alt` con `pos` in forma `chr1:1770788`. Le posizioni ammesse sono
da 2 a 2147483646, per la finestra di tre basi, con coordinate uniche
e basi REF/ALT distinte. Il cromosoma non contiene spazi o `:`.

Il pileup importato deve essere tabulato, senza intestazione, con i nomi
delle letture (QNAME) nella settima colonna. Per un BAM NIPAT prepara
questa informazione automaticamente con samtools. I filtri di acquisizione
di un pileup importato dipendono dal comando con cui è stato prodotto.

La tabella `SNPcall_output.txt` contiene 17 colonne.

| Colonne | Significato |
| --- | --- |
| `chr`, `pos`, `REF`, `ALT` | Coordinate e alleli del pannello. |
| `N_REF`, `N_ALT`, `N_Other`, `total_count` | Conteggi dopo i filtri; il totale comprende le altre basi. |
| `ratio` | Frazione REF su REF + ALT, quando definita. |
| `GL0`, `GL1`, `GL2` | Log-likelihood naturali per `0/0`, `0/1`, `1/1`. |
| `GT` | Genotipo assegnato. Può essere `NA` se mancano osservazioni informative o il controllo delle altre basi non è superato. |
| `reads_discarded_for_indels`, `ratio_reads_discarded_for_indels` | Numero e frazione di osservazioni complete con indel sulla base centrale. |
| `combined_bases`, `combined_counts` | Basi e conteggi corrispondenti separati da trattini, nello stesso ordine. |

Il [catalogo scientifico](CATALOGO_SCIENTIFICO.md) descrive i filtri e gli
indicatori. La preparazione da BAM usa `samtools mpileup -d 0` per
impostazione predefinita.

### Contamination

Selezionare tabelle individuali con `--input` ripetuto. La modalità
`--input-dir` cerca ricorsivamente i file TXT e TSV, escluso il pannello
selezionato. Se la cartella contiene riepiloghi o file eterogenei,
selezionare direttamente le tabelle compatibili.

Servono `N_REF`, `N_ALT`, `N_Other` interi non negativi e coordinate
univoche `chr,pos` per SNP oppure `chr,pos1,pos2` per DNP.
Se le tabelle includono `ratio_REF_ALT`, NIPAT lo conserva e segnala
un'eventuale incoerenza con i conteggi. Il pannello richiede le coordinate
del medesimo tipo e può includere gli alleli. Il filtro sulle altre basi
usa `N_Other / (N_REF + N_ALT + N_Other)`.
La stima per sito usa i conteggi inattesi su `N_REF + N_ALT`.
I siti con stima zero sono inclusi per impostazione predefinita, con
possibilità di regolare soglie e `include_zero`.

Il riepilogo riporta la media e la deviazione standard sui siti informativi.
Una frazione `0.025` equivale al 2,5%. Il conteggio dei siti informativi
e gli eventuali valori `NA` aiutano a interpretare il risultato.

### CPI

Fornire una cartella con le tabelle di cfDNA materno e del presunto padre
e il file delle frequenze di popolazione. Le tabelle contengono coordinate,
`REF`, `ALT`, `N_REF`, `N_ALT`, `N_Other` e `total_count`. Le
frequenze contengono le coordinate dello stesso tipo e `Ref_f.pop`,
`Alt_f.pop`. Le frequenze devono essere finite, in `(0, 1]`, con loci
univoci. NIPAT segnala una somma REF/ALT diversa da uno.

Nell'analisi singola `--pairs A1:A1` seleziona `MotherA1.txt` e
`FatherA1.txt` con i prefissi predefiniti. Più coppie si separano con
virgole. Nei workflow i ruoli vengono assegnati esplicitamente a ogni
coppia. La corrispondenza dei file riguarda la forma dei dati e il ruolo
dichiarato. La scelta dei campioni e delle frequenze compete a chi esegue
l'analisi.

| Selezione dei siti | Opzione CLI del comando `cpi` |
| --- | --- |
| Tutti i siti disponibili | Omettere l'opzione di filtro. |
| Un pannello | `--panel PATH` |
| Più pannelli con etichette univoche | `--cutoff LABEL PATH`, ripetibile. |
| Mappa di pannelli | `--cutoff-map "LABEL=PATH,LABEL2=PATH2"` |

Le opzioni sono alternative. La forma ripetuta `--cutoff` permette di
gestire percorsi che contengono virgola o `=`. Per impostare una costante
d'errore specifica del run usare `--err-const` con valore finito in
`(0, 1]`. Omettendola si usa il parametro del tipo SNP o DNP selezionato.

### CPIN / CPI postnatale

Fornire una cartella con le tabelle di madre, padre e figlio, le terne e
le frequenze. I ruoli devono riguardare tre campioni distinti. Le tabelle
e le frequenze usano lo stesso schema SNP o DNP del CPI. Con
`--trios A:A:A` e prefissi predefiniti i file sono `MotherA.txt`,
`FatherA.txt` e `ChildA.txt`. Più terne si separano con virgole.

Un pannello CPIN facoltativo richiede coordinate **e alleli REF/ALT**.
Senza pannello si usano i siti disponibili. `cpin.site_selection` accetta
`other_allele`, `all` o `both`; vedere i [parametri effettivi](#parametri-scientifici-valori-effettivi-e-costanti)
per letture minime, costanti e filtri.

## Parametri scientifici, valori effettivi e costanti

In **Configura → S** si consultano e salvano i parametri dei moduli; la
voce **5 — Parametri scientifici e costanti** del riepilogo modifica solo
l'analisi in corso. Per consultare regole
e formati, scegliere **Guida e informazioni → Catalogo scientifico**
o utilizzare `parameters`.

```powershell
& $nipat settings cpin
& $nipat parameters snp-call --section preparation
& $nipat settings --export ".\parametri.json"
& $nipat --scientific-config ".\parametri.json" --set cpin.min_child_reads=4 settings cpin
```

Il file di configurazione è un JSON per modulo, ad esempio
`{"snp-call":{"min_base_quality":20},"cpin":{"site_selection":"both"}}`.
Può contenere le sole modifiche da applicare oppure tutti i parametri.
`--set modulo.chiave=valore`
è ripetibile e prevale sul file. `settings` mostra i valori effettivi,
gli intervalli ammessi e le costanti. I risultati conservano le impostazioni
applicate per rendere il confronto ripetibile.

## Comandi diretti

Negli esempi PowerShell, `$nipat` indica il launcher della cartella
effettivamente installata, anche se scelta durante il setup.

```powershell
$app = (Get-ItemProperty -LiteralPath 'HKCU:\Software\NIPAT\desktop' -Name app_dir).app_dir
$nipat = Join-Path $app 'nipat.cmd'
& $nipat --version
& $nipat --help
& $nipat wizard
```

Su Ubuntu usare `nipat`. Su macOS usare
`/Applications/NIPAT Desktop.app/Contents/Resources/NIPAT.command`
tra virgolette dalla shell. Nei comandi POSIX, sostituire i percorsi con
quelli del proprio sistema e usare il carattere di continuazione
della shell.

Opzioni globali come `--runs-dir`, `--execution-mode`, `--max-workers`,
`--scientific-config` e `--dry-run` precedono il comando. `--dry-run`
controlla gli input e registra una richiesta `planned` senza eseguire
il motore. Usare un nome diverso per una successiva esecuzione reale.

```powershell
& $nipat dnp-call --bam ".\campione.bam" --reference ".\genome.fa" --panel ".\dnp.txt"
& $nipat snp-call --pileup ".\campione.pileup" --panel ".\snp.tsv"
& $nipat contamination --input ".\conteggi.txt" --panel ".\dnp.txt"
& $nipat cpi --input-dir ".\coppie" --pairs "A1:A1" --popfreq ".\frequenze.tsv"
& $nipat cpin --input-dir ".\terne" --trios "A:A:A" --popfreq ".\frequenze.tsv"
```

Sostituire i percorsi con quelli dei file effettivi. Ogni comando accetta
`--help`, ad esempio `& $nipat workflow analyze --help`. Per controllare
l'installazione usare `& $nipat doctor --runtime`; per gli esempi numerici
distribuiti usare `& $nipat self-test`. Su Windows è disponibile anche il
[collaudo installato dei cinque moduli](COLLAUDO_INSTALLAZIONE.md).

## Risultati e analisi in sequenza

In **W — Workflow automatici** si può partire dai BAM, da pileup SNP o
da tabelle disponibili. DNPcall e SNPcall producono conteggi per
Contamination, CPI e CPIN. Se si usano entrambi i caller, ogni ramo
ha i propri pannelli e frequenze. Contamination e gli indici di
paternità leggono le tabelle del caller scelto. La stima di contaminazione
non è un input ai modelli CPI o CPIN.

### Scelta del workflow automatico

| Tasto | Menu | Comando dopo `workflow` |
| --- | --- | --- |
| `1` | DNPcall → Contamination | `dnp-contamination` |
| `2` | DNPcall → CPI | `dnp-cpi` |
| `3` | DNPcall → Contamination e CPI | `dnp-contamination-cpi` |
| `4` | SNPcall su più campioni | `snp-batch` |
| `5` | Workflow completo | `analyze` |

I primi tre preset possono aggiungere SNPcall sugli stessi BAM tramite
`--snp-panel`; le analisi successive dei preset continuano a usare
i conteggi DNP. Per inviare i conteggi SNP alle analisi successive
usare il workflow completo. In un piano automatico un passaggio fallito
impedisce l'avvio di quelli rimanenti.

### Workflow completo

In **W → 5** scegliere i dati, assegnare un ID a ciascun campione e
indicare le analisi successive. `--pair ID CFDNA_MATERNO PADRE` definisce
una coppia CPI. `--trio ID MADRE PADRE FIGLIO` definisce una terna CPIN.
I ruoli fanno riferimento agli ID dei campioni dichiarati nel comando.

Questo esempio usa due rami: DNPcall alimenta CPI e SNPcall alimenta
Contamination. Gli input e le frequenze sono percorsi di esempio.

```powershell
& $nipat workflow analyze --caller both `
  --sample Plasma ".\plasma.bam" --sample Padre ".\padre.bam" `
  --reference ".\genome.fa" --dnp-panel ".\dnp.txt" --snp-panel ".\snp.tsv" `
  --dnp-analyses cpi --snp-analyses contamination `
  --pair Famiglia1 Plasma Padre --dnp-popfreq ".\frequenze-dnp.tsv"
```

`--analyses contamination,cpi,cpin` imposta le stesse analisi per i rami
selezionati. `--snp-analyses` e `--dnp-analyses` impostano invece il
singolo ramo. Una stringa vuota lascia solo il calling per quel ramo.
NIPAT può riutilizzare il pannello di calling per Contamination. Per
calcolare CPI o CPIN occorrono le frequenze del ramo e le coppie o
terne esplicite.

### Preset DNPcall e batch SNPcall

```powershell
& $nipat workflow dnp-contamination `
  --bam ".\a.bam" --bam ".\b.bam" --reference ".\genome.fa" --panel ".\dnp.txt"

& $nipat workflow dnp-cpi `
  --pair Coppia1 ".\plasma.bam" ".\padre.bam" --reference ".\genome.fa" `
  --panel ".\dnp.txt" --popfreq ".\frequenze-dnp.tsv"

& $nipat workflow snp-batch `
  --bam ".\a.bam" --bam ".\b.bam" --reference ".\genome.fa" --panel ".\snp.tsv"
```

`dnp-contamination` può usare un pannello distinto con
`--contamination-panel`. Nei preset con CPI ripetere `--pair` per altre
coppie. L'ID della coppia è un'etichetta distinta, lunga fino a 64
caratteri ASCII, che parte con una lettera e accetta lettere, cifre,
`-` e `_`. Un BAM può essere condiviso tra coppie nello stesso ruolo.
`--cpi-panel`, `--cutoff` e `--cutoff-map` selezionano i siti a partire
dai conteggi DNP; in loro assenza si usano i siti disponibili.

Per un batch SNP, `--bamlist` sostituisce i BAM elencati in CLI.
Per partire da pileup, ripetere `--pileup` senza BAM o FASTA. I batch
richiedono una modalità uniforme, un pannello condiviso e campioni
distinti. `workflow analyze` permette di combinare BAM e pileup con
ID espliciti quando si sceglie il ramo SNP.

### Utilizzo di tabelle già disponibili

In **W → 5 → Tabelle esistenti** selezionare le tabelle individuali,
assegnare gli ID e dichiarare le coppie o terne richieste. In CLI
usare `workflow analyze --caller tables` con
`--dnp-table ID PATH` e/o `--snp-table ID PATH`.

Per Contamination singola si possono scegliere le tabelle DNP in
`output/individual_outputs` del run sorgente. Per CPI o CPIN singoli
preparare copie con i prefissi richiesti e conservare la mappa verso
i campioni originali. La [guida ai risultati](ESECUZIONI.md) indica dove
trovare gli output e come verificare a quale campione appartengono.

## Problemi e segnalazioni

| Situazione | Cosa controllare |
| --- | --- |
| Setup Windows incompleto | In **Cartella NIPAT Desktop**, consultare `.runtime\installer\setup.log` e `state.json`, poi usare il collegamento per completare la preparazione. |
| File non accessibile | Controllare percorso, permessi e accesso del backend. Su Windows usare un disco locale fisso. |
| Riferimento FASTA rifiutato | Scegliere il file delle sequenze e verificare la presenza del `.fai` e dell'eventuale `.gzi`. |
| Nome di run già presente | Cambiare il nome o usare un nome automatico. |
| Analisi fallita o interrotta | Aprire `run-report.html` e `execution.log`; nei workflow verificare lo stato e il log del passaggio. |
| Tempi o memoria inattesi | Consultare la [guida alle prestazioni](PERFORMANCE.md) e i [limiti delle risorse](RISORSE.md). |
| Valori inattesi | Verificare associazioni dei campioni, input, modello e parametri effettivi. Registrare atteso e osservato nella [scheda di validazione](VALIDAZIONE.md). |

La cartella di ogni run contiene il riepilogo del calcolo, le tabelle, i
grafici e le evidenze tecniche. Per aprirla usare la schermata finale
o **6 — Ultima esecuzione** nella sessione corrente. Nomi e percorsi dei
campioni possono comparire nei metadati: verificare i file che si
intendono condividere.

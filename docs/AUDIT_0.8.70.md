# Audit tecnico per la 0.8.70

Questo documento è la base di lavoro per la 0.8.70. I rilievi riguardano la
stabile **0.8.60** (`d19e6bf58941a349d26d2f32ebb79bd24b6b7fcc`) e la pipeline
su **main** (`b9ebdc80917eba70d5597d7ac8e690a5a1f00d45`). Su tale revisione
`main` differisce dalla stabile nelle procedure CI, nella pubblicazione e nel
record di accettazione. I sorgenti client, motore e installer coincidono.

La revisione copre client CLI e menu, piani e contratti degli input, calcolo
R e controlli degli output, runtime, packaging e aggiornamenti per piattaforma,
CI, provenienza, pubblicazione e documentazione pubblica. Le righe dei file
citati si riferiscono alle revisioni sopra. **P1** indica una priorità prima
della prossima stabile. **P2** indica una correzione circoscritta o una
misura da confermare. **P3** indica manutenzione o rifinitura.

## Risultati scientifici

| ID | Evidenza e impatto | Intervento e criterio di accettazione |
| --- | --- | --- |
| **S1 · P1** | **SNPcall e DNPcall convertono identificatori testuali in numeri.** QNAME numerici distinti con zeri iniziali sono stati fusi in un read apparente, producendo `N_REF=1` e `GT=0/0` benché nessun read coprisse la finestra. In entrambi i caller la conversione del contig `01` in `1` può perdere loci. Riprodotto con pileup SNP e con BAM/FASTA DNP sintetici. Con tabelle sintetiche CPI e CPIN hanno unito contig diversi `01` e `1`, generando un log10 CPI positivo. Contamination ha incluso un sito di `1` in un pannello che selezionava solo `01`. [CPI R:67–69](../scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R#L67), [CPIN R:96–98](../scientific/vendor/NEWPAT/CPI_postnatal/Postnatal_CPI.R#L96), [SNPcall.R:130–136](../scientific/vendor/NEWPAT/SNPcall/SNPcall.R#L130), [DNPcall.R:101–112, 335–401](../scientific/vendor/DNPcall/DNPcall.R#L101), [dnp_blocks.R:13–22](../src/nipat_scientific/dnp_blocks.R#L13) | Dichiarare come testo contig, basi, qualità e QNAME in lettura. Verificare identificatori con zeri iniziali e ID alfanumerici con confronti su conteggi e join attesi. Applicare la stessa semantica della colonna `chr` nei cinque moduli. |
| **S2 · P1** | **REF discordante accettato da entrambi i caller.** In SNP un read di riferimento A con pannello G/A e in DNP un read di riferimento AA con pannello GG/AA hanno prodotto `N_ALT=1` e `GT=1/1`. Riprodotto con pileup SNP e BAM/FASTA DNP sintetici. [snp.py:66–84](../src/nipat_scientific/snp.py#L66), [SNPcall.R:130–160](../scientific/vendor/NEWPAT/SNPcall/SNPcall.R#L130), [outputs.py:287–311](../src/nipat_scientific/outputs.py#L287) | Verificare l'accordo delle basi nei loci acquisiti. Per BAM, controllare anche la coerenza fra coordinate del pannello, contig e riferimento. Test distinti per mismatch, locus fuori riferimento e sito valido a copertura zero. |
| **S3 · P1** | **CPI prenatale perde valori finiti nel prodotto.** Con 400 loci informativi sintetici e PI 10 per locus, il log10 CPI atteso è 400 e il riepilogo riporta `Inf`. Con 200 PI di .002 il log10 atteso è circa −539,794 e il riepilogo riporta `NA`. Entrambe le prove terminano con codice 0. [cfDNA_CPI_estimator.R:362–414, 444–454](../scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R#L362), [outputs.py:272–275](../src/nipat_scientific/outputs.py#L272) | Calcolare e aggregare il CPI in spazio logaritmico. Verificare compatibilità di soglie, statistiche e grafici sui casi a profondità ordinaria. Il riferimento numerico attuale conserva il comportamento del prodotto. Concordare il cambiamento numerico e aggiungere oracoli per overflow, underflow e zero siti. |
| **S4 · P1** | **Conteggi e colonne derivate incoerenti possono cambiare il risultato.** In Contamination, a conteggi 99 REF, 1 ALT e 0 Other invariati, fornire `ratio_REF_ALT=.99` oppure `.01` produce rispettivamente .01 o .99. `NA` rimuove il locus. Nel CPI prenatale un `total_count` incoerente altera il filtro delle altre basi. Entrambi riprodotti con tabelle sintetiche. Il preflight segnala alcune incoerenze come avvisi. CPIN rifiuta già il totale incoerente nel calcolo R, dopo la preparazione. [files.py:139–165](../src/nipat_scientific/files.py#L139), [Contamination R:168–226](../scientific/vendor/NEWPAT/contamination/detect_contamination.R#L168), [CPI R:243–249, 593–600](../scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R#L243) | Concordare l'autorità dei conteggi e la gestione di campi derivati, valori mancanti e copertura zero. Rifiutare o ricalcolare i campi incompatibili con regola documentata. Verificare tabelle importate e generate, per SNP e DNP, incluse eventuali deroghe esplicite. |
| **S5 · P2** | **Le letture sovrapposte possono far fallire SNPcall.** Con BAQ disabilitato e un BAM sintetico paired-end, `count_overlaps=true` trasmette `-x` a samtools. I due mate hanno lo stesso QNAME e il calcolo delle statistiche indel trova più di tre elementi nel gruppo. Il caso di controllo con gestione sovrapposizioni standard completa. [snp.py](../src/nipat_scientific/snp.py), [SNPcall.R:263–289](../scientific/vendor/NEWPAT/SNPcall/SNPcall.R#L263) | Definire come trattare i mate nella finestra. Finché la semantica non è definita, rifiutare la combinazione incompatibile con un messaggio utilizzabile. Provare mate sovrapposti e separati. |
| **S6 · P2** | **DNPcall interrompe un run senza copertura.** Un BAM ordinato valido con soli header e pannello a un locus produce pileup vuoto con samtools riuscito. L'indicizzatore DNP solleva `DNP pileup contains no rows`. [dnp_blocks.R:69](../src/nipat_scientific/dnp_blocks.R#L69), [DNPcall.R:199–201](../scientific/vendor/DNPcall/DNPcall.R#L199) | Distinguere regione valida senza copertura da riferimento o pannello incompatibile. Definire lo stato e le tabelle attese per zero copertura. Verificare anche il batch con campioni coperti e scoperti. |
| **S7 · P2** | **Parte degli output resta fuori dal contratto.** Il validatore CPI ha accettato una copia di un output valido privata di `curves/`. Il validatore DNP ha accettato una tabella con CC/TT al posto di AA/GG allo stesso locus. Prove sintetiche di alterazione controllata degli output. [outputs.py:204–253, 350–376](../src/nipat_scientific/outputs.py#L204) | Aggiungere validatori mirati alle curve e al riepilogo DNP. Verificare che il run respinga artefatti mancanti, alterazioni di alleli e riepiloghi incoerenti con i risultati individuali. |

## Client e installatori

| ID | Evidenza e impatto | Intervento e criterio di accettazione |
| --- | --- | --- |
| **D1 · P1** | **Il numero di versione è fissato in più punti.** Il builder usa `pyproject.toml`; il lettore del manifest Windows e il collaudo installato esigono letteralmente 0.8.60. Con una fixture coerente e il vero lettore PowerShell, il manifest 0.8.70 viene rifiutato. [bootstrap-common.ps1:5–11](../installer/windows/bootstrap-common.ps1#L5), [test-installed.ps1:8–10](../scripts/windows/test-installed.ps1#L8) | Derivare l'identità attesa dalla build e testare sul payload estratto. Un test di incremento versione deve coprire setup, launcher e collaudo usando i rispettivi metadata generati. |
| **D2 · P1** | **Aggiornamento Windows con riavvio richiesto.** L'handoff passa `/NORESTART` e attende il codice 3010. Inno Setup per impostazione predefinita restituisce 0 se il setup è riuscito e richiede riavvio. NIPAT usa `NeedRestart` ma omette `/RESTARTEXITCODE=3010`. Il ramo di successo controlla lo stato `ready` e può rifiutare lo stato legittimo `awaiting_reboot`. Evidenza da codice e [contratto Inno Setup](https://jrsoftware.org/ishelp/topic_setupcmdline.htm). [update-handoff.ps1:108–130](../installer/windows/update-handoff.ps1#L108), [NIPAT.iss:849–869](../installer/windows/NIPAT.iss#L849) | Passare il codice di riavvio esplicito e usare il setup compilato per verificare l'handoff con bootstrap che richiede riavvio. Il test corrente con stub restituisce direttamente 3010. |
| **D3 · P1** | **Rollback DEB lascia il launcher in manutenzione.** Una prova dpkg isolata con gli script del pacchetto adattati a una directory temporanea ha lasciato il marker `update-in-progress` dopo il ritorno a `install ok installed` della versione precedente. Gli handler di rollback non tolgono il marker e il launcher rifiuta l'avvio. [build_linux_installer.py:118, 193–196](../scripts/build_linux_installer.py#L193), [Debian Policy, script di manutenzione](https://www.debian.org/doc/debian-policy/ch-maintainerscripts.html) | Gestire le azioni di rollback di dpkg dopo il ripristino effettivo e conservare il blocco per uno stato parziale. Provare aggiornamento interrotto, rollback e successivo avvio della versione precedente. |
| **D4 · P2** | **I controlli di preparazione possono attendere senza limite.** In Windows i log stdout/stderr diventano disponibili dopo l'uscita del processo atteso. L'attivazione Linux ha log durante l'esecuzione ma un'attesa analoga. Rilievo statico. [bootstrap-common.ps1:149–180](../installer/windows/bootstrap-common.ps1#L149), [installer/linux/launch.py:230–252](../installer/linux/launch.py#L230) | Scrivere i log durante l'esecuzione, definire un limite distinto per fase e lasciare uno stato riprendibile. Provare processo bloccato e uscita tardiva senza interferire con altre sessioni. |
| **D5 · P2** | **Aggiornamento Ubuntu può scadere durante la lettura del DEB.** L'handoff valida più volte l'hash dopo il download. Il processo figlio rilegge il pacchetto prima di segnalare disponibilità, mentre il padre attende fino a 15 s. Per i 608 MB della 0.8.60, la sola rilettura in 15 s richiede circa 41 MB/s. È una soglia teorica. [update_handoff.py:158–172](../src/nipat/update_handoff.py#L158), [linux_update.py:118–128, 165–180, 210–273](../src/nipat/linux_update.py#L165) | Distinguere l'avvio del figlio dalla verifica del pacchetto e riusare controlli eseguiti sullo stesso file immutato. Mantenere la verifica prima di APT. Provare disco lento, timeout reale e digest modificato. |
| **D6 · P2** | **Preferenze sovrascritte tra due finestre.** Riprodotto con due oggetti realmente caricati. La finestra A salva la modalità seriale. La B salva il canale di aggiornamento dal proprio stato precedente e perde la scelta della A. [wizard_settings.py:144–154](../src/nipat/wizard_settings.py#L144), [preferences.py:302–320](../src/nipat/preferences.py#L302) | Aggiornare i campi interessati sotto lock o verificare la revisione prima del salvataggio. Provare due istanze, cambi distinti e conflitto sullo stesso campo. |
| **D7 · P2** | **Il wizard può chiedere tabelle che il piano non usa.** Riprodotta la richiesta di una tabella DNP obbligatoria con sorgente tabelle, rami separati, ramo DNP senza analisi e Contamination soltanto su SNP. Selezioni familiari obsolete possono restare visibili dopo un cambio di sorgente. In CLI alcune risorse fornite per un ramo inattivo vengono ignorate. [analysis_forms.py:76–102, 192–257](../src/nipat/analysis_forms.py), [analysis_plan.py:133–154, 184–210](../src/nipat/execution/analysis_plan.py#L133) | Usare lo stesso insieme di rami, campioni e risorse attivi nel modulo, nel riepilogo e nel compilatore del piano. Segnalare le opzioni esplicite inutilizzate. Provare cambio ramo e importazione asimmetrica. |
| **D8 · P2** | **Lo stesso run può apparire riuscito o ignoto.** Un record valido di 2.097.272 byte viene letto da recupero e HTML. La lista risultati lo ignora per il limite di 2 MiB. Gli altri lettori hanno soglie di 16 e 32 MiB. [results.py:16, 103–123, 227–240](../src/nipat/results.py#L103), [recovery.py:36–49](../src/nipat/execution/recovery.py#L36), [run_report.py:16, 36–44](../src/nipat/run_report.py#L36) | Usare una lettura limitata coerente o separare un indice compatto dalle evidenze dettagliate. Esprimere chiaramente record fuori soglia o danneggiati. Testare i limiti e le differenze di presentazione. |
| **D10 · P2** | **Il codice di uscita può mascherare un esito parziale.** La CLI restituisce 0 anche quando un riavvio richiesto da `resources configure --apply --yes --restart` richiede verifica successiva. Riprodotto con un gestore simulato nella CLI reale. `runs stop` restituisce 0 anche per stato `stopped` con rimozione non completata. [cli.py:349–365, 410–414](../src/nipat/cli.py#L349), [resources.py:530–588](../src/nipat/resources.py#L530) | Definire quali esiti soddisfano l’operazione richiesta e documentare i codici per automazione. Testare un riavvio parziale, un arresto senza rimozione e gli esiti di successo. |
| **D9 · P3** | **Help incorporato fuori sincronia.** Il menu presenta tutta la serie 0.8 come sperimentale e descrive i workflow con i soli preset DNP. La stabile dispone anche di batch SNP e piani con tutti i moduli. [wizard.py:99–135](../src/nipat/wizard.py#L99) | Derivare il testo dell'aggiornamento dal canale e aggiornare la guida integrata. Verificare italiano e inglese e riprendere le prove console dell'[issue #9](https://github.com/GregorioDalia/nipat-desktop/issues/9). |

## CI e pubblicazione

| ID | Evidenza e impatto | Intervento e criterio di accettazione |
| --- | --- | --- |
| **R1 · P1** | **La CI di main osservata è fallita nella prova di OOM intenzionale.** Il confronto DNP con e senza diagnostica era riuscito. Il container della prova successiva è uscito 137 e Docker ha restituito `OOMKilled=false`. Il controllo resta non confermato, i controlli scientifici successivi nello stesso job non sono partiti e il publisher ha saltato l'esecuzione. Lo stesso albero Git era verde in PR. [CI main](https://github.com/GregorioDalia/nipat-desktop/actions/runs/43504273747), [CI PR](https://github.com/GregorioDalia/nipat-desktop/actions/runs/43500774899), [verify_performance.py:152–185](../scripts/verify_performance.py#L152) | Separare parità numerica, osservabilità e capacità di diagnosticare OOM sul runner. Raccogliere evidenza del cgroup e ripetere con ambiente qualificato. Un 137 da solo deve restare non confermato. Verificare che le prove scientifiche producano comunque un esito leggibile quando una diagnostica d'infrastruttura è indisponibile. |
| **R2 · P1** | **Il publisher automatico deduce il canale dal nome.** Una versione numerica viene pubblicata Stable/Latest anche se il workflow manuale consente Testing. Il builder ufficiale richiede una versione numerica 0.8.x, perciò il ramo automatico per suffissi prerelease non parte dalla build ufficiale corrente. Il rischio è ricavato dal codice. [automatic_release.py:39–71](../.github/scripts/automatic_release.py#L39), [verify_release_source.py:19–26](../.github/scripts/verify_release_source.py#L19) | Registrare canale e decisione di pubblicare nel record di accettazione. Rendere coerenti input del builder e publisher. Provare una candidata numerica Testing, la pubblicazione Stable e un record privo di autorizzazione. |
| **R3 · P1** | **Un run di pubblicazione in coda può essere sostituito.** Il gruppo condiviso viene acquisito prima di stabilire se la modifica riguarda l'accettazione. GitHub cancella per default un tentativo già in attesa quando ne arriva un altro nello stesso gruppo. Anche una CI su main senza accettazione può quindi sostituire un tentativo utile. [Workflow automatico:12–27](../.github/workflows/publish-accepted-release.yml#L12), [regole GitHub sulla coda](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency) | Selezionare i record in un job a sola lettura, serializzare soltanto i job che pubblicano e usare una coda che preservi i candidati. Ricontrollare l'accettazione corrente prima della scrittura. Provare due accettazioni e un evento senza accettazione durante una pubblicazione. |
| **R4 · P2** | **Il rilancio automatico verifica solo parte dell'identità pubblicata.** La scorciatoia per una release esistente confronta tag nominale, `target_commitish` e canale. Il commit effettivo del tag e i digest non sono ricontrollati. Il publisher manuale possiede già i controlli sugli artefatti e una ricerca per le bozze. [automatic_release.py:49–71](../.github/scripts/automatic_release.py#L49), [publish_windows_release.py:567–642](../.github/scripts/publish_windows_release.py#L567) | Condividere il lookup tra i due ingressi e verificare commit e asset prima di dichiarare equivalenza. Provare rilancio su bozza e su release completa o incoerente. |
| **R5 · P2** | **Alcune modifiche al client sono classificate come documentazione.** Il selettore lascia i controlli veloci attivi, ma modifiche al driver di accettazione, al launcher PowerShell o ai valori iniziali possono mancare dei livelli di integrazione pertinenti. Il test unitario dell'integrità del bundle esiste. [ci_changes.py:25–55](../.github/scripts/ci_changes.py#L25), [test_installed_suite.py:24–37](../tests/test_installed_suite.py#L24) | Rendere esplicita l'associazione ai livelli richiesti, con fixture per launcher, harness e configurazione. Verificare il payload con il launcher distribuito. |

La [PR #41](https://github.com/GregorioDalia/nipat-desktop/pull/41) è integrata.
L'attivazione automatica è stata osservata con skip dopo una CI fallita. Una
pubblicazione automatica riuscita da record di accettazione resta da
qualificare. La build già pubblicata della 0.8.60 ha un record proprio e ha
usato le evidenze scientifiche della candidata. Le PR
[#11](https://github.com/GregorioDalia/nipat-desktop/pull/11) e
[#26](https://github.com/GregorioDalia/nipat-desktop/pull/26) restano revisioni
separate delle Actions e degli strumenti di qualità.

## Prestazioni e misure

### Benchmark sul client Windows 0.8.60

Il profilo esteso sul pacchetto stabile ha completato **51 run su 51 in
18m 08s**, con 3 casi sui file della Sapienza e 48 sintetici. I casi reali
hanno usato il parallelismo automatico, blocchi da 32 MiB e 64 loci e
diagnostica attiva. L'alimentazione a corrente è stata rilevata all'inizio
e alla fine di ogni run. WSL riportava 32 CPU logiche e 15.858 MiB di memoria.

| Caso sui file reali | Tempo del run (s) | Tempo dal lancio della CLI (s) | Picco del container (MiB) |
| --- | ---: | ---: | ---: |
| DNPcall → Contamination | 235,01 | 236,61 | 3.458 |
| DNPcall | 232,65 | 234,16 | 3.315 |
| Contamination dalle tabelle DNP | 5,58 | 7,03 | 159 |

Nel workflow completo DNPcall ha impiegato **227,23 s**, pari al **97%**
del tempo del run. Il calcolo dei blocchi (107,92 s), la produzione del
pileup (78,71 s) e l'indice (29,78 s) coprono insieme il 92% del totale.
Blocchi e indice valgono circa il 59% e sono il primo punto da misurare.
Le tre fasi del run DNPcall autonomo hanno durate analoghe. Nel run breve
di Contamination il processo R dura 0,77 s a fronte di 7,03 s dal lancio.
Per individuare il costo fisso occorre distinguere launcher, preparazione
del runtime, controlli e scrittura degli output.

Nelle ultime tre prove archiviate della 0.8.30, il workflow DNPcall →
Contamination aveva mediana 210,88 s. Il nuovo run dura **24,13 s in più
(11,4%)**. Le sei misure storiche su due sessioni vanno da 203,39 a 228,96 s.
I rapporti coincidono per metadati dei sette input, digest dei quattro file
piccoli, modalità, dimensione dei blocchi e risorse WSL rilevate. Per BAM e
FASTA l'identità è basata sui metadati. Una sola ripetizione della 0.8.60 in
una sessione separata lascia aperta l'attribuzione dello scarto alla versione.

| Modulo autonomo su input sintetici | Casi | Tempo del run (s) |
| --- | ---: | ---: |
| DNPcall | 2 | 9,79–10,32 |
| SNPcall | 2 | 6,43–8,11 |
| Contamination | 10 | 4,71–5,90 |
| CPI prenatale | 16 | 6,41–11,26 |
| CPIN postnatale | 8 | 7,03–12,89 |

Gli intervalli aggregano input e opzioni diverse. Nei 10 casi sintetici
combinati, il workflow sui cinque moduli ha impiegato 46,20 s in seriale,
36,74 s in automatico e 40,10 s con un massimo di due processi. I picchi
del container sono rispettivamente 185, 553 e 375 MiB. È stata eseguita una
prova per modalità. Tutti i 9 confronti di parità delle tabelle nel
benchmark riguardano casi sintetici e hanno avuto esito positivo. Gli esiti
dei casi reali attestano il completamento dei run. La parità su quei file
resta da misurare con le tabelle di riferimento della 0.8.60.

### Interventi da misurare

| Area | Evidenza disponibile | Prova o modifica da valutare |
| --- | --- | --- |
| **DNP sui due BAM reali** | Il calcolo dei blocchi e l'indice totalizzano 137,70 s nel workflow della 0.8.60. Il pileup richiede altri 78,71 s. | Misurare tokenizer e indice seriali, scansioni e GC per task e merge progressivi del riepilogo. Verificare il guadagno sui due BAM e confrontare le tabelle prima di intervenire sul pileup. [dnp_blocks.R:25–69, 247–263](../src/nipat_scientific/dnp_blocks.R#L25), [DNPcall.R:794–837](../scientific/vendor/DNPcall/DNPcall.R#L794) |
| **CPI ad alta profondità** | Lo script alloca sequenze e vettori per ogni soglia di read fino al massimo osservato. Conserva le curve delle coppie e dei cutoff prima dell'esportazione. Analisi del codice. | Valutare intervalli compatti e statistiche ponderate con equivalenza sul riferimento denso. Misurare picco memoria e durata con profondità crescente. [cfDNA_CPI_estimator.R:382–454, 728–744](../scientific/vendor/NEWPAT/CPI_from_cffDNA/cfDNA_CPI_estimator.R#L382) |
| **Analisi brevi e avvio a caldo** | In 48 casi sintetici archiviati della 0.8.50 riparata, mediana run 8,563 s. La mediana della preparazione prima del comando scientifico è 3,402 s e la mediana delle quote per caso è circa 40%. I due probe dell'immagine sono circa 1 s in mediana. Su macOS il launcher valida e prepara Lima anche prima di comandi informativi, con ulteriore verifica nel runner. | Misurare avvio freddo/caldo per piattaforma. Accorpare probe, memorizzare la descrizione per immagine immutabile nella stessa sessione e mantenere la verifica di identità prima del calcolo. [runner.py:384–420, 505–550, 617–627](../src/nipat/execution/runner.py#L384), [macOS launch.py:103–127](../installer/macos/launch.py#L103) |
| **Preparazione Windows** | Sul ripristino dopo un errore successivo all'importazione, lo script può ricalcolare l'hash e ricaricare l'archivio scientifico da circa 602 MB. Percorso verificato nel codice, risparmio da misurare. | Conservare la ricevuta di importazione legata a digest, distro e immagine risolta, poi ispezionare l'immagine a ogni ripresa e ricaricare quando serve. [bootstrap-common.ps1:278–296](../installer/windows/bootstrap-common.ps1#L278) |
| **Recupero run** | Una prova con 15 record storici già rimossi ha contato 15 ispezioni Docker e 15 risultati ad ogni scansione. Il menu richiama la scansione al rientro. | Mostrare prima i casi attivi o incerti e conservare l'ispezione puntuale nello storico. Raggruppare le interrogazioni. Testare anche daemon indisponibile. [recovery.py:174–187](../src/nipat/execution/recovery.py#L174), [recovery_ui.py:44](../src/nipat/recovery_ui.py#L44) |
| **Input grandi e batch** | `--input-hashes full` effettua tre letture integrali nel percorso provato. BAM e FASTA del benchmark sommano 8,49 GB, quindi circa 25,46 GB di letture di hash. Con mille input il controllo duplicati ha chiamato `samefile` 499.500 volte. I pileup SNP importati possono essere riletti a più confini prima del calcolo. | Conservare la verifica dei file. Misurare e ridurre i passaggi ridondanti, usare una sola identità file per rilevare duplicati e mantenere il riconoscimento degli hardlink. Contare le letture del pileup prima di modificare il confine di validazione. [tracking.py:41–75](../src/nipat/execution/tracking.py#L41), [workflows.py:102–104](../src/nipat/execution/workflows.py#L102), [files.py:276–298](../src/nipat_scientific/files.py#L276) |
| **Batch SNP** | Il coordinatore ricommette l’intero stato a ogni poll di 50 ms. Con 200 worker simulati, budget di due e completamenti ritardati, 2.103 scritture invocate, di cui 1.902 identiche alla precedente. Circa 135 MB serializzati nella prova; nessuna stima di risparmio sul disco dei dispositivi reali. | Persistenza durevole sulle transizioni e sugli errori, senza ricommettere lo stato immutato. Misurare su Windows/WSL con batch numerosi. [snp_parallel.py:147–197](../src/nipat_scientific/snp_parallel.py#L147), [executor.py:60–85](../src/nipat_scientific/executor.py#L60) |
| **Pipeline** | Build accettata 0.8.60 in 25m44s, pubblicazione in 5m54s. Nella verifica congiunta della build, 194 s per i quattro download e 65 s per i quattro upload duplicati poi rimossi dalla #41. La coda macOS ARM ha aggiunto circa 10 minuti rispetto all'avvio del job Intel. | Misurare la prima build con i nuovi artifact. Valutare download concorrenti mantenendo la verifica dei byte. Far partire il job scientifico prima, o riusare sul merge l'evidenza della PR legata a identico albero e immagine. Tenere separati coda, durata dei job e percorso critico. [Build](https://github.com/GregorioDalia/nipat-desktop/actions/runs/43484430540), [Pubblicazione](https://github.com/GregorioDalia/nipat-desktop/actions/runs/43490395205) |

## Documentazione pubblica

Il README presenta prodotto, pacchetti, input, primo run e risultati. L'indice
delle [guide correnti](README.md) raggruppa i contenuti per operazione.
I documenti su installazione, uso, risultati, prestazioni, validazione e
contributi sono stati ricontrollati con il codice e i pacchetti pubblicati.
Le note di rilascio, gli audit precedenti e le misure datate rimangono
rintracciabili dall'[archivio](archive/README.md). Licenze, attribuzioni e record
di accettazione documentano la provenienza. Gli indici nuovi sono
destinati a GitHub. Prima di includerli nei pacchetti futuri, verificare
l'elenco esplicito in [distribution-files.txt](../distribution-files.txt).

La ricognizione GitHub comprende pacchetti, note di rilascio pubblicate,
wiki, issue e pull request aperte e configurazione dei controlli. L'URL
della wiki pubblica rimanda alla home. L'issue #9 conserva le verifiche
manuali della console. La documentazione corrente ha un solo punto
d'ingresso nel repository.

## Ordine di lavoro proposto

1. Riprodurre e correggere S1–S4, mantenendo casi numerici indipendenti e
   concordando le correzioni che cambiano risultati.
2. Rendere aggiornabile il pacchetto con D1–D3. Provare rollback, riavvio
   richiesto e collaudo installato su una candidata con versione nuova.
3. Ripristinare l'esito completo di CI e qualificare la pubblicazione con
   R1–R3. Costruire dal commit di `main` integrato o conservare l'esatto
   commit costruito se il branch viene integrato successivamente.
4. Misurare prima calcolo dei blocchi e indice DNP, poi il pileup. Ripetere
   il workflow reale sulla stabile e sulla candidata nelle stesse condizioni,
   registrando tempi per fase, durata totale, memoria e tabelle di riferimento.
   Profilare l'avvio per i workflow brevi con misure dedicate.
5. Chiudere i rilievi P2 che incidono sugli scenari scelti per la release e
   aggiornare la guida incorporata con D9.

## Verifiche eseguite e limiti

- Suite Python locale su main: **1.272 passati, 32 saltati** per prerequisiti
  nativi, piattaforme e fixture di permessi. Controlli CI e pubblicazione:
  **328 passati**. Ruff e sintassi dell'helper shell verificati.
- Suite mirate su client e installer: **597** e **236 passati**. Le suite
  si sovrappongono ai test locali e i risultati non si sommano.
- Suite scientifiche mirate: **235 passati** con R locale 4.5.0 e samtools 1.21.
  Le riproduzioni sintetiche sono state eseguite contro il codice invariato.
  Il runtime scientifico distribuito va qualificato anche con le nuove
  regressioni. Prova mirata di rollback dpkg, lettura manifest Windows con
  PowerShell 7 e verifiche sui record precedenti.
- Il collaudo sintetico 0.8.60 sul PC Windows è stato riportato come 70 esiti
  positivi. Il benchmark successivo misura il client già installato. Setup
  nativo, aggiornamento con riavvio e app macOS su dispositivi fisici restano
  da riqualificare. Per ogni correzione scientifica occorrono i casi di
  regressione specifici e un riferimento numerico indipendente.

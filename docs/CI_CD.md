# Integrazione continua e distribuzione

NIPAT verifica separatamente il client, il motore scientifico, gli installatori
e il funzionamento sui dispositivi reali. La versione 0.8.50 distribuisce
Windows 10/11 x64, Ubuntu 24.04 x86_64 e macOS 14 o successivo Intel/Apple Silicon.
Tutti i pacchetti incorporano lo stesso archivio scientifico Linux AMD64.

## Workflow GitHub Actions

| Workflow | Attivazione | Risultato |
| --- | --- | --- |
| [CI](../.github/workflows/ci.yml) | Pull request, push su `main`, avvio manuale. | Controlli applicabili ai file modificati; per i soli record di accettazione, verifica Linux delle evidenze della build. |
| [Installers (review build)](../.github/workflows/windows-installer.yml) | Avvio manuale su un commit revisionato. | Quattro installatori con manifest, checksum e rapporti; nessuna pubblicazione automatica. |
| [Prepare or publish verified release](../.github/workflows/publish-windows-release.yml) | Avvio manuale su `main`. | Bozza e pubblicazione dei pacchetti accettati, in fasi separate oppure in un'unica esecuzione esplicita, senza ricompilarli. |
| [Publish accepted release](../.github/workflows/publish-accepted-release.yml) | CI riuscita dopo un push su `main` contenente soltanto record di accettazione. | Verifica e pubblicazione automatica degli installer accettati. |
| [Published runtime security report](../.github/workflows/security-monitoring.yml) | Pianificazione e avvio manuale. | Inventari e segnalazioni sulle immagini pubblicate, da esaminare separatamente. |

La CI seleziona i controlli in base ai file modificati. Contratti, runtime,
installer e pipeline attivano i livelli corrispondenti; un confronto Git non
disponibile non viene interpretato come una modifica della sola documentazione.
Il controllo aggregato `required` verifica l'esito dei job richiesti.
I branch di sviluppo ricevono la CI tramite la pull request, evitando la seconda
esecuzione sul push dello stesso commit. Su un branch senza PR si può avviare
la CI manualmente.
Gli installatori completi vengono costruiti su richiesta, non a ogni push.
Una modifica al solo workflow di pubblicazione richiede i controlli di packaging
e i controlli rapidi obbligatori; non riesegue il runtime scientifico. Le modifiche
al selettore, alla CI, alla build o a workflow non riconosciuti conservano tutti
i livelli. Una modifica scientifica concomitante riattiva sempre quel livello.

Una modifica limitata a `.github/release-acceptance/vVERSIONE.json` esegue
`acceptance` su Linux e il controllo `required`. Verifica il commit, il successo
della build e di tutti i job dei pacchetti, gli hash dei quattro installer,
il manifest, la baseline e i rapporti scientifici usando il bundle di evidenze
vincolato alla build. Il download è limitato alle evidenze testuali. Record
mancanti, alterati o riferiti a build diverse fanno fallire il controllo.

## Copertura e limiti

| Livello | Verifiche | Limite dell'evidenza |
| --- | --- | --- |
| Python e contratti | CLI/menu, input, workflow, registri, risultati, aggiornamenti e annullamento sui sistemi previsti dalla matrice. | Non sostituisce l'installazione sul computer del ricercatore. |
| Risorse | Configurazione WSL/Lima, anteprima, backup, conferme, lock fra processi, conservazione delle impostazioni estranee. | Le simulazioni WSL non dimostrano un riavvio reale di Windows 10. |
| Diagnostica | Identità del container, raccolta dello stato prima della pulizia, OOM confermato o causa non accertata. | Il solo codice 137 non dimostra memoria esaurita. |
| Prestazioni | Diagnostica facoltativa, campioni e fasi, invarianza delle tabelle DNPcall, conservazione delle evidenze dopo un OOM controllato. | I test sintetici verificano la raccolta; i benchmark su BAM grandi misurano le prestazioni, senza soglie sui runner condivisi. |
| Presentazione | Mappa dei campioni, nomi originali, HTML/TSV, esportazione scientifica e testo nei PDF. | La leggibilità su ogni visualizzatore rimane una prova d'uso. |
| Windows | Prerequisiti, bootstrap, layout, riparazione/rimozione, compilazione e verifica del Python incorporato. | Il payload preparato non equivale a installazione Inno Setup e avvio WSL su un desktop pulito. |
| Ubuntu | Installazione APT, dipendenze, analisi da utente non root, reinstallazione/rimozione e aggiornamento dalla 0.7.2. | Il runner configurato non rappresenta ogni Ubuntu Desktop. |
| macOS | Pacchetti ARM64/Intel, launcher e componenti nativi, trasporto e configurazione Lima. | La costruzione del `.pkg` non prova l'avvio della VM o l'accettazione Gatekeeper. |
| Motore scientifico | Cinque analisi, piani composti, BAM sintetici, confronti numerici, input errati e originali invariati. | Non costituisce validazione di dominio su tutti i campioni reali. |
| Documentazione | File, immagini, link relativi e sezioni Markdown. | Non verifica disponibilità dei siti esterni o contenuto scientifico della prosa. |

Ogni difetto riproducibile deve essere coperto dal test del livello pertinente.
Il numero di test non sostituisce l'esame dei casi coperti. Gli esiti distinguono
prove eseguite, fallite, saltate e non eseguite; un job facoltativo saltato non
è una prova superata.

## Regressioni scientifiche

La 0.8.50 verifica i due caller con `scripts/verify_r_equivalence.py`:
17 casi contro NIPAT 0.8.5 per DNP e SNPcall 2.0 per SNP, con rapporto
`r-equivalence.json`. I riferimenti rimangono congelati. CPI e Contamination
adottano il modello NEWPAT aggiornato; CPIN usa il nuovo modello postnatale.
Non si richiede a questi tre moduli l'equivalenza con le formule precedenti.

`scripts/verify_five_modules.py --image IMMAGINE --full` confronta i tre moduli
con NEWPAT al commit `9c2a8be60afcb944153710da6a61cd0559e2b4cf` e oracoli
analitici indipendenti. Conserva `five-module-qualification.json`: 86 esecuzioni,
16 confronti upstream e 54 prove batch con 2/3/5 famiglie o campioni, marcatori
SNP/DNP, modalità seriale/automatica/limite 2. Registra sorgenti e fixture,
input invariati, parametri e costanti effettivi, output, completamento e budget
dei worker. La tolleranza numerica dei confronti upstream è `1e-11` assoluta
e relativa; le identità di campioni, coppie e trii devono coincidere.

Entrambi i gate sono obbligatori nella CI scientifica. Prima dell'esportazione,
la build richiede i loro rapporti: li esegue oppure riusa una qualificazione CI
verificata dello stesso albero Git e della stessa immagine, come descritto sotto.
Il publisher schema 7 lega i due rapporti alla
stessa immagine immutabile e ai byte Git della candidata. I riferimenti di test
non sono inclusi nell'applicazione. I test Python sono raccolti con pytest,
comprese le classi unittest. Le regressioni native sui campioni vuoti o privi
di copertura e sui parametri vengono eseguite anche nell'immagine finale:
una dipendenza R mancante o un test saltato impedisce il completamento.

Per DNP/SNP le tabelle esportate e i valori R non arrotondati devono
coincidere con il rispettivo riferimento scientifico. Dalla 0.8.30, i grafici aggiornati sono
verificati per contenuto, dimensioni e classi degli istogrammi; i rendering
devono essere identici tra le modalità seriale e parallele della candidata.
Le versioni precedenti conservano il confronto esatto con i PDF della baseline.

Il container contiene R, samtools, gli script scientifici, gli adattatori e
l'orchestrazione. Il client verifica i contratti e non monta gli script R
dalla cartella dell'applicazione. I workflow composti vengono confrontati
con le analisi singole equivalenti, usando risultati attesi. Il gate
dell'immagine finale esercita anche un piano di dieci passi su tre BAM:
DNP, SNP e le tre analisi a valle per entrambi i caller, in seriale e con
limite 2, verificando tabelle, immagine usata, impostazioni e input invariati.

La verifica della presentazione confronta le tabelle numeriche con e senza
etichette leggibili e controlla il testo estratto dai PDF. Gli output canonici
rimangono disponibili; gli export leggibili non sostituiscono gli input delle
fasi successive. Il catalogo scientifico identifica tramite hash gli script
R e i componenti di preparazione effettivamente distribuiti.

Su Apple Silicon Lima usa un guest ARM64 e Rosetta per il container AMD64.
Il successo del calcolo su Ubuntu AMD64 non sostituisce una prova di questo
trasporto su Mac. I risultati attesi rimangono gli stessi.

## Build degli installatori

Avviare **Installers (review build)** sul commit da distribuire, su `main`,
`release/VERSIONE` o `release/VERSIONE-...`, con la stessa versione dichiarata
dai sorgenti, ad esempio `release/0.8.50`. Il controllo
`installer-required` verifica sorgenti, manifest, checksum e archivio scientifico
comune ai quattro pacchetti. La build produce:

| Artefatto Actions | Pacchetto |
| --- | --- |
| `nipat-windows-setup` | `NIPAT-Setup.exe`. |
| `nipat-linux-setup` | `nipat-desktop_0.8.50_amd64.deb`. |
| `nipat-macos-setup-arm64` | `NIPAT-0.8.50-macos-arm64.pkg`. |
| `nipat-macos-setup-x86_64` | `NIPAT-0.8.50-macos-x86_64.pkg`. |
| `nipat-installer-set-evidence` | Identità e verifica congiunta dei pacchetti. |

Ogni job conserva il proprio pacchetto nell'artefatto originale. Il job finale
li scarica per la verifica congiunta e pubblica il riepilogo degli hash, evitando
quattro ulteriori caricamenti delle stesse copie binarie. Gli artefatti Actions
sono archivi di revisione con pacchetti e rapporti; la release offre i file
EXE/DEB/PKG da installare direttamente.

I controlli Windows e il runtime Linux partono in parallelo dopo la verifica
della sorgente. Il compilatore Windows attende entrambi; il controllo finale
richiede il successo di tutti e quattro gli installer. Sul profilo temporale
riportato sotto, la sovrapposizione eliminerebbe circa 3 min 34 s dal percorso
critico, da confermare con una build completa. Se Windows fallisce, il ramo
Linux può consumare ulteriore tempo di esecuzione, ma la pubblicazione resta bloccata.

La release espone direttamente il file da installare per ciascuna piattaforma.
I pacchetti **Source code** non contengono l'ambiente pronto all'uso. Gli archivi
del runtime e i rapporti servono a verifica e recupero, non richiedono operazioni
manuali durante l'installazione ordinaria.

## Riuso delle evidenze scientifiche

Dopo il successo dei sette controlli scientifici, la CI produce l'artefatto
`nipat-scientific-qualification-N-TREE`, dove `N` identifica il tentativo del run
e `TREE` l'albero Git completo. Il nome evita di scaricare prove di sorgenti
diverse, ma non sostituisce la verifica dei contenuti.
Contiene un descrittore e un archivio limitato alle evidenze testuali sintetiche;
non trasferisce un'altra copia dell'immagine Docker. Le diagnostiche dei run
falliti vengono conservate separatamente e non sono riutilizzabili.

La build costruisce l'immagine usando la cache e cerca una CI già completata
con successo nello stesso repository. Il riuso richiede tutte queste condizioni:

- albero Git completo identico, file tracciati invariati e nessun file non tracciato,
  includendo
  sorgenti, verificatori, fixture, workflow e definizioni delle dipendenze;
- ID Docker completo, sistema Linux e architettura AMD64 identici;
- provenienza del checkout CI verificabile tramite GitHub, distinguendo il
  commit di merge delle pull request dalla testa del loro ramo;
- successo del run, del job scientifico e dei sette controlli nello stesso
  tentativo; esclusione delle esecuzioni provenienti da fork;
- identità dell'artefatto, checksum del trasporto e corrispondenza di ogni file
  al descrittore, con limiti su dimensioni, numero e percorsi.

Un cambio di commit con albero Git identico può riusare la prova. Anche una
modifica della sola documentazione cambia invece l'albero e provoca un nuovo
controllo: questa prima versione privilegia un contratto conservativo.
Il confronto dell'ID dell'immagine include i byte effettivi delle dipendenze;
la sola uguaglianza del Dockerfile o del tag non basta.

I rapporti vengono ripristinati senza riscrivere immagine, timestamp o risultati.
`build/scientific-reuse/reuse.json` registra la decisione, la nuova build e il
produttore CI, con artefatto e digest quando il riuso riesce. Il record entra nei
log scientifici e nel bundle finale. Il record di accettazione continua a
identificare la nuova build installer; non attribuisce alla build l'esecuzione
originale dei test CI.

Se non esiste una prova compatibile, è scaduta, l'API non è disponibile o una
verifica fallisce, la build esegue tutti e sette i controlli. Non attende run CI
ancora attivi e non considera la cache mancante un esito scientifico positivo.
La ricerca considera al massimo 30 run completati, con un budget complessivo
di due minuti; un errore di rete interrompe la ricerca senza ripetere la stessa
attesa per tutti i candidati.
I controlli del client, il preflight delle evidenze, il runtime WSL, il caricamento
dell'archivio esportato nel motore distribuito e le verifiche dei quattro pacchetti
restano obbligatori nella nuova build.

Il beneficio dipende dal numero di corrispondenze effettive. Il profilo precedente
attribuiva circa 14 minuti ai sette controlli: il risparmio netto sottrae ricerca,
download e verifica delle evidenze, e va misurato sulla build reale.

## Audit Windows e concorrenza dalla 0.8.20

La build Windows compila preventivamente il componente di coordinamento e
verifica la ripetibilità dei binari C# interessati. Una fixture derivata dalla
definizione Inno esercita installazione, aggiornamento e rimozione sul runner:
solo nella fixture vengono sostituiti il bootstrap e i requisiti desktop.
Il rapporto dichiara `production_setup_executed: false`; il setup distribuito
non acquisisce opzioni per saltare i propri controlli.

Il rapporto Authenticode distingue componenti firmati, privi di firma e
fallimenti di verifica. Le firme non valide non vengono convertite in un
esito positivo. La presenza del rapporto non attesta l'esecuzione su Windows
11 con Smart App Control, che resta una prova separata.

Il publisher richiede esplicitamente anche i casi differenziali DNP con
2, 3 e 6 BAM e i controlli helper della coda comune. Il verificatore misura
la concorrenza effettiva globale e per coordinatore e rifiuta budget superati
o attività fallite. Questi controlli verificano correttezza e rispetto delle
risorse; non impongono soglie di velocità sui runner condivisi.

## Verifiche Lima su runner dedicati

Il parametro `qualify_macos_runtime` abilita le prove reali su runner dedicati
con etichette `self-hosted`, `macOS`, `nipat-runtime` e `ARM64` oppure `X64`.
Devono esporre virtualizzazione e requisiti del pacchetto. Non eseguire codice
di pull request non fidate su questi runner.

Registrare hardware, macOS, architettura, Lima/Rosetta, commit e checksum del
pacchetto. Una prova su un'architettura non qualifica l'altra. Le prove di VM
non sostituiscono quelle di interazione Finder o delle policy del dispositivo.

## Pubblicazione

Integrare il record accettato con una PR contenente soltanto i JSON di accettazione
avvia la CI Linux dedicata su `main`. Al suo successo, **Publish accepted release**
usa esattamente quel commit e pubblica la build indicata. Le versioni senza
suffisso vengono pubblicate su `stable` come `Latest`; `a`, `b` e `rc` usano
`testing`. Una modifica mista richiede l'avvio manuale descritto sotto.
L'automazione verifica che il run provenga dal push su `main` di questo repository,
con `acceptance` e `required` riusciti. Il publisher verifica nuovamente i pacchetti
e i digest remoti. I rilanci riconoscono una release già pubblicata e possono
riprendere una bozza coerente. Il workflow manuale e quello automatico condividono
lo stesso limite di concorrenza.

Sorgenti e record di accettazione vengono integrati in `main` conservando il
commit compilato. Il publisher crea una bozza con gli stessi byte verificati;
`prepare-and-publish` prepara e pubblica in un'unica esecuzione esplicita,
ricontrollando la bozza prima della pubblicazione. In alternativa, `prepare`
e `publish` mantengono le due fasi separate per esaminare la bozza.
`stable` identifica la release ufficiale e `Latest`; `testing` una pre-release.
La scelta non dichiara una validazione scientifica generale.

Windows/Linux usano `update-manifest.json`; macOS usa
`update-manifest-macos.json`. I client verificano piattaforma, versione,
dimensione e checksum. Le build Actions e le bozze non sono aggiornamenti.
Per ricerca pre-1.0 sono ammessi scenari desktop non ancora eseguiti, dichiarati
nel record; la [procedura di pubblicazione](../.github/RELEASE.md) specifica
le evidenze richieste e la [scheda di validazione](VALIDAZIONE.md) raccoglie
le osservazioni dei ricercatori.

## Tempi e gestione dei rilanci

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

Congelare la candidata prima della build e completare i controlli locali pertinenti.
Creare il ramo di accettazione quando il record è disponibile, evitando una nuova
CI completa su un ramo provvisorio senza modifiche. Per un guasto transitorio su
uno stesso commit usare il rilancio dei soli job falliti; una correzione dei sorgenti
richiede evidenze corrispondenti alla nuova candidata. La modalità combinata di
pubblicazione evita il secondo download e la seconda qualificazione locale degli
stessi pacchetti, mantenendo la verifica dei contenuti della bozza.

Il riuso della qualificazione tra CI e build segue il contratto descritto sopra.
La CI produce sempre evidenze nuove quando esegue il livello scientifico; la build
può consumarle soltanto dopo averne verificato l'identità completa.

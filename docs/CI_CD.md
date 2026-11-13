# Integrazione continua e distribuzione

NIPAT verifica separatamente il client, il motore scientifico, gli installatori
e il funzionamento sui dispositivi reali. La versione 0.8.50 distribuisce
Windows 10/11 x64, Ubuntu 24.04 x86_64 e macOS 14 o successivo Intel/Apple Silicon.
Tutti i pacchetti incorporano lo stesso archivio scientifico Linux AMD64.

## Workflow GitHub Actions

| Workflow | Attivazione | Risultato |
| --- | --- | --- |
| [CI](../.github/workflows/ci.yml) | Push, pull request, avvio manuale. | Test del client e dei contratti, controlli dei sorgenti e della documentazione, componenti di piattaforma e regressioni scientifiche applicabili. |
| [Installers (review build)](../.github/workflows/windows-installer.yml) | Avvio manuale su un commit revisionato. | Quattro installatori con manifest, checksum e rapporti; nessuna pubblicazione automatica. |
| [Prepare or publish verified release](../.github/workflows/publish-windows-release.yml) | Avvio manuale su `main`. | Bozza e pubblicazione dei pacchetti accettati, in fasi separate oppure in un'unica esecuzione esplicita, senza ricompilarli. |
| [Published runtime security report](../.github/workflows/security-monitoring.yml) | Pianificazione e avvio manuale. | Inventari e segnalazioni sulle immagini pubblicate, da esaminare separatamente. |

La CI seleziona i controlli in base ai file modificati. Contratti, runtime,
installer e pipeline attivano i livelli corrispondenti; un confronto Git non
disponibile non viene interpretato come una modifica della sola documentazione.
Il controllo aggregato `required` verifica l'esito dei job richiesti.
I controlli della pull request rimangono attivi quando il push viene deduplicato.
Gli installatori completi vengono costruiti su richiesta, non a ogni push.
Una modifica al solo workflow di pubblicazione richiede i controlli di packaging
e i controlli rapidi obbligatori; non riesegue il runtime scientifico. Le modifiche
al selettore, alla CI, alla build o a workflow non riconosciuti conservano tutti
i livelli. Una modifica scientifica concomitante riattiva sempre quel livello.

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

Entrambi i gate sono obbligatori nella CI scientifica e nella build, prima
dell'esportazione del runtime. Il publisher schema 7 lega i due rapporti alla
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

Il riuso della qualificazione tra CI e build non è ancora implementato: richiede
un contratto che identifichi sorgenti, verificatori, fixture, dipendenze e immagine
esatti. Il numero dei test, da solo, non motiva l'eliminazione di controlli numerici.

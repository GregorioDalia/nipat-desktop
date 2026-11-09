# Integrazione continua e distribuzione

NIPAT verifica separatamente il client, il motore scientifico, gli installatori
e il funzionamento sui dispositivi reali. La versione 0.8.20 distribuisce
Windows 10/11 x64, Ubuntu 24.04 x86_64 e macOS 14 o successivo Intel/Apple Silicon.
Tutti i pacchetti incorporano lo stesso archivio scientifico Linux AMD64.

## Workflow GitHub Actions

| Workflow | Attivazione | Risultato |
| --- | --- | --- |
| [CI](../.github/workflows/ci.yml) | Push, pull request, avvio manuale. | Test del client e dei contratti, controlli dei sorgenti e della documentazione, componenti di piattaforma e regressioni scientifiche applicabili. |
| [Installers (review build)](../.github/workflows/windows-installer.yml) | Avvio manuale su un commit revisionato. | Quattro installatori con manifest, checksum e rapporti; nessuna pubblicazione automatica. |
| [Prepare or publish verified release](../.github/workflows/publish-windows-release.yml) | Avvio manuale su `main`. | Preparazione di una bozza o pubblicazione separata dei pacchetti accettati, senza ricompilarli. |
| [Published runtime security report](../.github/workflows/security-monitoring.yml) | Pianificazione e avvio manuale. | Inventari e segnalazioni sulle immagini pubblicate, da esaminare separatamente. |

La CI seleziona i controlli in base ai file modificati. Contratti, runtime,
installer e pipeline attivano i livelli corrispondenti; un confronto Git non
disponibile non viene interpretato come una modifica della sola documentazione.
Il controllo aggregato `required` verifica l'esito dei job richiesti.
I controlli della pull request rimangono attivi quando il push viene deduplicato.
Gli installatori completi vengono costruiti su richiesta, non a ogni push.

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
| Motore scientifico | Quattro analisi, piani composti, BAM sintetici, confronti numerici, input errati e originali invariati. | Non costituisce validazione di dominio su tutti i campioni reali. |
| Documentazione | File, immagini, link relativi e sezioni Markdown. | Non verifica disponibilità dei siti esterni o contenuto scientifico della prosa. |

Ogni difetto riproducibile deve essere coperto dal test del livello pertinente.
Il numero di test non sostituisce l'esame dei casi coperti. Gli esiti distinguono
prove eseguite, fallite, saltate e non eseguite; un job facoltativo saltato non
è una prova superata.

## Regressioni scientifiche

Le modifiche R della 0.8.9 richiedono anche un confronto differenziale con i
sorgenti congelati della 0.8.5. `scripts/verify_r_equivalence.py` esegue le
due versioni nello stesso runtime e conserva risultati, log e rapporto
`r-equivalence.json`. Un errore o una differenza impedisce il completamento
del job scientifico. La build degli installatori applica lo stesso controllo
prima dell'esportazione del runtime. I riferimenti di test non sono inclusi
nel payload installato. I criteri sono descritti nel
[piano di verifica 0.8.9](OPTIMIZATION_0.8.9.md).

Il container contiene R, samtools, gli script scientifici, gli adattatori e
l'orchestrazione. Il client verifica i contratti e non monta gli script R
dalla cartella dell'applicazione. I workflow composti vengono confrontati
con le analisi singole equivalenti, usando risultati attesi.

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
dai sorgenti, ad esempio `release/0.8.20`. Il controllo
`installer-required` verifica sorgenti, manifest, checksum e archivio scientifico
comune ai quattro pacchetti. La build produce:

| Artefatto Actions | Pacchetto |
| --- | --- |
| `nipat-windows-setup` | `NIPAT-Setup.exe`. |
| `nipat-linux-setup` | `nipat-desktop_0.8.20_amd64.deb`. |
| `nipat-macos-setup-arm64` | `NIPAT-0.8.20-macos-arm64.pkg`. |
| `nipat-macos-setup-x86_64` | `NIPAT-0.8.20-macos-x86_64.pkg`. |
| `nipat-installer-set-evidence` | Identità e verifica congiunta dei pacchetti. |

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
un secondo avvio pubblica quella bozza dopo averne ricontrollato i contenuti.
`stable` identifica la release ufficiale e `Latest`; `testing` una pre-release.
La scelta non dichiara una validazione scientifica generale.

Windows/Linux usano `update-manifest.json`; macOS usa
`update-manifest-macos.json`. I client verificano piattaforma, versione,
dimensione e checksum. Le build Actions e le bozze non sono aggiornamenti.
Per ricerca pre-1.0 sono ammessi scenari desktop non ancora eseguiti, dichiarati
nel record; la [procedura di pubblicazione](../.github/RELEASE.md) specifica
le evidenze richieste e la [scheda di validazione](VALIDAZIONE.md) raccoglie
le osservazioni dei ricercatori.

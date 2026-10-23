# Installatore Windows

Il pacchetto Windows di NIPAT 0.5 contiene l'applicazione, Python portabile,
il launcher `NIPAT.exe`, il filesystem WSL e l'immagine scientifica. Il file
`NIPAT-Setup.exe` è autosufficiente per i componenti NIPAT: non occorre
scaricare archivi runtime separati o creare una cartella `assets`.

La versione 0.5.0a1 è una Preview non pubblicata. I pacchetti prodotti da
GitHub Actions sono artefatti di revisione tecnica; la loro costruzione non
attesta il completamento delle prove di installazione o della validazione di
dominio. Questo documento descrive struttura, preparazione e verifica del
pacchetto Windows. L'uso delle analisi è trattato nella
[guida per l'utilizzo](GUIDA_UTILIZZO.md).

## Requisiti e installazione

Il target è Windows 11 x64 con virtualizzazione hardware disponibile e WSL2.
Il setup opera nell'account dell'utente e richiede autorizzazione amministrativa
soltanto per abilitare i prerequisiti Windows mancanti. L'abilitazione o
l'aggiornamento dei componenti WSL può richiedere Internet e un riavvio.
Le politiche di un dispositivo gestito possono richiedere l'intervento
dell'amministratore. Docker Desktop, R, samtools e Python installati a livello
di sistema non sono necessari.

1. Avviare `NIPAT-Setup.exe` con doppio clic dal proprio account Windows,
   senza scegliere «Esegui come amministratore».
2. Completare il setup e, se richiesto, autorizzare l'abilitazione dei componenti
   Windows. Dopo un riavvio, accedere allo stesso account per riprendere.
3. Attendere la verifica degli archivi, la preparazione del runtime e gli
   autotest. La configurazione è completa quando compare `NIPAT: ready`.
4. Aprire **NIPAT 0.5 Preview** dal menu Start o dal collegamento sul desktop.

Lo spazio disponibile deve contenere applicazione, cache degli archivi,
filesystem WSL importato e immagine scientifica, oltre a input e risultati.
Un aggiornamento del filesystem WSL richiede spazio anche per conservare
l'ambiente precedente. I file scientifici selezionati possono risiedere su
qualsiasi disco locale fisso accessibile all'account; il trasporto WSL non
supporta condivisioni UNC, unità di rete o dischi rimovibili.

## Identità e percorsi

Il file [`install-profile.json`](../installer/windows/install-profile.json)
definisce l'identità del canale. Il builder genera da questo profilo le
istruzioni Inno Setup e le verifica rispetto al manifest.

| Risorsa | Valore |
| --- | --- |
| Canale | `preview-0.5` |
| Nome applicazione | `NIPAT 0.5 Preview` |
| Applicazione | `%LOCALAPPDATA%\Programs\NIPAT-0.5-Preview` |
| Dati e risultati predefiniti | `%LOCALAPPDATA%\NIPAT-0.5-Preview\data` e `runs` |
| Cache | `%LOCALAPPDATA%\NIPAT-0.5-Preview\cache` |
| Registri del runtime | `%LOCALAPPDATA%\NIPAT-0.5-Preview\wsl` |
| Distribuzione WSL2 | `NIPAT-05-Preview-` seguito dalle prime 40 cifre dello SHA-256 del rootfs |
| Ripresa al successivo accesso | Valore RunOnce `NIPAT-05-Preview-ResumeSetup` |

AppId, mutex, collegamenti e voce di disinstallazione appartengono al medesimo
canale. La destinazione dell'applicazione è fissa; opzioni `/DIR` o `/GROUP`
che alterano le destinazioni previste vengono rifiutate prima della copia.
I controlli rifiutano anche junction e collegamenti nelle destinazioni protette.

Manifest, backend, stato, proprietà del runtime e registri di recupero devono
indicare il canale previsto. Il setup non adotta ambienti o configurazioni
di altri canali. Il componente Windows WSL rimane una risorsa del sistema.

Il launcher installato usa la propria configurazione e non eredita le variabili
NIPAT di percorso/backend di una shell esterna. L'utente può selezionare
esplicitamente dati e risultati con `--data-dir` e `--runs-dir`.

## Preparazione e identità dell'immagine

Il manifest incorporato contiene commit sorgente, versione, profilo e identità
degli archivi. Il setup verifica i rispettivi SHA-256 prima dell'utilizzo.
Gli archivi incorporati vengono estratti nella cache dell'utente con nomi
comprendenti il digest; la cache permette la ripresa senza una nuova estrazione
manuale. Il setup non scarica un manifest sostitutivo.

Il filesystem WSL include Docker Engine e Compose dedicati. Dopo l'importazione,
`nipat-engine ensure` avvia il motore interno. Il setup carica l'archivio
scientifico verificato e acquisisce l'unico ID immutabile restituito da
`docker load`, verificando che l'immagine sia Linux amd64.

L'ID locale può differire dall'ID della build perché i motori Docker possono
identificare configurazioni o manifest delle immagini in modo diverso.
Stato e backend conservano separatamente ID della build, ID risolto localmente
e SHA-256 dell'archivio. Le esecuzioni usano l'ID locale verificato, con pull
disabilitato. Il launcher ne controlla il legame con il manifest installato.

## Aggiornamento e ripresa

Un filesystem WSL con lo stesso digest completo può essere riutilizzato solo
se registrazione e proprietà appartengono al canale. Un digest diverso produce
una distribuzione affiancata. Un nome già occupato da un ambiente non
riconosciuto interrompe la preparazione senza sostituirlo.

Il setup conserva una copia dello stato e del backend precedenti per ogni
combinazione di commit e filesystem in `.runtime\installer\recovery`.
Conserva inoltre le cartelle dati e risultati di una configurazione valida
appartenente allo stesso canale. I dati dell'utente non sono trasferiti nel
filesystem Linux.

Il candidato viene verificato con `doctor --runtime` e `self-test` prima
dell'attivazione del backend; lo stato `ready` viene scritto per ultimo.
Ogni ripresa verifica e ricarica l'archivio. L'avvio ordinario riusa invece
l'ID locale registrato e avvia autonomamente il motore se è fermo.

Dopo un errore, aprire **NIPAT 0.5 Preview - completa preparazione** dal menu
Start. Conservare questi file della cartella applicativa:

- `.runtime\installer\setup.log`: dettagli della preparazione;
- `.runtime\installer\state.json`: fase ed errore registrati;
- `.runtime\backend.json`: configurazione attivata, se presente.

Non modificare questi file per forzare lo stato `ready`. I registri di recupero
sono evidenze di configurazione, non un backup completo dell'applicazione.
Inno Setup copia i file applicativi prima della preparazione del runtime:
un errore lascia l'applicazione bloccata fino al completamento del setup,
anche se la distribuzione precedente è ancora presente.

La disinstallazione rimuove l'applicazione e la sua ripresa automatica;
conserva dati, risultati, cache e distribuzioni WSL. Non elimina automaticamente
gli ambienti conservati dagli aggiornamenti.

## Client Windows da sorgenti

Questo percorso è destinato allo sviluppo. `1_SETUP.cmd` prepara il Python
locale e verifica un runtime WSL già configurato; non crea il filesystem WSL
e non costruisce o scarica l'immagine scientifica.

Per usare il runtime di una Preview già preparata, leggere il suo backend e
selezionarlo esplicitamente nella sessione PowerShell del checkout:

```powershell
$nipatApp = Join-Path $env:LOCALAPPDATA "Programs\NIPAT-0.5-Preview"
$nipatBackend = Get-Content -Raw -LiteralPath `
    (Join-Path $nipatApp ".runtime\backend.json") | ConvertFrom-Json
$env:NIPAT_BACKEND = "wsl"
$env:NIPAT_WSL_DISTRO = $nipatBackend.wsl_distro
$env:NIPAT_RUNTIME_IMAGE = $nipatBackend.runtime_image

# Eseguire dalla radice del checkout NIPAT.
& ".\1_SETUP.cmd"
if ($LASTEXITCODE -ne 0) { throw "Preparazione del client non riuscita." }
& ".\2_AVVIA.cmd"
```

Il pacchetto installato deve aver già completato la preparazione. Il client
verifica nuovamente l'immagine e le sue interfacce; un runtime incompatibile
viene rifiutato. Il setup da sorgenti richiede un nome WSL esplicito e un ID
immagine `sha256:<64 cifre esadecimali>`. Le variabili hanno effetto nella
sessione corrente e non modificano la configurazione del pacchetto installato.
Per un ambiente di sviluppo indipendente, usare una distribuzione WSL dedicata
con `nipat-engine`, Docker Engine e Compose e importarvi l'archivio verificato
della stessa build; non riutilizzare nomi di distribuzioni gestite da altri canali.

## Costruzione e accettazione del pacchetto

Il workflow [Installers (review build)](../.github/workflows/windows-installer.yml)
compila e prova il launcher, verifica il motore scientifico, esporta gli archivi,
prepara i sorgenti ammessi da `distribution-files.txt` e compila l'EXE con
Inno Setup. `installer-build.json` lega l'eseguibile a commit, versione,
manifest, launcher, profilo e archivi incorporati. I dettagli e gli artefatti
sono descritti in [CI/CD](CI_CD.md).

Per una prova tecnica usare il solo `NIPAT-Setup.exe` estratto dall'artefatto
`nipat-windows-setup` di una build riuscita e identificata dal commit.
Il launcher separato nello stesso artefatto è un'evidenza di compilazione,
non un'installazione autonoma.

Registrare prima installazione, riavvio del runtime, analisi di un caso noto,
aggiornamento nello stesso canale, ripresa dopo errore e disinstallazione con
conservazione dei dati. I test automatici dei confini Windows/WSL non
sostituiscono queste prove del pacchetto reale. Usare la
[scheda di validazione](VALIDAZIONE.md) per associare gli esiti alla build.

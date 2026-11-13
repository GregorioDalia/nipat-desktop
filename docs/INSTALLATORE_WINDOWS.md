# Installatore Windows

Il pacchetto Windows di NIPAT Desktop contiene l'applicazione, Python portabile,
i componenti di avvio, il filesystem WSL e l'immagine scientifica. Il file
`NIPAT-Setup.exe` è autosufficiente per i componenti NIPAT: non occorre
scaricare archivi runtime separati o creare una cartella `assets`.

Questo documento descrive **NIPAT Desktop 0.8.30**. Scaricare `NIPAT-Setup.exe`
dalla pagina [Releases](https://github.com/GregorioDalia/nipat-desktop/releases).
Le [note della versione](RELEASE_0.8.30.md) distinguono controlli automatici,
prove desktop e valutazione di dominio. Il setup aggiorna le installazioni
NIPAT Desktop riconosciute e conserva i percorsi scelti dall'utente.

## Requisiti e installazione

I sistemi supportati sono **Windows 10 22H2 x64, build 19045**, e
**Windows 11 x64**, con virtualizzazione hardware disponibile e WSL2.
Windows Server, Windows ARM, Windows a 32 bit e build Windows 10 precedenti
non sono supportati. Il setup legge edizione, build e architettura prima di
preparare l'ambiente; il controllo non dipende dalla lingua del sistema.

**Windows 10 Pro 22H2, build 19045.6466**, rientra in questo target.
Il numero `6466` indica la revisione dell'aggiornamento cumulativo: il setup
controlla la build `19045`, senza imporre quella specifica revisione o escludere
gli aggiornamenti successivi della stessa build. L'idoneità del sistema al
controllo iniziale non attesta che l'installazione o il runtime siano già stati
collaudati su tale configurazione.

La disponibilità di WSL viene rilevata sul dispositivo. Il setup distingue
un componente utilizzabile da prerequisiti mancanti o non pronti e avvia
la preparazione necessaria. La versione del sistema non basta da sola:
virtualizzazione, componenti Windows, kernel WSL e policy del dispositivo
possono impedire l'avvio. I test simulati non qualificano un Windows 10 reale.
Il setup opera nell'account dell'utente e richiede autorizzazione amministrativa
soltanto per abilitare i prerequisiti Windows mancanti. L'abilitazione o
l'aggiornamento dei componenti WSL può richiedere Internet e un riavvio.
Le politiche di un dispositivo gestito possono richiedere l'intervento
dell'amministratore. Docker Desktop, R, samtools e Python installati a livello
di sistema non sono necessari.

### Controlli di sicurezza di Windows e del browser

I checksum identificano i file distribuiti; non costituiscono una firma
Authenticode né attestano il riconoscimento del distributore da parte di Windows.
Il pacchetto non dispone di una firma Authenticode NIPAT. Smart App Control
può bloccare il setup, un eseguibile o gli script usati dalla preparazione
e dall'avvio.
Un'installazione riuscita non dimostra che tutti i componenti siano autorizzati
all'esecuzione sul dispositivo.

In presenza di un blocco, conservare il testo completo dell'avviso, il nome del
file indicato e il riferimento alla build scaricata. Distinguere Smart App
Control, SmartScreen e un rilevamento antivirus: richiedono verifiche diverse.
Il setup non disattiva le protezioni né introduce esclusioni antivirus.
Il referente del collaudo deve verificare l'errore sul componente indicato
prima di considerare utilizzabile il pacchetto su quel dispositivo.

La 0.8.20 elimina la compilazione di una DLL temporanea durante la
preparazione. Questo migliora l'identificazione dei componenti, ma non
sostituisce la firma del distributore. Il cambio di numero di versione non
garantisce l'accettazione da parte di Smart App Control; la firma e la
reputazione riguardano i file effettivi. Il rapporto `windows-trust-check.json`
della release elenca hash e stato delle firme senza dichiarare un collaudo
Smart App Control.

Per identificare un blocco aprire **Visualizzatore eventi → Registri
applicazioni e servizi → Microsoft → Windows → CodeIntegrity → Operational**
e cercare gli eventi vicini all'orario del tentativo, in particolare 3077
(blocco) e 3076 (audit). Conservare il percorso del file e il messaggio.
La raccolta diagnostica non richiede di disattivare la protezione.

### Procedura

1. Avviare `NIPAT-Setup.exe` con doppio clic dal proprio account Windows,
   senza scegliere «Esegui come amministratore».
2. Scegliere la cartella applicativa nella pagina di destinazione, quindi
   le cartelle di ambiente WSL, cache, dati e risultati. Verificare la modalità
   indicata dal setup: **Installazione** per una cartella vuota oppure
   **Aggiornamento e riparazione** per un’installazione NIPAT Desktop riconosciuta. Se richiesto,
   autorizzare l'abilitazione dei componenti Windows. Dopo un riavvio,
   accedere allo stesso account per riprendere.
3. Attendere la verifica degli archivi, la preparazione del runtime e gli
   autotest. La configurazione è completa quando compare `NIPAT: ready`.
4. Se la preparazione è completa e non serve un riavvio, il setup propone
   **Avvia NIPAT Desktop**. Per gli utilizzi successivi aprire il
   collegamento dal menu Start o dal desktop, creato se selezionato nel setup.

I collegamenti avviano `2_AVVIA.cmd` con la cartella dati come directory
corrente e il logo NIPAT come icona. `nipat.cmd` espone gli stessi workflow
per l'uso nei terminali. Entrambi passano attraverso `scripts/windows/run.ps1`,
che verifica stato `ready`, manifest e associazione al runtime prima di
preparare l'ambiente del client. Il launcher `NIPAT.exe` resta incluso come
componente aggiuntivo, ma non è il destinatario dei collegamenti ordinari.
Il collegamento **Cartella NIPAT Desktop** nel menu Start apre la cartella applicativa
selezionata, con documentazione e comandi disponibili.

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

| Risorsa | Valore o percorso predefinito |
| --- | --- |
| Canale | `desktop` |
| Nome applicazione | `NIPAT Desktop` |
| Applicazione | `%LOCALAPPDATA%\Programs\NIPAT-Desktop` |
| Ambiente WSL | `%LOCALAPPDATA%\NIPAT-Desktop\wsl` |
| Cache | `%LOCALAPPDATA%\NIPAT-Desktop\cache` |
| Dati | `%LOCALAPPDATA%\NIPAT-Desktop\data` |
| Risultati | `%LOCALAPPDATA%\NIPAT-Desktop\runs` |
| Registri delle destinazioni | `%LOCALAPPDATA%\NIPAT-Desktop\installations` |
| Preferenze del menu | `%LOCALAPPDATA%\NIPAT-Desktop\preferences.json` |
| Distribuzione WSL2 | Nome con prefisso `NIPAT-Desktop-`, associato al filesystem Linux e alla posizione scelta. |
| Ripresa al successivo accesso | Valore RunOnce `NIPAT-Desktop-ResumeSetup` |

AppId, mutex, collegamenti e voce di disinstallazione appartengono al medesimo
canale. Le cinque radici di applicazione, ambiente WSL, cache, dati e risultati
sono configurabili; i registri centrali restano nel profilo dell'utente.
Le preferenze salvate in `HKCU` ripropongono le scelte nelle reinstallazioni,
anche dopo la rimozione dell'applicazione. L'aggiornamento di un'installazione
NIPAT Desktop deve usare la stessa cartella applicativa.

Il setup verifica percorsi assoluti su dischi locali fissi, scrivibili
dall'account e privi di junction o collegamenti. Le cinque radici non possono
coincidere né essere annidate tra loro; non sono ammesse sovrapposizioni con
cartelle di sistema, `Windows`, `Program Files` o destinazioni predefinite
delle altre installazioni NIPAT. Sono rifiutati percorsi UNC, unità di rete e supporti
rimovibili. La cartella applicativa deve essere vuota o riconosciuta come
appartenente a NIPAT Desktop. Una configurazione di stato e backend valida può
identificare anche i residui di una disinstallazione, senza richiedere che
la cartella contenga soltanto `.runtime`. La presenza di altri file non ne
autorizza la cancellazione.

Per una cartella estranea non vuota, il setup può proporre la sottocartella
vuota `NIPAT-Desktop`, previa conferma. Questa scelta cambia soltanto la
destinazione. Se anche la sottocartella contiene file, occorre scegliere
un'altra cartella vuota: il setup non svuota il contenuto né crea una catena
di sottocartelle. Dati e risultati possono contenere file preesistenti, che
non vengono trasferiti o cancellati dal setup.

Manifest, backend, stato, proprietà del runtime e registri di recupero devono
indicare il canale previsto. Il setup non adotta ambienti o configurazioni
di altri canali. NIPAT Desktop conserva la propria identità:
nessuna installazione sperimentale o di un altro canale viene adottata
o aggiornata da questo setup. Il componente Windows WSL rimane una risorsa del sistema.

Il launcher installato usa la propria configurazione e non eredita le variabili
NIPAT di percorso/backend di una shell esterna. Nel menu, **Configura** applica
le preferenze salvate alle cartelle e ai parametri delle analisi, senza cambiare
posizione dell'applicazione, cache o runtime. Le opzioni `--data-dir` e
`--runs-dir` selezionano esplicitamente le destinazioni; nella sessione guidata
prevalgono sulle preferenze. I comandi diretti non leggono queste preferenze.

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

## Aggiornamento e riparazione

**9 — Verifica aggiornamenti** consulta il canale selezionato e verifica il
download del nuovo setup. L'installazione usa lo stesso profilo `desktop`,
conservando le cartelle riconosciute e i risultati. È possibile scaricare
manualmente il setup dalla pagina Releases.

Se altre sessioni NIPAT sono aperte, l'aggiornamento viene fermato senza
terminarle: chiuderle al termine del lavoro e riprovare. Il passaggio al setup
conserva `handoff.log` e, in caso di errore, `error.txt` nella sottocartella
`updates\handoff-*` della cache configurata. Se Windows richiede un riavvio,
completare poi la preparazione dal collegamento nel menu Start; la sola
conclusione della copia dei file non autorizza le analisi.

Il setup riutilizza la cartella di NIPAT Desktop riconosciuta, conservando i
percorsi selezionati. Un inventario dei file distribuiti distingue i componenti
gestiti dall'installatore dai file aggiunti dall'utente. Prima di sovrascrivere
un componente differente, il setup ne salva la copia in
`%LOCALAPPDATA%\NIPAT-Desktop\installations\backups\<UTC-guid>`.
Il backup include anche l'inventario precedente, la configurazione dei percorsi,
lo stato dell'installatore, il backend, il marcatore applicativo e il Python
portabile generato sotto `.runtime\python`. I componenti applicativi identici
non richiedono una copia.
Solo quando `.distribution\application-files.json` è assente, il setup può
usare la mappa `source_sha256` di `.distribution\installer-manifest.json`
come inventario precedente, dopo averne verificato schema, profilo, commit e
corrispondenze fra percorsi e hash; un inventario presente ma non valido non
abilita questo recupero alternativo.

I file estranei ai componenti distribuiti rimangono nella loro posizione;
un file con lo stesso nome di un componente da installare viene salvato prima
della sovrascrittura. Un componente presente nell'inventario precedente ma non
più distribuito viene rimosso soltanto se il suo hash coincide con quello
registrato; se è stato modificato, rimane nella propria posizione e viene
anche copiato nel backup. I file estranei non elencati negli inventari e non
coinvolti nelle sostituzioni rimangono in posizione, senza una copia nel backup.
Un inventario precedente danneggiato viene salvato, ma non autorizza la rimozione di componenti obsoleti.
Un inventario del nuovo pacchetto non valido interrompe invece la preparazione.
Non viene svuotata l'intera cartella applicativa. Il backup selettivo non
comprende tutti i dati o il filesystem WSL e non realizza un ripristino
automatico completo in caso di errore.

### Preparazione del runtime e ripresa

Il manifest distingue applicazione, immagine scientifica e componente WSL.
La provenienza WSL identifica i suoi sorgenti, la base Linux e le dipendenze
effettivamente risolte, indipendentemente dal commit del client. Il builder
può riutilizzare un archivio pubblicato soltanto se il descrittore del
componente e il contenuto verificato corrispondono. Il setup continua a
verificare i byte dell'archivio tramite SHA-256 prima dell'importazione.

Una distribuzione può essere riutilizzata soltanto se digest completo,
registrazione WSL, proprietà del canale e posizione effettiva sono coerenti.
I nuovi nomi combinano il prefisso del canale, 32 cifre del digest del
filesystem Linux e 12 cifre del digest della posizione. Un ambiente già
posseduto da NIPAT Desktop con un nome precedente può essere riutilizzato nella
stessa destinazione, dopo le medesime verifiche di proprietà. Un nome occupato
da un ambiente non riconosciuto interrompe la preparazione senza sostituirlo.
Se una distribuzione posseduta da NIPAT Desktop è stata rimossa manualmente da
WSL, il setup può ricrearla soltanto quando la destinazione precedente è vuota.
La ricevuta precedente viene conservata nello storico delle registrazioni;
una cartella ancora contenente file non viene cancellata per forzare l'importazione.

Un digest Linux diverso o una diversa cartella dell'ambiente WSL produce una
distribuzione affiancata: il setup non copia né elimina quella precedente.
Le cartelle dati e risultati scelte diventano i valori predefiniti del client;
modificarle non trasferisce i file esistenti. I run precedenti rimangono nella
loro destinazione e i dati dell'utente non vengono importati nel filesystem Linux.

Il setup conserva una copia dello stato e del backend precedenti per ogni
combinazione di commit e filesystem in `.runtime\installer\recovery`.
I piccoli registri centrali delle installazioni conservano le destinazioni
attuali e precedenti necessarie per la verifica delle risorse del canale.

Il candidato viene verificato con `doctor --runtime` e `self-test` prima
dell'attivazione del backend; lo stato `ready` viene scritto per ultimo.
Ogni ripresa verifica e ricarica l'archivio. L'avvio ordinario riusa invece
l'ID locale registrato e avvia autonomamente il motore se è fermo.

Dopo un errore, aprire **NIPAT Desktop - completa preparazione** dal menu
Start. Conservare questi file della cartella applicativa:

- `.runtime\installer\setup.log`: dettagli della preparazione;
- `.runtime\installer\state.json`: fase ed errore registrati;
- `.runtime\backend.json`: configurazione attivata, se presente.

Le versioni con diagnostica esplicita conservano anche `doctor.stdout.log`,
`doctor.stderr.log`, `self-test.stdout.log`, `self-test.stderr.log` e i rispettivi
file `*.exit-code.txt` in `.runtime\installer`. Questi file descrivono l'ultimo
controllo concluso. Un messaggio su stderr non equivale da solo a un fallimento:
il bootstrap considera il codice di uscita e conserva entrambi gli stream.

Non modificare questi file per forzare lo stato `ready`. I registri di recupero
e il backup selettivo hanno scopi distinti; nessuno costituisce una copia
completa dell'installazione. Inno Setup copia i file applicativi prima della
preparazione del runtime:
un errore lascia l'applicazione bloccata fino al completamento del setup,
anche se la distribuzione precedente è ancora presente.

### Riparazione dell'autotest CPIN della 0.8.50

Il setup ufficiale 0.8.50 contiene un difetto nell'avvio di
`scripts/verify_cpin_update.py`: il Python incorporato non aggiunge automaticamente
la cartella dello script ai percorsi di importazione. Il controllo può quindi
terminare con `ModuleNotFoundError: No module named 'verify_contamination_update'`.
Il transcript delle versioni precedenti può omettere questo dettaglio.

Lo script [repair-0850-self-test.ps1](../scripts/windows/repair-0850-self-test.ps1)
applica una correzione locale soltanto al verificatore conosciuto della release
ufficiale. Verifica versione e hash, conserva backup e ricevuta separata e ripete
la preparazione completa con i controlli originali. Usarlo da PowerShell normale,
senza elevazione, indicando il commit immutabile da cui è stato scaricato tramite
`-HotfixSourceCommit`. Dati, risultati e manifest della release restano intatti.
Lo stato `ready` viene scritto esclusivamente dal bootstrap dopo il successo.

L'installazione risultante è **0.8.50 con correzione locale**. La ricevuta distingue
il pacchetto originario dalla correzione; non riscrive l'inventario per dichiarare
che il file modificato appartenga al setup originale. La funzione di manutenzione
«recupera» rileva questa differenza. Rieseguire l'EXE 0.8.50 originale ripristina
il verificatore difettoso; un successivo installer ufficiale corretto sostituisce
la riparazione locale.

La verifica del payload ora avvia tutti e cinque i verificatori con `--help`
usando il Python incorporato. Questo controllo rapido intercetta import mancanti
prima della distribuzione, senza ripetere i calcoli scientifici.

## Manutenzione dei componenti installati

**Guida e informazioni → Installazione e spazio** legge l'inventario delle
risorse possedute e le dimensioni di ambienti WSL e cache. Gli elementi
attivi e il precedente ambiente più recente sono protetti. La pulizia è
selettiva: richiede un elemento esplicitamente rimovibile, una conferma e
una nuova verifica di proprietà, percorso e integrità prima della rimozione.
File estranei, dati e risultati vengono conservati; non viene eseguito un
`prune` generale di Docker o WSL.

La riparazione riguarda la versione installata: verifica il payload e
avvia `bootstrap.ps1 -Resume`, con diagnostica e autotest. I registri dei
backup selettivi sono consultabili ma non autorizzano il ripristino di una
versione precedente. Un ripristino automatico completo richiederebbe anche
una copia coerente di tutti i componenti applicativi e della configurazione
dell'installatore, che il backup selettivo non rappresenta.

I comandi equivalenti sono `installation inspect [--json]`,
`installation cleanup --target ID` e
`installation recover --target current-installation`. Le ultime due
operazioni richiedono conferma, oppure `--yes` per una richiesta automatizzata.
Un processo separato conferma la ricezione, attende la chiusura del client
e acquisisce l'accesso esclusivo all'installazione prima di intervenire.
Il passaggio del client con codice `85` non indica una pulizia o riparazione
riuscita. Il risultato finale è in
`.runtime/maintenance/<id>/result.json`; i dettagli della preparazione restano
nei log dell'installatore. In caso di errore conservare entrambi.

## Disinstallazione

La disinstallazione rimuove i file applicativi gestiti dal setup, i collegamenti
e la ripresa automatica. Conserva sempre dati e risultati, comprese le
destinazioni precedenti registrate. Dopo la conferma di disinstallazione,
una seconda richiesta propone la rimozione dell'ambiente WSL e della cache,
con **No** come scelta predefinita. **Annulla** interrompe prima della pulizia.
Con **Sì**, il programma verifica le risorse di NIPAT Desktop nelle destinazioni
correnti e nello storico registrato prima di rimuoverle.

La rimozione riguarda soltanto distribuzioni WSL con proprietà e registrazione
coerenti e archivi della cache riconosciuti e verificati. Non consiste nella
cancellazione ricorsiva delle radici selezionate: file estranei, Docker Desktop,
altre distribuzioni WSL e risorse delle altre installazioni NIPAT non sono destinazioni
di rimozione. Una verifica fallita interrompe la pulizia e viene segnalata;
un errore durante le operazioni può lasciare risorse da rimuovere. In entrambi
i casi la disinstallazione dei file applicativi viene interrotta. Conservare
l'esito e il log persistente in
`%LOCALAPPDATA%\NIPAT-Desktop\installations\logs\uninstall-*.log`
prima di riprovare.

Preferenze dei percorsi e registri centrali delle installazioni sopravvivono
alla disinstallazione. Servono a riproporre le destinazioni e a identificare
le risorse conservate; non sono copie di sicurezza dei dati o del filesystem WSL.
Nella cartella applicativa possono restare i marcatori di proprietà, la
configurazione dei percorsi e file generati non gestiti da Inno Setup, come
Python portabile in `.runtime\python`. La disinstallazione non garantisce
quindi una cartella applicativa vuota; la configurazione conservata consente
la verifica della successiva reinstallazione. La rimozione dell'ambiente
NIPAT non disinstalla il componente WSL di Windows.

## Client Windows da sorgenti

Questo percorso è destinato allo sviluppo. `1_SETUP.cmd` prepara il Python
locale e verifica un runtime WSL già configurato; non crea il filesystem WSL
e non costruisce o scarica l'immagine scientifica.

Per usare il runtime di un’installazione NIPAT Desktop già preparata, leggere il suo backend e
selezionarlo esplicitamente nella sessione PowerShell del checkout:

```powershell
# Indicare la cartella applicativa scelta nel setup.
$nipatApp = Read-Host "Cartella applicativa NIPAT Desktop"
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

La compilazione dei componenti C# richiede Roslyn, disponibile con Visual
Studio Build Tools sulla macchina di build. Il computer destinatario non
richiede un compilatore. `NipatActivityNative.dll` viene confezionata insieme
all'applicazione; prima del caricamento il codice verifica l'hash contro
l'inventario associato al manifest. Le build ripetute del launcher e del
componente nativo vengono confrontate per SHA-256. Per eseguire dal checkout Windows i test e le funzioni di preparazione
e manutenzione dell'installatore, compilare prima il componente con:

```powershell
& .\installer\windows\build-native.ps1
```

Questo comando appartiene al flusso di sviluppo, non alla procedura ordinaria
di installazione. Non abilita né aggira Smart App Control.

Per una prova tecnica usare **NIPAT-Setup.exe** della build riuscita identificata
dal commit. Il riepilogo Actions riporta i download disponibili e il periodo
di conservazione; per gli artefatti può essere richiesto l'accesso a GitHub.
L'artefatto `nipat-windows-setup` conserva installatore ed evidenze. Il launcher
separato è un'evidenza di compilazione, non un'installazione autonoma.

Il [protocollo di accettazione](ACCETTAZIONE_INSTALLATORI.md) distingue la
distribuzione per ricerca dalla qualificazione desktop completa. Registrare
progressivamente prima installazione, riavvio del runtime, analisi di un caso
noto, coesistenza con le installazioni sperimentali, percorsi personalizzati, reinstallazione
e disinstallazione. Le prove del codice Windows/WSL non dimostrano attivazione
e ripresa su un Windows 10 reale; i casi non eseguiti restano espliciti nelle
note della candidata.

Un aggiornamento fra versioni differenti richiede una prova distinta dalla
reinstallazione. La [scheda di validazione](VALIDAZIONE.md) raccoglie i risultati
osservati, separando installazione e valutazione scientifica.

## Configurazione delle risorse

Il menu **Configura** mostra RAM e CPU del computer, risorse effettive di WSL
e limiti del container. Le impostazioni `.wslconfig` sono globali per l'account:
una modifica può interessare anche altre distribuzioni WSL2. NIPAT mostra
l'anteprima, conserva un backup e richiede conferma prima di applicare la
modifica. Il riavvio è distinto dal salvataggio; finché non avviene, il menu
indica che i nuovi valori non sono ancora attivi. Non vengono arrestate analisi
NIPAT in corso per applicare una configurazione.

Il limite memoria del container non aumenta la memoria di WSL.
La [guida alle risorse](RISORSE.md) descrive impostazioni e diagnosi degli arresti.

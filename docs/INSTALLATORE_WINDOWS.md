# Installatore Windows: compilazione e verifica

La revisione `0.3.0a1` introduce un candidato `NIPAT-Setup.exe` per
**Windows 11 x64**. La release precedente `0.2.0a2` resta disponibile con
Docker Desktop. Questo documento distingue la costruzione dell’installatore
dalla verifica dell’installazione completa e dalla validazione scientifica.

## Flusso previsto per l’utilizzo

1. Scaricare `NIPAT-Setup.exe` dalla release GitHub.
2. Avviare il file dal proprio account Windows, senza “Esegui come amministratore”.
3. Il setup prepara l’applicazione per l’utente. Se WSL non è disponibile,
   richiede l’autorizzazione amministrativa per abilitarne i prerequisiti.
4. Se serve riavviare Windows, la configurazione riprende al successivo accesso
   allo stesso account. Il collegamento per la configurazione consente anche
   una ripresa manuale dopo un errore.
5. Il setup importa l’ambiente dedicato, carica l’immagine scientifica e lancia
   gli autotest. Il collegamento **NIPAT** apre il menu CLI.

Le dipendenze vengono gestite dalla configurazione. Internet è necessario
per scaricare i componenti; le analisi successive si svolgono localmente.
Virtualizzazione disabilitata o restrizioni dell’ente possono impedire WSL e
richiedere intervento IT. L’installatore non modifica tali policy.

## Componenti e confini

- Applicazione per utente: `%LOCALAPPDATA%\Programs\NIPAT`.
- Dati e risultati predefiniti: `%LOCALAPPDATA%\NIPAT\data` e `runs`.
- Distribuzione WSL2: `NIPAT-Runtime`, dedicata a NIPAT.
- Python portabile 3.12.10, senza modificare il PATH del sistema.
- Docker Engine e Compose nel solo ambiente dedicato; Docker Desktop non serve.
- Runtime scientifico precompilato, identificato dal suo ID Docker.

Gli input rimangono nelle cartelle scelte dall’utente e vengono montati in
sola lettura. Il backend WSL inizialmente supporta percorsi su dischi locali fissi
Windows; condivisioni UNC e unità di rete non sono incluse. La GUI non fa parte
di questa revisione. Non vengono modificati gli algoritmi R.

La disinstallazione rimuove i file applicativi e la ripresa automatica, ma
conserva dati, risultati, cache e distribuzione WSL. Una nuova installazione
può riutilizzare solo lo stesso rootfs verificato; la migrazione a un rootfs
diverso non è automatica in questo candidato.

L’installatore non sostituisce automaticamente una distribuzione esistente:
controlla il marcatore NIPAT e l’associazione all’installazione corrente prima
di riutilizzarla. Non arresta né elimina altre distribuzioni WSL. L’applicazione
è per utente: non avviare l’intero setup con un altro account amministratore.

## Costruzione su GitHub

Il workflow `.github/workflows/windows-installer.yml`:

1. Esegue la suite Python, costruisce l’immagine scientifica ed esegue
   `doctor --runtime` e `self-test` con Docker Linux.
2. Esporta l’immagine verificata e costruisce l’archivio dell’ambiente WSL.
3. Registra commit, versioni dei pacchetti, dimensioni, ID immagine e SHA-256
   nel materiale di distribuzione. Ogni asset deve rientrare nel limite
   imposto dal builder per GitHub Releases.
4. Prepara solo i sorgenti presenti in `distribution-files.txt`, il Python
   verificato e il manifest dell’installatore.
5. Su Windows esegue i test e il controllo della sintassi PowerShell, compila
   l’helper per WSL e l’installatore Inno Setup, quindi conserva gli artefatti.

Il manifest fidato è incorporato nell’EXE. Per impostazione predefinita gli
archivi vengono scaricati dagli URL della stessa release GitHub. Il setup
verifica gli hash prima dell’importazione e l’ID dell’immagine dopo `docker load`.
Non scarica un manifest sostitutivo dalla rete.

Il workflow **non pubblica automaticamente** una release. Conservare il log
e gli artefatti della compilazione utilizzata per le prove. Non ricostruire
un runtime diverso fra verifica e distribuzione.

## Prova prima della pubblicazione

Gli asset non sono ancora disponibili all’URL della futura release. Scaricare
da GitHub Actions gli artefatti della stessa esecuzione del workflow: installer
e archivi runtime. Estrarli localmente e avviare l’EXE indicando la cartella
che contiene gli archivi, per esempio:

```powershell
& ".\NIPAT-Setup.exe" '/ASSETDIR=C:\percorso\asset-nipat'
```

Il percorso è un esempio da sostituire. Anche per gli asset locali valgono
gli hash del manifest incorporato. Non occorre applicare patch al progetto di
sviluppo né copiare i propri BAM/FASTA nell’installazione.

Registrare versione di Windows, versione WSL, commit, ID del workflow e ID
immagine insieme agli esiti. Per questa nuova modalità servono prove reali di:

| Caso | Esito da osservare |
| --- | --- |
| PC Windows senza WSL e senza Docker Desktop | Prerequisiti, eventuale riavvio, ripresa, importazione e autotest completi. |
| PC con WSL già disponibile | Ambiente NIPAT separato; distribuzioni preesistenti utilizzabili. |
| Riavvio successivo all’installazione | Il collegamento NIPAT avvia il motore senza operazioni manuali. |
| Interruzione del download o configurazione fallita | Errore leggibile, log conservato, ripetizione sicura senza falso esito positivo. |
| Archivio alterato | Rifiuto prima dell’importazione. |
| Nome distribuzione già occupato da ambiente non NIPAT | Arresto con messaggio, nessuna sostituzione automatica. |
| Input su più unità locali, spazi e caratteri speciali | Tutti i workflow operativi, originali invariati, risultati nella cartella scelta. |
| Interruzione di un’analisi | Stato del run registrato e container dell’analisi fermato. |
| Riesecuzione del setup e disinstallazione | Nessuna perdita di dati o risultati; indicazioni esplicite per l’ambiente conservato. |

La compilazione su GitHub non copre l’avvio di WSL e l’interazione con UAC
su un PC fisico. Gli autotest numerici non coprono tutti i casi DNPcall da BAM:
proseguire con la [scheda di validazione](VALIDAZIONE.md).

## Pubblicazione della versione verificata

Dopo le prove, creare un nuovo tag sul commit esatto compilato e una
**pre-release** corrispondente alla versione del manifest. Allegare l’EXE,
i due archivi e il manifest/checksum prodotti dalla stessa esecuzione.
Le etichette e i nomi degli asset devono corrispondere agli URL incorporati
nell’installer. Verificare la firma del codice se disponibile; il candidato
compilato senza certificato è privo di firma e Windows può mostrare l’avviso
per autore non riconosciuto.

Riportare nelle note della release i controlli effettivamente superati e le
prove ancora aperte. Condividere il link alla release: chi utilizza NIPAT
scarica soltanto l’EXE; sarà la configurazione a ottenere gli altri asset.
Non sostituire gli asset di una versione già consegnata: usare una nuova
versione. I pacchetti conservano le licenze dei componenti; prima della
redistribuzione verificare che materiale e sorgenti richiesti dalle relative
licenze siano disponibili.

## Riferimenti tecnici

- [Installazione WSL](https://learn.microsoft.com/en-us/windows/wsl/install).
- [Importazione e comandi WSL](https://learn.microsoft.com/en-us/windows/wsl/basic-commands).
- [Docker Engine su Debian](https://docs.docker.com/engine/install/debian/).
- [Inno Setup: privilegi](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm).

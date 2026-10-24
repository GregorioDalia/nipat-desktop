# Firma dei pacchetti Windows

La firma Authenticode associa i componenti Windows a un distributore verificato
e consente di controllarne l'integrità. I checksum SHA-256 identificano una
build, ma non sostituiscono il certificato del distributore. La firma non è
un'analisi antivirus e non garantisce l'assenza di avvisi di reputazione.

## Servizio e stato dell'integrazione

Il percorso previsto è SignPath Foundation, soggetto all'ammissione del progetto
al programma open source. Il certificato del programma è intestato a SignPath
Foundation. Non è ancora attivo un servizio di firma per NIPAT: le build di
revisione sono prive della firma NIPAT. La verifica della firma del compilatore
Inno Setup in CI riguarda il compilatore scaricato, non gli eseguibili prodotti.

L'attivazione richiede ammissione, configurazione del progetto e delle policy,
identificazione dei responsabili e autorizzazione delle richieste di firma.
Le chiavi private rimangono nel servizio. Token e credenziali non appartengono
al repository, ai pacchetti o ai log.

## Copertura

| Componente | Verifica richiesta |
| --- | --- |
| `NIPAT-Setup.exe` | Firma del pacchetto finale e timestamp. |
| `NIPAT.exe` | Firma del launcher incorporato nel setup. |
| `EnableWsl.exe` | Firma del componente che richiede elevazione per i prerequisiti. |
| Disinstallatore Inno Setup | Firma del componente effettivamente incorporato e installato. |
| Script PowerShell distribuiti | Inventario e firma degli script eseguiti su Windows; verifica nel contesto di Smart App Control. |
| Python portabile e librerie Windows | Inventario, provenienza e controllo dei componenti upstream; non attribuire loro la firma NIPAT. |

La firma dell'EXE esterno non firma automaticamente i file incorporati.
Il core R e gli strumenti Linux appartengono all'immagine scientifica;
la loro identità resta verificata dai manifest e dai checksum del runtime.

## Ordine della pipeline

1. Compilare e testare i componenti Windows dal commit revisionato su runner
   GitHub-hosted; conservare gli artefatti da inviare al servizio di firma.
2. Firmare launcher, helper e script previsti, verificando identità e timestamp.
3. Configurare Inno Setup per il disinstallatore firmato e costruire il setup
   con i componenti già firmati. Firmare infine `NIPAT-Setup.exe`.
4. Verificare nuovamente le firme sui file finali e conservare l'identità della
   richiesta SignPath, il commit e le evidenze di provenienza della build.
5. Calcolare i checksum dei file firmati e le evidenze Windows/Ubuntu;
   eseguire il collaudo desktop su questi stessi file.
6. Pubblicare soltanto i byte verificati, senza firmare o ricostruire dopo
   l'accettazione.

La firma degli script PowerShell cambia i loro byte. L'integrazione deve quindi
distinguere gli hash dei sorgenti revisionati dagli hash del payload firmato,
verificando la corrispondenza prima e dopo la firma. Non rimuovere i controlli
del manifest né sostituire arbitrariamente gli hash per accettare uno script.
Questa trasformazione del payload e l'integrazione SignPath non sono ancora
implementate dalla build di revisione.

## Verificatore degli eseguibili

`installer/windows/verify-signatures.ps1` controlla quattro file distinti:
setup, launcher, helper WSL e disinstallatore. Richiede Windows PowerShell 5.1,
SignTool del Windows SDK e il subject completo del certificato atteso,
ricavato dal profilo approvato del servizio, non da un eseguibile non verificato.

```powershell
& .\installer\windows\verify-signatures.ps1 `
    -SetupPath $setupExe `
    -LauncherPath $launcherExe `
    -WslHelperPath $wslHelperExe `
    -UninstallerPath $uninstallerExe `
    -ExpectedPublisherSubject $approvedPublisherSubject `
    -SignToolPath $windowsSdkSignTool `
    -OutputPath $newEvidencePath
```

I percorsi devono identificare i file finali della stessa build; il file di
evidenza non deve esistere. Il verificatore richiede una firma Authenticode
valida secondo Windows, identità esatta, uso del certificato per code signing
e timestamp. Esegue anche `signtool verify /pa /all /tw`, rifiutando errori
e avvisi, e controlla che i file non cambino durante la verifica. È possibile
limitare ulteriormente i certificati mediante hash SHA-256 approvati.

Lo strumento non firma, non avvia gli EXE e non modifica gli archivi di fiducia.
Il rapporto riguarda solo i quattro eseguibili forniti: non certifica il
contenuto interno del setup, tutti gli script, i risultati scientifici o
l'esito di un antivirus. La pipeline dovrà verificare che i componenti
controllati siano quelli effettivamente incorporati. I test del verificatore
simulano gli esiti di fiducia; il loro successo non equivale a una firma reale.

## Gestione dei blocchi

**Smart App Control** controlla l'esecuzione e può bloccare codice sconosciuto
privo di firma riconosciuta. **SmartScreen** considera anche la reputazione
del file e del distributore; un programma firmato può mostrare un avviso
iniziale. Chrome distingue download pericolosi, sospetti e non verificati:
il testo preciso dell'avviso è necessario per individuare il caso.

Conservare build, checksum, nome del file, messaggio e nome dell'eventuale
rilevamento. Verificare il componente indicato e sottoporre un eventuale falso
positivo al produttore della protezione. Non assumere che un blocco sia un
falso positivo soltanto perché il programma proviene dal repository ufficiale.
La preparazione completata del runtime non dimostra che ogni componente
Windows abbia superato questi controlli.

## Riferimenti

- [Microsoft: Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/overview)
- [Microsoft: firma per Smart App Control](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control)
- [Microsoft: reputazione SmartScreen](https://learn.microsoft.com/en-us/windows/apps/package-and-deploy/smartscreen-reputation)
- [Chrome: blocchi dei download](https://support.google.com/chrome/answer/6261569)
- [SignPath Foundation: condizioni](https://signpath.org/terms.html)
- [SignPath: integrazione GitHub](https://docs.signpath.io/trusted-build-systems/github)

# Audit tecnico 0.8.20

Data: 9 novembre 2026. Base revisionata: `3cf998bfc49e06ca5025865ef1cd58326dab9e3b`,
contenente la release 0.8.14. L'audit comprende client Python, orchestrazione,
quattro moduli R e helper, confezionamento Windows/Linux/macOS, CI e pubblicazione.
La revisione del codice e i test mirati non costituiscono una prova su ogni
configurazione hardware o un'attestazione dell'assenza di difetti.

## Risultati e interventi

| Area | Riscontro | Intervento 0.8.20 |
| --- | --- | --- |
| Preparazione Windows | `activity-lock.ps1` compilava codice C# tramite `Add-Type -TypeDefinition` durante installazione e manutenzione. Questa scelta precede la 0.8.14; non identifica da sola il file bloccato da Windows. | Componente compilato durante la build, incluso nell'inventario e verificato prima del caricamento; nessuna compilazione temporanea di ripiego. |
| Identità dei componenti Windows | Il compilatore precedente produceva nuove identità dei binari anche ricompilando gli stessi sorgenti. | Compilazione deterministica con Roslyn e confronto SHA-256 tra compilazioni ripetute. Il controllo non certifica la riproducibilità dell'intero setup. |
| Fiducia Windows | Nessuna firma Authenticode NIPAT riconosciuta; i checksum e i test funzionali non soddisfano questo requisito. | Inventario delle firme sui byte distribuiti e raccolta diagnostica in sola lettura. La compatibilità Smart App Control resta non qualificata. |
| Test del setup | La verifica del payload con Python incorporato non eseguiva le operazioni Inno di installazione e rimozione. | Fixture Inno compilata con le operazioni reali e bootstrap simulato, con prove di aggiornamento e conservazione dei file. Non equivale all'esecuzione del setup distribuito su Windows 11. |
| Launcher macOS | Ctrl+C poteva terminare il client dal supervisore e rilasciare anticipatamente il lock, mentre il client gestiva l'annullamento. | Il supervisore attende l'uscita del client. Regressione con terminale, gruppo di processi e verifica indipendente del lock. |
| Aggiornamento Linux | Il processo finale di aggiornamento poteva terminare il client riavviato alla ricezione di Ctrl+C. | Il processo viene sostituito dal launcher; le interruzioni durante APT e preparazione restano invariate. |
| Input DNP | Una prima posizione uguale a 1 produceva un intervallo BED con inizio negativo nella finestra precedente al sito. | Rifiuto anticipato con messaggio specifico; il confine valido 2 rimane accettato e un pannello non valido non crea output. |
| Test degli input SNP | Un test configurava un backend inesistente e falliva prima di controllare i pannelli malformati. | Backend valido, verifica degli errori specifici e controllo positivo con pannello corretto. |
| Concorrenza scientifica | Il verificatore confrontava budget dichiarati e presenza di sovrapposizione, senza verificare il picco reale complessivo né tutti gli esiti delle attività. | Controlli sul numero osservato di processi, sui coordinatori e sull'esito di ogni attività; casi negativi per sovrallocazione e fallimenti. |
| Pubblicazione scientifica | I casi multibam estesi venivano eseguiti, ma il minimo obbligatorio del publisher non ne impediva l'omissione futura. | Requisiti espliciti dalla 0.8.20 per casi 2/3/6 BAM, seriale/automatico/manuale e ripetibilità, con i relativi helper. |
| Compilatore Inno | Il download verificava la firma del distributore senza fissare anche l'identità esatta dell'archivio. | SHA-256 e dimensione fissati dalla release ufficiale, oltre al controllo Authenticode già presente. |

## Controlli conservati

Gli input rimangono in sola lettura e ogni esecuzione mantiene una cartella
distinta. Il runner usa argomenti separati per i processi e verifica la
proprietà e l'identità immutabile del container prima della pulizia.
Aggiornamenti e manifest collegano versione, tag, commit, dimensioni e hash.
I controlli di percorsi, link, archivi e proprietà delle installazioni
continuano a proteggere i dati dell'utente durante aggiornamento e rimozione.

La revisione dei quattro moduli non ha individuato una regressione scientifica
dimostrata che richiedesse modifiche alle formule. La coda DNP mantiene un
budget comune a tutti i campioni e conserva l'ordine della ricomposizione.
I sorgenti R e il riferimento congelato 0.8.5 non vengono modificati dalla
0.8.20. Il confronto differenziale viene comunque rieseguito sull'immagine
esatta confezionata, con tabelle, valori non arrotondati e rendering PDF.

La CI conserva azioni fissate a commit, permessi limitati, controllo degli
esiti obbligatori e build esplicite. La pubblicazione continua a verificare
la stessa build in due passaggi, senza ricompilazione e senza sovrascrivere
release pubblicate. Il monitoraggio delle vulnerabilità resta separato:
un'associazione componente/CVE non dimostra sfruttabilità, e il superamento
dei test non equivale a un esito pulito di tale monitoraggio.

## Blocco di Smart App Control

Il confronto tra la candidata `e04ff883fc6417748174d2a7c3b49cadad989308`
e il commit pubblicato `b3ee5598d86e75884ead424e6c2ad4cbd137d2a1` non mostra
modifiche ai file Windows dell'installatore, agli entrypoint o al workflow
di costruzione. Il riuso del numero 0.8.14 riguarda la rilevazione degli
aggiornamenti, che confronta versioni; non prova la causa di un rifiuto
di Smart App Control. Una ricompilazione produce comunque nuovi byte del
setup, che non ereditano automaticamente la reputazione di un altro file.

Microsoft descrive Smart App Control come un controllo basato sulla valutazione
di sicurezza e sulla firma attendibile dei componenti. Un file privo di firma
riconosciuta può essere bloccato quando la valutazione non ne consente
l'esecuzione. Occorre identificare il file concreto nei registri Code Integrity;
il nome dell'applicazione mostrato dal messaggio può non bastare.

La DLL precompilata rende il componente identificabile e firmabile durante
la build, ma **non risolve da sola la fiducia del distributore**. Occorrono
un'identità di firma riconosciuta, la firma dei componenti pertinenti
(inclusi script, installer e uninstaller) e la verifica su Windows con Smart
App Control attivo. Il repository non configura attualmente tale identità.
Non vengono introdotti certificati autofirmati, esclusioni o modifiche alle
policy del dispositivo.

Riferimenti Microsoft consultati il 9 novembre 2026:

- [Funzionamento di Smart App Control](https://support.microsoft.com/it-it/windows/security/threat-malware-protection/smart-app-control-frequently-asked-questions).
- [Firma delle applicazioni](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/code-signing-for-smart-app-control).
- [Verifica dei componenti e registri degli eventi](https://learn.microsoft.com/en-us/windows/apps/develop/smart-app-control/test-your-app-with-smart-app-control).

## Ambito delle evidenze

| Evidenza | Cosa dimostra | Cosa non dimostra |
| --- | --- | --- |
| Test Python e PowerShell | Contratti, errori, proprietà dei processi e operazioni simulate o locali esercitate. | Ogni combinazione di input o policy del computer finale. |
| Fixture Inno su Server 2022 | Operazioni di confezionamento/installazione esercitate con i componenti indicati. | Installazione del setup finale su Windows 10/11, WSL reale o accettazione Smart App Control. |
| Rapporto Authenticode | Stato osservato delle firme e hash dei componenti elencati. | Reputazione cloud futura, assenza di malware o esecuzione consentita da ogni policy. |
| Regressione R nell'immagine esatta | Equivalenza rispetto alla 0.8.5 per i casi coperti e rispetto dei budget osservati. | Validazione biologica generale o accelerazione su BAM reali grandi. |
| Pacchetti Mac nativi | Contenuto, architettura e verifiche native previste. | Preparazione Lima sui dispositivi finali o autorizzazione Gatekeeper. |

I rapporti della build e il record di accettazione della release conservano
commit, immagini, checksum, esiti e scenari non eseguiti. Le 42 esecuzioni
storiche della candidata 0.8.14 restano evidenze di quella candidata;
non vengono attribuite alla 0.8.20. Gli input BAM/FASTA reali non sono
disponibili per una nuova misura end-to-end in questo ambiente.

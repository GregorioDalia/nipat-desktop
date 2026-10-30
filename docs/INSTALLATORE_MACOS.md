# Installatore macOS

**NIPAT Experimental08 0.8.0a1** è un pacchetto sperimentale per macOS 14 o
successivo, disponibile per Intel e Apple Silicon. Mantiene menu CLI,
workflow e codici R. L'installatore e il trasporto Lima devono essere
collaudati sui due tipi di Mac: il confezionamento riuscito in CI non
costituisce una qualificazione desktop.

## Requisiti e pacchetti

| Mac | Pacchetto | Esecuzione scientifica |
| --- | --- | --- |
| Intel x86_64 | `NIPAT-Experimental-0.8.0a1-macos-x86_64.pkg` | Guest Lima AMD64 e container Linux AMD64. |
| Apple Silicon arm64 | `NIPAT-Experimental-0.8.0a1-macos-arm64.pkg` | Guest Lima ARM64 e container Linux AMD64 tramite Rosetta. |

Python e Lima nativi per l'host sono inclusi; Homebrew, R, samtools e Docker
Desktop non sono prerequisiti. Servono spazio per applicazione, immagine,
disco della VM, input e risultati e una connessione Internet al primo avvio
per la preparazione del guest e del motore. Rosetta è necessaria alla modalità
AMD64 su Apple Silicon. La virtualizzazione deve essere disponibile.

Il pacchetto non dispone di firma Developer ID né di notarizzazione Apple.
Gatekeeper o le policy amministrative possono impedire installazione e avvio.
Il setup non disattiva le protezioni. In presenza di un blocco, conservare
messaggio, componente indicato e identità del pacchetto per la diagnosi.
L'assenza di una firma riconosciuta impedisce di garantire un'esperienza senza
intervento su ogni dispositivo del team.

## Installazione e primo avvio

1. Scaricare il `.pkg` della propria architettura dalla build sperimentale
   o dalla pre-release dedicata. Controllare versione e checksum associati.
2. Aprirlo con doppio clic e completare la procedura di Installer.
3. Aprire **NIPAT Experimental08** da Applicazioni. Si apre il Terminale:
   mantenere la finestra aperta durante la preparazione iniziale.
4. Attendere la creazione dell'ambiente Lima, l'importazione verificata
   dell'immagine e il controllo dei contratti del motore. Un errore interrompe
   la preparazione; non viene avviata un'analisi con stato incompleto.
5. Quando compare il menu, scegliere l'analisi o il workflow automatico.

Gli avvii successivi usano lo stesso collegamento e lo stesso ambiente
verificato. Dopo la preparazione i calcoli sono locali; non richiedono
una connessione per scaricare componenti scientifici. Il singolo container
di analisi ha la rete disabilitata.

NIPAT Experimental08 ha un'identità distinta dalla distribuzione stabile.
Non adotta una VM Lima esistente dell'utente e non modifica configurazioni
Docker Desktop o altre VM.

## Percorsi e accesso ai file

| Risorsa | Percorso |
| --- | --- |
| Applicazione | `/Applications/NIPAT Experimental08.app` |
| Launcher CLI | `/Applications/NIPAT Experimental08.app/Contents/Resources/NIPAT.command` |
| Area dell'utente | `~/Library/Application Support/NIPAT-Experimental08` |
| Dati e risultati predefiniti | Sottocartelle `data` e `runs` dell'area utente. |
| Preferenze | `preferences.json` nell'area utente. |
| Stato e log runtime | `.runtime/macos/runtime.json` e `.runtime/macos/setup.log` nell'area utente. |
| Lima home | `~/.nipat08/lima` |
| VM dedicata | `nipat08` |

La cartella Lima ha un percorso breve per rispettare i limiti dei socket
Unix. La configurazione e il registro di proprietà associano la VM a questa
installazione; il solo nome non autorizza la rimozione di una VM estranea.

La VM espone la home dell'utente, `/Volumes`, `/private/tmp` e la directory
temporanea dell'account in lettura/scrittura. La cartella applicativa è
esposta in sola lettura quando esterna alla home. Questo è l'accesso della
VM: il **container di ogni analisi** riceve soltanto gli input selezionati
in sola lettura e la directory del relativo run in lettura/scrittura.
I permessi macOS, incluse le autorizzazioni per cartelle protette, continuano
ad applicarsi. Non è garantito accesso indiscriminato a tutti i dischi.

Gli input possono contenere spazi nei percorsi. I percorsi relativi partono
dalla directory corrente indicata dal menu. Le opzioni `--data-dir` e
`--runs-dir` selezionano le destinazioni; **Configura** conserva le preferenze
del menu. La verifica dei mount può rifiutare un percorso non esposto nella VM.

Per radici aggiuntive, `--runtime prepare --mount <percorso>` le dichiara
alla prima preparazione. Modificare i mount di una VM già creata richiede
una ricreazione esplicita del solo runtime: non avviene automaticamente durante
un'analisi e non trasferisce dati o risultati. Conservare le evidenze di una
prova prima di ricreare il suo ambiente.

## CLI e diagnostica

Il launcher accetta i comandi NIPAT con gli stessi argomenti scientifici
delle altre piattaforme. Ad esempio:

```bash
"/Applications/NIPAT Experimental08.app/Contents/Resources/NIPAT.command" doctor --runtime
"/Applications/NIPAT Experimental08.app/Contents/Resources/NIPAT.command" self-test
```

La preparazione iniziale controlla archivio e contratti del motore; non
esegue automaticamente gli autotest numerici. Il comando `self-test` li
esegue esplicitamente. **8 — Verifica ambiente** dal menu offre la diagnostica.

I comandi di gestione del runtime sono separati dalle analisi:

```bash
"/Applications/NIPAT Experimental08.app/Contents/Resources/NIPAT.command" --runtime status
"/Applications/NIPAT Experimental08.app/Contents/Resources/NIPAT.command" --runtime ensure
"/Applications/NIPAT Experimental08.app/Contents/Resources/NIPAT.command" --runtime stop
```

`status` consulta lo stato; `ensure` rende disponibile il runtime preparato;
`stop` arresta la VM. Non arrestare la VM durante un'analisi: annullare prima
il calcolo dal menu con Ctrl+C e attendere la conclusione della procedura.
Per una preparazione fallita conservare `setup.log`, il messaggio completo,
versione e architettura macOS e commit del pacchetto. Dopo aver risolto la
causa, riaprire l'applicazione o utilizzare `--runtime prepare`.

## Aggiornamento e rimozione

Il canale sperimentale non usa gli aggiornamenti automatici della stabile.
Per una nuova build scaricare il nuovo `.pkg` sperimentale, chiudere NIPAT
e installarlo. I dati e i risultati dell'account restano separati dal bundle
applicativo. Non installare un pacchetto per l'architettura diversa da quella
host per tentare di cambiare la modalità scientifica.

La rimozione dell'applicazione non elimina automaticamente VM, dati e
risultati. Per rimuovere **soltanto il runtime Lima gestito da NIPAT**, dopo
aver chiuso le analisi, usare prima di rimuovere l'applicazione:

```bash
"/Applications/NIPAT Experimental08.app/Contents/Resources/NIPAT.command" --runtime remove-runtime
```

Il comando verifica la proprietà dell'ambiente e rimuove la VM dedicata;
conserva dati e risultati. Una nuova preparazione dovrà ricreare la VM e
importare l'immagine. Non rimuovere manualmente altre istanze Lima o cartelle
con contenuto non identificato come appartenente all'esperimento.

## Ambito delle verifiche

La CI ospitata controlla client, contratti e confezionamento Intel/Apple Silicon.
Le prove di VM Lima reali sono distinte e richiedono runner con virtualizzazione
appropriata. L'installazione dal Finder, le policy di sicurezza, i permessi
sui file e la ripresa su un Mac reale vanno registrati separatamente nella
[scheda di validazione](VALIDAZIONE.md). La medesima versione R e gli stessi
input attesi non sostituiscono il confronto numerico sul trasporto Rosetta.

La [guida per l'utilizzo](GUIDA_UTILIZZO.md) descrive gli input e i workflow;
le [note della versione](RELEASE_0.8.0a1.md) delimitano la sperimentazione.

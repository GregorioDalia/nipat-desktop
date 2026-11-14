# Risorse, memoria e arresti

NIPAT distingue tre livelli. Un valore indicato come **non disponibile** non
viene interpretato come zero o come risorsa illimitata.

| Livello | Significato |
| --- | --- |
| Computer | RAM fisica e CPU del sistema che esegue NIPAT, condivise con le altre applicazioni. |
| Ambiente scientifico | RAM e CPU visibili in WSL2 o Lima. Su Ubuntu nativo non esiste una VM NIPAT. |
| Analisi | Limiti imposti al container del run, entro le risorse disponibili nell'ambiente. |

Se Lima dispone di 4 GiB, impostare un limite del container di 8 GiB non
porta la VM a 8 GiB. Analogamente, un computer con 16 GiB non rende
necessariamente disponibili tutti i 16 GiB a WSL. Il sistema ospite e il
motore Docker consumano parte della memoria dell'ambiente.

## Consultare e scegliere i valori

Aprire **Configura → Risorse, prestazioni e provenienza**. La schermata mostra
valori configurati ed effettivi, quando rilevabili. I suggerimenti si basano
sulle risorse del dispositivo e lasciano spazio al sistema operativo; non
stimano la memoria necessaria a uno specifico BAM o pannello.

La configurazione salvata, le risorse effettive attuali e i suggerimenti
sono valori distinti. Un ambiente può usare limiti automatici senza avere
valori espliciti nel file di configurazione. Nel modulo di modifica, **Invio
mantiene il valore corrente**, compresa l'impostazione automatica; non
applica il suggerimento. Per adottarlo esplicitamente usare `:suggerito`.
Se entrambi i campi restano invariati, non vengono salvati limiti né eseguiti
riavvii. Per salvare nuovi limiti espliciti occorre indicare sia RAM sia CPU;
un campo automatico non viene sostituito con il valore effettivo rilevato.

I limiti dell'analisi sono facoltativi. **Nessun limite NIPAT** significa che
NIPAT non impone un ulteriore tetto: restano attivi i limiti della VM, del
sistema e delle altre applicazioni. Un limite troppo basso può causare
l'arresto del calcolo. Non assegnare tutta la RAM fisica all'ambiente virtuale.

La quota CPU del container limita il tempo di processore disponibile, non
modifica il numero di worker scelto internamente dallo script R. La modalità
seriale/parallela di DNPcall è una scelta separata. Elaborare più campioni in
parallelo può aumentare il consumo di memoria; il formato e la copertura dei
dati contano oltre alla dimensione del BAM su disco.

## macOS e Lima

La VM è dedicata a NIPAT. Per cambiare RAM o CPU, inserire i valori desiderati,
controllare l'anteprima e confermare. NIPAT conserva una copia della configurazione
precedente. Il riavvio richiesto per rendere effettiva una modifica viene
segnalato separatamente; l'applicazione non interrompe un'analisi per applicarlo.

Se la VM Lima è attiva, la modifica richiede anche la conferma del suo
arresto e riavvio; rinviando questa conferma non viene salvata.
Non è necessario eliminare dati, risultati o ricreare la VM per cambiare
le risorse. Il controllo di proprietà impedisce di configurare VM estranee.

## Windows e WSL2

RAM e CPU in `.wslconfig` riguardano **tutte le distribuzioni WSL2 dell'account**,
non soltanto quella NIPAT. Le impostazioni del container riguardano invece
il singolo run. La gestione guidata distingue queste due operazioni.

Prima di una modifica globale NIPAT mostra configurazione corrente, proposta
e impatto. Il salvataggio conserva le altre impostazioni e crea un backup.
Per applicare immediatamente i valori può essere necessario riavviare WSL:
l'applicazione richiede una conferma separata e segnala le distribuzioni attive.
Un'analisi NIPAT in corso impedisce la riconfigurazione; una modifica concorrente
della configurazione richiede una nuova anteprima.

È possibile salvare e rimandare il riavvio. La schermata continua a distinguere
i valori salvati da quelli effettivi. Chiudere normalmente le altre attività
WSL prima di autorizzare un riavvio globale. Il comportamento di `.wslconfig`
è descritto nella [documentazione Microsoft](https://learn.microsoft.com/it-it/windows/wsl/wsl-config).

## Ubuntu nativo

NIPAT usa Docker Engine locale e non crea una VM. Si configurano i limiti del
container; l'applicazione non modifica la RAM del sistema, lo swap globale
o i limiti degli altri servizi. Permessi Docker, eventuali limiti del servizio
e disponibilità del sistema possono restringere le risorse utilizzabili.

## Errori di memoria e codice 137

Un codice 137 è compatibile con una terminazione mediante `SIGKILL`.
Non dimostra da solo un esaurimento della memoria. NIPAT conserva, quando
il motore lo rende disponibile, lo stato del container prima della pulizia,
compreso l'indicatore `OOMKilled` e i limiti applicati. Una diagnosi non
acquisibile viene dichiarata, senza essere trasformata in un esito positivo.

In caso di errore:

1. Consultare il messaggio e il resoconto del run, poi `execution.log`.
2. Verificare se il limite è quello del container o dell'ambiente virtuale.
3. Registrare sistema, RAM fisica, valori impostati, numero di campioni e
   modalità seriale/parallela.
4. Modificare la configurazione necessaria e avviare una nuova esecuzione.

Un run fallito non viene riutilizzato o sovrascritto. Le prove successive
conservano la propria configurazione e il proprio esito. Non viene eseguito
un tentativo automatico con più memoria, perché cambierebbe le condizioni
dell'analisi senza una scelta esplicita.

## Comandi e backup

```sh
nipat resources inspect
nipat resources inspect --json
nipat resources configure --memory-mib 8192 --vm-cpus 4
```

Il comando `configure` mostra soltanto l'anteprima. `--apply --yes` conferma
il salvataggio; `--restart` autorizza separatamente il riavvio necessario.
Le opzioni sono esplicite anche negli script automatizzati.

Il codice di uscita `0` conferma l'operazione richiesta. Con `--apply --yes`
senza `--restart`, lo stato `saved-restart-required` conferma il salvataggio
per un riavvio successivo. Aggiungendo `--restart`, il codice è `0` soltanto
con stato `applied`, dopo la verifica delle risorse effettive. Un riavvio
non completato o valori da verificare restituiscono `2`; il rapporto,
anche con `--json`, conserva stato, avvisi e percorso del backup.

Il backup indicato dall'applicazione è un file JSON che conserva percorso,
hash e contenuto precedente codificato in base64, compresa l'eventuale assenza
del file. Conservare il backup per diagnosi e recupero manuale della
configurazione. Il JSON del backup è un record, mentre WSL e Lima leggono
il contenuto della configurazione nel proprio formato.

## Velocità di DNPcall

La dimensione del BAM compresso non determina da sola durata o RAM necessarie.
Contano letture, copertura, pannello, disco, processore e ambiente di esecuzione.
Se tutti i BAM hanno un indice utilizzabile, i dizionari sono compatibili e
i cromosomi sono separabili, DNPcall può preparare il pileup per cromosoma.
Negli altri casi usa il percorso non partizionato. Il calcolo R distribuisce
i blocchi di uno o più campioni entro un budget comune, che vale anche per
la preparazione del pileup.

I tempi dipendono anche da lettura e I/O. Confrontare richieste identiche e
leggere strategia, tempi e worker osservati in `work/dnp-pileup.json` e
`work/dnp-blocks.json`. La [guida alle prestazioni](PERFORMANCE.md) descrive
come interpretarli.

Gli export con etichette originali aggiungono una seconda resa dei grafici.
Il tempo totale del run comprende questo costo; i tempi stampati dal solo R
non comprendono necessariamente tutti i passaggi, come i grafici conclusivi.
Per confrontare configurazioni usare gli stessi input e parametri, registrare
risorse effettive e distinguere prima esecuzione e ripetizioni. Il
[benchmark dei workflow](ESECUZIONI.md#misure-delle-prestazioni) conserva
le prove senza promettere prestazioni su altri computer.

# Validazione tecnica e di dominio

Questa scheda registra separatamente installazione, esecuzione e concordanza
scientifica di **NIPAT Experimental08 0.8.0a1**. Identificare sempre versione,
commit, pacchetto e piattaforma realmente provati. Gli esiti della stabile
0.7.2 non attestano automaticamente il comportamento dell'esperimento.

La prova può procedere per incrementi: registrare ciò che è stato eseguito
e ciò che rimane da verificare, senza considerare un caso non eseguito come
superato. Gli autotest controllano soltanto i casi inclusi; il giudizio
scientifico su dati rappresentativi richiede una valutazione distinta.
Il [protocollo dei pacchetti](ACCETTAZIONE_INSTALLATORI.md) separa l'esperimento
dalla pubblicazione stabile e dalla qualificazione desktop completa.

## Ambiente e preparazione

Compilare una scheda per ciascuna combinazione di sistema e pacchetto:
Windows 10 22H2 x64 build 19045, Windows 11 x64, macOS 14 o successivo Intel,
macOS 14 o successivo Apple Silicon. Windows usa WSL2; macOS usa Lima, con
immagine scientifica AMD64 e Rosetta su Apple Silicon. Il checkout Linux
con Docker Engine locale è una prova da sorgenti, distinta dagli installatori.

| Campo | Valore da registrare |
| --- | --- |
| Sistema operativo, versione e architettura | |
| Versione NIPAT e commit o identificativo del pacchetto | |
| Origine del pacchetto e checksum, se disponibile | |
| Windows: versione e disponibilità iniziale di WSL2 | |
| macOS: modello, architettura, versione Lima e disponibilità Rosetta | |
| Linux da sorgenti: versioni Docker Engine e Compose, origine e accesso utente | |
| Prima installazione o aggiornamento dello stesso profilo sperimentale | |
| Cartelle dati e risultati configurate | |
| Esito del setup, eventuali autorizzazioni o riavvii | |
| Esito di `doctor --runtime` | |
| Esito finale di `self-test` | |
| Apertura e interazione con il menu | |
| Isolamento: nessuna proposta di migrazione al/dal canale stabile | |
| Preferenze salvate in Configura e valori effettivi nel riepilogo dell'analisi | |
| Modalità checksum degli input e limiti CPU, memoria e processi | |

Nel pacchetto Windows verificare l'avvio con doppio clic di `NIPAT-Setup.exe`,
il completamento con `NIPAT: ready` e l'apertura dell'icona **NIPAT Experimental08**.
Annotare eventuali passaggi manuali non previsti. Conservare `setup.log` e
`state.json` nella sottocartella `.runtime\installer` dell'applicazione
selezionata nel setup.
L'attivazione iniziale di WSL, la ripresa dopo riavvio e un aggiornamento
costituiscono prove distinte dall'installazione su WSL già funzionante.

Sul Mac verificare l'apertura del `.pkg` della propria architettura, l'avvio
da Applicazioni, la preparazione Lima e l'apertura del menu nel Terminale.
Conservare `runtime.json` e `setup.log` in
`~/Library/Application Support/NIPAT-Experimental08/.runtime/macos`.
Annotare richieste di autorizzazione e limitazioni di Gatekeeper o dei percorsi.
Su Apple Silicon registrare esplicitamente il funzionamento AMD64 tramite
Rosetta: la sola riuscita su Intel non copre questa configurazione.

Per ogni pacchetto provare progressivamente riapertura, reinstallazione,
ripresa di una preparazione interrotta e conservazione dei dati. Un aggiornamento
fra versioni differenti è distinto da una reinstallazione della stessa build.
Non modificare installazioni stabili o VM estranee; per la rimozione del runtime
Mac usare il comando documentato che ne verifica la proprietà.

I controlli automatici del repository sono descritti in
[CI_CD.md](CI_CD.md). Una build riuscita non dimostra il completamento
dell'installazione sul sistema dell'utilizzatore: registrare l'esito osservato
sul pacchetto effettivamente provato.

## Prima sequenza operativa

1. Aprire NIPAT, verificare la versione e scegliere una cartella risultati
   dedicata alla prova.
2. Eseguire **8 — Verifica ambiente** dal menu principale.
3. Selezionare **DNPcall** e utilizzare BAM, riferimento indicizzato e pannello
   di un caso con risultati attesi disponibili. Confermare il riepilogo.
4. Verificare stato finale, numero di campioni, corrispondenza degli alias,
   siti analizzati, conteggi e genotipi.
5. Eseguire **Contamination** sulle tabelle individuali compatibili del run,
   utilizzando il pannello appropriato. Confrontare riepilogo e risultati per sito.
6. Eseguire **SNPcall** e **CPI** con casi e riferimenti adeguati ai rispettivi
   workflow, secondo la [guida per l'utilizzo](GUIDA_UTILIZZO.md).

Le conferme di avvio eseguono calcoli reali. Per una prova della sola
compilazione utilizzare esplicitamente `--dry-run`; tale prova deve essere
registrata come simulazione e non come analisi riuscita.

### Workflow automatici

La [guida per l'utilizzo](GUIDA_UTILIZZO.md#risultati-e-analisi-in-sequenza) descrive
configurazione e avvio dal pacchetto installato. Per ogni composizione
selezionata registrare sia il risultato complessivo sia quello dei singoli passaggi:

- per DNPcall → Contamination e/o CPI, confrontare le tabelle DNP prodotte
  con quelle usate dalle analisi successive; CPI deve mantenere i ruoli e gli
  ID delle coppie dichiarate, anche quando condividono un campione;
- quando si aggiunge SNPcall, verificare il pannello scelto, l'associazione
  di ciascuna tabella al BAM originale e la separazione dai risultati DNP;
- per SNPcall su più campioni, confrontare BAM e pileup dello stesso caso,
  verificando anche campioni con lo stesso nome di file in cartelle diverse;
- confrontare la composizione con le analisi singole a parità di input e
  parametri, e con risultati indipendenti quando disponibili;
- provare un input non valido e un'interruzione: i passaggi rimanenti non
  devono partire, le evidenze già prodotte devono restare disponibili e la
  ripetizione deve usare una nuova cartella.

Il piano completo richiede BAM cfDNA materni e paterni appropriati, frequenze
di popolazione e pannelli compatibili. I casi per cui mancano questi dati
vanno registrati come non eseguiti. La stima Contamination non rappresenta
un filtro automatico per CPI; SNPcall non produce tabelle di ingresso per
Contamination o CPI.

## Scheda per ciascuna analisi

| Campo | Valore da registrare |
| --- | --- |
| Identificativo del caso, privo di dati identificativi personali | |
| Versione NIPAT, identificativo dell'immagine e nome del run | |
| Workflow e modalità di input | |
| Provenienza degli input; pannello e riferimento genomico | |
| Parametri configurati | |
| Workflow automatico: ID dei passaggi, campioni e coppie dichiarate | |
| Percorsi e destinazione dei risultati | |
| Risultato atteso e fonte del riferimento | |
| Risultato osservato: conteggi, stime e grafici pertinenti | |
| Criterio di confronto e tolleranza numerica applicata | |
| Esito tecnico: riuscito, fallito o interrotto | |
| Esito scientifico: concordante, discordante o non valutabile | |
| Difficoltà di utilizzo o messaggi poco chiari | |
| Materiali condivisibili per riprodurre la prova | |

Preferire un riferimento indipendente quando disponibile. Un confronto
con un'altra esecuzione dello stesso programma verifica la ripetibilità,
ma non dimostra da solo l'accuratezza del metodo.

## Copertura dei casi

La scelta dei dati e dei criteri di accettazione richiede competenze di dominio.
Documentare almeno le condizioni rilevanti per l'uso previsto:

| Area | Casi utili |
| --- | --- |
| DNPcall | Uno e più BAM; lista e argomenti ripetuti; modalità seriale e parallela; corrispondenza tra alias, conteggi e genotipi. |
| SNPcall | BAM e pileup compatibile dello stesso caso; conteggi REF, ALT e altre letture; formato QNAME richiesto. |
| Contamination | Singoli file e cartella con gli stessi input; presenza e assenza di `ratio_REF_ALT`; nessun sito informativo. |
| CPI | Coppie appropriate; prefissi configurati; ALL, pannello singolo e più cutoff; nessun sito informativo. |
| Workflow automatici | Composizioni DNPcall/Contamination/CPI; campioni condivisi fra coppie; SNPcall indipendente e batch; corrispondenza fra piano, campioni, output e analisi separate; passaggi bloccati dopo errore o interruzione. |
| Robustezza | Percorsi con spazi, input fuori dal progetto, risultati in una destinazione scelta; file mancanti, codifica errata, intestazioni duplicate, conteggi non validi e nomi in conflitto. |
| Utilizzo | Salvataggio e ripristino delle preferenze; persistenza dopo la riapertura; correzione per la singola analisi; campioni, coppie e run sempre selezionati esplicitamente; annullamento, riepilogo, apertura dei risultati e recupero dopo errore. |

Verificare che un cambiamento in **Configura** venga riproposto nel menu dopo
la riapertura e non alteri un comando CLI diretto. Ripetere un caso con gli
stessi parametri espliciti, confrontando i valori effettivi in `run.json`.
Provare l'annullamento senza salvataggio, il ripristino e un riferimento
salvato non più disponibile. Dati e risultati devono restare invariati.

Per modalità equivalenti, verificare gli stessi risultati usando lo stesso
insieme di dati. Nei confronti numerici stabilire prima quali colonne,
ordinamenti e tolleranze considerare; non usare il solo confronto dei nomi
o delle dimensioni dei file. I casi CPI con più cutoff devono mantenere
distinti i risultati delle etichette selezionate.

Per i pannelli SNP confrontare anche rappresentazioni equivalenti in maiuscolo
e minuscolo: la normalizzazione deve lasciare invariati i conteggi e il file
originale. Provare tabelle con conteggi negativi, loci duplicati e frequenze
non finite: devono essere rifiutate prima di R. Registrare separatamente gli
avvisi che mantengono i valori forniti, come frequenze zero o rapporti
incoerenti con i conteggi; il loro significato va valutato nel caso scientifico.

Provare Ctrl+C attraverso il collegamento installato, oltre che dalla CLI.
Dopo un fallimento, verificare che **Ultima esecuzione** mostri il run fallito
e i suoi log. La consultazione delle esecuzioni incomplete deve distinguere
runtime irraggiungibile, container assente e container ancora attivo senza
alterare i record storici.

Distinguere un errore del programma da un risultato scientifico inatteso.
Un valore `NA` in assenza di siti informativi può essere corretto.
Per DNPcall verificare anche gli output, poiché lo script R non propaga
esplicitamente tutti gli errori della propria chiamata interna a samtools.
Gli stati e i limiti dei record sono descritti in [ESECUZIONI.md](ESECUZIONI.md).

## Verifica dell'isolamento e degli aggiornamenti

Nel profilo sperimentale, **Verifica aggiornamenti** non deve proporre né
scaricare il pacchetto stabile. L'installazione 0.7.2, se presente, mantiene
configurazione, runtime, dati e risultati. Verificare la separazione dei
percorsi e il nome dell'applicazione prima di avviare le analisi.

Per provare una nuova build sperimentale, registrare versioni iniziale e
finale, checksum degli installatori e log. Chiudere le analisi prima di
installare. Controllare preferenze, percorsi e conservazione dei risultati,
quindi eseguire un caso noto. I record dei run devono identificare le versioni
con cui sono stati prodotti. Una reinstallazione della stessa build non
costituisce una prova di aggiornamento fra versioni differenti.

## Conservazione e segnalazioni

Conservare l'intero run, inclusi `run.json`, `execution.log` e `work`, insieme
ai risultati e agli input necessari alla riproduzione. Per file maggiori di
16 MiB, la modalità predefinita `auto` registra dimensione e data di modifica
senza calcolare l'hash. Usare `--input-hashes full` quando il protocollo richiede
checksum completi, registrando il costo delle letture aggiuntive; conservare
sempre gli input originali necessari alla riproduzione.

Una segnalazione utile riporta versione, piattaforma, sequenza di operazioni,
atteso, osservato e messaggio d'errore completo. Nomi e percorsi dei campioni
non sono anonimizzati automaticamente. Verificare gli allegati e usare un
canale appropriato al contenuto dei dati.

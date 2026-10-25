# NIPAT Desktop 0.6.0

NIPAT Desktop 0.6.0 offre quattro analisi scientifiche locali, un menu testuale
guidato, configurazione persistente e aggiornamenti dall'applicazione.
La pagina [Releases](https://github.com/GregorioDalia/nipat-desktop/releases)
identifica i pacchetti effettivamente pubblicati. Queste note descrivono le
funzionalità della versione e il suo ambito di distribuzione per ricerca
pre-1.0. La campagna di accettazione con le esperte di dominio è prevista
sulla 0.7; la 0.6 non attesta una validazione scientifica generale.

## Installazione

| Piattaforma | Pacchetto | Avvio |
| --- | --- | --- |
| Windows 11 x64 | `NIPAT-Setup.exe`, con Python portabile, ambiente WSL2 dedicato e immagine scientifica incorporata. | Doppio clic sul setup, poi sul collegamento **NIPAT Desktop**. |
| Ubuntu 24.04 LTS x86_64 | `nipat-desktop_0.6.0_amd64.deb`, con applicazione e stessa immagine scientifica. | Installazione con APT; collegamento **NIPAT Desktop** oppure comando `nipat`. |

NIPAT Desktop utilizza identità e percorsi propri. Su Windows il setup consente di scegliere applicazione,
ambiente WSL, cache, dati e risultati; aggiornamento e riparazione dello stesso
prodotto conservano le destinazioni e i file estranei ai componenti installati.

Su Windows WSL2 richiede virtualizzazione disponibile; la sua attivazione può
richiedere Internet, autorizzazione amministrativa e riavvio. Non servono
Docker Desktop, R, samtools o Python installati separatamente. Il pacchetto
Windows non dispone di una firma Authenticode NIPAT: l'esecuzione deve essere
verificata con le protezioni dei dispositivi destinatari.

Su Ubuntu APT installa Python 3.12, Docker Engine e Compose v2 se mancanti.
L'autorizzazione dell'account a usare il socket Docker è un'operazione
amministrativa distinta. NIPAT va eseguito come utente non root.

## Menu e configurazione

I quattro workflow sono **DNPcall**, **SNPcall**, **Contamination** e **CPI**.
Il menu presenta indicazioni nei campi, un riepilogo e una conferma esplicita
prima del calcolo: il solo Invio nel riepilogo annulla, mentre **1 — Avvia
analisi** esegue il workflow. Non è inclusa una GUI grafica.

- **Configura** conserva cartelle dati e risultati, modalità, riferimenti e
  parametri predefiniti dei workflow fra gli avvii.
- I valori proposti possono essere modificati per la singola analisi; campioni,
  coppie CPI e nome del run si scelgono ogni volta.
- **Guida e informazioni** e **Verifica ambiente** sono voci separate.
- Le preferenze del menu non modificano i comandi CLI diretti.

Le preferenze sono conservate in
`%LOCALAPPDATA%\NIPAT-Desktop\preferences.json` su Windows e in
`${XDG_CONFIG_HOME:-~/.config}/nipat-desktop/preferences.json` su Linux.
Lo spostamento di applicazione, ambiente WSL o cache richiede il setup.

## Aggiornamenti dall'applicazione

**9 — Verifica aggiornamenti** consulta le release pubblicate e approvate su
GitHub e permette di scaricare l'installatore completo con verifica di
integrità. Download e installazione richiedono conferme distinte; è possibile
annullare o rimandare. Il setup conserva percorsi, preferenze, dati e risultati.
Su Ubuntu l'installazione del `.deb` richiede autorizzazione amministrativa APT.

**Configura → Aggiornamenti** offre i canali `testing` e `stable`. Il primo,
predefinito, include pre-release e release stabili approvate; il secondo
considera soltanto le stabili. La verifica all'avvio è facoltativa e
inizialmente disattivata: mostra un avviso senza scaricare o installare.
Le analisi restano locali e l'installazione pronta è utilizzabile offline.

Il controllo degli aggiornamenti non sostituisce l'accettazione dei pacchetti
e non rende pubblica una build di revisione. Ogni run conserva la versione
dell'applicazione e l'identità del motore effettivamente utilizzati.

## Motore e risultati

Il motore scientifico è un'immagine autonoma con gli script R, samtools,
dipendenze e preparazione dei workflow. La versione 0.6 non riscrive gli
algoritmi scientifici R. I calcoli avvengono localmente; gli input sono montati
in sola lettura e ogni analisi usa una cartella distinta.

Ogni run conserva risultati in `output`, intermedi disponibili in `work`,
parametri e stato in `run.json`, messaggi in `execution.log`. Le analisi in
sequenza si compongono selezionando gli output compatibili come input del
workflow successivo. I risultati esistenti non vengono sovrascritti.

Gli autotest verificano i casi distribuiti. La decisione di pubblicazione
integra i controlli automatici con una prova manuale documentata di
installazione e funzionamento, indicando gli scenari desktop ancora da
verificare. Un eventuale riferimento a una build precedente richiede il
confronto dei sorgenti operativi e non equivale a una prova del nuovo EXE.
Le evidenze e i limiti sono conservati con la release; la valutazione di
dominio sarà svolta sulla 0.7 con input e risultati di riferimento appropriati.

## Documentazione

- [Guida per l'utilizzo](GUIDA_UTILIZZO.md)
- [Distribuzione e requisiti](DISTRIBUZIONE.md)
- [Risultati e registri](ESECUZIONI.md)
- [Accettazione degli installatori](ACCETTAZIONE_INSTALLATORI.md)
- [Validazione tecnica e di dominio](VALIDAZIONE.md)

Il codice originale NIPAT è distribuito con licenza
[GPL-3.0-or-later](../LICENSE). Le attribuzioni sono in
[THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md).

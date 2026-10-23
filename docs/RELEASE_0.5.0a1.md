# NIPAT 0.5.0a1 — Preview per la validazione

NIPAT 0.5.0a1 esegue DNPcall, SNPcall, Contamination e CPI attraverso un menu
testuale guidato e comandi riproducibili. Questa pre-release è destinata
alla verifica tecnica e alla valutazione di dominio. Non include una GUI
grafica e non costituisce una validazione scientifica per ogni scenario d’uso.

## Installatori

- **Windows 11 x64:** `NIPAT-Setup.exe`, con Python portabile, ambiente WSL2
  dedicato, Docker Engine gestito da NIPAT e immagine scientifica incorporata.
  Installazione e avvio avvengono tramite doppio clic. L’attivazione di WSL2
  richiede virtualizzazione disponibile e può richiedere Internet,
  autorizzazione amministrativa e riavvio.
- **Ubuntu 24.04 LTS x86_64:** `nipat-05-preview_0.5.0~a1_amd64.deb`, con
  applicazione e la stessa immagine scientifica del pacchetto Windows.
  APT installa Python 3.12, Docker Engine e Compose v2 se mancano.
  L’accesso dell’account a Docker richiede autorizzazione amministrativa
  distinta; NIPAT si esegue come utente non root.

Entrambi i pacchetti usano il nome **NIPAT 0.5 Preview** e percorsi dedicati.
L’immagine scientifica contiene script R, samtools, dipendenze e preparazione
degli input. I calcoli avvengono sul computer e usano l’immagine verificata
localmente, senza scaricarne una sostitutiva durante le analisi.

## Funzionamento

Il menu raccoglie input e parametri, presenta un riepilogo e avvia il calcolo
soltanto dopo conferma. Sono disponibili la diagnostica del runtime e gli
autotest dei casi distribuiti. Ogni analisi conserva risultati, intermedi,
metadati e log in una nuova cartella; gli input sono letti senza modificarli.
Le analisi possono essere concatenate selezionando output compatibili come
input del workflow successivo.

## Requisiti e limiti

Su Windows gli input devono trovarsi su dischi locali fissi; unità di rete,
condivisioni UNC e unità rimovibili non sono supportate dal backend WSL.
Docker Desktop non è richiesto. Su Ubuntu è supportato il daemon Docker
locale di sistema, senza rootless o rimappatura degli UID.

La rimozione dell’applicazione conserva dati, risultati e runtime previsti
dal pacchetto. La reinstallazione della stessa build non dimostra un
aggiornamento fra versioni differenti. Gli autotest verificano i casi
inclusi: i dati e i parametri dello specifico impiego richiedono valutazione
di dominio.

Consultare la [guida per l’utilizzo](https://github.com/GregorioDalia/nipat-desktop/blob/v0.5.0a1/docs/GUIDA_UTILIZZO.md), i requisiti di
[distribuzione](https://github.com/GregorioDalia/nipat-desktop/blob/v0.5.0a1/docs/DISTRIBUZIONE.md) e la [scheda di validazione](https://github.com/GregorioDalia/nipat-desktop/blob/v0.5.0a1/docs/VALIDAZIONE.md).
Il codice originale NIPAT è distribuito con licenza
[GPL-3.0-or-later](https://github.com/GregorioDalia/nipat-desktop/blob/v0.5.0a1/LICENSE); le attribuzioni sono in
[THIRD_PARTY_NOTICES.md](https://github.com/GregorioDalia/nipat-desktop/blob/v0.5.0a1/THIRD_PARTY_NOTICES.md).

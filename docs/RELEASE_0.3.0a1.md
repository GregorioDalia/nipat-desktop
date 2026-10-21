# NIPAT CLI 0.3.0a1 — prove di dominio su Windows

Pre-release per Windows 11 x64 con **WSL2 già funzionante**. La CLI comprende
DNPcall, SNPcall, Contamination e CPI; la GUI non è ancora inclusa.

## Avvio

1. Scaricare **NIPAT-Setup.exe** dagli asset della release GitHub.
2. Avviarlo con doppio clic dal proprio account, senza “Esegui come amministratore”.
3. Attendere download, configurazione e autotest, fino a **`NIPAT: ready`**.
4. Aprire **NIPAT** dal menu Start e scegliere analisi, input e cartella risultati.

Il setup prepara Python portabile e un ambiente WSL dedicato con Docker Engine,
R, samtools e i pacchetti necessari. Non serve installare Docker Desktop,
Python o R separatamente. Il primo setup richiede Internet; le analisi
successive vengono eseguite sul computer.

- [Guida per l'utilizzo](GUIDA_UTILIZZO.md): installazione, input, risultati e sequenze di analisi.
- [Sunto del progetto](../SUNTO.md): integrazioni e funzionamento.
- [Scheda di validazione](VALIDAZIONE.md): registrazione delle prove e degli esiti.

## Verifiche e limiti

I controlli automatici comprendono test Python e PowerShell, esempio SNPcall,
casi sintetici CPI/Contamination, modalità di input esterne e caricamento/
esecuzione/ricaricamento dell'immagine nel motore distribuito.
Sul PC di sviluppo, un precedente candidato corretto localmente ha completato
setup e autotest, riavviato il proprio motore e riprodotto 11 siti e 11 colonne
confrontate di un BAM reale. La cronologia e il perimetro esatto sono in
[INSTALLATORE_WINDOWS.md](INSTALLATORE_WINDOWS.md).

Restano aperte la prima installazione del nuovo EXE su un altro PC e la
validazione scientifica su casi indipendenti. L'attivazione iniziale di WSL e
la ripresa dopo riavvio Windows non sono state verificate: per questa consegna
si assume WSL2 funzionante. Gli input devono trovarsi su dischi locali fissi;
condivisioni UNC e unità di rete non sono supportate dal backend WSL.

L'EXE non è firmato con un certificato di pubblicazione; Windows può mostrare
l'avviso per autore non riconosciuto. Un ambiente NIPAT sperimentale esistente
con rootfs diverso non viene migrato automaticamente. In caso di errore,
conservare `setup.log` e `state.json` secondo la guida, senza eliminare
distribuzioni o risultati per forzare l'installazione.

Il tag, il commit sorgente e gli asset della release devono corrispondere al
manifest incorporato nell'EXE. `SHA256SUMS` permette di verificare i download.
I precedenti tag `v0.2.0a1` e `v0.2.0a2` restano invariati.

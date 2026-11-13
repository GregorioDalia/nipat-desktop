# NIPAT Desktop 0.8.60

La 0.8.60 consolida i cinque moduli e i workflow della 0.8.50, corregge
la preparazione del setup Windows e include il collaudo sintetico da eseguire
sull'installazione locale. I modelli scientifici, i parametri e le formule
rimangono quelli descritti nelle [note della 0.8.50](RELEASE_0.8.50.md).

## Setup Windows

Il verificatore CPIN risolve esplicitamente il proprio helper locale anche
con il Python incorporato nell'installer. Questo corregge l'errore che,
nella 0.8.50, poteva lasciare il setup con la preparazione incompleta.
La build esegue i cinque verificatori distribuiti con il vero interprete
incorporato, prima della pubblicazione. Anche il nuovo driver di collaudo
viene verificato nello stesso ambiente Python.

L'autotest di preparazione registra stdout, stderr e codice di uscita nei
log del setup. Se un prerequisito non è disponibile, il setup conserva uno
stato riprendibile e non dichiara pronta un'installazione non verificata.
La 0.8.60 contiene già la correzione: non occorre il riparatore della 0.8.50.

## Collaudo sul PC

`scripts/windows/test-installed.ps1` è incluso nel pacchetto. Esegue cinque
moduli e workflow con dati sintetici, confronta i risultati con attese
analitiche indipendenti e controlla la parità fra seriale, automatico e
limite di due processi. Comprende ingressi BAM, pileup e tabelle, tre campioni,
ruoli familiari espliciti e casi di input non valido.

Il collaudo usa Python e runtime WSL dell'applicazione installata. Verifica
versione, commit e immagine, lavora in una nuova cartella separata e controlla
che input, installazione e preferenze restino invariati. Conserva report HTML,
JSON, log e ZIP. Le istruzioni sono in [Collaudo installazione](COLLAUDO_INSTALLAZIONE.md).

Il precedente collaudo sul PC Windows ha superato 70 controlli in 10 minuti
e 57 secondi sulla **0.8.50 con riparazione CPIN**. È un'evidenza storica
separata, non una prova di installazione del nuovo pacchetto 0.8.60.

## CI e qualità del codice

La build può riutilizzare le sette evidenze scientifiche di una CI riuscita
solo quando albero Git e immagine Docker coincidono esattamente. Identità,
rapporti, completezza e hash vengono verificati; senza corrispondenza la
build esegue le prove. La pubblicazione può preparare e pubblicare in un
unico workflow gli stessi installer già qualificati, senza ricostruirli.

L'[audit della 0.8.60](AUDIT_0.8.60.md) documenta perimetro, difetti corretti
e limiti. Il test Windows del riavvio dopo aggiornamento ora mantiene
l'handle del processo osservato e usa una conferma esplicita: controlla
sempre il vero codice di uscita, anche quando il processo termina rapidamente.

Su terminali Mac/Linux il ritorno al menu con Ctrl+C viene gestito anche
quando l’interruzione arriva subito dopo la comparsa del campo di input.
Il percorso della console Windows rimane invariato.

## Aggiornamento

Usare **Verifica aggiornamenti** sul canale `stable`, oppure scaricare il
pacchetto del proprio sistema dalla
[release 0.8.60](https://github.com/GregorioDalia/nipat-desktop/releases/tag/v0.8.60).
Chiudere le analisi prima dell'aggiornamento. Sono disponibili Windows x64,
Ubuntu 24.04 x86_64 e macOS ARM64/Intel. Su Windows il percorso applicativo
e l'avvio tramite script/PowerShell restano compatibili con la 0.8.50.

I controlli automatici del pacchetto e le fixture del setup restano distinti
dall'installazione completa con WSL/Lima sui dispositivi finali. Le evidenze
legate ai byte pubblicati e gli scenari desktop ancora da verificare sono
nel record `.github/release-acceptance/v0.8.60.json`. La validazione di dominio
con dati biologici reali resta un'attività separata.

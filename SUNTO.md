# NIPAT in sintesi

NIPAT Desktop elabora BAM, pileup SNP e tabelle di conteggi per analisi genetiche locali. Il menu guidato aiuta a scegliere dati e parametri. I comandi CLI permettono di ripetere l'analisi con opzioni esplicite.

| Modulo | Risultato |
| --- | --- |
| DNPcall | Conteggi e genotipi per loci di due basi adiacenti da BAM. |
| SNPcall | Conteggi, likelihood e genotipi per loci a singola base da BAM o pileup compatibile. |
| Contamination | Stima della contaminazione da tabelle SNP o DNP. |
| CPI prenatale | Frazione fetale e indice di paternità da cfDNA materno e profilo del presunto padre. |
| CPIN postnatale | Indice di paternità da profili di madre, presunto padre e figlio. |

Un workflow può collegare uno o entrambi i caller alle analisi successive. I rami SNP e DNP mantengono tabelle e risultati distinti. Si possono importare conteggi già disponibili e indicare esplicitamente i ruoli di coppie e trii.

1. Installare il pacchetto adatto al [proprio sistema](docs/DISTRIBUZIONE.md).
2. Aprire NIPAT Desktop e scegliere l'analisi o il workflow.
3. Selezionare gli input e verificare il riepilogo prima di avviare.
4. Consultare risultati, resoconto e log dalla schermata finale.

L'ambiente scientifico comprende R, samtools e le relative dipendenze. Usa WSL2 su Windows, Lima su macOS e Docker Engine su Ubuntu. Ogni analisi scrive in una cartella dedicata e accede ai file selezionati in sola lettura.

Il catalogo espone i parametri scientifici, i valori predefiniti e le costanti. Ogni esecuzione registra le impostazioni applicate e le associazioni fra campioni, input e output. Sono disponibili modalità seriale, parallela automatica e diagnostica facoltativa delle prestazioni.

Per istruzioni operative e riferimenti tecnici, consultare l'[indice della documentazione](https://github.com/GregorioDalia/nipat-desktop/blob/main/docs/README.md).

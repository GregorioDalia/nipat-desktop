# Identità visiva NIPAT

Il simbolo combina una N con due tratti paralleli che richiamano dati di sequenza
accoppiati. Il blu scuro (`#142D4E`), il bianco e il verde acqua (`#48D6C5`)
mantengono il contrasto su superfici chiare e scure.

## File disponibili

- `nipat-symbol.svg`: simbolo vettoriale, usato dal collegamento Linux.
- `nipat-logo.svg`: logotipo per superfici chiare, con lettere convertite in tracciati.
- `nipat-logo-dark.svg`: logotipo per superfici scure.
- `nipat-icon.png`: icona trasparente a 512 × 512 pixel.
- `nipat-icon.ico`: icona Windows a 16, 20, 24, 32, 40, 48, 64, 128 e 256 pixel.

Il launcher Windows e l'installatore incorporano l'ICO. Il collegamento Linux
usa l'SVG installato e verificato con i sorgenti dell'applicazione. Non sono
necessari font o download aggiuntivi per visualizzare il marchio.

## Rigenerazione

`build_assets.py` contiene la geometria condivisa degli SVG e delle icone raster.
Per rigenerare gli asset utilizzare Python 3.12 e Pillow 12.3.0 in un ambiente
di sviluppo separato:

```console
python -m pip install Pillow==12.3.0
python assets/branding/build_assets.py
```

Il programma genera gli stessi file senza metadati temporali. Le dipendenze di
questo comando non sono richieste dall'applicazione o dalla compilazione degli
installatori, che usano i file già versionati. Il materiale grafico originale
segue la licenza del progetto.

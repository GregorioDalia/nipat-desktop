# Immutable NEWPAT scientific reference (13 November 2026)

These original R files were retrieved from NEWPAT commit
`9c2a8be60afcb944153710da6a61cd0559e2b4cf`. `manifest.json` pins their exact
UTF-8 bytes. They are independent reference implementations, not installed
operational code. Do not change them to make a candidate pass.

The 0.8.50 candidate intentionally exposes additional settings and diagnostics.
Comparison uses common scientific fields, not PDF bytes, added columns or paths.
Contamination now uses Other/(REF+ALT+Other); its changed estimates are checked
against this reference, not forced to equal NIPAT 0.8.35. CPI strips irrelevant
population metadata before its joins. CPIN is a new model.

DNPcall and SNPcall retain their separate pre-existing immutable references.

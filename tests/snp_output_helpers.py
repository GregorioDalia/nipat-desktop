"""Small native-artifact fixture for process-independent SNP adapter tests."""

import csv


def write_snp_auxiliary(output):
    import json
    import os
    from pathlib import Path

    settings_path = os.environ.get("NIPAT_SCIENTIFIC_SETTINGS")
    if settings_path:
        (output / "scientific-settings.json").write_bytes(Path(settings_path).read_bytes())
    else:
        from nipat_scientific.settings import defaults, describe_settings
        (output / "scientific-settings.json").write_text(json.dumps({
            "schema_version": 1, "workflow": "snp-call", "parameters": defaults("snp-call"),
            "constants": describe_settings("snp-call")["constants"]}))
    summary = output / "summary"
    summary.mkdir(exist_ok=True)
    with (output / "SNPcall_output.txt").open(newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter="\t"))
    with (summary / "SNPcall_AllGenotypes.txt").open("w", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(["chr", "pos", "REF", "ALT", "GT_sample_0001"])
        writer.writerows([row["chr"], row["pos"], row["REF"], row["ALT"], row["GT"]] for row in rows)
    (summary / "resources.tsv").write_text(
        "sample\tseconds\tresident_MB_start\tresident_MB_end\n"
        "sample_0001\t1.2\t20\t21\n")
    (summary / "Unassigned_genotypes.pdf").write_bytes(b"%PDF-1.4 fixture")
    plots = output / "plots/sample_0001"
    plots.mkdir(parents=True, exist_ok=True)
    for name in ("N_genotypes", "Ref_read_count", "Alt_read_count", "Other_read_count"):
        (plots / f"sample_0001_{name}.pdf").write_bytes(b"%PDF-1.4 fixture")

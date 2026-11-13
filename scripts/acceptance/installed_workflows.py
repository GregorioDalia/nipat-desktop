"""Independent caller oracles and public workflow cases for the installed client.

Expected counts come from the committed artificial SAM recipes. The combined
three-BAM plan tests routing; it is not a simulated biologically valid trio.
Separate analytical model cases qualify positive CPI/CPIN outputs.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from pathlib import Path
import shutil


SNP_FIELDS = {"chr", "pos", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count",
              "ratio", "GL0", "GL1", "GL2", "GT", "reads_discarded_for_indels",
              "ratio_reads_discarded_for_indels", "combined_bases", "combined_counts"}


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def table(path, delimiter="\t"):
    with Path(path).open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle, delimiter=delimiter)
        rows = list(reader)
        require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames),
                f"Intestazione mancante o duplicata: {path}")
        require(all(None not in row and all(value is not None for value in row.values()) for row in rows),
                f"Righe incomplete: {path}")
        return rows


def number(actual, expected, label, *, tolerance=1e-9):
    value = float(actual)
    require(math.isfinite(value) and math.isclose(value, expected, rel_tol=tolerance, abs_tol=tolerance),
            f"{label}: trovato {actual}, atteso {expected}")


def pdf(path):
    path = Path(path)
    require(path.is_file() and path.stat().st_size > 5 and path.read_bytes().startswith(b"%PDF-"),
            f"PDF assente o non valido: {path}")


def keyed(path, coordinates):
    rows = table(path)
    values = {tuple(row[field] for field in coordinates): row for row in rows}
    require(len(values) == len(rows), f"Loci duplicati: {path}")
    return values


def check_snp(actual, expected):
    """Compare all 17 SNP2 fields, including GL, NA and allele/count identity."""
    observed = keyed(actual, ("chr", "pos"))
    wanted = keyed(expected, ("chr", "pos"))
    require(wanted and observed.keys() == wanted.keys(), "Loci SNP mancanti o inattesi")
    integers = {"N_REF", "N_ALT", "N_Other", "total_count", "reads_discarded_for_indels"}
    floats = {"ratio", "GL0", "GL1", "GL2", "ratio_reads_discarded_for_indels"}
    for key, row in observed.items():
        require(set(row) == SNP_FIELDS and set(wanted[key]) == SNP_FIELDS, "Schema SNP diverso dai 17 campi attesi")
        for field in SNP_FIELDS:
            value, reference = row[field], wanted[key][field]
            if value == "NA" or reference == "NA":
                require(value == reference, f"SNP {key}/{field}: NA non corrispondente")
            elif field in integers:
                require(int(value) == int(reference), f"SNP {key}/{field}: conteggio diverso")
            elif field in floats:
                number(value, float(reference), f"SNP {key}/{field}", tolerance=1e-12)
            else:
                require(value == reference, f"SNP {key}/{field}: {value}, atteso {reference}")
    return {"loci": len(wanted), "fields_per_locus": 17}


def check_dnp(run, fixtures, samples=("A", "B", "A")):
    output = run / "output"
    oracle = table(fixtures / "dnp_engine/expected.tsv")
    expected = {sample: {(row["chr"], row["pos1"], row["pos2"]): row for row in oracle
                         if row["sample"] == sample} for sample in samples}
    summary = keyed(output / "summary/output_AllGenotypes.txt", ("chr", "pos1", "pos2"))
    require(set(summary) == set(expected[samples[0]]), "Riepilogo DNP: loci diversi dalla ricetta SAM")
    ids = [f"sample_{index:04d}" for index in range(1, len(samples) + 1)]
    require({path.name for path in (output / "individual_outputs").iterdir()} ==
            {f"full_output_{identity}.txt" for identity in ids}, "DNP: campioni mancanti, ripetuti o inattesi")
    require(list(next(iter(summary.values()))) == ["chr", "pos1", "pos2", "REF", "ALT", *[f"GT_{identity}" for identity in ids]],
            "DNP: ordine o identita dei campioni nel riepilogo diversi")
    for identity, sample in zip(ids, samples):
        rows = keyed(output / "individual_outputs" / f"full_output_{identity}.txt", ("chr", "pos1", "pos2"))
        require(rows.keys() == expected[sample].keys(), f"DNP {identity}: loci incompleti")
        for key, row in rows.items():
            wanted = expected[sample][key]
            for field in ("chr", "pos1", "pos2", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "GT", "total_count"):
                require(row[field] == wanted[field], f"DNP {identity}/{key}/{field}: {row[field]}, atteso {wanted[field]}")
            bases, counts = row["combined_bases"].split("-"), row["combined_counts"].split("-")
            observed = dict(zip(bases, map(int, counts)))
            combined = {wanted[allele]: int(wanted[count]) for allele, count in
                        (("REF", "N_REF"), ("ALT", "N_ALT"), ("OTHER", "N_Other")) if int(wanted[count])}
            require(len(bases) == len(counts) == len(observed) and observed == combined,
                    f"DNP {identity}/{key}: aplotipi/conteggi diversi")
            require(row["reads_discarded_for_indels"] == "0" and row["ratio_reads_discarded_for_indels"] == "0",
                    "DNP: indel inattesi nella ricetta senza indel")
            gl = [float(row[f"GL{index}"]) for index in range(3)]
            number(gl[1], -(int(wanted["N_REF"]) + int(wanted["N_ALT"])) * math.log(2), "DNP GL1", tolerance=.00051)
            require(all(math.isfinite(value) for value in gl) and ("0/0", "0/1", "1/1")[gl.index(max(gl))] == wanted["GT"],
                    "DNP: likelihood o genotipo incoerenti")
            require(summary[key][f"GT_{identity}"] == wanted["GT"], "DNP: genotipo aggregato diverso")
        for suffix in ("N_genotypes", "Ref_read_count", "Alt_read_count", "Other_read_count"):
            pdf(output / "plots" / identity / f"{identity}_{suffix}.pdf")
    pdf(output / "summary/Unassigned_genotypes.pdf")
    if len(samples) > 1:
        pdf(output / "summary/DNPs_covered_UpSet_plot.pdf")
    return {"samples": len(samples), "loci_per_sample": len(summary), "oracle": "SAM counts, genotype and analytical GL1"}


def _artifacts(value):
    if isinstance(value, dict):
        if "path" in value and "sha256" in value:
            yield value
        else:
            for item in value.values():
                yield from _artifacts(item)
    elif isinstance(value, list):
        for item in value:
            yield from _artifacts(item)


def check_plan(parent, workflows):
    """Require real completed steps and retained artifacts, never exit-code alone."""
    root = parent / "output/workflow"
    state = json.loads((root / "workflow-state.json").read_text(encoding="utf-8"))
    plan = json.loads((root / "plan.json").read_text(encoding="utf-8"))
    record = json.loads((parent / "run.json").read_text(encoding="utf-8"))
    require(record.get("status") == state.get("status") == "succeeded" and state.get("exit_code") == 0,
            "Workflow non concluso realmente")
    require(len(record.get("commands", [])) == 1 and "execute-plan" in record["commands"][0]["argv"],
            "Workflow non eseguito come singolo piano nel motore installato")
    require(sorted(step["workflow"] for step in plan["steps"]) == sorted(workflows), "Moduli/numero di step diversi dal piano richiesto")
    planned = {step["id"]: step for step in plan["steps"]}
    executed = {step["id"]: step for step in state["steps"]}
    require(len(planned) == len(plan["steps"]) == len(executed) == len(state["steps"]) and planned.keys() == executed.keys(),
            "Step persi o duplicati")
    require(state.get("plan_sha256") == hashlib.sha256((root / "plan.json").read_bytes()).hexdigest(), "Hash del piano non corrispondente")
    artifact_count = 0
    for identity, step in executed.items():
        require(step.get("status") == "succeeded" and step.get("exit_code") == 0 and step.get("finished_utc"),
                f"Step {identity} non concluso correttamente")
        for artifact in _artifacts(step.get("artifacts", {})):
            relative = Path(artifact["path"])
            path = (root / relative).resolve()
            require(not relative.is_absolute() and path.is_relative_to(root.resolve()) and path.is_file(), "Artefatto fuori dal run o mancante")
            require(hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"], f"Hash artefatto diverso: {path}")
            artifact_count += 1
        step_root = root / "steps" / identity
        effective = json.loads((step_root / "work/effective-scientific-settings.json").read_text())
        applied = json.loads((step_root / "output/scientific-settings.json").read_text())
        require(effective == applied and applied.get("workflow") == planned[identity]["workflow"],
                f"Impostazioni richieste/applicate diverse: {identity}")
    require(artifact_count > 0, "Workflow senza artefatti scientifici verificati")
    return root, plan, state


def check_snp_plan(parent, expected, count, *, additional=()):
    root, plan, state = check_plan(parent, ["snp-call"] * count + list(additional))
    ids = []
    for step in plan["steps"]:
        if step["workflow"] == "snp-call":
            check_snp(root / "steps" / step["id"] / "output/SNPcall_output.txt", expected)
            ids.append(step["inputs"]["sample"])
    require(len(set(ids)) == count, "SNP batch: campioni duplicati")
    groups = state.get("snp_summary", [])
    if count == 1:
        require(not groups, "SNP singolo: riepilogo multi-campione inatteso")
        return {"snp_samples": 1, "steps": len(plan["steps"])}
    require(len(groups) == 1 and set(groups[0]["samples"]) == set(ids), "SNP: riepilogo campioni incompleto")
    summary = table(root / groups[0]["genotypes"]["path"])
    oracle = table(expected)
    require(len(summary) == len(oracle), "SNP: riepilogo genotipi con loci mancanti")
    expected_by_locus = {(row["chr"], row["pos"]): row for row in oracle}
    require({(row["chr"], row["pos"]) for row in summary} == set(expected_by_locus), "SNP: coordinate aggregate diverse")
    for row in summary:
        for identity in ids:
            require(row[f"GT_{identity}"] == expected_by_locus[(row["chr"], row["pos"])]["GT"], "SNP: genotipo aggregato diverso")
    for artifact in groups[0]["plots"]:
        pdf(root / artifact["path"])
    return {"snp_samples": count, "steps": len(plan["steps"])}


def check_all_five(parent, fixtures):
    root, plan, _ = check_plan(parent, ["dnp-call"] + ["snp-call"] * 3 + ["contamination", "cpi", "cpin"] * 2)
    check_dnp(root / "steps/dnp", fixtures)
    check_snp_plan(parent, fixtures / "snp_engine/expected.tsv", 3,
                   additional=["dnp-call"] + ["contamination", "cpi", "cpin"] * 2)
    for step in plan["steps"]:
        if step["workflow"] in {"cpi", "cpin"}:
            refs = step["inputs"]["pairs" if step["workflow"] == "cpi" else "trios"]
            for family in refs:
                for role in ("mother", "father") + (("child",) if step["workflow"] == "cpin" else ()):
                    require(family[role]["output"] in {"dnp-tables", "snp-tables"} and
                            planned_workflow(plan, family[role]["step"]) in {"dnp-call", "snp-call"},
                            "Riferimento familiare collegato a un modulo consumatore invece che al caller")
    return {"steps": 10, "bam_count": 3, "scope": "caller numerical oracles; downstream routing/contracts; not a biologically valid trio"}


def planned_workflow(plan, identity):
    return next(step["workflow"] for step in plan["steps"] if step["id"] == identity)


def check_positive_cpi(parent, *, contamination, snp, cutoffs, oracle_dir=None):
    expected_workflows = ["dnp-call", "cpi"] + (["contamination"] if contamination else []) + (["snp-call"] * 2 if snp else [])
    root, plan, state = check_plan(parent, expected_workflows)
    for index, counts in enumerate(((96, 4), (50, 50)), 1):
        rows = table(root / f"steps/dnp/output/individual_outputs/full_output_sample_{index:04d}.txt")
        require({(row["chr"], int(row["pos1"]), int(row["pos2"])) for row in rows} ==
                {("chrDnpSynthetic", pos, pos + 1) for pos in (50, 140, 230)}, "Catena CPI: loci persi")
        require(all(tuple(int(row[field]) for field in ("N_REF", "N_ALT", "N_Other", "total_count")) == (*counts, 0, 100)
                    for row in rows), "Catena CPI: conteggi BAM diversi dalla ricetta 96/4 e 50/50")
        require(all(row["GT"] == ("0/0" if index == 1 else "0/1") for row in rows),
                "Catena CPI: genotipi diversi dalla ricetta")
        if snp:
            require(oracle_dir is not None, "Oracolo SNP positivo assente")
            check_snp(root / f"steps/snp_{index:04d}/output/SNPcall_output.txt",
                      oracle_dir / ("maternal-expected.tsv" if index == 1 else "paternal-expected.tsv"))
    rows = table(root / "steps/cpi/output/Summary_FetalFraction_CPI.csv", ",")
    require(len(rows) == (2 if cutoffs else 1), "Catena CPI: numero di riepiloghi inatteso")
    if cutoffs:
        require({row.get("Cutoff") for row in rows} == {"Full", "First"}, "Catena CPI: cutoff persi o scambiati")
    for row in rows:
        first = row.get("Cutoff") == "First"
        for field in ("N_sites_mother", "N_sites_father"):
            number(row[field], 1 if first else 3, field)
        for field, expected in (("Median_fetal_fraction_raw", .08), ("Median_fetal_fraction_percent", 8),
                                ("Error_constant", .0000892303778101497), ("Min_fetal_reads", 2)):
            number(row[field], expected, field)
        for field in ("Max_logCPI", "Min_logCPI", "Median_logCPI", "Mean_logCPI", "CPI_medianFF"):
            number(row[field], .301 if first else .903, field)
        require(row["Marker_type"] == "DNP", "Catena CPI: marker inatteso")
    check_positive_curves(root / "steps/cpi/output/curves", cutoffs=cutoffs)
    cpi_step = next(step for step in plan["steps"] if step["workflow"] == "cpi")
    require(all(reference["step"] == "dnp" for family in cpi_step["inputs"]["pairs"]
                for reference in (family["mother"], family["father"])), "CPI non legge le tabelle DNP originali")
    if contamination:
        executed = next(step for step in state["steps"] if step["id"] == "contamination")
        summary = {row["individuo"]: row for row in table(root / executed["artifacts"]["summary"]["path"])}
        mapped = {item["sample"]: item for item in executed["artifacts"]["contamination-tables"]}
        require(len(summary) == len(mapped) == 2, "Catena positiva: campioni Contamination persi")
        mother = summary[mapped["sample_0001"]["native_name"]]
        father = summary[mapped["sample_0002"]["native_name"]]
        for field, expected in (("informative_sites", 3), ("mean_contamination", .04), ("sd_contamination", 0)):
            number(mother[field], expected, "Contamination positiva " + field)
        require(father["informative_sites"] == "0" and father["mean_contamination"] == father["sd_contamination"] == "NA",
                "Contamination: il padre eterozigote deve avere zero siti informativi")
    for path in (root / "steps/cpi/output/plots").glob("*.pdf"):
        pdf(path)
    require(any((root / "steps/cpi/output/plots").glob("*.pdf")), "Catena CPI senza PDF")
    return {"fetal_fraction": .08, "CPI_full": 8, "CPI_first_locus": 2 if cutoffs else None}


def check_positive_curves(directory, *, cutoffs):
    curves = list(directory.glob("*.tsv"))
    require(len(curves) == (2 if cutoffs else 1), "Catena CPI: curve assenti")
    curve_cutoffs = []
    for path in curves:
        curve = table(path)
        labels = {row.get("Cutoff") for row in curve}
        require(len(labels) == 1, "Catena CPI: etichette cutoff incoerenti nella curva")
        label = next(iter(labels))
        require(label in {"Full", "First"} if cutoffs else label == "ALL",
                "Catena CPI: cutoff della curva inatteso")
        curve_cutoffs.append(label)
        expected_cpi = 2 if label == "First" else 8
        require([int(row["Iteration"]) for row in curve] == [2, 3, 4], "Catena CPI: soglie della curva inattese")
        for row in curve:
            number(row["CPI"], expected_cpi, "CPI non arrotondato")
            number(row["log_CPI"], math.log10(expected_cpi), "log_CPI non arrotondato")
    require(set(curve_cutoffs) == ({"Full", "First"} if cutoffs else {"ALL"}),
            "Catena CPI: curve cutoff mancanti o duplicate")


def _positive_sams(fixtures, destination):
    templates, headers = {}, []
    loci = {20: ("AC", "GT"), 110: ("TA", "CG"), 200: ("GC", "AT")}
    for sample in ("A", "B"):
        for line in (fixtures / f"dnp_engine/reads_{sample}.sam").read_text().splitlines():
            if line.startswith("@"):
                if sample == "A":
                    headers.append(line)
                continue
            fields = line.split("\t")
            position = int(fields[3])
            if position in loci and fields[5] == "62M" and fields[9][30:32] in loci[position]:
                templates.setdefault((position, fields[9][30:32]), fields)
    require(len(templates) == 6, "Mancano i sei template SAM indipendenti REF/ALT")
    for role, counts in (("maternal", (96, 4)), ("paternal", (50, 50))):
        lines = headers.copy()
        for position, alleles in loci.items():
            for allele, count in zip(alleles, counts):
                for index in range(count):
                    fields = templates[(position, allele)].copy()
                    fields[0] = f"cpi_{role}_{position}_{allele}_{index:03d}"
                    fields[1], fields[10] = ("16" if index % 2 else "0"), "I" * 62
                    lines.append("\t".join(fields))
        (destination / f"{role}.sam").write_text("\n".join(lines) + "\n", encoding="utf-8")


def check_imported_tables(parent):
    root, plan, _ = check_plan(parent, ["cpi"])
    step = plan["steps"][0]
    require(all("step" not in family[role] for family in step["inputs"]["pairs"]
                for role in ("mother", "father")), "Import tabelle collegato erroneamente a un caller")
    output = root / "steps" / step["id"] / "output"
    rows = table(output / "Summary_FetalFraction_CPI.csv", ",")
    require(len(rows) == 1 and rows[0]["Marker_type"] == "DNP", "Import: famiglia o marker diversi")
    for field, expected in (("N_sites_mother", 3), ("N_sites_father", 3),
                            ("Median_fetal_fraction_raw", .06), ("Median_fetal_fraction_percent", 6),
                            ("Max_logCPI", 1.301), ("Min_logCPI", .301), ("Median_logCPI", .602),
                            ("Mean_logCPI", .735), ("CPI_medianFF", .602),
                            ("Error_constant", .0000892303778101497), ("Min_fetal_reads", 2)):
        number(rows[0][field], expected, "Import CPI " + field)
    curves = list((output / "curves").glob("*.tsv"))
    require(len(curves) == 1, "Import: curva mancante o duplicata")
    curve = table(curves[0])
    require([int(row["Iteration"]) for row in curve] == [2, 3, 4], "Import: soglie diverse")
    for row, expected, sites in zip(curve, (20, 4, 2), (3, 2, 1)):
        for field in ("InfSites_mother", "InfSites_father"):
            number(row[field], sites, "Import " + field)
        number(row["CPI"], expected, "Import CPI non arrotondato")
        number(row["log_CPI"], math.log10(expected), "Import log_CPI non arrotondato")
    plots = list((output / "plots").glob("*.pdf"))
    require(plots, "Import: PDF assenti")
    for path in plots:
        pdf(path)
    return {"imported_tables": 2, "fetal_fraction": .06, "CPI_curve": [20, 4, 2]}


def _positive_snp_oracle(destination, role, n_ref, n_alt):
    fields = ["chr", "pos", "REF", "ALT", "N_REF", "N_ALT", "N_Other", "total_count", "ratio",
              "GL0", "GL1", "GL2", "GT", "reads_discarded_for_indels", "ratio_reads_discarded_for_indels",
              "combined_bases", "combined_counts"]
    error = 10 ** -4
    likelihoods = [n_ref * math.log((2 - g) / 2 * (1 - error) + g / 2 * error) +
                   n_alt * math.log((2 - g) / 2 * error + g / 2 * (1 - error)) for g in range(3)]
    genotype = ("0/0", "0/1", "1/1")[likelihoods.index(max(likelihoods))]
    with (destination / f"{role}-expected.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(fields)
        for position, ref, alt in ((50, "A", "G"), (140, "T", "C"), (230, "G", "A")):
            counts = dict(sorted({ref: n_ref, alt: n_alt}.items()))
            writer.writerow(["chrDnpSynthetic", position, ref, alt, n_ref, n_alt, 0, n_ref + n_alt,
                             n_ref / (n_ref + n_alt), *likelihoods, genotype, 0, 0,
                             "-".join(counts), "-".join(str(value) for value in counts.values())])


def prepare_inputs(fixtures: Path, generated: Path, samtools):
    """Build small BAMs using samtools supplied by the installed scientific image."""
    combined = generated / "caller inputs with spaces"
    positive = generated / "positive CPI inputs"
    combined.mkdir(parents=True, exist_ok=False)
    positive.mkdir()
    dnp, snp = fixtures / "dnp_engine", fixtures / "snp_engine"
    reference = combined / "reference.fa"
    reference.write_bytes((dnp / "reference.fa").read_bytes() + (snp / "reference.fa").read_bytes())
    samtools(["faidx", reference])
    snp_lines = (snp / "reads.sam").read_text().splitlines()
    bams = []
    for index, source in enumerate(("A", "B", "A"), 1):
        lines = (dnp / f"reads_{source}.sam").read_text().splitlines()
        headers = [line for line in lines if line.startswith("@")] + [line for line in snp_lines if line.startswith("@SQ")]
        reads = [f"sample{index}_" + line for line in lines + snp_lines if not line.startswith("@")]
        sam = combined / f"sample{index}.sam"
        sam.write_text("\n".join(headers + reads) + "\n", encoding="utf-8")
        bam = combined / f"sample{index}.bam"
        samtools(["sort", "-o", bam, sam])
        bams.append(bam)
    shutil.copyfile(dnp / "DNP_list.txt", combined / "dnp-panel.tsv")
    shutil.copyfile(snp / "SNPlist.tsv", combined / "snp-panel.tsv")
    # SNP2 needs the adjacent pileup positions to qualify the central SNP.
    (combined / "snp-regions.bed").write_text("chrSynthetic\t48\t51\nchrSynthetic\t118\t121\n", encoding="utf-8")
    pileup = combined / "sample1.pileup"
    samtools(["mpileup", "-f", reference, "-l", combined / "snp-regions.bed", "--output-QNAME", "-d", "0",
              "--no-output-ins", "--no-output-del", "--no-output-ends", "-o", pileup, bams[0]])
    pileups = [pileup]
    for index in (2, 3):
        path = combined / f"sample{index}.pileup"
        shutil.copyfile(pileup, path)
        pileups.append(path)
    for marker in ("dnp", "snp"):
        text = ("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\n" + "".join(
            f"chrDnpSynthetic\t{pos}\t{pos+1}\t0.6\t0.4\n" for pos in (50, 140, 230))) if marker == "dnp" else (
            "chr\tpos\tRef_f.pop\tAlt_f.pop\nchrSynthetic\t50\t0.6\t0.4\nchrSynthetic\t120\t0.6\t0.4\n")
        (combined / f"{marker}-frequency.tsv").write_text(text, encoding="utf-8")
    _positive_sams(fixtures, positive)
    shutil.copyfile(dnp / "reference.fa", positive / "reference.fa")
    shutil.copyfile(dnp / "DNP_list.txt", positive / "dnp-panel.tsv")
    samtools(["faidx", positive / "reference.fa"])
    for role in ("maternal", "paternal"):
        samtools(["sort", "-o", positive / f"{role}.bam", positive / f"{role}.sam"])
        _positive_snp_oracle(positive, role, *( (96, 4) if role == "maternal" else (50, 50)))
    (positive / "population.tsv").write_text("chr\tpos1\tpos2\tRef_f.pop\tAlt_f.pop\n" + "".join(
        f"chrDnpSynthetic\t{pos}\t{pos+1}\t0.75\t0.25\n" for pos in (50, 140, 230)), encoding="utf-8")
    (positive / "first.tsv").write_text("chr\tpos1\tpos2\nchrDnpSynthetic\t50\t51\n", encoding="utf-8")
    (positive / "snp-panel.tsv").write_text("pos\tref\talt\nchrDnpSynthetic:50\tA\tG\nchrDnpSynthetic:140\tT\tC\nchrDnpSynthetic:230\tG\tA\n", encoding="utf-8")
    (combined / "invalid-six-columns.pileup").write_text("chrSynthetic\t50\tA\t1\t.\tI\n", encoding="utf-8")
    (combined / "corrupt.bam").write_bytes(b"This is deliberately not a BAM file.\n")
    return {"combined": combined, "positive": positive, "bams": bams, "pileups": pileups}


def build_cases(fixtures: Path, generated: Path, metadata):
    del generated
    c, positive = metadata["combined"], metadata["positive"]
    bams, pileups = metadata["bams"], metadata["pileups"]
    bam_args = [part for bam in bams for part in ("--bam", bam)]
    dna = ["--reference", c / "reference.fa", "--panel", c / "dnp-panel.tsv"]
    snp = ["--panel", c / "snp-panel.tsv"]
    cases = []

    def add(identity, args, validate=None, *, mode="serial", compare_group=None, expect_failure=None):
        value = {"id": identity, "category": "workflow" if args[0] == "workflow" else "caller",
                 "args": args, "mode": mode, "validate": validate}
        if compare_group:
            value["compare_group"] = compare_group
        if expect_failure:
            value["expect_failure"] = expect_failure
            value["category"] = "invalid-input"
        cases.append(value)

    for mode in ("serial", "cap2"):
        add(f"dnp-three-{mode}", ["dnp-call", *bam_args, *dna], lambda run: check_dnp(run, fixtures),
            mode=mode, compare_group="dnp-three")
    add("snp-bam", ["snp-call", "--bam", bams[0], "--reference", c / "reference.fa", *snp],
        lambda run: check_snp(run / "output/SNPcall_output.txt", fixtures / "snp_engine/expected.tsv"), compare_group="snp-input-modes")
    add("snp-pileup", ["snp-call", "--pileup", pileups[0], *snp],
        lambda run: check_snp(run / "output/SNPcall_output.txt", fixtures / "snp_engine/expected.tsv"), compare_group="snp-input-modes")
    add("snp-batch-bam", ["workflow", "snp-batch", *bam_args, "--reference", c / "reference.fa", *snp],
        lambda run: check_snp_plan(run, fixtures / "snp_engine/expected.tsv", 3), mode="auto")
    add("snp-batch-pileup", ["workflow", "snp-batch", *[part for path in pileups for part in ("--pileup", path)], *snp],
        lambda run: check_snp_plan(run, fixtures / "snp_engine/expected.tsv", 3), mode="cap2")
    full = ["workflow", "analyze", "--caller", "both", "--analyses", "contamination,cpi,cpin",
            *[part for name, path in zip(("mother", "father", "child"), bams) for part in ("--sample", name, path)],
            "--reference", c / "reference.fa", "--dnp-panel", c / "dnp-panel.tsv", "--snp-panel", c / "snp-panel.tsv",
            "--dnp-popfreq", c / "dnp-frequency.tsv", "--snp-popfreq", c / "snp-frequency.tsv",
            "--dnp-cpin-panel", c / "dnp-panel.tsv", "--snp-cpin-panel", c / "snp-panel.tsv",
            "--pair", "prenatal", "mother", "father", "--trio", "postnatal", "mother", "father", "child"]
    for mode in ("serial", "auto", "cap2"):
        add(f"all-five-{mode}", full.copy(), lambda run: check_all_five(run, fixtures), mode=mode, compare_group="all-five")
    def contamination_plan(run):
        root, _, _ = check_plan(run, ["dnp-call", "contamination"])
        return check_dnp(root / "steps/dnp", fixtures)
    add("preset-dnp-contamination", ["workflow", "dnp-contamination", *bam_args, *dna], contamination_plan)
    pairs = ["--pair", "family_a", positive / "maternal.bam", positive / "paternal.bam",
             "--reference", positive / "reference.fa", "--panel", positive / "dnp-panel.tsv", "--popfreq", positive / "population.tsv"]
    add("preset-dnp-cpi-positive", ["workflow", "dnp-cpi", *pairs],
        lambda run: check_positive_cpi(run, contamination=False, snp=False, cutoffs=False))
    add("preset-full-positive", ["workflow", "dnp-contamination-cpi", *pairs,
        "--cutoff", "Full", positive / "dnp-panel.tsv", "--cutoff", "First", positive / "first.tsv", "--snp-panel", positive / "snp-panel.tsv"],
        lambda run: check_positive_cpi(run, contamination=True, snp=True, cutoffs=True, oracle_dir=positive), mode="auto")
    add("analyze-pileup", ["workflow", "analyze", "--caller", "snp", "--pileup", "source", pileups[0], "--snp-panel", c / "snp-panel.tsv"],
        lambda run: check_snp_plan(run, fixtures / "snp_engine/expected.tsv", 1))
    imported = fixtures / "five_modules/DNP/cpi"
    add("analyze-imported-tables", ["workflow", "analyze", "--caller", "tables", "--analyses", "cpi",
        "--dnp-table", "mother", imported / "MotherM.txt", "--dnp-table", "father", imported / "FatherF.txt",
        "--dnp-popfreq", imported / "population.tsv", "--pair", "imported", "mother", "father"], check_imported_tables)
    add("reject-six-column-pileup", ["snp-call", "--pileup", c / "invalid-six-columns.pileup", *snp],
        expect_failure=r"(?i)(almeno 7 colonne|QNAME)")
    add("reject-duplicate-sample", ["workflow", "analyze", "--caller", "dnp", "--sample", "same", bams[0], "--sample", "same", bams[1],
        "--reference", c / "reference.fa", "--dnp-panel", c / "dnp-panel.tsv"], expect_failure=r"(?i)(duplicat|ripetut|univoc)")
    add("reject-corrupt-bam", ["workflow", "dnp-contamination", "--bam", c / "corrupt.bam", *dna],
        expect_failure=r"(?i)fail to read the header of")
    return cases

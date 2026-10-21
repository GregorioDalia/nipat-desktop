# Consolidated decisions

## Domain-testing pre-release 0.4.0

- Consolidate the guided CLI and both Windows distributions as `v0.4.0`, marked
  as a GitHub pre-release for domain testing, not completed scientific validation.
- The maintainer authorizes this handoff assuming working WSL2. Record this as
  the accepted testing scope, not a new independent Windows installation test
  or a successful Docker Desktop test.
- Provide versioned download links for the single `NIPAT-Setup.exe` and
  `NIPAT-DockerDesktop-0.4.0-windows-x64.zip`. Keep prior release notes and
  evidence historical; do not transfer their outcomes to new packages.
- Document Docker Desktop setup and a real DNPcall-to-Contamination trial,
  with expected/observed results and setup/run logs, before extending coverage.

## Common Windows launcher and dual delivery (0.3.0a2 candidate)

- The external validation handoff must use the latest interface reviewed by the
  maintainer. Keep published `v0.3.0a1` unchanged; publish the new candidate only
  after reviewing the actual versioned packages, rather than sharing a moving
  development branch or an older installer.
- Ship a common `NIPAT.exe` in both the WSL installer and Docker Desktop ZIP.
  Double-click opens the guided CLI; explicit analysis confirmation executes the
  same R scripts and workflow tools as the direct CLI. PowerShell may be used
  internally by the launcher, but users do not need to open it manually.
- Preserve `nipat.cmd` and `2_AVVIA.cmd`, caller-relative input paths, and all
  direct CLI arguments. The EXE uses the configuration of its own application
  directory; it does not automatically switch to another installed copy.
- Build both packages from one source commit and reuse the same SHA-256-verified
  scientific archive. Resolve the imported image's local ID from its verified
  load receipt in either backend; do not assume equality across engine stores.
- Keep Docker Desktop as the prerequisite for the Docker ZIP. The WSL installer
  manages its dedicated engine. Setup and self-tests precede domain analyses.
- Make the primary installer a single `NIPAT-Setup.exe` download containing
  the verified runtime archives as well as the application and portable Python.
  Users double-click setup and then the NIPAT icon; they do not arrange asset
  directories or download runtime files separately. Preserve embedded assets
  automatically for resumed setup. Initial Windows WSL activation may still
  require Internet, administrator consent and a restart.
- Explain runtime updates as preparation of NIPAT's internal Linux environment,
  not manual Windows or WSL maintenance. Keep technical diagnostics separate
  from the normal installation and analysis steps.
- Apply GPL-3.0-or-later to original NIPAT code and preserve the licenses and
  attribution of vendored components. Do not imply a broader grant for upstream
  code than its own license provides.
- Plan interface localization through separate message catalogs, with English
  as the reference language and an Italian option. This is future work; current
  guided messages remain Italian and scientific file schemas remain unchanged.
- Upgrade WSL by preparing a side-by-side distribution when the full rootfs
  digest changes. Qualify new distribution names with the rootfs hash and keep
  per-target ownership records. Preserve the legacy distribution and its
  ownership; reuse it only for the same verified rootfs and validated ownership.
- Snapshot the prior setup state and backend once per target source commit and
  full rootfs digest.
  Preserve valid configured data and results roots. Run `doctor` and scientific
  self-tests against the candidate before publishing its backend configuration;
  write the ready state last. Repeating setup resumes its owned target.
- Do not unregister old distributions or delete data automatically. A failed
  preparation leaves the updated application blocked until setup succeeds.
  Preserving the prior runtime is not full application rollback: Inno Setup has
  already replaced application files. Record final-package fresh-install and
  upgrade checks on Windows separately from automated implementation tests.

## Guided terminal experience (0.3.0a2 candidate)

- Add a versioned NIPAT banner and a vertical menu. Arrow/Enter interaction is
  limited to supported interactive terminals; numbered and plain-text input
  remains available. Do not require new Python packages in embedded Python.
- Validate files during input collection, preserve values while editing, offer
  `:indietro` and `:annulla`, and require an explicit launch from the editable
  input/parameter summary. Preserve all four workflows and their input modes.
- Expose result/run folders, execution metadata and logs through the final
  screen. Main-menu option 6 recalls only the current session's latest run;
  option 5 still changes the results root for the current session only.
- Offer help and an on-demand environment check through option 7. Never infer
  runtime readiness merely from opening the menu or reading backend settings.
- Keep execution status separate from scientific interpretation. A dry-run is
  planned, not completed analysis; file availability is not scientific validity.
- Keep direct CLI arguments and scientific defaults available. Persistent
  preferences, cross-session history and workflow chaining remain later work.
- Preserve the published `v0.3.0a1` installer. Record the new candidate's tests
  separately; manual Windows terminal verification remains to be recorded.

## Managed Windows installer (0.3.0a1 candidate)

- Distribute a per-user `NIPAT-Setup.exe` through GitHub Releases, targeting
  Windows 11 x64 for the first installation trial.
- Preserve the scientific Linux image. Use a dedicated WSL2 distribution with
  Docker Engine to avoid a separate Docker Desktop installation.
- Keep Windows Python input validation and native Docker execution available;
  opt into WSL through the installed configuration.
- Build and test the scientific image in CI. Embed asset hashes in the installer
  and verify archives and the imported image ID before reporting success.
- Do not equate the builder's image ID with the destination engine's ID:
  graphdriver and containerd identify different objects. Load the SHA-256-verified
  single-image archive, require one immutable ID in its load receipt, inspect
  Linux amd64, and persist both IDs plus the archive hash. Never choose an image
  from a daemon-wide listing. Check the persisted release binding at launch.
- Add an actual exported-archive load/run/reload gate in the shipped engine.
  The local correction and Windows trial were reviewed on 2026-10-21; build
  39581854492 at 0595c47 subsequently passed this gate and compiled the EXE.
- The first domain-testing handoff assumes working WSL2 on Windows 11 x64.
  Clean-machine WSL activation and restart/resume remain separate, unverified
  installation cases; they do not block this scoped pre-release. Each tester
  must still complete setup and self-tests before starting domain analyses.
- The physical-PC evidence uses candidate 19507bb with three locally corrected
  scripts. It includes engine restart after WSL termination and one real-BAM
  DNPcall comparison (11 sites, 11 selected count/genotype columns). Do not
  present this as a full installation test of the later rebuilt EXE, a complete
  17-column WSL comparison, or independent scientific validation.
- Publish EXE, runtime archives and manifest from one successful build at the
  exact tagged source commit. Include the updated usage guide in that build;
  never mix an older executable or manifest with revised source documents.
- Elevate only Windows prerequisite activation. Register the distro under the
  invoking user; never automatically replace an existing distro.
- Complete self-tests before reporting setup success. CI success does not
  establish clean-machine installation success or scientific validity.
- Retain `v0.2.0a2` and its evidence. Do not transfer its successful Docker
  Desktop tests to the new WSL installation claim.
- Use “Guida per l’utilizzo” and generic domain validation terminology in
  public documentation; rename the guide to `docs/GUIDA_UTILIZZO.md`.

## Input portability and complete CLI modes (0.2.0a2)

- Input paths are user-selected and can be outside the project, `data` or
  `runs`. Selective read-only file mounts expose the required inputs and
  sidecars without copying large BAM/FASTA files or adding mounts of external
  parent directories. Original-to-container mappings are recorded for each run.
- `--data-dir` and `--runs-dir`, or their `NIPAT_DATA_DIR` / `NIPAT_RUNS_DIR`
  environment variables, configure default locations. CLI options take
  precedence and must precede the subcommand. Relative paths use the caller's
  current directory; BAM-list entries use the list's parent directory.
  Wizard option 5 changes the results root for subsequent runs in the current
  session, after validation and directory creation; it does not persist a setting.
- DNPcall accepts repeated BAM arguments or a BAM list, with optional parallel
  execution. Stable numbered aliases avoid the R script's filename limitations;
  the run records the original sample mapping. BAM indexes are optional for
  the current `mpileup -l` execution; FASTA `.fai` and BGZF `.gzi` are required.
  A small DNP-panel copy in `work` carries the validated coordinates and
  uppercase REF/ALT alleles; the original panel is preserved.
- SNPcall accepts either BAM/FASTA or a ready seven-column pileup with QNAME.
  Contamination accepts individual tables or recursive TXT/TSV directory input
  and coordinate panels. CPI accepts all sites, one panel or multiple labeled
  cutoffs, including the native cutoff-map interface. The wizard exposes these
  modes and the existing CPI error constant.
- Each run is created in a new subdirectory of the chosen results root.
  Scientific output filenames are preserved; existing run directories are
  rejected. The scientific algorithms and defaults are unchanged in this revision.
- Windows checks for `0.2.0a2` were observed on the maintainer's PC on
  2026-10-20: 99 unit tests passed and one symlink test was skipped; after
  fixing sibling imports under embedded Python, all 34 targeted CLI tests
  passed. These are separate runs, not a full 101-test Windows run.
  Setup and all four self-test groups passed, including external inputs on
  another drive. The wizard accepted a relative results directory and exited
  with code 0. A separate DNPcall real-BAM regression reproduced all 11 rows
  and 17 columns, ignoring row order, with the original BAM mapping recorded.
  See [distribution evidence](DISTRIBUZIONE.md) for scope and remaining work.
- Preserve the existing `v0.2.0a1` tag and create `v0.2.0a2` only for the
  verified commit. GitHub remains the distribution channel; Docker/WSL
  prerequisite automation is outside this revision.

## CLI validation handoff (2026-10-20)

- Consolidate run evidence before the GUI: `run.json` and a live/persistent
  `execution.log` describe the full workflow, including multi-command SNPcall.
- Resolve and record the actual Docker image ID and scientific package versions;
  use that image ID for the run. A Docker tag alone is not a version guarantee.
- The first assisted distribution targets Windows x64 through a versioned
  GitHub release. Testers download the source archive directly from GitHub;
  setup prepares embedded Python 3.12.10 and builds the Docker scientific runtime.
  Docker Desktop Linux containers are currently a manual prerequisite.
  Prerequisite installation automation is planned, not implemented in this release.
- The text wizard calls the same Workflows services as the existing CLI.
  DNPcall remains serial by default.
- CLI 0.2.0a1 was prepared as a validation candidate. Bundled numerical checks cover the SNP
  reference example and synthetic CPI/Contamination cases; domain validation
  and raw-BAM coverage are separate. No scientific algorithm changes here.
- Windows setup for 0.2.0a1 was exercised on the maintainer's PC on 2026-10-20: 48 Python
  tests passed, one symlink test was skipped, and all three real Docker numerical
  self-tests passed. Docker was already installed and the build reused cached
  layers; a clean-machine installation and the colleague's domain tests remain.

## Existing scientific and architectural decisions

- The R scripts supplied on 2026-07-21 are the scientific baseline. DNPcall includes the compatibility fixes, while CPI and contamination include the upstream updates recorded in `scientific/README.md`; SNPcall retains the supplied baseline version.
- The first prototype covers DNPcall, SNPcall, contamination and CPI.
- The existing `DNP_list.txt` remains a provisional reference panel; users can
  select other compatible panels. Python may derive the coordinate-only view
  mechanically from the five-column DNP list.
- SNPcall can generate pileup from BAM, FASTA and the SNP list, or accept an
  existing compatible pileup.
- Population-frequency tables remain user-selectable.
- The current `err_const` default is frozen but exposed by the CPI command and wizard.
- Scientific thresholds follow the recorded upstream versions. The CPI update applies the existing minimum of two fetal reads to its summary as well as its curves. Defaults are documented in `config/defaults.toml`.
- The application is local and is being designed for Windows, Linux and macOS.
- Genomic data and run outputs remain outside the Git repository.

## Contamination interface

The DNPcall output does not include `ratio_REF_ALT`. The vendored contamination
script from NEWPAT commit `17d2b8bbd09b1a0ff0651198c21e544aef197824` computes the
missing field as `N_REF / (N_REF + N_ALT)`, excluding zero-denominator sites. An
existing ratio column is passed through to the upstream script. Python validates
the required count/coordinate columns and does not invent a scientific field.

Contamination now includes informative sites with zero unexpected reads. The
resulting counts, mean and standard deviation can differ from the baseline.
The summary is a tab-separated TXT with an informative-site count. Samples with
no informative sites have count zero and `NA` estimates.

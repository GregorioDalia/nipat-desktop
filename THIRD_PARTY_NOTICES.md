# NIPAT licensing and third-party notices

## Original NIPAT material

The original NIPAT source code, scripts and project documentation in this
repository are licensed under the **GNU General Public License, version 3 or,
at your option, any later version** (`GPL-3.0-or-later`), except where a file
or component carries its own notice. Copyright remains with the respective
authors and contributors.

NIPAT is free software: you can redistribute it and/or modify it under the
terms of the GNU General Public License as published by the Free Software
Foundation, either version 3 of the License, or (at your option) any later
version.

NIPAT is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.

The complete, unmodified license text is in [LICENSE](LICENSE). It was obtained
from <https://www.gnu.org/licenses/gpl-3.0.txt>.

The license permits academic and commercial use. Redistribution must comply
with its conditions, including the applicable source-code obligations.
Using NIPAT does not transfer ownership of the user's input data or, merely
because they were produced with NIPAT, place scientific results under the GPL.

## Scientific components included in the source tree

| Component | Upstream source | Included license and scope |
| --- | --- | --- |
| NEWPAT | <https://github.com/lpistacchia/NEWPAT> | [Upstream LICENSE](scientific/vendor/NEWPAT/LICENSE), containing the GNU GPL version 3 text. Includes the supplied SNPcall, CPI and Contamination files and accompanying examples. |
| DNPcall | <https://github.com/fravasini/DNPcall> | [Upstream LICENSE](scientific/vendor/DNPcall/LICENSE), containing the GNU GPL version 3 text. Includes the supplied DNPcall files and accompanying examples. |

These components retain their original authorship, license texts and notices.
The `GPL-3.0-or-later` grant for original NIPAT material does not add an
"or later" permission to third-party files. Their own applicable terms govern
them.

[scientific/README.md](scientific/README.md) records the upstream revisions
and local compatibility changes;
[scientific/SHA256SUMS](scientific/SHA256SUMS) identifies the exact scientific
files used by NIPAT. Preserve these records when distributing a modified copy.

## Software supplied with the runtime

The Windows packages and Linux runtime also contain software with its own
licenses. The NIPAT license does not replace those licenses.

- **Python:** the Windows embedded distribution is obtained from python.org.
  Its license and third-party notices are included in that distribution and
  must remain with the extracted runtime.
- **R, R packages, samtools and HTSlib:** the scientific image is assembled by
  [docker/scientific-runtime/Dockerfile](docker/scientific-runtime/Dockerfile).
  Each component retains its own terms. R package descriptions and their
  associated license files identify the package-specific conditions. The
  samtools release's notices are retained in the scientific image at
  `/usr/share/doc/nipat-samtools/samtools/LICENSE`,
  `/usr/share/doc/nipat-samtools/htslib/LICENSE`,
  `/usr/share/doc/nipat-samtools/htscodecs/LICENSE.md` and
  `/usr/share/doc/nipat-samtools/lz4/LICENSE` before its build sources are removed.
- **Debian packages and the dedicated Docker Engine:** the WSL filesystem is
  assembled by [installer/runtime/Dockerfile](installer/runtime/Dockerfile).
  Its package inventory is stored in `/usr/share/nipat/apt-versions.tsv`,
  package metadata in `/usr/share/nipat/docker-package-metadata.txt`, and
  provenance in `/etc/nipat-runtime.json`. Package notices are retained under
  `/usr/share/doc`; the exact engine's upstream LICENSE and NOTICE are also
  retained under `/usr/share/doc/docker-ce`.
- **Docker Desktop:** this is a separately installed prerequisite for the
  Docker Desktop distribution of NIPAT. It is not included in that package
  and is governed by its own terms.

This inventory describes the principal components; it is not a replacement
for the license and notice files of every dependency in a runtime image.

## Redistribution and release records

Distribute this notice, the root LICENSE and the original third-party license
files with both Windows delivery formats. The release's source commit identifies
the matching NIPAT source, including launcher and build scripts, at
<https://github.com/GregorioDalia/nipat-desktop>.

For binary runtime components, retain the notices for the exact distributed
versions and provide corresponding source wherever their licenses require it.
A component list or a Dockerfile alone does not replace that source. Maintain
source availability together with the release assets rather than relying on
temporary CI artifacts.

Changing the license of a future release does not revoke rights already granted
for copies distributed under the GPL while its conditions are met. Any future
alternative licensing must account for the rights of all relevant contributors
and the separate terms of third-party components.

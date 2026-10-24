# SignPath Foundation application preparation

This document contains project information for an application to the
[SignPath Foundation program](https://signpath.org/apply.html). It does not
represent an application already submitted or approval by the Foundation.

## Project information

| Field | Proposed content |
| --- | --- |
| Project name | NIPAT |
| Repository | https://github.com/GregorioDalia/nipat-desktop |
| Release page | https://github.com/GregorioDalia/nipat-desktop/releases |
| License | GPL-3.0-or-later for original NIPAT material; bundled third-party components retain their documented licenses. |
| Maintainer | Gregorio Dalia, GitHub `GregorioDalia`. |
| Build system | GitHub Actions, GitHub-hosted Windows and Ubuntu runners. |
| Windows installer | Inno Setup EXE, with a C# launcher and WSL prerequisite helper. |
| Signing scope | First-party Windows executables and PowerShell scripts; installer and uninstaller. |

Suggested project description:

> NIPAT is an open-source research application that provides guided command-line
> access to DNPcall, SNPcall, contamination estimation and combined paternity
> index workflows. Its scientific implementation remains in R. On Windows,
> a per-user installer prepares a dedicated WSL2 environment containing Docker
> Engine and a versioned scientific image. Users select local input files and
> output directories. Scientific analyses run in containers with networking
> disabled. The installer may request administrative approval to enable missing
> Windows prerequisites. The project also provides a native Ubuntu package.
> Windows code signing is needed to identify the distributor and support
> execution with Smart App Control enabled.

## Information the maintainer must confirm

- Contact email for the application and the identity used to register.
- MFA for each person with relevant GitHub and SignPath access.
- Named authors, reviewers and signing approvers, including the review process.
- Current compliance of the application and included components with the
  Foundation's licensing and distribution conditions.
- Evidence of active maintenance, existing releases and project reputation.
  Eligibility is assessed by the Foundation; acceptance is not guaranteed.
- Agreement to the Foundation's terms and the certificate publisher identity.

Do not add private contact information, credentials or identity documents to
this file. Complete these fields in the provider's application process.

## Integration after approval

Obtain the approved organization ID, project and artifact-configuration slugs,
signing-policy slug and publisher certificate subject. Configure the GitHub
integration only for this repository and the required signing operations.
Keep API credentials in protected GitHub secrets. Require explicit approval
for production signing and bind requests to reviewed commits and build artifacts.

The build must sign internal components before packaging and sign the final
installer before computing release checksums. The PowerShell signing path must
preserve the separate provenance of reviewed source and signed payload.
Retain and verify the signed uninstaller as well as the launcher and helper.
See [Windows signing](../docs/FIRMA_WINDOWS.md) for the verification boundary.

No placeholder organization IDs, tokens or signing requests are installed in
the build. A production signing policy and signature publication gate must be
configured and tested before a package is described as signed.

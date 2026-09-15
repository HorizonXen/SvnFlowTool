# Public release checklist

1. Run `python3 scripts/check_public_tree.py` and the focused tests.
2. Review `git ls-files`; reports, logs, workbooks, local preferences, archives, vendored runtimes and Penpot account metadata must not be present.
3. Run `packaging/build-release.sh`. This creates a trial package only and never updates the delivery directory.
4. Trial the exact package. Only after the human trial passes, run `packaging/approve-trial.sh` to bind approval to its version, build and SHA-256.
5. Run `packaging/publish-approved-release.sh`. Publishing fails when approval is absent or the package changed after approval.
6. Push a matching `v*` tag, or run `Build release packages` manually. Clean CI runners build macOS and Windows artifacts from the same `release.json`; a tag run uploads both platform packages, checksums, installers and `release.json` to one GitHub Release.
7. Sign and notarize the macOS application; sign the Windows package before presenting either artifact as a stable public release.
8. Publish SHA-256 checksums and a concise list of platform-specific limitations.
9. Re-run a secret-history scanner before pushing an existing repository or force-updated branch.

No open-source license has been selected yet. Do not publish the source as an open-source project until the copyright holder chooses a license and confirms the provenance of adapted code.

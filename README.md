# Quantum Kaggle submission archive

Repository for the original `submission.zip` produced for Google Verifiable Quantum Circuit Compilation.

- Original filename: `submission.zip`
- Size: **73,818,680 bytes**
- SHA-256: `04cf2fc7518e9cc2f9207f61b9421448a0b02368756c6b342fb4cea8c47b0f43`

## Upload from a browser

GitHub's browser uploader limits individual files to 25 MiB. Upload the four `submission.zip.partNN` files (each at most 20 MiB) to the repository, together with the manifest and restoration script already stored here.

## Restore

```sh
python3 restore.py
```

The script joins the four pieces in order and verifies every part plus the reconstructed ZIP using SHA-256.

For Git command-line users, the unsplit ZIP (73.8 MB) can instead be committed directly; GitHub will warn for files over 50 MiB but accepts regular Git files below its 100 MiB hard limit. An attached GitHub Release asset avoids storing the ZIP in Git history.

---
name: pdf-processing
description: Extracts text and tables from PDF files, fills PDF forms, and merges PDFs. Use when the user mentions PDFs, forms, or document extraction.
license: Apache-2.0
compatibility: Requires python3 and pdftotext; no network access needed.
metadata:
  author: example-org
  version: "1.0"
allowed-tools: Bash(pdftotext:*) Read
---

# PDF processing

1. Run `scripts/extract.py input.pdf` to dump the text.
2. For form fields see [the reference guide](references/FORMS.md).

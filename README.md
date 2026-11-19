# driver_discovery_m

Call-driver discovery pipeline with unsupervised clustering, supervised classification, feedback tools, and a checking app.

See [doc/README.md](doc/README.md) for setup and pipeline documentation.

Step 1 reuses `unsupervised/step1_extraction/result/extractions.json` when available unless `--refresh` is supplied. Existing caches and generated results are retained in the local workspace and are not included in this public repository.

Raw input data, credentials, virtual environments, and Python bytecode caches are excluded from this repository.

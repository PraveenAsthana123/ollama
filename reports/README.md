# Reports

The JSONL audit contains bounded health checks for the catalog. Generated
output samples are short synthetic greetings; no user prompts or secrets are
included. `not_load_tested` means the model exceeded the conservative 6.1 GB
GPU-fit threshold, not that the model is broken.

Known failed tags from the captured audit:

- `kivi:local`: manifest resolved through the merged catalog but Ollama reported
  the model as unavailable; keep it out of automatic routing.
- `SparkLLM/Spark-X2.5-1.7B:latest`: installed Ollama does not recognize the
  `spark2_5` architecture.

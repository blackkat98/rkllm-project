# Models folder

Put `.rkllm` model files here (converted for **RK3588**, runtime **1.2.0**). The folder is
mounted read-only into the backend container at `/models` and is never baked into the image.
You can point it somewhere else with `MODELS_DIR` in `deploy/.env`, e.g. an NVMe path.

After you copy files in, open **Admin → Models → Rescan**. New models show up disabled
until an admin enables them.

* Size policy: files over `MAX_MODEL_FILE_GB` (2.8 GB by default, about 2B parameters at w8a8)
  are marked `too_large` and can't be enabled.
* Optional `models.yaml` (see `deploy/models.example.yaml`) sets the display name,
  template family, context length and sampling on the first scan.
* Optional `<model-name>.tokenizer.json` next to a model gives exact token counts for
  memory management.

Models converted for 1.2.0: https://huggingface.co/thanhtantran

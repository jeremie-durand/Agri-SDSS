# SOM research reference

Provenance for the production SOM model in
[`som_ml_backend.py`](../som_ml_backend.py), the Colab work the RandomForest
pipeline was derived from, kept so the method behind the published results stays
traceable.

## `som_ml_algorithm_reference.ipynb`

Three Colab sessions concatenated (`RS_FinalVersion_Jan2026`, `کد پیشرفته`,
`Jadid-30Jan2026`), originally exported as a single 3.7k-line `.py` under
`gis-pipeline/scripts/` and converted back to a notebook here.

Reference only — not executable as-is and not part of any code path:

- Paths point at Colab's `/content/`, so the inputs are not present here.
- Nothing in the repo imports it, and `**/research/` is in `.dockerignore`, so
  it is excluded from every image build.

Changing the production model means changing `som_ml_backend.py`. This notebook
records how that model was arrived at; it does not define it.

"""Import / export of manufacturing master data (M1-DESIGN 8, WP-B): pure, no FastAPI/SQLAlchemy.

- `read.read_upload(bytes)` -> staged raw sheets (xlsx / csv / zip of csv, with every limit of M 8.3 / R4),
- `mapping.suggest_mapping` / `mapping.apply_mapping` -> `MfgBundle` rows with their source positions,
- `plan.plan_import(bundle, dataset, options)` -> `ImportPlan` (pure diff by natural keys),
- `export.bundle_to_xlsx` / `export.bundle_to_csv_zip` / `export.template_bundle`.
"""

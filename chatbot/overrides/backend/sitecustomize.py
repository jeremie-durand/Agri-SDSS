"""
Auto-imported by Python at startup (PYTHONPATH=/app).
Patches MODIS NDVI rendering to use a vegetation-focused rescale range so
that real NDVI values (0–9000) spread properly across the rdylgn colormap
instead of being compressed into the yellow mid-band.
"""


def _patch_ndvi_rendering() -> None:
    try:
        from hybrid_rendering_system import EXPLICIT_RENDER_CONFIGS

        for cid in ("modis-13Q1-061", "modis-13A1-061"):
            if cid in EXPLICIT_RENDER_CONFIGS:
                cfg = EXPLICIT_RENDER_CONFIGS[cid]
                cfg.rescale = (0.0, 9000.0)
                cfg.colormap = "rdylgn"
    except Exception:
        pass  # upstream not yet imported — safe to skip, patch is idempotent


_patch_ndvi_rendering()

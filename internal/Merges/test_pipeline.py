from engine.mcp.comms_framework import _build_default_pipeline
print(len(_build_default_pipeline()._interceptors))

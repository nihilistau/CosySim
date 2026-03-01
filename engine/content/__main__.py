"""engine/content/__main__.py — Run content seeding via ``python -m engine.content``."""
from engine.content.seed_all import seed_content_engine, seed_nexus_qa

seed_content_engine()
seed_nexus_qa()

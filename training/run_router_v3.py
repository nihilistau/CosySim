"""Trigger router_v3 finetuning via RouterFinetuneCycle."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from engine.nexus.router_finetune_cycle import RouterFinetuneCycle

cycle = RouterFinetuneCycle()
print("Preparing splits...")
info = cycle.prepare_splits()
print(f"Train: {info['train']}, Val: {info['val']}")
print("Starting training job...")
result = cycle.run(dry_run=False)
print(f"Done: {result}")

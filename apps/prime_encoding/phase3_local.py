#!/usr/bin/env python3
"""
Phase 3 Local — Real Language Modelling on RTX 2060
=====================================================

Adapted from PrimePE_Phase3_H100.ipynb for local execution on RTX 2060 (12GB).
Same experiments (perplexity at long context, lost-in-the-middle), smaller scale.

Version: v0.3.0-local [2026-03-27]
Author:  CosySim Research

Model: 6 layers, d=256, 8 heads (~15M params)
Data:  WikiText-103
Tests: Perplexity at 512/1K/2K/4K, Lost-in-the-Middle benchmark

Usage:
    python apps/prime_encoding/phase3_local.py                # Full run (~2h)
    python apps/prime_encoding/phase3_local.py --quick         # Smoke test (~20min)
    python apps/prime_encoding/phase3_local.py --steps 1000    # Custom steps
"""
from __future__ import annotations

import argparse
import gc
import json
import math
import os
import sys
import time
from itertools import cycle
from pathlib import Path
from typing import Any, Dict, List, Optional

import torch
import torch.nn as nn
import torch.nn.functional as F

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT / "apps"))

RESULTS_DIR = ROOT / "apps" / "prime_encoding" / "results" / "phase3"


# ──── Configuration ──────────────────────────────────────────────────────────

def get_config(quick: bool = False, steps: int = 0) -> Dict[str, Any]:
    """Build config scaled for RTX 2060 (12GB VRAM)."""
    return {
        # Model (scaled down from H100 notebook)
        "d_model":    256,
        "n_heads":    8,
        "n_layers":   6,
        "ffn_dim":    1024,
        "dropout":    0.1,
        "vocab_size": 50257,  # GPT-2 tokenizer

        # Training
        "max_steps":    500 if quick else (steps or 5000),
        "batch_size":   4,
        "grad_accum":   2,  # effective batch = 8
        "lr":           3e-4,
        "warmup_steps": 200 if not quick else 50,
        "weight_decay": 0.1,
        "train_seq_len": 512,

        # Evaluation context lengths
        "eval_seq_lens": [512, 1024, 2048] if quick else [512, 1024, 2048, 4096],
        "eval_batches":  10 if quick else 30,

        # PE variants to test
        "pe_variants": ["sinusoidal", "prime_05", "prime_10", "zeta", "hybrid",
                        "hybrid_70z", "hybrid_90z"],

        # Lost-in-the-middle
        "litm_ctx_lens": [512, 1024, 2048] if quick else [512, 1024, 2048, 4096],
        "litm_fracs":    [0.1, 0.25, 0.5, 0.75, 0.9],
        "litm_trials":   50 if quick else 200,

        "results_dir":  str(RESULTS_DIR),
    }


# ──── PE Frequency Generators ────────────────────────────────────────────────

from prime_encoding.primes import (
    first_n_primes,
    ZETA_ZEROS_IMAGINARY,
)


def make_frequencies(pe_type: str, d_model: int) -> torch.Tensor:
    """Generate frequency tensor for a given PE type."""
    half = d_model // 2

    if pe_type == "sinusoidal":
        return torch.exp(torch.arange(0, half, dtype=torch.float) * -(math.log(10000.0) / d_model))

    elif pe_type == "prime_05":
        primes = first_n_primes(half)
        return torch.tensor([1.0 / (p ** 0.5) for p in primes], dtype=torch.float)

    elif pe_type == "prime_10":
        primes = first_n_primes(half)
        return torch.tensor([1.0 / float(p) for p in primes], dtype=torch.float)

    elif pe_type == "zeta":
        zeros = ZETA_ZEROS_IMAGINARY[:half]
        if len(zeros) < half:
            # Extend with scaled primes
            extra = first_n_primes(half - len(zeros))
            last = zeros[-1] if zeros else 100.0
            zeros = list(zeros) + [last + p for p in extra]
        freqs = torch.tensor([1.0 / z for z in zeros[:half]], dtype=torch.float)
        return freqs / freqs.max()  # normalize

    elif pe_type == "hybrid":
        # Fix: normalise each band to [0,1] BEFORE merging, then interleave
        # so prime and zeta frequencies cover the same magnitude range
        quarter = half // 2
        primes = first_n_primes(quarter)
        prime_f = torch.tensor([1.0 / (p ** 0.8) for p in primes])
        prime_f = prime_f / prime_f.max()  # normalise to [0, 1]

        n_zeta = half - quarter
        zeros = list(ZETA_ZEROS_IMAGINARY[:n_zeta])
        if len(zeros) < n_zeta:
            extra = first_n_primes(n_zeta - len(zeros))
            last = zeros[-1] if zeros else 100.0
            zeros.extend([last + p for p in extra])
        zeta_f = torch.tensor([1.0 / z for z in zeros[:n_zeta]])
        zeta_f = zeta_f / zeta_f.max()  # normalise to [0, 1]

        # Interleave: alternate prime and zeta at each scale
        combined = torch.zeros(half)
        for i in range(quarter):
            combined[2 * i] = prime_f[i]
            if i < n_zeta:
                combined[2 * i + 1] = zeta_f[i]
        # Fill any remaining slots
        idx = 2 * quarter
        for i in range(quarter, n_zeta):
            if idx < half:
                combined[idx] = zeta_f[i]
                idx += 1

        return combined

    elif pe_type.startswith("hybrid_") and pe_type[-1] == "z":
        # Weighted hybrid: hybrid_70z = 70% zeta, 30% prime
        # Tests whether prime is contributing or fighting
        zeta_pct = int(pe_type.replace("hybrid_", "").replace("z", "")) / 100.0
        prime_pct = 1.0 - zeta_pct
        n_zeta = int(half * zeta_pct)
        n_prime = half - n_zeta

        primes = first_n_primes(n_prime)
        prime_f = torch.tensor([1.0 / (p ** 0.8) for p in primes])
        prime_f = prime_f / prime_f.max()

        zeros = list(ZETA_ZEROS_IMAGINARY[:n_zeta])
        if len(zeros) < n_zeta:
            extra = first_n_primes(n_zeta - len(zeros))
            last = zeros[-1] if zeros else 100.0
            zeros.extend([last + p for p in extra])
        zeta_f = torch.tensor([1.0 / z for z in zeros[:n_zeta]])
        zeta_f = zeta_f / zeta_f.max()

        # Interleave: distribute the minority band evenly across the majority
        combined = torch.zeros(half)
        pi, zi = 0, 0
        for i in range(half):
            # Decide which band to pull from based on target ratio
            prime_target = (i + 1) * prime_pct
            zeta_target = (i + 1) * zeta_pct
            if pi < n_prime and (zi >= n_zeta or pi < prime_target):
                combined[i] = prime_f[pi]
                pi += 1
            elif zi < n_zeta:
                combined[i] = zeta_f[zi]
                zi += 1
        return combined

    elif pe_type == "hybrid_v1":
        # Original stratified hybrid (kept for comparison — shows +11.1% degradation)
        quarter = half // 2
        primes = first_n_primes(quarter)
        prime_f = [1.0 / (p ** 0.8) for p in primes]
        n_zeta = half - quarter
        zeros = list(ZETA_ZEROS_IMAGINARY[:n_zeta])
        if len(zeros) < n_zeta:
            extra = first_n_primes(n_zeta - len(zeros))
            last = zeros[-1] if zeros else 100.0
            zeros.extend([last + p for p in extra])
        zeta_f = [1.0 / z for z in zeros[:n_zeta]]
        combined = sorted(prime_f + zeta_f, reverse=True)
        while len(combined) < half:
            combined.append(combined[-1] * 0.9)
        max_f = max(combined)
        return torch.tensor(combined[:half], dtype=torch.float) / max_f

    raise ValueError(f"Unknown PE type: {pe_type}")


# ──── Model ──────────────────────────────────────────────────────────────────

class Phase3Model(nn.Module):
    """Transformer LM with swappable PE for Phase 3 experiments."""

    def __init__(self, cfg: Dict, pe_type: str) -> None:
        super().__init__()
        d = cfg["d_model"]
        self.d_model = d
        self.pe_type = pe_type

        self.tok_emb = nn.Embedding(cfg["vocab_size"], d)
        self.drop = nn.Dropout(cfg["dropout"])

        # PE
        freqs = make_frequencies(pe_type, d)
        self.register_buffer("freqs", freqs)

        # Transformer
        layer = nn.TransformerEncoderLayer(
            d_model=d, nhead=cfg["n_heads"], dim_feedforward=cfg["ffn_dim"],
            dropout=cfg["dropout"], activation="gelu", batch_first=True, norm_first=True,
        )
        self.transformer = nn.TransformerEncoder(layer, num_layers=cfg["n_layers"])
        self.ln_f = nn.LayerNorm(d)
        self.lm_head = nn.Linear(d, cfg["vocab_size"], bias=False)

        # Weight tying
        self.lm_head.weight = self.tok_emb.weight
        self._init()

    def _init(self) -> None:
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def _make_pe(self, seq_len: int) -> torch.Tensor:
        pos = torch.arange(seq_len, device=self.freqs.device, dtype=torch.float).unsqueeze(1)
        angles = pos * self.freqs.unsqueeze(0)
        pe = torch.zeros(seq_len, self.d_model, device=self.freqs.device)
        pe[:, 0::2] = torch.sin(angles)
        pe[:, 1::2] = torch.cos(angles)
        return pe

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T = x.shape
        h = self.tok_emb(x) * math.sqrt(self.d_model)
        h = h + self._make_pe(T).unsqueeze(0)
        h = self.drop(h)

        # Causal mask
        mask = nn.Transformer.generate_square_subsequent_mask(T, device=x.device)
        h = self.transformer(h, mask=mask, is_causal=True)
        h = self.ln_f(h)
        return self.lm_head(h)

    def count_params(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)


# ──── Data ───────────────────────────────────────────────────────────────────

_data_cache: Dict[str, torch.Tensor] = {}


def load_data(seq_len: int, split: str = "train", max_tokens: int = 2_000_000) -> torch.Tensor:
    """Load WikiText-103, tokenize a subset, chunk into sequences.

    Uses a token cap to avoid OOM on machines with limited RAM.
    Caches tokenized data per split to avoid re-downloading.

    Args:
        seq_len: Sequence length for chunking.
        split: Dataset split (train/test/validation).
        max_tokens: Maximum tokens to use (2M = ~8MB, safe for 12GB VRAM).

    Returns:
        Tensor of shape (n_chunks, seq_len + 1).
    """
    cache_key = f"{split}_{max_tokens}"

    if cache_key not in _data_cache:
        from datasets import load_dataset
        from transformers import GPT2TokenizerFast

        print(f"  Loading WikiText-103 ({split})...", end=" ", flush=True)
        raw = load_dataset("wikitext", "wikitext-103-raw-v1", split=split, trust_remote_code=True)
        tok = GPT2TokenizerFast.from_pretrained("gpt2")
        tok.pad_token = tok.eos_token

        # Tokenize in batches to avoid huge memory spike
        all_ids: List[int] = []
        for row in raw:
            text = row["text"]
            if text.strip():
                all_ids.extend(tok.encode(text))
                if len(all_ids) >= max_tokens:
                    break

        _data_cache[cache_key] = torch.tensor(all_ids[:max_tokens], dtype=torch.long)
        print(f"{len(_data_cache[cache_key]):,} tokens cached")

    ids = _data_cache[cache_key]
    n = (len(ids) // (seq_len + 1)) * (seq_len + 1)
    chunks = ids[:n].reshape(-1, seq_len + 1)
    print(f"  Chunked: {chunks.shape[0]} x {seq_len + 1}")
    return chunks


# ──── Training ───────────────────────────────────────────────────────────────

def cosine_lr(step: int, cfg: Dict) -> float:
    if step < cfg["warmup_steps"]:
        return cfg["lr"] * step / max(1, cfg["warmup_steps"])
    t = (step - cfg["warmup_steps"]) / max(1, cfg["max_steps"] - cfg["warmup_steps"])
    return cfg["lr"] * 0.5 * (1 + math.cos(math.pi * t))


@torch.no_grad()
def evaluate_ppl(model: nn.Module, data: torch.Tensor, n_batches: int, device: torch.device) -> float:
    """Compute perplexity on data chunks."""
    model.eval()
    losses = []
    for i in range(min(n_batches, len(data))):
        chunk = data[i].unsqueeze(0).to(device)
        x, y = chunk[:, :-1], chunk[:, 1:]
        logits = model(x)
        loss = F.cross_entropy(logits.view(-1, logits.size(-1)), y.reshape(-1))
        losses.append(loss.item())
    return math.exp(sum(losses) / len(losses)) if losses else float("inf")


def train_variant(pe_type: str, cfg: Dict) -> Dict[str, Any]:
    """Train one PE variant and evaluate at multiple context lengths."""
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"\n{'='*60}")
    print(f"  Training: {pe_type} on {device}")
    print(f"{'='*60}")

    torch.manual_seed(42)
    model = Phase3Model(cfg, pe_type).to(device)
    print(f"  Params: {model.count_params():,}")

    optimizer = torch.optim.AdamW(model.parameters(), lr=cfg["lr"], weight_decay=cfg["weight_decay"])
    scaler = torch.amp.GradScaler("cuda") if device.type == "cuda" else None

    # Load training data
    train_data = load_data(cfg["train_seq_len"], "train")
    train_loader = cycle(range(len(train_data)))

    t0 = time.time()
    loss_history = []

    for step in range(1, cfg["max_steps"] + 1):
        model.train()
        optimizer.zero_grad()

        accum_loss = 0.0
        for _ in range(cfg["grad_accum"]):
            idx = next(train_loader)
            chunk = train_data[idx].unsqueeze(0).to(device)
            x, y = chunk[:, :-1], chunk[:, 1:]

            if scaler:
                with torch.amp.autocast("cuda", dtype=torch.bfloat16):
                    logits = model(x)
                    loss = F.cross_entropy(logits.view(-1, logits.size(-1)), y.reshape(-1))
                    loss = loss / cfg["grad_accum"]
                scaler.scale(loss).backward()
            else:
                logits = model(x)
                loss = F.cross_entropy(logits.view(-1, logits.size(-1)), y.reshape(-1))
                loss = loss / cfg["grad_accum"]
                loss.backward()

            accum_loss += loss.item()

        if scaler:
            scaler.unscale_(optimizer)
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            scaler.step(optimizer)
            scaler.update()
        else:
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            optimizer.step()

        # Update LR
        lr = cosine_lr(step, cfg)
        for g in optimizer.param_groups:
            g["lr"] = lr

        loss_history.append(accum_loss)

        if step % 500 == 0 or step == cfg["max_steps"]:
            elapsed = time.time() - t0
            ppl = evaluate_ppl(model, train_data[:100], 20, device)
            print(f"  step {step:>5}/{cfg['max_steps']}  loss={accum_loss:.4f}  "
                  f"ppl={ppl:.1f}  lr={lr:.2e}  [{elapsed:.0f}s]")

    # ── Long-context perplexity evaluation ──
    print(f"\n  Evaluating perplexity at different context lengths...")
    ppl_results = {}
    for seq_len in cfg["eval_seq_lens"]:
        try:
            test_data = load_data(seq_len, "test")
            ppl = evaluate_ppl(model, test_data, cfg["eval_batches"], device)
            ppl_results[seq_len] = ppl
            print(f"    ctx={seq_len:>5}: ppl={ppl:.2f}")
        except Exception as e:
            print(f"    ctx={seq_len:>5}: FAILED ({e})")
            ppl_results[seq_len] = None

    # ── Lost-in-the-Middle benchmark ──
    print(f"\n  Running Lost-in-the-Middle benchmark...")
    litm_results = lost_in_the_middle(model, cfg, device)
    for ctx_len, fracs in litm_results.items():
        summary = ", ".join(f"{f:.1f}:{a:.3f}" for f, a in sorted(fracs.items()))
        print(f"    ctx={ctx_len}: {summary}")

    # ── Attention Distance Probe ──
    # Measures mean attended distance per frequency band (zeta vs prime dims)
    # This is the experiment that validates the scale decomposition hypothesis
    print(f"\n  Running attention distance probe...")
    probe_results = attention_distance_probe(model, cfg, device)
    if probe_results:
        for band, dist in sorted(probe_results.items()):
            print(f"    {band}: mean_dist={dist:.1f} tokens")

    elapsed = time.time() - t0
    print(f"\n  Total time: {elapsed:.0f}s")

    # Cleanup
    del model, optimizer
    if scaler:
        del scaler
    torch.cuda.empty_cache()
    gc.collect()

    return {
        "pe_type": pe_type,
        "loss_history": loss_history[-10:],  # last 10 losses
        "final_loss": loss_history[-1] if loss_history else 0,
        "ppl_by_ctx": ppl_results,
        "litm": litm_results,
        "attention_probe": probe_results,
        "train_time_secs": elapsed,
        "params": cfg["d_model"] * cfg["n_layers"],  # rough
    }


# ──── Attention Distance Probe ───────────────────────────────────────────────
# The critical experiment: do zeta-frequency dimensions attend at longer range
# than prime-frequency dimensions? If yes, the scale decomposition is real.

@torch.no_grad()
def attention_distance_probe(
    model: nn.Module,
    cfg: Dict,
    device: torch.device,
    n_batches: int = 50,
    seq_len: int = 512,
) -> Dict[str, float]:
    """Measure mean attended distance per frequency band.

    For hybrid models: splits dimensions into "zeta band" and "prime band"
    based on which frequency generator produced them. Computes the average
    distance each band attends to.

    For non-hybrid models: splits dimensions into "low freq" (bottom half)
    and "high freq" (top half) to see if frequency magnitude correlates
    with attention distance.

    Args:
        model: Trained model to probe.
        cfg: Config dict.
        device: Compute device.
        n_batches: Number of batches to average over.
        seq_len: Sequence length for probing.

    Returns:
        Dict mapping band name → mean attended distance.
    """
    model.eval()
    pe_type = model.pe_type

    # We need attention weights — hook into the transformer layers
    attn_distances: Dict[str, List[float]] = {}
    hooks = []

    def make_hook(layer_idx: int):
        def hook_fn(module, input, output):
            # nn.TransformerEncoderLayer doesn't directly expose attention weights
            # So we compute attention from the self_attn sublayer
            pass
        return hook_fn

    # Alternative approach: compute attention manually from the model
    # by running a forward pass and extracting Q, K from the self-attention layers
    try:
        train_data = load_data(seq_len, "test", max_tokens=500_000)
    except Exception:
        return {}

    d_model = cfg["d_model"]
    half = d_model // 2

    # Determine band assignments based on PE type
    if "hybrid" in pe_type or pe_type in ("hybrid_70z", "hybrid_90z"):
        # For hybrid: determine which dimensions are zeta vs prime
        # In the interleaved scheme, even indices are prime, odd are zeta (for 50/50)
        # For weighted: we know the ratio from the pe_type
        if "90z" in pe_type:
            n_prime = int(half * 0.1)
        elif "70z" in pe_type:
            n_prime = int(half * 0.3)
        else:
            n_prime = half // 2
        n_zeta = half - n_prime
        # In interleaved layout, prime and zeta alternate
        prime_dims = list(range(0, min(2 * n_prime, half), 2))  # even positions up to n_prime
        zeta_dims = [i for i in range(half) if i not in prime_dims]
        band_map = {"zeta_band": zeta_dims, "prime_band": prime_dims}
    else:
        # For non-hybrid: split by frequency magnitude (low = long range, high = short range)
        band_map = {
            "low_freq (long-range)": list(range(half // 2, half)),
            "high_freq (short-range)": list(range(0, half // 2)),
        }

    # Compute mean attended distance by examining model output sensitivity
    # Use a perturbation approach: for each position, measure how much the
    # output at other positions changes when we perturb this position's
    # PE in a specific band
    all_band_distances: Dict[str, List[float]] = {b: [] for b in band_map}

    for batch_idx in range(min(n_batches, len(train_data))):
        chunk = train_data[batch_idx].unsqueeze(0).to(device)
        x = chunk[:, :-1]
        T = x.shape[1]

        # Get baseline output
        with torch.amp.autocast("cuda", dtype=torch.bfloat16):
            base_logits = model(x)

        # For each band, perturb PE at a probe position and measure effect range
        probe_pos = T // 2  # probe from the middle
        pe_original = model._make_pe(T).clone()

        for band_name, dim_indices in band_map.items():
            # Perturb the PE at probe_pos for this band's dimensions
            pe_perturbed = pe_original.clone()
            for d in dim_indices:
                pe_perturbed[probe_pos, 2 * d] *= -1      # flip sin
                pe_perturbed[probe_pos, 2 * d + 1] *= -1  # flip cos

            # Forward with perturbed PE
            h = model.tok_emb(x) * math.sqrt(model.d_model)
            h = h + pe_perturbed.unsqueeze(0)
            h = model.drop(h)
            mask = nn.Transformer.generate_square_subsequent_mask(T, device=device)

            with torch.amp.autocast("cuda", dtype=torch.bfloat16):
                h = model.transformer(h, mask=mask, is_causal=True)
                h = model.ln_f(h)
                perturbed_logits = model.lm_head(h)

            # Measure where the perturbation has the most effect
            diff = (perturbed_logits - base_logits).abs().mean(dim=-1).squeeze(0)  # (T,)

            # Compute mean affected distance from probe_pos, weighted by effect magnitude
            distances = torch.arange(T, device=device, dtype=torch.float) - probe_pos
            distances = distances.abs()
            if diff.sum() > 1e-8:
                mean_dist = (diff * distances).sum() / diff.sum()
                all_band_distances[band_name].append(mean_dist.item())

    # Average across batches
    results = {}
    for band_name, dists in all_band_distances.items():
        if dists:
            results[band_name] = sum(dists) / len(dists)

    return results


# ──── Lost-in-the-Middle ────────────────────────────────────────────────────

@torch.no_grad()
def lost_in_the_middle(model: nn.Module, cfg: Dict, device: torch.device) -> Dict:
    """Synthetic needle retrieval at various context positions.

    Place a rare token at fraction frac of context, fill rest with common tokens.
    Check if the model assigns higher probability to the needle token at the
    needle position vs random positions.
    """
    model.eval()
    results: Dict[int, Dict[float, float]] = {}

    # Use specific tokens
    NEEDLE = 50250   # rare token (beyond common vocab)
    FILLER_START = 1000
    FILLER_END = 2000

    for ctx_len in cfg["litm_ctx_lens"]:
        if ctx_len > 4096:
            continue  # skip if too long for VRAM
        frac_results: Dict[float, float] = {}

        for frac in cfg["litm_fracs"]:
            correct = 0
            total = cfg["litm_trials"]

            for trial in range(total):
                # Build sequence: filler tokens with a needle at position frac*ctx_len
                seq = torch.randint(FILLER_START, FILLER_END, (ctx_len,))
                needle_pos = max(1, min(int(frac * ctx_len), ctx_len - 2))
                seq[needle_pos] = NEEDLE

                x = seq[:-1].unsqueeze(0).to(device)
                y = seq[1:].unsqueeze(0).to(device)

                try:
                    with torch.amp.autocast("cuda", dtype=torch.bfloat16):
                        logits = model(x)

                    # Check: does the model predict NEEDLE at needle_pos?
                    # We check if needle token is in top-10 predictions at (needle_pos - 1)
                    if needle_pos > 0:
                        pred_pos = needle_pos - 1  # predict token at needle_pos from position needle_pos-1
                        top_k = logits[0, pred_pos].topk(10).indices
                        if NEEDLE in top_k:
                            correct += 1
                except RuntimeError:
                    # OOM or other CUDA error — skip this context length
                    break

            frac_results[frac] = correct / max(total, 1)

        results[ctx_len] = frac_results

    return results


# ──── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Phase 3 Local — Real LM on RTX 2060")
    parser.add_argument("--quick", action="store_true", help="Smoke test (~20min)")
    parser.add_argument("--steps", type=int, default=0, help="Override training steps")
    parser.add_argument("--pe", type=str, default=None, help="Single PE variant to test")
    args = parser.parse_args()

    cfg = get_config(quick=args.quick, steps=args.steps)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    print(f"\n  Phase 3 Local — PrimePE Real Language Modelling")
    print(f"  {'='*50}")
    print(f"  Model: {cfg['n_layers']}L, d={cfg['d_model']}, {cfg['n_heads']}H")
    print(f"  Steps: {cfg['max_steps']}, batch={cfg['batch_size']}x{cfg['grad_accum']}")
    print(f"  Eval: ctx={cfg['eval_seq_lens']}")
    print(f"  PE variants: {cfg['pe_variants']}")
    print()

    pe_list = [args.pe] if args.pe else cfg["pe_variants"]
    all_results = {}

    for pe in pe_list:
        result = train_variant(pe, cfg)
        all_results[pe] = result

        # Save after each variant (in case of crash)
        out_path = RESULTS_DIR / "phase3_results.json"
        with open(out_path, "w") as f:
            json.dump(all_results, f, indent=2, default=str)
        print(f"  Saved to {out_path}")

    # ── Summary Table ──
    print(f"\n{'='*70}")
    print(f"  PHASE 3 RESULTS — Perplexity by Context Length")
    print(f"{'='*70}")
    header = f"  {'PE':<16}"
    for l in cfg["eval_seq_lens"]:
        header += f"  ctx={l:<5}"
    print(header)
    print(f"  {'-' * (16 + 9 * len(cfg['eval_seq_lens']))}")

    for pe, r in all_results.items():
        row = f"  {pe:<16}"
        for l in cfg["eval_seq_lens"]:
            ppl = r["ppl_by_ctx"].get(l) or r["ppl_by_ctx"].get(str(l))
            if ppl is not None:
                row += f"  {ppl:>7.1f}"
            else:
                row += f"  {'---':>7}"
        print(row)

    print(f"\n  Lost-in-the-Middle (accuracy at position fraction 0.5):")
    print(f"  {'-' * 50}")
    for pe, r in all_results.items():
        litm = r.get("litm", {})
        mid_accs = []
        for ctx, fracs in litm.items():
            if isinstance(fracs, dict) and 0.5 in fracs:
                mid_accs.append(f"ctx={ctx}:{fracs[0.5]:.3f}")
        print(f"  {pe:<16} {', '.join(mid_accs)}")

    print()


if __name__ == "__main__":
    main()

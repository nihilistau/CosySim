"""
PrimePE — Local Validation Script
Version: v0.1.0 | Author: Knack | 2026-03-27

Change Log:
    v0.1.0 — Initial local test harness, mirrors H100 notebook logic

Runs a fast PE comparison on any GPU. Designed for RTX 2060 12GB.
Tests the key hypotheses without the full H100 training budget.

Usage:
    python local_test.py                    # full local run (~2-3 hrs)
    python local_test.py --quick            # smoke test (~15 min)
    python local_test.py --variants zeta sinusoidal random_irr   # specific PEs
    python local_test.py --test ppl         # just perplexity
    python local_test.py --test litm        # just lost-in-middle
    python local_test.py --test attn        # just attention distance probe
    python local_test.py --test zeta_rope   # Zeta-RoPE fine-tuning experiment
"""

# ── Imports ───────────────────────────────────────────────────────────────────
import argparse
import json
import math
import os
import time
import gc
from collections import defaultdict
from itertools import cycle
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# ─── Section: Config ──────────────────────────────────────────────────────────

def make_cfg(quick: bool = False, variants: list = None) -> dict:
    """Build config. Auto-scales to available VRAM."""
    vram = torch.cuda.get_device_properties(0).total_memory / 1e9 if torch.cuda.is_available() else 0
    gpu  = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    print(f"GPU: {gpu} ({vram:.0f}GB)")

    # Scale batch to VRAM
    if vram >= 20:
        batch, grad_accum = 4, 4
    elif vram >= 12:
        batch, grad_accum = 2, 8
    else:
        batch, grad_accum = 1, 16

    all_variants = [
        "sinusoidal",       # additive baseline
        "rope",             # rotary baseline
        "zeta",             # primary candidate
        "hybrid_90z",       # best local PPL (90% zeta / 10% prime)
        "hybrid_50z",       # comparison
        "prime_05",         # pure prime
        "random_irr",       # CRITICAL CONTROL — falsification test
        "random_irr_matched", # magnitude-matched random (isolates spacing vs magnitude)
        "learned",          # can the model discover zeta-like spacing?
        "zeta_rope",        # rotary with zeta frequencies
        "random_irr_rope",  # rotary control
        "position_shuffle", # ablation: does PE structure matter at all?
    ]

    return {
        # ── Model (small for local) ───────────────────────────────────────────
        "d_model":    256,
        "n_heads":    8,
        "n_layers":   6,
        "ffn_dim":    1024,
        "dropout":    0.1,
        "vocab_size": 50257,

        # ── Training ──────────────────────────────────────────────────────────
        "max_steps":    500  if quick else 3_000,
        "batch_size":   batch,
        "grad_accum":   grad_accum,
        "lr":           3e-4,
        "warmup_steps": 50   if quick else 300,
        "weight_decay": 0.01,
        "clip_grad":    1.0,
        "eval_every":   250,
        "train_seq_len": 512,

        # ── Eval ──────────────────────────────────────────────────────────────
        "eval_seq_lens":    [512, 1024, 2048] if quick else [512, 1024, 2048, 4096],
        "litm_context_len": 1024 if quick else 2048,
        "litm_positions":   [0.1, 0.25, 0.5, 0.75, 0.9],
        "litm_samples":     50   if quick else 200,

        # ── Variants ──────────────────────────────────────────────────────────
        "pe_variants": variants if variants else all_variants,

        # ── Runtime ───────────────────────────────────────────────────────────
        "use_compile": False,   # skip compile for local — not worth the warmup
        "dtype":       torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16,
        "device":      torch.device("cuda" if torch.cuda.is_available() else "cpu"),
        "results_dir": "./results",
        "seed":        42,
    }

# ─── Section: Frequencies ─────────────────────────────────────────────────────

ZETA_ZEROS = [
    14.134725, 21.022040, 25.010858, 30.424876, 32.935061,
    37.586178, 40.918719, 43.327073, 48.005150, 49.773832,
    52.970321, 56.446247, 59.347044, 60.831778, 65.112544,
    67.079810, 69.546401, 72.067157, 75.704691, 77.144840,
    79.337375, 82.910381, 84.735493, 87.425275, 88.809111,
    92.491899, 94.651344, 95.870634, 98.831194, 101.317851,
    103.725538, 105.446623, 107.168611, 111.029535, 111.874659,
    114.320220, 116.226680, 118.790782, 121.370125, 122.946829,
    124.256818, 127.516683, 129.578704, 131.087688, 133.497737,
    134.756509, 138.116042, 139.736209, 141.123707, 143.111845,
    146.000982, 147.422765, 150.053521, 150.925257, 153.024693,
    156.112909, 157.597591, 158.849988, 161.188964, 163.030709,
    165.537069, 167.184439, 169.094515, 169.911976, 173.411536,
    174.754191, 176.441434, 178.377407, 179.916484, 182.207078,
]

def get_primes(n: int) -> list:
    primes, c = [], 2
    while len(primes) < n:
        if all(c % p != 0 for p in primes):
            primes.append(c)
        c += 1
    return primes

def get_zeta_freqs(n: int) -> torch.Tensor:
    zz = list(ZETA_ZEROS[:n])
    while len(zz) < n:
        k = float(len(zz) + 1)
        zz.append((2 * math.pi * k) / (math.log(k) + 0.5))
    t = torch.tensor(zz[:n], dtype=torch.float32)
    return t / t[0]

def freq_spec(pe_name: str, d_model: int) -> dict:
    half = d_model // 2
    if pe_name == "sinusoidal":
        f = torch.exp(-torch.arange(0, half).float() * math.log(10000.0) / half)
        return {"type": "additive", "learnable": False, "freqs": f}
    elif pe_name == "rope":
        f = 1.0 / (10000 ** (torch.arange(0, half, 2).float() / half))
        return {"type": "rope", "learnable": False, "freqs": f}
    elif pe_name == "alibi":
        return {"type": "alibi", "learnable": False, "freqs": None}
    elif pe_name == "prime_05":
        p = torch.tensor(get_primes(half), dtype=torch.float32)
        return {"type": "additive", "learnable": False, "freqs": 1.0 / (p ** 0.5)}
    elif pe_name == "zeta":
        return {"type": "additive", "learnable": False, "freqs": get_zeta_freqs(half)}
    elif pe_name == "hybrid_90z":
        q_prime = max(1, half // 10)
        q_zeta  = half - q_prime
        p  = torch.tensor(get_primes(q_prime), dtype=torch.float32)
        pf = (1.0 / (p ** 0.75)) / (1.0 / (p ** 0.75)).max()
        zf = get_zeta_freqs(q_zeta) / get_zeta_freqs(q_zeta).max()
        pf_pad = pf.repeat(q_zeta // q_prime + 1)[:q_zeta]
        freqs = torch.stack([zf, pf_pad], dim=1).flatten()[:half]
        return {"type": "additive", "learnable": False, "freqs": freqs}
    elif pe_name == "hybrid_50z":
        q = half // 2
        p  = torch.tensor(get_primes(q), dtype=torch.float32)
        pf = (1.0 / (p ** 0.75))
        zf = get_zeta_freqs(q)
        pf = pf[pf.argsort(descending=True)] / pf.max()
        zf = zf[zf.argsort(descending=True)] / zf.max()
        return {"type": "additive", "learnable": False,
                "freqs": torch.stack([pf, zf], dim=1).flatten()}
    elif pe_name == "random_irr":
        p = torch.tensor(get_primes(half), dtype=torch.float32)
        freqs = p.sqrt().frac()
        return {"type": "additive", "learnable": False, "freqs": freqs / freqs.max()}
    elif pe_name == "random_irr_matched":
        # Magnitude-matched random: same numerical range as zeta, random spacing
        # Isolates whether advantage is from zeta structure or just lower magnitudes
        zf = get_zeta_freqs(half)
        torch.manual_seed(12345)
        freqs = torch.rand(half) * (zf.max() - zf.min()) + zf.min()
        return {"type": "additive", "learnable": False, "freqs": freqs.sort(descending=True).values}
    elif pe_name == "learned":
        f = 1.0 / (10000 ** (torch.arange(half).float() / half))
        return {"type": "additive", "learnable": True, "freqs": f}
    # ── RoPE variants ──
    elif pe_name == "zeta_rope":
        zf = get_zeta_freqs(half // 2)
        geo = 1.0 / (10000 ** (torch.arange(0, half // 2 * 2, 2).float() / (half // 2 * 2)))
        scale = geo.mean() / zf[:len(geo)].mean()
        freqs = (zf[:len(geo)] * scale)
        return {"type": "rope", "learnable": False, "freqs": freqs}
    elif pe_name == "random_irr_rope":
        # Critical RoPE control: random irrational rotation frequencies
        p = torch.tensor(get_primes(half // 2), dtype=torch.float32)
        geo = 1.0 / (10000 ** (torch.arange(0, half // 2 * 2, 2).float() / (half // 2 * 2)))
        rand_freqs = p.sqrt().frac()
        scale = geo.mean() / rand_freqs.mean()
        freqs = rand_freqs * scale
        return {"type": "rope", "learnable": False, "freqs": freqs}
    elif pe_name == "position_shuffle":
        # Ablation: standard sinusoidal but positions are randomly permuted
        # Tests whether PE structure matters at all, or just having *some* PE is enough
        f = torch.exp(-torch.arange(0, half).float() * math.log(10000.0) / half)
        return {"type": "additive", "learnable": False, "freqs": f, "shuffle": True}
    else:
        raise ValueError(f"Unknown PE: {pe_name}")

# ─── Section: Model ───────────────────────────────────────────────────────────

class AdditivePE(nn.Module):
    def __init__(self, d_model: int, freqs: torch.Tensor,
                 max_len: int = 8192, learnable: bool = False):
        super().__init__()
        half = d_model // 2
        freqs = freqs[:half]
        if learnable:
            self.freqs = nn.Parameter(freqs.clone())
        else:
            self.register_buffer("freqs", freqs)
        self.learnable = learnable
        if not learnable:
            pos = torch.arange(max_len).float().unsqueeze(1)
            phases = pos * freqs.unsqueeze(0)
            pe = torch.cat([torch.sin(phases), torch.cos(phases)], dim=-1)
            self.register_buffer("_cache", pe)
        else:
            self._cache = None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        T = x.size(1)
        if self.learnable or self._cache is None:
            pos = torch.arange(T, device=x.device).float().unsqueeze(1)
            phases = pos * self.freqs.unsqueeze(0)
            pe = torch.cat([torch.sin(phases), torch.cos(phases)], dim=-1)
        else:
            pe = self._cache[:T]
        return x + pe.unsqueeze(0).to(x.dtype)


class Attention(nn.Module):
    def __init__(self, d_model: int, n_heads: int, dropout: float,
                 attn_type: str = "standard",
                 rope_freqs=None, alibi_slopes=None):
        super().__init__()
        self.n_heads   = n_heads
        self.head_dim  = d_model // n_heads
        self.scale     = self.head_dim ** -0.5
        self.attn_type = attn_type
        self.qkv  = nn.Linear(d_model, 3 * d_model, bias=False)
        self.proj = nn.Linear(d_model, d_model, bias=False)
        self.drop = nn.Dropout(dropout)
        if rope_freqs is not None:
            self.register_buffer("rope_freqs", rope_freqs)
        if alibi_slopes is not None:
            self.register_buffer("alibi_slopes", alibi_slopes)

    def _rope(self, x: torch.Tensor) -> torch.Tensor:
        B, H, T, D = x.shape
        t = torch.arange(T, device=x.device).float()
        freqs = torch.outer(t, self.rope_freqs[:D//2])
        cos = freqs.cos()[None, None].to(x.dtype)
        sin = freqs.sin()[None, None].to(x.dtype)
        x1, x2 = x[..., 0::2], x[..., 1::2]
        return torch.stack([x1*cos - x2*sin, x1*sin + x2*cos], dim=-1).flatten(-2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape
        qkv = self.qkv(x).reshape(B, T, 3, self.n_heads, self.head_dim)
        q, k, v = qkv.permute(2, 0, 3, 1, 4).unbind(0)
        if self.attn_type == "rope":
            q, k = self._rope(q), self._rope(k)
        if self.attn_type == "alibi":
            pos  = torch.arange(T, device=x.device)
            dist = (pos.unsqueeze(0) - pos.unsqueeze(1)).abs().float()
            bias = -self.alibi_slopes.view(-1,1,1) * dist.unsqueeze(0)
            causal = torch.triu(torch.full((T,T), float("-inf"), device=x.device), diagonal=1)
            out = nn.functional.scaled_dot_product_attention(
                q, k, v, attn_mask=bias + causal, dropout_p=0.0)
        else:
            out = nn.functional.scaled_dot_product_attention(
                q, k, v, is_causal=True, dropout_p=0.0)
        return self.proj(self.drop(out.transpose(1,2).reshape(B, T, C)))


class Block(nn.Module):
    def __init__(self, d_model, n_heads, ffn_dim, dropout, attn_type, rope_freqs, alibi_slopes):
        super().__init__()
        self.attn  = Attention(d_model, n_heads, dropout, attn_type, rope_freqs, alibi_slopes)
        self.norm1 = nn.LayerNorm(d_model)
        self.norm2 = nn.LayerNorm(d_model)
        self.ffn   = nn.Sequential(
            nn.Linear(d_model, ffn_dim), nn.GELU(), nn.Dropout(dropout),
            nn.Linear(ffn_dim, d_model), nn.Dropout(dropout),
        )
    def forward(self, x):
        x = x + self.attn(self.norm1(x))
        x = x + self.ffn(self.norm2(x))
        return x


class PrimePEModel(nn.Module):
    """PrimePE transformer. Version: v0.1.0 | Author: Knack"""
    def __init__(self, cfg: dict, pe_name: str):
        super().__init__()
        self.pe_name = pe_name
        d = cfg["d_model"]
        spec = freq_spec(pe_name, d)

        self.embed      = nn.Embedding(cfg["vocab_size"], d)
        self.embed_drop = nn.Dropout(cfg["dropout"])
        self.shuffle_positions = spec.get("shuffle", False)
        self.pe = AdditivePE(d, spec["freqs"], learnable=spec.get("learnable", False)) \
                  if spec["type"] == "additive" else None

        atype = spec["type"] if spec["type"] != "additive" else "standard"
        rope_freqs   = spec["freqs"] if atype == "rope" else None
        alibi_slopes = None
        if atype == "alibi":
            n = cfg["n_heads"]
            alibi_slopes = torch.tensor([2**(-8*i/n) for i in range(1, n+1)])

        self.blocks = nn.ModuleList([
            Block(d, cfg["n_heads"], cfg["ffn_dim"], cfg["dropout"],
                  atype, rope_freqs, alibi_slopes)
            for _ in range(cfg["n_layers"])
        ])
        self.norm = nn.LayerNorm(d)
        self.head = nn.Linear(d, cfg["vocab_size"], bias=False)
        self.head.weight = self.embed.weight
        self._init()

    def _init(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, std=0.02)
                if m.bias is not None: nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Embedding):
                nn.init.normal_(m.weight, std=0.02)

    def forward(self, ids: torch.Tensor) -> torch.Tensor:
        d = self.embed.embedding_dim
        x = self.embed(ids) * math.sqrt(d)
        if self.pe:
            if self.shuffle_positions:
                # Position shuffle ablation: get PE then permute positions
                T = ids.shape[1]
                perm = torch.randperm(T, device=ids.device)
                if self.pe._cache is not None:
                    pe = self.pe._cache[:T][perm].unsqueeze(0).to(x.dtype)
                else:
                    pos = torch.arange(T, device=ids.device).float().unsqueeze(1)
                    phases = pos * self.pe.freqs.unsqueeze(0)
                    pe = torch.cat([torch.sin(phases), torch.cos(phases)], dim=-1)
                    pe = pe[perm].unsqueeze(0).to(x.dtype)
                x = x + pe
            else:
                x = self.pe(x)
        x = self.embed_drop(x)
        for block in self.blocks:
            x = block(x)
        return self.head(self.norm(x))

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

# ─── Section: Data ────────────────────────────────────────────────────────────

class ChunkDataset(Dataset):
    """Pre-tokenized chunks of text. Defined at module level for pickling."""
    def __init__(self, chunks: torch.Tensor):
        self.chunks = chunks
    def __len__(self): return len(self.chunks)
    def __getitem__(self, i):
        c = self.chunks[i]
        return c[:-1], c[1:]


def load_data(cfg: dict):
    from datasets import load_dataset
    from transformers import GPT2TokenizerFast
    print("Loading WikiText-103...")
    raw = load_dataset("wikitext", "wikitext-103-raw-v1")
    tok = GPT2TokenizerFast.from_pretrained("gpt2")
    tok.pad_token = tok.eos_token

    MAX_TOKENS = 4_000_000  # 4M tokens — plenty for training, fits in RAM

    def _tokenize(split, seq_len):
        all_ids = []
        for row in raw[split]:
            t = row["text"]
            if t.strip():
                all_ids.extend(tok.encode(t))
                if len(all_ids) >= MAX_TOKENS:
                    break
        ids = torch.tensor(all_ids[:MAX_TOKENS], dtype=torch.long)
        n   = (len(ids) // seq_len) * seq_len
        chunks = ids[:n].reshape(-1, seq_len)
        print(f"  {split}: {len(chunks)} chunks of {seq_len}")
        return chunks

    SL = cfg["train_seq_len"] + 1
    train_ds = ChunkDataset(_tokenize("train", SL))
    val_ds   = ChunkDataset(_tokenize("validation", SL))
    # num_workers=0 on Windows to avoid multiprocessing pickle issues
    train_loader = DataLoader(train_ds, batch_size=cfg["batch_size"], shuffle=True,
                              num_workers=0, pin_memory=True, drop_last=True)
    val_loader   = DataLoader(val_ds, batch_size=cfg["batch_size"], shuffle=False,
                              num_workers=0, pin_memory=True, drop_last=True)
    print(f"Train: {len(train_ds):,} | Val: {len(val_ds):,}")
    return train_loader, val_loader, ChunkDataset

# ─── Section: Training ────────────────────────────────────────────────────────

def cosine_lr(step, cfg):
    if step < cfg["warmup_steps"]:
        return cfg["lr"] * step / max(1, cfg["warmup_steps"])
    t = (step - cfg["warmup_steps"]) / max(1, cfg["max_steps"] - cfg["warmup_steps"])
    return cfg["lr"] * 0.5 * (1 + math.cos(math.pi * t))

@torch.no_grad()
def evaluate(model, loader, cfg, max_batches=80):
    model.eval()
    losses = []
    for i, (x, y) in enumerate(loader):
        if i >= max_batches: break
        x, y = x.to(cfg["device"]), y.to(cfg["device"])
        with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
            logits = model(x)
        loss = nn.functional.cross_entropy(
            logits.float().reshape(-1, cfg["vocab_size"]), y.reshape(-1))
        losses.append(loss.item())
    model.train()
    return float(np.mean(losses))

def train_variant(pe_name: str, cfg: dict, train_loader, val_loader) -> dict:
    print(f"\n{'═'*56}\n  PE: {pe_name}\n{'═'*56}")
    torch.manual_seed(cfg["seed"])
    model = PrimePEModel(cfg, pe_name).to(cfg["device"])
    print(f"  Params: {model.n_params()/1e6:.1f}M")

    opt = torch.optim.AdamW(model.parameters(), lr=cfg["lr"],
                            weight_decay=cfg["weight_decay"], betas=(0.9, 0.95))
    scaler = torch.amp.GradScaler("cuda", enabled=(cfg["dtype"] == torch.float16))

    results = {"pe": pe_name, "steps": [], "val_loss": [],
               "final_val_loss": None, "final_val_ppl": None, "time_s": None}

    it = cycle(train_loader)
    t0 = time.time()
    step, running = 0, 0.0
    opt.zero_grad()

    while step < cfg["max_steps"]:
        for g in opt.param_groups: g["lr"] = cosine_lr(step, cfg)
        x, y = next(it)
        x, y = x.to(cfg["device"], non_blocking=True), y.to(cfg["device"], non_blocking=True)

        with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
            logits = model(x)
            loss = nn.functional.cross_entropy(
                logits.float().reshape(-1, cfg["vocab_size"]), y.reshape(-1)
            ) / cfg["grad_accum"]

        scaler.scale(loss).backward()
        running += loss.item()

        if (step + 1) % cfg["grad_accum"] == 0:
            scaler.unscale_(opt)
            nn.utils.clip_grad_norm_(model.parameters(), cfg["clip_grad"])
            scaler.step(opt); scaler.update()
            opt.zero_grad(set_to_none=True)

            if step % cfg["eval_every"] == 0 or step == cfg["max_steps"] - 1:
                val = evaluate(model, val_loader, cfg)
                elapsed = time.time() - t0
                tok_s = step * cfg["batch_size"] * cfg["train_seq_len"] / elapsed
                print(f"  step {step:5d} | val {val:.4f} | ppl {math.exp(val):.1f} "
                      f"| {tok_s/1e3:.1f}K tok/s | {elapsed:.0f}s")
                results["steps"].append(step)
                results["val_loss"].append(val)
                running = 0.0

        step += 1

    final = evaluate(model, val_loader, cfg, max_batches=300)
    results.update({"final_val_loss": final, "final_val_ppl": math.exp(final),
                    "time_s": time.time() - t0})
    print(f"  Final — PPL: {math.exp(final):.1f} | {results['time_s']/60:.1f}min")

    path = f"{cfg['results_dir']}/ckpt_{pe_name}.pt"
    torch.save(model.state_dict(), path)
    results["ckpt"] = path
    del model; gc.collect(); torch.cuda.empty_cache()
    return results

# ─── Section: Perplexity eval ─────────────────────────────────────────────────

@torch.no_grad()
def ppl_at_len(model, seq_len, cfg, ChunkDataset_cls, n_batches=40):
    """Evaluate perplexity at a specific context length."""
    from datasets import load_dataset
    from transformers import GPT2TokenizerFast
    MAX_TOKENS = 1_000_000
    raw = load_dataset("wikitext", "wikitext-103-raw-v1", split="test")
    tok = GPT2TokenizerFast.from_pretrained("gpt2")
    tok.pad_token = tok.eos_token
    all_ids = []
    for row in raw:
        t = row["text"]
        if t.strip():
            all_ids.extend(tok.encode(t))
            if len(all_ids) >= MAX_TOKENS:
                break
    ids = torch.tensor(all_ids[:MAX_TOKENS], dtype=torch.long)
    sl = seq_len + 1
    n = (len(ids) // sl) * sl
    chunks = ids[:n].reshape(-1, sl)
    ds = ChunkDataset_cls(chunks)
    loader = DataLoader(ds, batch_size=2, shuffle=False, drop_last=True)
    model.eval()
    losses = []
    for i, (x, y) in enumerate(loader):
        if i >= n_batches: break
        x, y = x.to(cfg["device"]), y.to(cfg["device"])
        try:
            with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
                logits = model(x)
            loss = nn.functional.cross_entropy(
                logits.float().reshape(-1, cfg["vocab_size"]), y.reshape(-1))
            losses.append(loss.item())
        except RuntimeError:
            print(f"    OOM at {seq_len} — skipping")
            break
    return math.exp(np.mean(losses)) if losses else float("nan")

# ─── Section: Lost-in-the-Middle ──────────────────────────────────────────────

@torch.no_grad()
def litm_benchmark(model, cfg):
    model.eval()
    ctx   = cfg["litm_context_len"]
    fracs = cfg["litm_positions"]
    results = {}
    for frac in fracs:
        pos = max(1, int(frac * ctx) - 1)
        correct = 0
        for _ in range(cfg["litm_samples"]):
            ids    = torch.randint(200, 2000, (ctx,))
            needle = torch.randint(40000, 45000, (1,)).item()
            ids[pos] = needle
            try:
                with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
                    logits = model(ids.unsqueeze(0).to(cfg["device"]))
                if logits[0, pos-1].argmax().item() == needle:
                    correct += 1
            except RuntimeError:
                break
        results[frac] = correct / cfg["litm_samples"]
    return results

# ─── Section: Attention Distance Probe ───────────────────────────────────────

@torch.no_grad()
def attn_distance_probe(model, cfg, ChunkDataset, n_batches=80):
    """
    Measures mean attended distance per head.
    Low-freq (zeta) dimensions should attend further than high-freq (prime) ones.
    """
    model.eval()
    store = defaultdict(list)
    hooks = []

    def make_hook(layer_idx):
        def hook(module, inp, out):
            x = inp[0]
            B, T, C = x.shape
            with torch.no_grad():
                qkv = module.qkv(x).reshape(B, T, 3, module.n_heads, module.head_dim)
                q, k, _ = qkv.permute(2,0,3,1,4).unbind(0)
                scores = (q @ k.transpose(-2,-1)) * module.scale
                mask = torch.triu(torch.ones(T, T, device=x.device, dtype=torch.bool), diagonal=1)
                scores = scores.masked_fill(mask, float("-inf"))
                weights = scores.softmax(-1)
                pos  = torch.arange(T, device=x.device).float()
                dist = (pos.unsqueeze(0) - pos.unsqueeze(1)).abs()
                mean_dist = (weights * dist).sum(-1).mean(-1).mean(0)  # (H,)
                for h in range(module.n_heads):
                    store[(layer_idx, h)].append(mean_dist[h].item())
        return hook

    for li, block in enumerate(model.blocks):
        hooks.append(block.attn.register_forward_hook(make_hook(li)))

    ds = ChunkDataset("test", cfg["train_seq_len"] + 1)
    loader = DataLoader(ds, batch_size=4, shuffle=False, drop_last=True)
    for i, (x, _) in enumerate(loader):
        if i >= n_batches: break
        with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
            model(x.to(cfg["device"]))

    for h in hooks: h.remove()
    return {k: float(np.mean(v)) for k, v in store.items()}

# ─── Section: Zeta-RoPE Fine-tune Experiment ─────────────────────────────────

def run_zeta_rope_experiment(cfg):
    """
    The high-value experiment: take a model trained with standard geometric RoPE,
    swap the rotation frequencies to normalised zeta zeros, fine-tune 1-2K steps,
    measure whether long-context PPL improves vs the geometric baseline.

    Tests: is Zeta-RoPE a practical drop-in upgrade for deployed models?
    If yes, any lab running RoPE models can benefit without full retraining.
    """
    print("\n" + "═"*56)
    print("  ZETA-ROPE FINE-TUNING EXPERIMENT")
    print("  Hypothesis: swapping geometric → zeta frequencies in a")
    print("  trained RoPE model + short fine-tune improves long-context PPL")
    print("═"*56)

    # ── Step 1: Train a standard RoPE baseline ────────────────────────────────
    print("\nStep 1: Training RoPE baseline...")
    # We'll use a small model trained to partial convergence as stand-in
    # For a proper experiment use actual pretrained weights (TinyLlama etc.)

    # ── Step 2: Clone model, swap rotation frequencies to zeta ────────────────
    print("\nStep 2: Cloning model + swapping frequencies to zeta zeros...")

    # The key swap — in a real RoPE model this would target the rope_freqs buffer
    # in every attention layer
    half_rope = cfg["d_model"] // 2 // 2  # RoPE uses half the head dims
    zeta_rope_freqs = get_zeta_freqs(half_rope)
    # Normalise to same magnitude range as geometric freqs for stability
    geo_freqs = 1.0 / (10000 ** (torch.arange(half_rope).float() / half_rope))
    scale = geo_freqs.mean() / zeta_rope_freqs.mean()
    zeta_rope_freqs = zeta_rope_freqs * scale

    print(f"  Geometric freq range: [{geo_freqs.min():.4f}, {geo_freqs.max():.4f}]")
    print(f"  Zeta freq range:      [{zeta_rope_freqs.min():.4f}, {zeta_rope_freqs.max():.4f}]")
    print("  (Scaled to match geometric magnitude for gradient stability)")

    print("\nStep 3: Fine-tune with zeta frequencies — NOT YET IMPLEMENTED")
    print("  Requires: pretrained RoPE model weights (TinyLlama-1.1B recommended)")
    print("  Next step: load TinyLlama, swap rope_freqs buffers, fine-tune 1K steps")
    print("  Expected result: PPL at 4K-8K improves; PPL at 512 stays flat")
    print("\n  To implement: run scripts/zeta_rope_finetune.py with --model_path")

# ─── Section: Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick",    action="store_true")
    parser.add_argument("--variants", nargs="+", default=None)
    parser.add_argument("--test",     choices=["all","ppl","litm","attn","zeta_rope"],
                        default="all")
    args = parser.parse_args()

    cfg = make_cfg(quick=args.quick, variants=args.variants)
    os.makedirs(cfg["results_dir"], exist_ok=True)
    device = cfg["device"]

    print(f"\nMode: {'QUICK' if args.quick else 'FULL'} | Test: {args.test}")
    print(f"Model: {cfg['n_layers']}L × d{cfg['d_model']} | Steps: {cfg['max_steps']:,}")
    print(f"Effective batch: {cfg['batch_size'] * cfg['grad_accum']}")
    print(f"Variants: {cfg['pe_variants']}\n")

    if args.test == "zeta_rope":
        run_zeta_rope_experiment(cfg)
        return

    # ── Load data ─────────────────────────────────────────────────────────────
    train_loader, val_loader, ChunkDataset_cls = load_data(cfg)

    # ── Training pass ─────────────────────────────────────────────────────────
    all_results = {}
    for pe in cfg["pe_variants"]:
        r = train_variant(pe, cfg, train_loader, val_loader)
        all_results[pe] = r
        with open(f"{cfg['results_dir']}/results.json", "w") as f:
            json.dump(all_results, f, indent=2, default=str)

    # ── PPL at context length ─────────────────────────────────────────────────
    ppl_results = {}
    if args.test in ("all", "ppl"):
        print("\n── Perplexity vs Context Length ──")
        for pe in cfg["pe_variants"]:
            ckpt = all_results[pe].get("ckpt")
            if not ckpt: continue
            model = PrimePEModel(cfg, pe).to(device)
            model.load_state_dict(torch.load(ckpt, map_location=device))
            ppl_results[pe] = {}
            row = f"  {pe:<14}"
            for sl in cfg["eval_seq_lens"]:
                ppl = ppl_at_len(model, sl, cfg, ChunkDataset_cls)
                ppl_results[pe][sl] = ppl
                row += f" {sl}→{ppl:.0f}"
            print(row)
            del model; gc.collect(); torch.cuda.empty_cache()
        with open(f"{cfg['results_dir']}/ppl.json", "w") as f:
            json.dump(ppl_results, f, indent=2)

    # ── Lost-in-middle ────────────────────────────────────────────────────────
    litm_results = {}
    if args.test in ("all", "litm"):
        print("\n── Lost-in-the-Middle ──")
        for pe in cfg["pe_variants"]:
            ckpt = all_results[pe].get("ckpt")
            if not ckpt: continue
            model = PrimePEModel(cfg, pe).to(device)
            model.load_state_dict(torch.load(ckpt, map_location=device))
            litm = litm_benchmark(model, cfg)
            litm_results[pe] = litm
            mid = litm.get(0.5, 0)
            vals = " | ".join(f"{int(k*100)}%:{v:.1%}" for k,v in litm.items())
            print(f"  {pe:<14} {vals}  {'← KEY' if mid > 0 else ''}")
            del model; gc.collect(); torch.cuda.empty_cache()
        with open(f"{cfg['results_dir']}/litm.json", "w") as f:
            json.dump(litm_results, f, indent=2)

    # ── Attention distance probe ──────────────────────────────────────────────
    dist_results = {}
    if args.test in ("all", "attn"):
        print("\n── Attention Distance Probe ──")
        for pe in [p for p in ["zeta","hybrid_90z","sinusoidal","random_irr"] if p in cfg["pe_variants"]]:
            ckpt = all_results[pe].get("ckpt")
            if not ckpt: continue
            model = PrimePEModel(cfg, pe).to(device)
            model.load_state_dict(torch.load(ckpt, map_location=device))
            per_head = attn_distance_probe(model, cfg, ChunkDataset_cls)
            # Group by layer half: first half = lower freq (more zeta-like), second = higher
            n_layers, n_heads = cfg["n_layers"], cfg["n_heads"]
            low_freq_dists  = [per_head.get((l,h),0) for l in range(n_layers) for h in range(n_heads//2)]
            high_freq_dists = [per_head.get((l,h),0) for l in range(n_layers) for h in range(n_heads//2, n_heads)]
            low_mean  = float(np.mean(low_freq_dists))
            high_mean = float(np.mean(high_freq_dists))
            delta = low_mean - high_mean
            print(f"  {pe:<14} low_freq={low_mean:.1f}tok  high_freq={high_mean:.1f}tok  Δ={delta:+.1f}")
            dist_results[pe] = {"low_freq": low_mean, "high_freq": high_mean, "delta": delta}
            del model; gc.collect(); torch.cuda.empty_cache()

        # Critical verdict
        if "zeta" in dist_results and "random_irr" in dist_results:
            zd = dist_results["zeta"]["delta"]
            rd = dist_results["random_irr"]["delta"]
            print(f"\n  zeta Δ={zd:+.1f} vs random_irr Δ={rd:+.1f}")
            if zd > rd + 1:
                print("  → Zeta structure produces more scale separation than random irrational ✅")
            else:
                print("  → Gap not significant — may be frequency magnitude effect, not structure")

        with open(f"{cfg['results_dir']}/attn_dist.json", "w") as f:
            json.dump(dist_results, f, indent=2)

    # ── Summary: Degradation Ratio Table ─────────────────────────────────────
    print("\n" + "═"*72)
    print("  DEGRADATION RATIO TABLE")
    print("═"*72)

    # Separate additive and rotary PE results
    additive_pes = [pe for pe in cfg["pe_variants"] if "rope" not in pe]
    rotary_pes = [pe for pe in cfg["pe_variants"] if "rope" in pe]

    if additive_pes:
        print(f"\n  Additive PE:")
        print(f"  {'PE':<18} ", end="")
        eval_lens = cfg["eval_seq_lens"]
        for sl in eval_lens:
            print(f" {'ctx='+str(sl):<9}", end="")
        print(f"  {'Degrad':>8}  {'LitM@50%':>8}")
        print(f"  " + "-" * (18 + 10 * len(eval_lens) + 20))
        for pe in additive_pes:
            ppls = ppl_results.get(pe, {})
            litm = litm_results.get(pe, {})
            mid = litm.get(0.5, float("nan"))
            row = f"  {pe:<18} "
            first_ppl = None
            last_ppl = None
            for sl in eval_lens:
                ppl = ppls.get(sl, float("nan"))
                row += f" {ppl:<9.1f}"
                if not math.isnan(ppl):
                    if first_ppl is None: first_ppl = ppl
                    last_ppl = ppl
            if first_ppl and last_ppl and first_ppl > 0:
                deg = (last_ppl / first_ppl - 1) * 100
                sign = "+" if deg > 0 else ""
                row += f"  {sign}{deg:>6.1f}%"
                if deg < 0:
                    row += " !!"
            else:
                row += f"  {'---':>8}"
            if not math.isnan(mid):
                row += f"  {mid:>7.1%}"
            print(row)

    # ── Rotary Comparison Block ──
    if rotary_pes:
        print(f"\n  Rotary PE (RoPE variants):")
        print(f"  {'PE':<18} ", end="")
        for sl in eval_lens:
            print(f" {'ctx='+str(sl):<9}", end="")
        print(f"  {'Degrad':>8}")
        print(f"  " + "-" * (18 + 10 * len(eval_lens) + 10))
        for pe in rotary_pes:
            ppls = ppl_results.get(pe, {})
            row = f"  {pe:<18} "
            first_ppl = None
            last_ppl = None
            for sl in eval_lens:
                ppl = ppls.get(sl, float("nan"))
                row += f" {ppl:<9.1f}"
                if not math.isnan(ppl):
                    if first_ppl is None: first_ppl = ppl
                    last_ppl = ppl
            if first_ppl and last_ppl and first_ppl > 0:
                deg = (last_ppl / first_ppl - 1) * 100
                sign = "+" if deg > 0 else ""
                row += f"  {sign}{deg:>6.1f}%"
                if deg < 0:
                    row += " !!"
            else:
                row += f"  {'---':>8}"
            print(row)

        # Verdict: does zeta_rope beat standard rope?
        rope_ppl = ppl_results.get("rope", {})
        zeta_rope_ppl = ppl_results.get("zeta_rope", {})
        if rope_ppl and zeta_rope_ppl:
            max_sl = max(eval_lens)
            rp = rope_ppl.get(max_sl)
            zp = zeta_rope_ppl.get(max_sl)
            if rp and zp:
                diff = (zp - rp) / rp * 100
                print(f"\n  Verdict: zeta_rope vs rope at ctx={max_sl}: {diff:+.1f}%", end="")
                if diff < -1:
                    print(" — zeta rotation frequencies help")
                elif diff > 1:
                    print(" — geometric rotation frequencies better")
                else:
                    print(" — no significant difference")

    print(f"\n  Results saved to {cfg['results_dir']}/")
    print()


if __name__ == "__main__":
    main()

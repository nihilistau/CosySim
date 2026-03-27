"""
PrimePE — Local Validation Script
Version: v0.2.2 | Author: Knack | 2026-03-27

Change Log:
    v0.1.0 — Initial local test harness
    v0.2.2 — spectral_rope: per-head log-spaced prime allocation (2→4096),
              SpectralRoPEAttention, _next_prime helper, per-head PRS probe
    v0.2.1 — PRS proximity bias fix
    v0.2.0 — zeta_rope + random_irr_rope (apples-to-apples rotary comparison),
              fixed LitM needle task (vocab frequency artifacts removed),
              dense loss tracking, degradation ratio table, rotary comparison block,
              position shuffle experiment

Usage:
    python local_test.py                              # full local run
    python local_test.py --quick                      # smoke test (~15 min)
    python local_test.py --variants zeta sinusoidal random_irr zeta_rope rope
    python local_test.py --test ppl
    python local_test.py --test litm
    python local_test.py --test attn
    python local_test.py --test shuffle
"""

import argparse
import json
import math
import os
import time
import gc
from collections import defaultdict
from itertools import cycle

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import Dataset, DataLoader

# ─── Section: Config ──────────────────────────────────────────────────────────

def make_cfg(quick: bool = False, variants: list = None) -> dict:
    vram = torch.cuda.get_device_properties(0).total_memory / 1e9 if torch.cuda.is_available() else 0
    gpu  = torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu"
    print(f"GPU: {gpu} ({vram:.0f}GB)")

    if vram >= 20:
        batch, grad_accum = 4, 4
    elif vram >= 12:
        batch, grad_accum = 2, 8
    else:
        batch, grad_accum = 1, 16

    default_variants = [
        "sinusoidal",    # additive baseline
        "rope",          # rotary baseline — geometric (load-bearing)
        "spectral_rope", # ★ correct experiment: per-head log-spaced primes
        "hybrid_90z",    # best additive from H100
        "random_irr",    # additive control
        "alibi",         # mechanism ceiling
    ]

    return {
        # ── Model ─────────────────────────────────────────────────────────────
        "d_model":    256,
        "n_heads":    8,
        "n_layers":   6,
        "ffn_dim":    1024,
        "dropout":    0.1,
        "vocab_size": 50257,

        # ── Training ──────────────────────────────────────────────────────────
        "max_steps":    500   if quick else 3_000,
        "batch_size":   batch,
        "grad_accum":   grad_accum,
        "lr":           3e-4,
        "warmup_steps": 50    if quick else 300,
        "weight_decay": 0.01,
        "clip_grad":    1.0,
        "eval_every":   250,
        "train_seq_len": 512,

        # ── Eval ──────────────────────────────────────────────────────────────
        "eval_seq_lens":    [512, 1024, 2048] if quick else [512, 1024, 2048, 4096],
        "litm_context_len": 1024 if quick else 2048,
        "litm_positions":   [0.1, 0.25, 0.5, 0.75, 0.9],
        "litm_samples":     50   if quick else 200,

        # ── Fixed needle tokens — removes vocab frequency artifacts ────────────
        "litm_haystack_tok": 318,   # " is" — very common
        "litm_needle_tok":   7400,  # " Constantinople" — distinctive

        # ── Position shuffle ──────────────────────────────────────────────────
        "shuffle_samples":  100  if quick else 200,
        "shuffle_distance": 50,

        # ── Variants ──────────────────────────────────────────────────────────
        "pe_variants": variants if variants else default_variants,

        # ── Runtime ───────────────────────────────────────────────────────────
        "use_compile": False,
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
]

def get_primes(n: int) -> list:
    primes, c = [], 2
    while len(primes) < n:
        if all(c % p != 0 for p in primes):
            primes.append(c)
        c += 1
    return primes

def _next_prime(n: int) -> int:
    """Return smallest prime >= n."""
    n = max(2, int(n))
    if n == 2: return 2
    if n % 2 == 0: n += 1
    while not all(n % i != 0 for i in range(3, int(n**0.5)+1, 2)):
        n += 2
    return n


def get_zeta_freqs(n: int) -> torch.Tensor:

    zz = list(ZETA_ZEROS[:n])
    while len(zz) < n:
        k = float(len(zz) + 1)
        zz.append((2 * math.pi * k) / (math.log(k) + 0.5))
    t = torch.tensor(zz[:n], dtype=torch.float32)
    return t / t[0]

def freq_spec(pe_name: str, d_model: int) -> dict:
    """Returns frequency tensor + type for a PE variant."""
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
    elif pe_name == "prime_10":
        p = torch.tensor(get_primes(half), dtype=torch.float32)
        return {"type": "additive", "learnable": False, "freqs": 1.0 / p}
    elif pe_name == "zeta":
        return {"type": "additive", "learnable": False, "freqs": get_zeta_freqs(half)}
    elif pe_name == "hybrid_90z":
        q_prime = max(1, half // 10)
        q_zeta  = half - q_prime
        p  = torch.tensor(get_primes(q_prime), dtype=torch.float32)
        pf = (1.0 / (p ** 0.75)) / (1.0 / (p ** 0.75)).max()
        zf = get_zeta_freqs(q_zeta) / get_zeta_freqs(q_zeta).max()
        pf_pad = pf.repeat(q_zeta // q_prime + 1)[:q_zeta]
        freqs  = torch.stack([zf, pf_pad], dim=1).flatten()[:half]
        return {"type": "additive", "learnable": False, "freqs": freqs}
    elif pe_name == "hybrid_50z":
        q  = half // 2
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
    elif pe_name == "learned":
        f = 1.0 / (10000 ** (torch.arange(half).float() / half))
        return {"type": "additive", "learnable": True, "freqs": f}
    elif pe_name == "zeta_rope":
        # ── KEY: RoPE architecture with zeta-zero frequencies ─────────────────
        # Apples-to-apples vs geometric RoPE — same per-layer rotation, different freqs
        rope_half = half // 2
        zf  = get_zeta_freqs(rope_half)
        geo = 1.0 / (10000 ** (torch.arange(rope_half).float() / rope_half))
        zf  = zf * (geo.mean() / zf.mean())  # match magnitude for gradient stability
        return {"type": "rope", "learnable": False, "freqs": zf}
    elif pe_name == "random_irr_rope":
        rope_half = half // 2
        p = torch.tensor(get_primes(rope_half), dtype=torch.float32)
        freqs = p.sqrt().frac() / p.sqrt().frac().max()
        geo   = 1.0 / (10000 ** (torch.arange(rope_half).float() / rope_half))
        freqs = freqs * (geo.mean() / freqs.mean())
        return {"type": "rope", "learnable": False, "freqs": freqs}
    elif pe_name == "spectral_rope":
        # ── THE CORRECT EXPERIMENT ────────────────────────────────────────
        # Per-head prime allocation, log-spaced from 2 → max_eval_context.
        # theta_h = 2*pi/p for each prime p assigned to head h.
        # Head 0: small primes (local 2-53 tok), Head N-1: large primes (long-range)
        rope_half   = half // 2
        n_h         = 8   # local_test uses 8 heads (d=256/8=32 head_dim)
        max_ctx     = 4096  # push primes out to full eval context
        total       = n_h * rope_half
        log_pos     = [2 * (max_ctx / 2) ** (i / (total - 1)) for i in range(total)]
        used, sel   = set(), []
        for pos in log_pos:
            p = _next_prime(int(pos))
            while p in used: p = _next_prime(p + 1)
            used.add(p); sel.append(p)
        freqs_flat = torch.tensor([2 * math.pi / p for p in sel], dtype=torch.float32)
        head_freqs = freqs_flat.reshape(n_h, rope_half)
        return {"type": "spectral_rope", "learnable": False,
                "freqs": freqs_flat, "head_freqs": head_freqs, "prime_list": sel}
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
            pos    = torch.arange(max_len).float().unsqueeze(1)
            phases = pos * freqs.unsqueeze(0)
            pe     = torch.cat([torch.sin(phases), torch.cos(phases)], dim=-1)
            self.register_buffer("_cache", pe)
        else:
            self._cache = None

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        T = x.size(1)
        if self.learnable or self._cache is None:
            pos    = torch.arange(T, device=x.device).float().unsqueeze(1)
            phases = pos * self.freqs.unsqueeze(0)
            pe     = torch.cat([torch.sin(phases), torch.cos(phases)], dim=-1)
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
        t     = torch.arange(T, device=x.device).float()
        freqs = torch.outer(t, self.rope_freqs[:D // 2])
        cos   = freqs.cos()[None, None].to(x.dtype)
        sin   = freqs.sin()[None, None].to(x.dtype)
        x1, x2 = x[..., 0::2], x[..., 1::2]
        return torch.stack([x1 * cos - x2 * sin, x1 * sin + x2 * cos], dim=-1).flatten(-2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape
        qkv = self.qkv(x).reshape(B, T, 3, self.n_heads, self.head_dim)
        q, k, v = qkv.permute(2, 0, 3, 1, 4).unbind(0)
        if self.attn_type == "rope":
            q, k = self._rope(q), self._rope(k)
        if self.attn_type == "alibi":
            pos    = torch.arange(T, device=x.device)
            dist   = (pos.unsqueeze(0) - pos.unsqueeze(1)).abs().float()
            bias   = -self.alibi_slopes.view(-1, 1, 1) * dist.unsqueeze(0)
            causal = torch.triu(torch.full((T, T), float("-inf"), device=x.device), diagonal=1)
            out    = nn.functional.scaled_dot_product_attention(
                q, k, v, attn_mask=bias + causal, dropout_p=0.0)
        else:
            out = nn.functional.scaled_dot_product_attention(
                q, k, v, is_causal=True, dropout_p=0.0)
        return self.proj(self.drop(out.transpose(1, 2).reshape(B, T, C)))


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


class SpectralRoPEAttention(nn.Module):
    """
    Per-head spectral RoPE.
    head_freqs: (n_heads, rope_half) — each head gets its own prime band.
    Version: v0.2.2 | Author: Knack
    """
    def __init__(self, d_model: int, n_heads: int, dropout: float,
                 head_freqs: torch.Tensor):
        super().__init__()
        self.n_heads  = n_heads
        self.head_dim = d_model // n_heads
        self.scale    = self.head_dim ** -0.5
        self.qkv  = nn.Linear(d_model, 3 * d_model, bias=False)
        self.proj = nn.Linear(d_model, d_model, bias=False)
        self.drop = nn.Dropout(dropout)
        self.register_buffer("head_freqs", head_freqs)

    def _apply_spectral_rope(self, x: torch.Tensor) -> torch.Tensor:
        B, H, T, D = x.shape
        t      = torch.arange(T, device=x.device, dtype=x.dtype)
        phases = torch.einsum("t,hd->htd", t, self.head_freqs[:, :D//2].to(x.dtype))
        cos    = phases.cos().unsqueeze(0)
        sin    = phases.sin().unsqueeze(0)
        x1, x2 = x[..., 0::2], x[..., 1::2]
        return torch.stack([x1*cos - x2*sin, x1*sin + x2*cos], dim=-1).flatten(-2)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        B, T, C = x.shape
        qkv = self.qkv(x).reshape(B, T, 3, self.n_heads, self.head_dim)
        q, k, v = qkv.permute(2, 0, 3, 1, 4).unbind(0)
        q, k = self._apply_spectral_rope(q), self._apply_spectral_rope(k)
        out = nn.functional.scaled_dot_product_attention(q, k, v, is_causal=True, dropout_p=0.0)
        return self.proj(self.drop(out.transpose(1, 2).reshape(B, T, C)))


class PrimePEModel(nn.Module):
    """
    PrimePE transformer with swappable PE.
    Version: v0.2.0 | Author: Knack
    Change Log:
        v0.1.0 — Initial
        v0.2.0 — zeta_rope, random_irr_rope; fixed embed scale; dense loss tracking
    """
    def __init__(self, cfg: dict, pe_name: str):
        super().__init__()
        self.pe_name = pe_name
        d    = cfg["d_model"]
        spec = freq_spec(pe_name, d)

        self.embed      = nn.Embedding(cfg["vocab_size"], d)
        self.embed_drop = nn.Dropout(cfg["dropout"])
        self.pe = AdditivePE(d, spec["freqs"], learnable=spec["learnable"]) \
                  if spec["type"] == "additive" else None

        atype        = spec["type"] if spec["type"] != "additive" else "standard"
        rope_freqs   = spec["freqs"] if atype == "rope" else None
        alibi_slopes = None
        if atype == "alibi":
            n = cfg["n_heads"]
            alibi_slopes = torch.tensor([2 ** (-8 * i / n) for i in range(1, n + 1)])

        if atype == "spectral_rope":
            hf = spec.get("head_freqs")
            self.blocks = nn.ModuleList([
                self._make_spectral_block(
                    d, cfg["n_heads"], cfg["ffn_dim"], cfg["dropout"], hf)
                for _ in range(cfg["n_layers"])
            ])
        else:
            self.blocks = nn.ModuleList([
                Block(d, cfg["n_heads"], cfg["ffn_dim"], cfg["dropout"],
                      atype, rope_freqs, alibi_slopes)
                for _ in range(cfg["n_layers"])
            ])
        self.norm = nn.LayerNorm(d)
        self.head = nn.Linear(d, cfg["vocab_size"], bias=False)
        self.head.weight = self.embed.weight
        self._init()

    def _make_spectral_block(self, d, n_heads, ffn_dim, dropout, head_freqs):
        class _SB(nn.Module):
            def __init__(sb):
                super().__init__()
                sb.attn  = SpectralRoPEAttention(d, n_heads, dropout, head_freqs)
                sb.norm1 = nn.LayerNorm(d)
                sb.norm2 = nn.LayerNorm(d)
                sb.ffn   = nn.Sequential(
                    nn.Linear(d, ffn_dim), nn.GELU(), nn.Dropout(dropout),
                    nn.Linear(ffn_dim, d), nn.Dropout(dropout),
                )
            def forward(sb, x):
                x = x + sb.attn(sb.norm1(x))
                x = x + sb.ffn(sb.norm2(x))
                return x
        return _SB()

    def _init(self):
        for m in self.modules():
            if isinstance(m, nn.Linear):
                nn.init.normal_(m.weight, std=0.02)
                if m.bias is not None:
                    nn.init.zeros_(m.bias)
            elif isinstance(m, nn.Embedding):
                nn.init.normal_(m.weight, std=0.02)

    def forward(self, ids: torch.Tensor) -> torch.Tensor:
        x = self.embed(ids) * math.sqrt(self.embed.embedding_dim)
        if self.pe:
            x = self.pe(x)
        x = self.embed_drop(x)
        for block in self.blocks:
            x = block(x)
        return self.head(self.norm(x))

    def n_params(self) -> int:
        return sum(p.numel() for p in self.parameters() if p.requires_grad)

# ─── Section: Data ────────────────────────────────────────────────────────────
# v0.3.0 — ChunkDataset at module level (picklable), row-by-row tokenization
# with 4M token cap (no 8GB string join), num_workers=0 for Windows

MAX_TOKENS = 4_000_000

class ChunkDataset(Dataset):
    """Pre-tokenized text chunks. Module-level for pickle compatibility."""
    def __init__(self, chunks: torch.Tensor):
        self.chunks = chunks
    def __len__(self): return len(self.chunks)
    def __getitem__(self, i):
        c = self.chunks[i]
        return c[:-1], c[1:]

_data_cache = {}

def _tokenize_split(split_data, max_tokens: int = MAX_TOKENS) -> torch.Tensor:
    """Tokenize row-by-row with a token cap. No giant string join."""
    all_ids = []
    for row in split_data:
        t = row["text"]
        if t.strip():
            all_ids.extend(_data_cache["tok"].encode(t))
            if len(all_ids) >= max_tokens:
                break
    return torch.tensor(all_ids[:max_tokens], dtype=torch.long)

def _make_eval_dataset(split: str, seq_len: int) -> ChunkDataset:
    """Create ChunkDataset for any split at any seq_len."""
    ids = _tokenize_split(_data_cache["raw"][split],
                          max_tokens=MAX_TOKENS if split == "train" else 1_000_000)
    n = (len(ids) // seq_len) * seq_len
    return ChunkDataset(ids[:n].reshape(-1, seq_len))

def load_data(cfg: dict):
    from datasets import load_dataset
    from transformers import GPT2TokenizerFast
    print("Loading WikiText-103...")
    raw = load_dataset("wikitext", "wikitext-103-raw-v1")
    tok = GPT2TokenizerFast.from_pretrained("gpt2")
    tok.pad_token = tok.eos_token
    _data_cache["raw"] = raw
    _data_cache["tok"] = tok

    SL = cfg["train_seq_len"] + 1
    train_ds = _make_eval_dataset("train", SL)
    print(f"  train: {len(train_ds)} chunks of {SL}")
    val_ds = _make_eval_dataset("validation", SL)
    print(f"  validation: {len(val_ds)} chunks of {SL}")
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
    print(f"\n{'═' * 56}\n  PE: {pe_name}\n{'═' * 56}")
    torch.manual_seed(cfg["seed"])
    model = PrimePEModel(cfg, pe_name).to(cfg["device"])
    print(f"  Params: {model.n_params() / 1e6:.1f}M")

    opt    = torch.optim.AdamW(model.parameters(), lr=cfg["lr"],
                               weight_decay=cfg["weight_decay"], betas=(0.9, 0.95))
    scaler = torch.amp.GradScaler("cuda", enabled=(cfg["dtype"] == torch.float16))

    results = {
        "pe": pe_name, "steps": [], "val_loss": [],
        "train_steps_dense": [], "train_loss_dense": [],
        "final_val_loss": None, "final_val_ppl": None, "time_s": None,
    }

    it = cycle(train_loader)
    t0, step, running = time.time(), 0, 0.0
    opt.zero_grad()

    while step < cfg["max_steps"]:
        for g in opt.param_groups: g["lr"] = cosine_lr(step, cfg)
        x, y = next(it)
        x, y = x.to(cfg["device"], non_blocking=True), y.to(cfg["device"], non_blocking=True)

        with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
            logits = model(x)
            loss   = nn.functional.cross_entropy(
                logits.float().reshape(-1, cfg["vocab_size"]), y.reshape(-1)
            ) / cfg["grad_accum"]

        scaler.scale(loss).backward()
        running += loss.item()

        if (step + 1) % cfg["grad_accum"] == 0:
            scaler.unscale_(opt)
            nn.utils.clip_grad_norm_(model.parameters(), cfg["clip_grad"])
            scaler.step(opt); scaler.update()
            opt.zero_grad(set_to_none=True)

            results["train_steps_dense"].append(step)
            results["train_loss_dense"].append(running * cfg["grad_accum"])

            if step % cfg["eval_every"] == 0 or step == cfg["max_steps"] - 1:
                val     = evaluate(model, val_loader, cfg)
                elapsed = time.time() - t0
                tok_s   = step * cfg["batch_size"] * cfg["train_seq_len"] / max(elapsed, 1)
                print(f"  step {step:5d} | val {val:.4f} | ppl {math.exp(val):.1f} "
                      f"| {tok_s / 1e3:.1f}K tok/s | {elapsed:.0f}s")
                results["steps"].append(step)
                results["val_loss"].append(val)
                running = 0.0

        step += 1

    final = evaluate(model, val_loader, cfg, max_batches=300)
    results.update({"final_val_loss": final, "final_val_ppl": math.exp(final),
                    "time_s": time.time() - t0})
    print(f"  Final — PPL: {math.exp(final):.1f} | {results['time_s'] / 60:.1f}min")

    path = f"{cfg['results_dir']}/ckpt_{pe_name}.pt"
    torch.save(model.state_dict(), path)
    results["ckpt"] = path
    del model; gc.collect(); torch.cuda.empty_cache()
    return results

# ─── Section: Evaluations ─────────────────────────────────────────────────────

@torch.no_grad()
def ppl_at_len(model, seq_len, cfg, ChunkDataset=None, n_batches=40):
    ds     = _make_eval_dataset("test", seq_len + 1)
    loader = DataLoader(ds, batch_size=2, shuffle=False, drop_last=True, num_workers=0)
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
            print(f"    OOM at {seq_len} — skipping"); break
    return math.exp(np.mean(losses)) if losses else float("nan")


@torch.no_grad()
def litm_benchmark(model, cfg):
    """Fixed-token needle — removes vocabulary frequency artifacts."""
    model.eval()
    ctx   = cfg["litm_context_len"]
    h_tok = cfg["litm_haystack_tok"]
    n_tok = cfg["litm_needle_tok"]
    results = {}
    for frac in cfg["litm_positions"]:
        pos, correct = max(1, int(frac * ctx) - 1), 0
        for _ in range(cfg["litm_samples"]):
            ids      = torch.full((ctx,), h_tok, dtype=torch.long)
            ids[pos] = n_tok
            try:
                with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
                    logits = model(ids.unsqueeze(0).to(cfg["device"]))
                if logits[0, pos - 1].argmax().item() == n_tok:
                    correct += 1
            except RuntimeError:
                break
        results[frac] = correct / cfg["litm_samples"]
    return results


@torch.no_grad()
def attn_distance_probe(model, cfg, ChunkDataset=None, n_batches=80):
    model.eval()
    store, hooks = defaultdict(list), []

    def make_hook(li):
        def hook(module, inp, out):
            x = inp[0]; B, T, C = x.shape
            with torch.no_grad():
                qkv = module.qkv(x).reshape(B, T, 3, module.n_heads, module.head_dim)
                q, k, _ = qkv.permute(2, 0, 3, 1, 4).unbind(0)
                scores   = (q @ k.transpose(-2, -1)) * module.scale
                mask     = torch.triu(torch.ones(T, T, device=x.device, dtype=torch.bool), diagonal=1)
                weights  = scores.masked_fill(mask, float("-inf")).softmax(-1)
                pos      = torch.arange(T, device=x.device).float()
                dist     = (pos.unsqueeze(0) - pos.unsqueeze(1)).abs()
                mean_d   = (weights * dist).sum(-1).mean(-1).mean(0)
                for h in range(module.n_heads):
                    store[(li, h)].append(mean_d[h].item())
        return hook

    for li, block in enumerate(model.blocks):
        hooks.append(block.attn.register_forward_hook(make_hook(li)))

    ds     = _make_eval_dataset("test", cfg["train_seq_len"] + 1)
    loader = DataLoader(ds, batch_size=4, shuffle=False, drop_last=True, num_workers=0)
    for i, (x, _) in enumerate(loader):
        if i >= n_batches: break
        with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
            model(x.to(cfg["device"]))

    for h in hooks: h.remove()
    return {k: float(np.mean(v)) for k, v in store.items()}


@torch.no_grad()
def position_shuffle_test(model, cfg: dict, n_samples: int = 200,
                          swap_distance: int = 50) -> dict:
    """
    Swaps PE vectors at positions i and i+swap_distance, measures KL divergence.
    Higher KL = model more sensitive to positional address = more distinct encoding.
    Prediction: zeta > sinusoidal > random_irr
    Only works for additive PE — RoPE/ALiBi skipped cleanly.
    """
    raw = model._orig_mod if hasattr(model, "_orig_mod") else model
    if raw.pe is None:
        return {"mean_kl": float("nan"), "note": "rotary/alibi — no additive PE to swap"}

    T, kls = cfg["train_seq_len"], []
    for _ in range(n_samples):
        ids    = torch.randint(100, 5000, (1, T)).to(cfg["device"])
        swap_i = torch.randint(10, T - swap_distance - 10, (1,)).item()
        swap_j = swap_i + swap_distance

        with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
            logits_orig = model(ids).float()

        if raw.pe._cache is not None:
            cache = raw.pe._cache
            oi, oj = cache[swap_i].clone(), cache[swap_j].clone()
            cache[swap_i], cache[swap_j] = oj, oi

            with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
                logits_swap = model(ids).float()

            cache[swap_i], cache[swap_j] = oi, oj
            p  = logits_orig[0, swap_i].softmax(-1).clamp(min=1e-9)
            q  = logits_swap[0, swap_i].softmax(-1).clamp(min=1e-9)
            kls.append((p * (p / q).log()).sum().item())

    if not kls:
        return {"mean_kl": float("nan"), "note": "no cache"}
    return {"mean_kl": float(np.mean(kls)), "median_kl": float(np.median(kls)),
            "swap_dist": swap_distance, "n_samples": len(kls)}

# ─── Section: Summary ─────────────────────────────────────────────────────────

def print_summary(cfg, all_results, ppl_results, litm_results,
                  dist_results=None, shuffle_results=None,
                  resonance_results=None):
    print("\n" + "═" * 70)
    print("SUMMARY")
    print("═" * 70)

    eval_lens = cfg["eval_seq_lens"]
    max_len   = max(eval_lens)

    # Degradation ratio
    print(f"\nDEGRADATION RATIO  (512 → {max_len} tokens | negative = improves)\n")
    print(f"  {'PE':<22} {'PPL@512':<10} {'PPL@'+str(max_len//1024)+'K':<10} {'Δ%':<10} Verdict")
    print("  " + "-" * 64)
    for pe in cfg["pe_variants"]:
        p512 = ppl_results.get(pe, {}).get(512, float("nan"))
        pmax = ppl_results.get(pe, {}).get(max_len, float("nan"))
        if not (math.isnan(p512) or math.isnan(pmax) or p512 == 0):
            delta   = (pmax / p512 - 1) * 100
            verdict = "IMPROVES ✅" if delta < -0.5 else "flat" if abs(delta) < 1 else "degrades"
        else:
            delta, verdict = float("nan"), "no data"
        print(f"  {pe:<22} {p512:<10.1f} {pmax:<10.1f} {delta:<+10.1f} {verdict}")

    # Rotary comparison
    print(f"\nROTARY COMPARISON")
    print(f"  zeta_rope Δ < rope Δ       → zeta freqs help within RoPE arch")
    print(f"  zeta_rope Δ ≈ rand_irr_rope → arch matters, not freq structure\n")
    for pe in ["rope", "zeta_rope", "random_irr_rope"]:
        p512 = ppl_results.get(pe, {}).get(512, float("nan"))
        pmax = ppl_results.get(pe, {}).get(max_len, float("nan"))
        delta = (pmax / p512 - 1) * 100 if not math.isnan(p512) and p512 > 0 else float("nan")
        print(f"  {pe:<24} PPL@512={p512:.1f}  Δ={delta:+.1f}%")

    # LitM
    print(f"\nLOST-IN-THE-MIDDLE @ {cfg['litm_context_len']} tokens")
    fracs = cfg["litm_positions"]
    print(f"  {'PE':<22} " + " ".join(f"@{int(f*100)}%" for f in fracs))
    print("  " + "-" * 56)
    for pe in cfg["pe_variants"]:
        res = litm_results.get(pe, {})
        row = f"  {pe:<22} " + " ".join(f"{res.get(f,0):<7.1%}" for f in fracs)
        if res.get(0.5, 0) > 0: row += " ← KEY"
        print(row)

    # Attn distance
    if dist_results:
        print(f"\nATTENTION DISTANCE (low-freq vs high-freq heads)")
        for pe, r in dist_results.items():
            print(f"  {pe:<22} low={r['low_freq']:.1f}tok  high={r['high_freq']:.1f}tok  Δ={r['delta']:+.1f}")

    # Position shuffle
    if shuffle_results:
        print(f"\nPOSITION SHUFFLE KL (higher = more distinct positional encoding)")
        for pe, r in sorted(shuffle_results.items(), key=lambda x: -x[1].get("mean_kl", 0)):
            kl = r.get("mean_kl", float("nan"))
            if not math.isnan(kl):
                print(f"  {pe:<22} mean_KL={kl:.4f}")
            else:
                print(f"  {pe:<22} {r.get('note','')}")
        zk = shuffle_results.get("zeta", {}).get("mean_kl", float("nan"))
        rk = shuffle_results.get("random_irr", {}).get("mean_kl", float("nan"))
        sk = shuffle_results.get("sinusoidal", {}).get("mean_kl", float("nan"))
        if not any(math.isnan(x) for x in [zk, rk, sk]):
            if zk > rk and zk > sk:
                print("  → Zeta encodes positions most distinctly ✅")
            elif zk > sk:
                print("  → Zeta beats sinusoidal, not random_irr — partial factor")
            else:
                print("  → No clear positional distinctness advantage")

    # Prime resonance
    if resonance_results:
        print(f"\nPRIME RESONANCE SCORES (PRS > 1.0 = arithmetic position grammar)")
        for pe, r in sorted(resonance_results.items(),
                            key=lambda x: -x[1].get("prs_total", 0)):
            prs = r.get("prs_total", float("nan"))
            flag = " ← RESONANCE ✅" if prs > 1.05 else ""
            if not math.isnan(prs):
                print(f"  {pe:<22} PRS={prs:.4f}{flag}")
        prime_prs = resonance_results.get("prime_05", {}).get("prs_total", float("nan"))
        rand_prs  = resonance_results.get("random_irr", {}).get("prs_total", float("nan"))
        if not any(math.isnan(x) for x in [prime_prs, rand_prs]):
            if prime_prs > rand_prs + 0.02:
                print("  → Number-theoretic prime structure creates arithmetic positional grammar ✅")
            else:
                print("  → Prime resonance not distinguishable from random irrational at this scale")

    print(f"\nResults → {cfg['results_dir']}/")

# ─── Section: Main ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick",    action="store_true")
    parser.add_argument("--variants", nargs="+", default=None)
    parser.add_argument("--test",     choices=["all", "ppl", "litm", "attn", "shuffle", "resonance"],
                        default="all")
    args = parser.parse_args()

    cfg = make_cfg(quick=args.quick, variants=args.variants)
    os.makedirs(cfg["results_dir"], exist_ok=True)

    print(f"\nMode: {'QUICK' if args.quick else 'FULL'} | Test: {args.test}")
    print(f"Model: {cfg['n_layers']}L × d{cfg['d_model']} | Steps: {cfg['max_steps']:,}")
    print(f"Effective batch: {cfg['batch_size'] * cfg['grad_accum']}")
    print(f"Variants: {cfg['pe_variants']}\n")

    train_loader, val_loader, ChunkDataset_cls = load_data(cfg)

    all_results = {}
    for pe in cfg["pe_variants"]:
        r = train_variant(pe, cfg, train_loader, val_loader)
        all_results[pe] = r
        with open(f"{cfg['results_dir']}/results.json", "w") as f:
            json.dump(all_results, f, indent=2, default=str)

    ppl_results, litm_results, dist_results, shuffle_results = {}, {}, {}, {}

    if args.test in ("all", "ppl"):
        print("\n── Perplexity vs Context Length ──")
        for pe in cfg["pe_variants"]:
            ckpt = all_results[pe].get("ckpt")
            if not ckpt: continue
            model = PrimePEModel(cfg, pe).to(cfg["device"])
            model.load_state_dict(torch.load(ckpt, map_location=cfg["device"]))
            ppl_results[pe] = {}
            row = f"  {pe:<22}"
            for sl in cfg["eval_seq_lens"]:
                ppl = ppl_at_len(model, sl, cfg, ChunkDataset_cls)
                ppl_results[pe][sl] = ppl
                row += f"  {sl}→{ppl:.0f}"
            print(row)
            del model; gc.collect(); torch.cuda.empty_cache()
        with open(f"{cfg['results_dir']}/ppl.json", "w") as f:
            json.dump(ppl_results, f, indent=2)

    if args.test in ("all", "litm"):
        print("\n── Lost-in-the-Middle ──")
        for pe in cfg["pe_variants"]:
            ckpt = all_results[pe].get("ckpt")
            if not ckpt: continue
            model = PrimePEModel(cfg, pe).to(cfg["device"])
            model.load_state_dict(torch.load(ckpt, map_location=cfg["device"]))
            litm = litm_benchmark(model, cfg)
            litm_results[pe] = litm
            vals = " | ".join(f"{int(k*100)}%:{v:.1%}" for k, v in litm.items())
            print(f"  {pe:<22} {vals}")
            del model; gc.collect(); torch.cuda.empty_cache()
        with open(f"{cfg['results_dir']}/litm.json", "w") as f:
            json.dump(litm_results, f, indent=2)

    if args.test in ("all", "attn"):
        print("\n── Attention Distance Probe ──")
        probe_pes = [p for p in cfg["pe_variants"]
                     if p in {"zeta","zeta_rope","hybrid_90z","sinusoidal",
                               "rope","random_irr","random_irr_rope"}]
        for pe in probe_pes:
            ckpt = all_results[pe].get("ckpt")
            if not ckpt: continue
            model = PrimePEModel(cfg, pe).to(cfg["device"])
            model.load_state_dict(torch.load(ckpt, map_location=cfg["device"]))
            ph   = attn_distance_probe(model, cfg, ChunkDataset_cls)
            n_l, n_h = cfg["n_layers"], cfg["n_heads"]
            low  = [ph.get((l,h), 0) for l in range(n_l) for h in range(n_h//2)]
            high = [ph.get((l,h), 0) for l in range(n_l) for h in range(n_h//2, n_h)]
            lm, hm = float(np.mean(low)), float(np.mean(high))
            dist_results[pe] = {"low_freq": lm, "high_freq": hm, "delta": lm - hm}
            print(f"  {pe:<22} low={lm:.1f}tok  high={hm:.1f}tok  Δ={lm-hm:+.1f}")
            del model; gc.collect(); torch.cuda.empty_cache()
        with open(f"{cfg['results_dir']}/attn_dist.json", "w") as f:
            json.dump(dist_results, f, indent=2)

    if args.test in ("all", "shuffle"):
        print(f"\n── Position Shuffle (swap_distance={cfg['shuffle_distance']}) ──")
        additive = [p for p in cfg["pe_variants"]
                    if p not in ("rope", "zeta_rope", "random_irr_rope", "alibi")]
        for pe in additive:
            ckpt = all_results[pe].get("ckpt")
            if not ckpt: continue
            model = PrimePEModel(cfg, pe).to(cfg["device"])
            model.load_state_dict(torch.load(ckpt, map_location=cfg["device"]))
            model.eval()
            res = position_shuffle_test(model, cfg,
                                        n_samples=cfg["shuffle_samples"],
                                        swap_distance=cfg["shuffle_distance"])
            shuffle_results[pe] = res
            kl = res.get("mean_kl", float("nan"))
            print(f"  {pe:<22} " + (f"mean_KL={kl:.4f}" if not math.isnan(kl)
                                     else res.get("note", "")))
            del model; gc.collect(); torch.cuda.empty_cache()
        with open(f"{cfg['results_dir']}/shuffle.json", "w") as f:
            json.dump(shuffle_results, f, indent=2)

    resonance_results = {}
    if args.test in ("all", "resonance"):
        print(f"\n── Prime Resonance Probe (v1.6.0) ──")
        print(f"Primes: {PRIME_SET}")
        print(f"PRS > 1.0 = attention elevated at prime-multiple distances\n")
        for pe in cfg["pe_variants"]:
            ckpt = all_results[pe].get("ckpt")
            if not ckpt: continue
            model = PrimePEModel(cfg, pe).to(cfg["device"])
            model.load_state_dict(torch.load(ckpt, map_location=cfg["device"]))
            model.eval()
            result = prime_resonance_probe(model, cfg, ChunkDataset_cls)
            resonance_results[pe] = result
            prs  = result["prs_total"]
            pprs = " ".join(f"p{p}:{v:.3f}" for p,v in list(result["prs_by_prime"].items())[:5])
            flag = " ← RESONANCE ✅" if prs > 1.05 else " ← flat"
            print(f"  {pe:<22} PRS={prs:.4f}  [{pprs}]{flag}")
            del model; gc.collect(); torch.cuda.empty_cache()

        # Verdict
        prime_prs = resonance_results.get("prime_05", {}).get("prs_total", float("nan"))
        rand_prs  = resonance_results.get("random_irr", {}).get("prs_total", float("nan"))
        sin_prs   = resonance_results.get("sinusoidal", {}).get("prs_total", float("nan"))
        print(f"\n  prime_05 PRS={prime_prs:.4f} | random_irr PRS={rand_prs:.4f} | sinusoidal PRS={sin_prs:.4f}")
        if not any(math.isnan(x) for x in [prime_prs, rand_prs, sin_prs]):
            if prime_prs > rand_prs + 0.02 and prime_prs > sin_prs + 0.02:
                print("  ✅ ARITHMETIC RELATIONAL POSITION HYPOTHESIS SUPPORTED")
                print("  Prime periods function as a positional grammar.")
            elif prime_prs > rand_prs:
                print("  🔬 MARGINAL — resonance present, weak — more training may strengthen")
            else:
                print("  ❌ NO RESONANCE at this training scale")

        with open(f"{cfg['results_dir']}/resonance.json", "w") as f:
            safe = {k: {kk: vv if not isinstance(vv, list) else vv[:200]
                        for kk,vv in v.items()} for k,v in resonance_results.items()}
            json.dump(safe, f, indent=2)

    print_summary(cfg, all_results, ppl_results, litm_results,
                  dist_results or None, shuffle_results or None,
                  resonance_results or None)


if __name__ == "__main__":
    main()

# ─── Section: Prime Resonance Probe ──────────────────────────────────────────

PRIME_SET = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29]

@torch.no_grad()
def prime_resonance_probe(model, cfg: dict, ChunkDataset=None, n_batches: int = 100) -> dict:
    """
    Arithmetic Relational Position Hypothesis (v1.6.0):
    If prime frequencies create resonance peaks at prime-multiple distances,
    attention-vs-distance should show a 'comb' pattern at p, 2p, 3p...

    Prime Resonance Score (PRS): ratio of mean attention at prime-multiple
    distances vs non-prime-multiple distances. PRS > 1.0 = resonance present.
    """
    model.eval()
    T = cfg["train_seq_len"]

    dist_sum   = torch.zeros(T + 1, device=cfg["device"])
    dist_count = torch.zeros(T + 1, device=cfg["device"])
    hooks = []

    def make_hook(li):
        def hook(module, inp, out):
            x = inp[0]; B, Tl, C = x.shape
            with torch.no_grad():
                qkv    = module.qkv(x).reshape(B, Tl, 3, module.n_heads, module.head_dim)
                q, k, _ = qkv.permute(2,0,3,1,4).unbind(0)
                scores  = (q @ k.transpose(-2,-1)) * module.scale
                mask    = torch.triu(torch.ones(Tl,Tl,device=x.device,dtype=torch.bool), diagonal=1)
                weights = scores.masked_fill(mask, float("-inf")).softmax(-1)
                w_mean  = weights.mean(dim=(0,1))  # (T, T)
                for delta in range(1, Tl):
                    diag = w_mean.diagonal(offset=-delta)
                    dist_sum[delta]   += diag.sum()
                    dist_count[delta] += diag.numel()
        return hook

    for li, block in enumerate(model.blocks):
        hooks.append(block.attn.register_forward_hook(make_hook(li)))

    ds     = _make_eval_dataset("test", T + 1)
    loader = DataLoader(ds, batch_size=2, shuffle=False, drop_last=True, num_workers=0)
    for i, (x, _) in enumerate(loader):
        if i >= n_batches: break
        with torch.autocast(device_type="cuda", dtype=cfg["dtype"]):
            model(x.to(cfg["device"]))

    for h in hooks: h.remove()

    mask_valid  = dist_count > 0
    attn_by_dist = torch.zeros(T + 1)
    attn_by_dist[mask_valid] = (dist_sum[mask_valid] / dist_count[mask_valid]).cpu()

    ad = attn_by_dist[1:T+1]  # distances 1..T, length T
    prs_by_prime = {}
    for p in PRIME_SET:
        pm = torch.zeros(T, dtype=torch.bool)
        for k in range(1, T // p + 1):
            if k * p <= T: pm[k*p-1] = True
        nm = ~pm
        # Exclude distances < p from non-multiple baseline.
        # Distance=1 is always high-attention and never a prime multiple
        # (for p>1), which inflates the denominator for all variants equally
        # and drives PRS < 1.0 structurally. Compare within range [p, T].
        nm[:p-1] = False
        if pm.sum() == 0 or nm.sum() == 0:
            prs_by_prime[p] = float("nan"); continue
        ma  = ad[pm].mean().item()
        mna = ad[nm].mean().item()
        prs_by_prime[p] = ma / mna if mna > 0 else float("nan")

    valid = [v for v in prs_by_prime.values() if not math.isnan(v)]
    prs_total = float(sum(valid)/len(valid)) if valid else float("nan")

    return {
        "attn_by_dist": attn_by_dist.tolist(),
        "prs_by_prime": prs_by_prime,
        "prs_total":    prs_total,
    }

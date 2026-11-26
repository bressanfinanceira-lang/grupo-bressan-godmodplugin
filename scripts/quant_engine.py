import numpy as np
import pandas as pd

def fractional_diff(series, d=0.4, thres=1e-4):
    """Diferenciacao Fracionaria para manter memoria com estacionariedade."""
    w = [1.0]
    k = 1
    while True:
        w_next = -w[-1] * (d - k + 1) / k
        if abs(w_next) < thres:
            break
        w.append(w_next)
        k += 1
    w = np.array(w[::-1])
    out = np.convolve(series, w, mode='valid')
    return out

def purged_kfold_splits(n_samples, n_splits=5, embargo_pct=0.02):
    """Gera indices Purged K-Fold com Embargo anti-vazamento."""
    indices = np.arange(n_samples)
    embargo = int(n_samples * embargo_pct)
    fold_size = n_samples // n_splits
    splits = []
    for i in range(n_splits):
        test_start = i * fold_size
        test_end = (i + 1) * fold_size if i < n_splits - 1 else n_samples
        test_idx = indices[test_start:test_end]
        train_left = indices[:max(0, test_start - embargo)]
        train_right = indices[min(n_samples, test_end + embargo):]
        train_idx = np.concatenate([train_left, train_right])
        splits.append((train_idx, test_idx))
    return splits

def monte_carlo_institutional(trade_returns, iterations=5000):
    """Monte Carlo de 5.000 cenarios com estresse de cauda."""
    if len(trade_returns) < 30:
        return {"approved": False, "reason": "Amostra menor que 30 trades"}
    dds, eqs = [], []
    for _ in range(iterations):
        s = np.random.choice(trade_returns, size=len(trade_returns), replace=True)
        shock = np.random.rand(len(s)) < 0.20
        s[shock] -= np.abs(s[shock]) * 0.30
        eq = np.cumprod(1 + s)
        pk = np.maximum.accumulate(eq)
        dds.append(np.min((eq - pk) / pk))
        eqs.append(eq[-1])
    w_dd = np.percentile(dds, 1) * 100
    med = (np.median(eqs) - 1) * 100
    return {"approved": bool(w_dd > -15.0 and med > 0), "worst_dd_99_pct": round(float(w_dd), 2), "median_return_pct": round(float(med), 2)}

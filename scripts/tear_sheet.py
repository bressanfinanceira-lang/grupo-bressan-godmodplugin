"""Gerador de Tear Sheet HTML Institucional - Grupo Bressan."""
import numpy as np

def generate_html_tearsheet(equity_curve, strategy_name="GrupoBressan_Bot", out_path="tearsheet.html"):
    total_ret = (equity_curve[-1] / equity_curve - 1) * 100
    peak = np.maximum.accumulate(equity_curve)
    max_dd = np.min((equity_curve - peak) / peak) * 100
    html = f"^<html^>^<body style='font-family:sans-serif;background:#0d1117;color:#c9d1d9;padding:40px'^>^<h1^>Grupo Bressan Quant Tear Sheet: {strategy_name}^</h1^>^<h2^>Retorno Total: {total_ret:.2f}%% ^| Max Drawdown: {max_dd:.2f}%%^</h2^>^<p^>Validado pelo Apex Sovereign Quant OS v7.0^</p^>^</body^>^</html^>"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    return out_path

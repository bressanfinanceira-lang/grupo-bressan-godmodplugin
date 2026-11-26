"""
Grupo Bressan - MT5 Live Trader + War Room (servidor HTTP em http://localhost:8000)

Executar SOMENTE com Python 3.12:
    py -3.12 scripts/mt5_live_trader.py            (abre o navegador automaticamente)
    py -3.12 scripts/mt5_live_trader.py --symbol WIN$ --lots 1 --no-browser

O que faz:
  * Conecta no terminal MetaTrader 5 aberto (mt5.initialize()).
  * Escolhe o ativo visivel na Observacao de Mercado (WIN$N, WIN$, WDO$N, WDO$, EURUSD, BTCUSD...).
    Se o ativo for serie continua nao negociavel (ex.: WIN$), as ordens vao para o contrato vigente (ex.: WINZ26).
  * Puxa os candles M1 reais do pregao de hoje, calcula VWAP, RSI(14), ATR(14) e
    Monte Carlo bootstrap (5000 caminhos) com os retornos reais do dia.
  * Envia ordens REAIS (mt5.order_send) com Stop Loss e Take Profit SOMENTE quando o
    botao AUTO-TRADE MT5 estiver ON na tela. Conta REAL exige confirmacao extra na tela.

Travas de seguranca: 1 posicao por vez (magic proprio), lote minimo por padrao, SL/TP obrigatorios
no servidor da corretora, circuit breaker de perda diaria, limite de trades/dia, PANIC STOP zera tudo.
"""
import argparse
import json
import os
import threading
import time
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

try:
    import MetaTrader5 as mt5
    HAS_MT5 = True
except ImportError:  # pragma: no cover
    mt5 = None
    HAS_MT5 = False

# ----------------------------------------------------------------------------- configuracao
HERE = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(HERE, "war_room.html")
HOST, PORT = "127.0.0.1", 8000

CANDIDATES = ["WIN$N", "WIN$", "WDO$N", "WDO$", "EURUSD", "BTCUSD"]
MAGIC = 20261125
LOOP_SECONDS = 2.0
RSI_PERIOD = 14
ATR_PERIOD = 14
MC_PATHS = 5000
MC_HORIZON = 30            # barras M1 a frente
SL_ATR = 1.5               # stop = 1.5 x ATR
TP_ATR = 3.0               # alvo = 3.0 x ATR  (risco:retorno 1:2)
MC_MIN_WIN = 0.40          # probabilidade minima de atingir o alvo antes do stop
MAX_TRADES_DAY = 10
MAX_DAILY_LOSS_PCT = 2.5   # circuit breaker sobre o saldo
MIN_BARS = 30
DEVIATION = 20

MT5_LOCK = threading.RLock()
STATE_LOCK = threading.Lock()

STATE = {
    "connected": False,
    "error": "",
    "account": None,
    "symbol": None,
    "trade_symbol": None,
    "session_date": None,
    "is_today": False,
    "bars": 0,
    "price": None, "bid": None, "ask": None, "spread": None, "digits": 2,
    "vwap": None, "rsi": None, "atr": None, "dist_vwap_pct": None,
    "mc": None,
    "signal": "AGUARDAR",
    "reason": "Inicializando...",
    "position": None,
    "score": {"wins": 0, "losses": 0, "pnl": 0.0, "trades": 0},
    "auto_trade": False,
    "real_confirmed": False,
    "circuit_breaker": False,
    "closes": [],
    "candles": [],
    "logs": [],
    "ticker": "GRUPO BRESSAN WAR ROOM | CONECTANDO AO METATRADER 5...",
    "updated": None,
    "lots": None,
}

RUNTIME = {"forced_symbol": None, "lots": None, "last_bar_time": None, "panic": False}


def log(msg):
    line = f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
    print(line, flush=True)
    with STATE_LOCK:
        STATE["logs"].append(line)
        STATE["logs"] = STATE["logs"][-40:]


def setstate(**kw):
    with STATE_LOCK:
        STATE.update(kw)


# ----------------------------------------------------------------------------- indicadores
def vwap_series(bars):
    tp = (bars["high"] + bars["low"] + bars["close"]) / 3.0
    vol = bars["real_volume"].astype(float)
    if vol.sum() <= 0:
        vol = bars["tick_volume"].astype(float)
    vol = np.where(vol <= 0, 1.0, vol)
    return np.cumsum(tp * vol) / np.cumsum(vol)


def rsi_wilder(close, period=RSI_PERIOD):
    if len(close) <= period:
        return None
    d = np.diff(close)
    gain, loss = np.clip(d, 0, None), np.clip(-d, 0, None)
    ag, al = gain[:period].mean(), loss[:period].mean()
    for g, l in zip(gain[period:], loss[period:]):
        ag = (ag * (period - 1) + g) / period
        al = (al * (period - 1) + l) / period
    if al == 0:
        return 100.0
    return float(100 - 100 / (1 + ag / al))


def atr_wilder(bars, period=ATR_PERIOD):
    h, l, c = bars["high"], bars["low"], bars["close"]
    if len(c) <= period:
        return None
    tr = np.maximum(h[1:] - l[1:], np.maximum(abs(h[1:] - c[:-1]), abs(l[1:] - c[:-1])))
    a = tr[:period].mean()
    for x in tr[period:]:
        a = (a * (period - 1) + x) / period
    return float(a)


def signal_from(last, vwl, rsi, mc):
    """Regra unica usada ao vivo e na simulacao do dia."""
    if rsi is None or mc is None or vwl is None:
        return "AGUARDAR"
    if last > vwl and 50 < rsi < 70 and mc["long_win"] >= MC_MIN_WIN and mc["long_win"] > mc["long_loss"]:
        return "COMPRA"
    if last < vwl and 30 < rsi < 50 and mc["short_win"] >= MC_MIN_WIN and mc["short_win"] > mc["short_loss"]:
        return "VENDA"
    return "AGUARDAR"


def monte_carlo(close, sl_dist, tp_dist, paths=MC_PATHS, horizon=MC_HORIZON, rng=None):
    """Bootstrap dos retornos log M1 REAIS do dia -> probabilidade de alvo antes do stop."""
    r = np.diff(np.log(close))
    r = r[np.isfinite(r)]
    if len(r) < 10 or sl_dist <= 0 or tp_dist <= 0:
        return None
    rng = rng or np.random.default_rng()
    last = close[-1]
    sim = last * np.exp(np.cumsum(rng.choice(r, size=(paths, horizon), replace=True), axis=1))

    def first_hit(mask):
        idx = np.argmax(mask, axis=1)
        idx[~mask.any(axis=1)] = horizon + 1
        return idx

    out = {"paths": paths, "horizon": horizon}
    for side, tp_lvl, sl_lvl, up in (("long", last + tp_dist, last - sl_dist, True),
                                     ("short", last - tp_dist, last + sl_dist, False)):
        t_hit = first_hit(sim >= tp_lvl if up else sim <= tp_lvl)
        s_hit = first_hit(sim <= sl_lvl if up else sim >= sl_lvl)
        win = (t_hit < s_hit) & (t_hit <= horizon)
        loss = (s_hit < t_hit) & (s_hit <= horizon)
        out[f"{side}_win"] = float(win.mean())
        out[f"{side}_loss"] = float(loss.mean())
    finals = sim[:, -1]
    out["p5"], out["p50"], out["p95"] = (float(np.percentile(finals, q)) for q in (5, 50, 95))
    return out


# ----------------------------------------------------------------------------- MT5 helpers
def mt5_connect():
    with MT5_LOCK:
        if not HAS_MT5:
            setstate(connected=False, error="Pacote MetaTrader5 nao instalado: py -3.12 -m pip install MetaTrader5")
            return False
        if mt5.terminal_info() is not None and mt5.account_info() is not None:
            return True
        mt5.shutdown()
        if not mt5.initialize():
            setstate(connected=False, error=f"mt5.initialize() falhou: {mt5.last_error()} - abra o MetaTrader 5 e faca login.")
            return False
        a = mt5.account_info()
        log(f"[MT5] Conectado: conta {a.login} @ {a.server} ({account_mode(a)})")
        setstate(connected=True, error="")
        return True


def account_mode(a):
    return {0: "DEMO", 1: "CONTEST", 2: "REAL"}.get(a.trade_mode, "?")


def pick_symbol():
    if RUNTIME["forced_symbol"]:
        s = RUNTIME["forced_symbol"]
        mt5.symbol_select(s, True)
        return s
    for s in CANDIDATES:
        i = mt5.symbol_info(s)
        if i is not None and i.visible:
            return s
    for i in mt5.symbols_get() or []:  # primeiro ativo visivel com candles
        if i.visible:
            r = mt5.copy_rates_from_pos(i.name, mt5.TIMEFRAME_M1, 0, 5)
            if r is not None and len(r):
                return i.name
    return None


def resolve_trade_symbol(sym):
    """WIN$ / WIN$N nao sao negociaveis -> contrato vigente com vencimento mais proximo."""
    info = mt5.symbol_info(sym)
    if info is not None and info.trade_mode == mt5.SYMBOL_TRADE_MODE_FULL:
        return sym
    base = sym.split("$")[0]
    now = time.time()
    best = None
    for i in mt5.symbols_get(group=f"{base}*") or []:
        if "$" in i.name or i.trade_mode != mt5.SYMBOL_TRADE_MODE_FULL:
            continue
        if i.expiration_time and i.expiration_time < now:
            continue
        key = (0 if i.visible else 1, i.expiration_time or 9e18)
        if best is None or key < best[0]:
            best = (key, i.name)
    if best:
        mt5.symbol_select(best[1], True)
        return best[1]
    return None


def round_tick(price, tick):
    return round(round(price / tick) * tick, 10) if tick > 0 else price


def server_date(ts):
    return datetime.fromtimestamp(int(ts), tz=timezone.utc).date()


def bot_positions(sym):
    return [p for p in (mt5.positions_get(symbol=sym) or []) if p.magic == MAGIC]


def daily_score(session_date):
    now = datetime.now() + timedelta(days=1)
    deals = mt5.history_deals_get(now - timedelta(days=3), now) or []
    wins = losses = 0
    pnl = 0.0
    for d in deals:
        if d.magic != MAGIC or server_date(d.time) != session_date:
            continue
        if d.entry in (mt5.DEAL_ENTRY_OUT, mt5.DEAL_ENTRY_OUT_BY, mt5.DEAL_ENTRY_INOUT):
            res = d.profit + d.commission + d.swap + getattr(d, "fee", 0.0)
            pnl += res
            if res > 0:
                wins += 1
            else:
                losses += 1
    return {"wins": wins, "losses": losses, "pnl": round(pnl, 2), "trades": wins + losses}


def send_market(sym, side, volume, sl=0.0, tp=0.0, position=None, comment="GB WarRoom"):
    info = mt5.symbol_info(sym)
    tick = mt5.symbol_info_tick(sym)
    if info is None or tick is None:
        return False, "sem cotacao"
    is_buy = side == "BUY"
    req = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": sym,
        "volume": float(volume),
        "type": mt5.ORDER_TYPE_BUY if is_buy else mt5.ORDER_TYPE_SELL,
        "price": tick.ask if is_buy else tick.bid,
        "deviation": DEVIATION,
        "magic": MAGIC,
        "comment": comment,
        "type_time": mt5.ORDER_TIME_DAY,
    }
    if position is not None:
        req["position"] = position
    else:
        req["sl"], req["tp"] = float(sl), float(tp)
    last = "order_check falhou"
    for fill in (mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_RETURN):
        req["type_filling"] = fill
        chk = mt5.order_check(req)
        if chk is None:
            last = f"order_check None {mt5.last_error()}"
            continue
        if chk.retcode not in (0, mt5.TRADE_RETCODE_DONE):
            last = f"order_check {chk.retcode} {chk.comment}"
            if chk.retcode == mt5.TRADE_RETCODE_INVALID_FILL:
                continue
            return False, last
        res = mt5.order_send(req)
        if res is None:
            return False, f"order_send None {mt5.last_error()}"
        if res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
            return True, f"ticket {res.order} @ {res.price}"
        last = f"order_send {res.retcode} {res.comment}"
        if res.retcode != mt5.TRADE_RETCODE_INVALID_FILL:
            return False, last
    return False, last


def close_all(reason):
    sym = STATE.get("trade_symbol")
    if not sym:
        return
    with MT5_LOCK:
        for p in bot_positions(sym):
            side = "SELL" if p.type == mt5.POSITION_TYPE_BUY else "BUY"
            ok, msg = send_market(sym, side, p.volume, position=p.ticket, comment="GB PANIC")
            log(f"[{reason}] Fechando posicao {p.ticket}: {'OK ' if ok else 'FALHA '}{msg}")


# ----------------------------------------------------------------------------- ciclo principal
def cycle():
    if not mt5_connect():
        return
    with MT5_LOCK:
        acc = mt5.account_info()
        term = mt5.terminal_info()
        if acc is None or term is None:
            setstate(connected=False, error="Terminal desconectado")
            return
        sym = pick_symbol()
        if sym is None:
            setstate(error="Nenhum ativo visivel na Observacao de Mercado.")
            return
        if sym != STATE["symbol"]:
            tsym = resolve_trade_symbol(sym)
            log(f"[DADOS] Ativo: {sym} | ordens em: {tsym or 'NENHUM CONTRATO NEGOCIAVEL'}")
            setstate(symbol=sym, trade_symbol=tsym)
        tsym = STATE["trade_symbol"]
        sinfo = mt5.symbol_info(tsym or sym)
        tick = mt5.symbol_info_tick(tsym or sym)
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 1500)
        if rates is None or len(rates) < 3:
            setstate(error=f"Sem candles M1 para {sym}: {mt5.last_error()}")
            return

        # pregao do ultimo candle (horario do servidor) e somente barras FECHADAS (sem look-ahead)
        sess = server_date(rates[-1]["time"])
        day = rates[np.array([server_date(t) == sess for t in rates["time"]])]
        closed = day[:-1] if len(day) > 1 else day
        today_srv = datetime.now().date()  # servidor B3 = horario de Brasilia
        # mercado "ao vivo" = o tick mudou nos ultimos 120 s (independe do fuso do servidor)
        if tick is not None:
            if RUNTIME.get("last_tick_msc") is not None and tick.time_msc != RUNTIME["last_tick_msc"]:
                RUNTIME["last_tick_wall"] = time.time()
            RUNTIME["last_tick_msc"] = tick.time_msc
        market_live = time.time() - RUNTIME.get("last_tick_wall", 0) < 120
        close = closed["close"].astype(float)
        vw = vwap_series(closed)
        rsi = rsi_wilder(close)
        atr = atr_wilder(closed)
        price = float(day["close"][-1])
        digits = sinfo.digits if sinfo else 2
        tick_size = sinfo.trade_tick_size if sinfo else 0.0
        mc = None
        if atr and len(close) >= MIN_BARS:
            mc = monte_carlo(close, SL_ATR * atr, TP_ATR * atr)
        score = daily_score(sess)
        pos = bot_positions(tsym) if tsym else []
        p = pos[0] if pos else None
        lots = RUNTIME["lots"] or (sinfo.volume_min if sinfo else 1.0)

        account = {
            "login": acc.login, "server": acc.server, "company": acc.company, "currency": acc.currency,
            "balance": acc.balance, "equity": acc.equity, "profit": acc.profit,
            "margin_free": acc.margin_free, "mode": account_mode(acc),
            "algo_enabled": bool(term.trade_allowed), "account_trade": bool(acc.trade_allowed and acc.trade_expert),
        }

    # ---- sinal (somente com barras fechadas)
    signal, reason = "AGUARDAR", "Aguardando dados suficientes"
    vwl = float(vw[-1]) if len(vw) else None
    if rsi is not None and mc and vwl:
        last = float(close[-1])
        signal = signal_from(last, vwl, rsi, mc)
        if signal == "COMPRA":
            reason = f"Acima da VWAP, RSI {rsi:.1f}, MC alvo {mc['long_win']:.0%}"
        elif signal == "VENDA":
            reason = f"Abaixo da VWAP, RSI {rsi:.1f}, MC alvo {mc['short_win']:.0%}"
        else:
            reason = f"{'Acima' if last > vwl else 'Abaixo'} da VWAP, RSI {rsi:.1f}, MC L {mc['long_win']:.0%} / S {mc['short_win']:.0%}"
    elif len(close) < MIN_BARS:
        reason = f"Pregao com {len(close)} barras (minimo {MIN_BARS})"

    position = None
    if p is not None:
        position = {"ticket": p.ticket, "type": "BUY" if p.type == mt5.POSITION_TYPE_BUY else "SELL",
                    "volume": p.volume, "price_open": p.price_open, "sl": p.sl, "tp": p.tp, "profit": p.profit}

    spread = None
    if tick and sinfo and sinfo.point:
        spread = round((tick.ask - tick.bid) / sinfo.point)

    setstate(
        connected=True, error="", account=account, session_date=str(sess), is_today=(sess == today_srv),
        market_live=market_live,
        bars=int(len(closed)), price=price, bid=tick.bid if tick else None, ask=tick.ask if tick else None,
        spread=spread, digits=digits, vwap=vwl, rsi=rsi, atr=atr,
        dist_vwap_pct=((price / vwl - 1) * 100 if vwl else None), mc=mc, signal=signal, reason=reason,
        position=position, score=score, lots=lots,
        closes=[float(x) for x in day["close"][-90:]],
        vwaps=[float(x) for x in vwap_series(day)[-90:]],
        candles=[[float(b["open"]), float(b["high"]), float(b["low"]), float(b["close"])] for b in day[-48:]],
        updated=datetime.now().strftime("%H:%M:%S"),
    )

    # ---- circuit breaker
    if account["balance"] > 0 and score["pnl"] <= -account["balance"] * MAX_DAILY_LOSS_PCT / 100 and not STATE["circuit_breaker"]:
        setstate(circuit_breaker=True, auto_trade=False)
        log(f"[CIRCUIT BREAKER] Perda diaria {score['pnl']:.2f} >= {MAX_DAILY_LOSS_PCT}% do saldo. Auto-trade DESLIGADO.")

    pos_txt = f"{position['type']} {position['volume']:g} P&L {position['profit']:+.2f}" if position else "SEM POSICAO"
    setstate(ticker=f"{sym} {price:.{digits}f} | VWAP {vwl or 0:.{digits}f} | RSI {rsi or 0:.1f} | SINAL: {signal} | "
                    f"{pos_txt} | PLACAR {score['wins']}W/{score['losses']}L {score['pnl']:+.2f} {account['currency']} | "
                    f"AUTO-TRADE {'ON' if STATE['auto_trade'] else 'OFF'}")

    # ---- execucao: uma decisao por candle fechado
    bar_t = int(closed["time"][-1])
    new_bar = bar_t != RUNTIME["last_bar_time"]
    RUNTIME["last_bar_time"] = bar_t
    if not (new_bar and STATE["auto_trade"] and signal != "AGUARDAR"):
        return
    if not tsym:
        log("[BLOQUEIO] Nenhum contrato negociavel encontrado para enviar ordens.")
        return
    if not STATE["is_today"] or not STATE.get("market_live"):
        log("[BLOQUEIO] Mercado sem negociacao agora (sem ticks novos) - ordem nao enviada.")
        return
    if not account["algo_enabled"]:
        log("[BLOQUEIO] Ative o botao 'Algo Trading' no MetaTrader 5.")
        return
    if account["mode"] == "REAL" and not STATE["real_confirmed"]:
        log("[BLOQUEIO] Conta REAL sem confirmacao na tela.")
        return
    if position is not None:
        return
    if score["trades"] >= MAX_TRADES_DAY:
        log(f"[BLOQUEIO] Limite de {MAX_TRADES_DAY} trades/dia atingido.")
        return
    side = "BUY" if signal == "COMPRA" else "SELL"
    with MT5_LOCK:
        tk = mt5.symbol_info_tick(tsym)
        si = mt5.symbol_info(tsym)
        if tk is None or si is None:
            return
        entry = tk.ask if side == "BUY" else tk.bid
        min_dist = (si.trade_stops_level or 0) * si.point
        sl_d = max(SL_ATR * atr, min_dist + tick_size)
        tp_d = max(TP_ATR * atr, min_dist + tick_size)
        sl = round_tick(entry - sl_d if side == "BUY" else entry + sl_d, si.trade_tick_size)
        tp = round_tick(entry + tp_d if side == "BUY" else entry - tp_d, si.trade_tick_size)
        ok, msg = send_market(tsym, side, lots, sl=sl, tp=tp)
    log(f"[ORDEM {'ENVIADA' if ok else 'REJEITADA'}] {side} {lots:g} {tsym} SL {sl} TP {tp} | {msg}")


# ----------------------------------------------------------------------------- simulacao do dia (sem ordens)
def backtest_today(paths=2000):
    """Roda a MESMA regra candle a candle sobre os candles M1 reais de hoje. Nao envia ordens.

    Sem look-ahead: o sinal usa so barras ate i (VWAP cumulativa, RSI/ATR/MC sobre close[:i+1]);
    a entrada e na ABERTURA do candle i+1. Se stop e alvo cabem no mesmo candle, conta o STOP
    (conservador). Posicao aberta no ultimo candle fecha no fechamento. Sem custos/slippage.
    """
    t0 = time.time()
    if not mt5_connect():
        return {"ok": False, "msg": "MetaTrader 5 desconectado."}
    with MT5_LOCK:
        sym = STATE.get("symbol") or pick_symbol()
        tsym = STATE.get("trade_symbol") or resolve_trade_symbol(sym) or sym
        rates = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M1, 0, 1500)
        si = mt5.symbol_info(tsym) or mt5.symbol_info(sym)
    if rates is None or si is None or len(rates) < MIN_BARS + 2:
        return {"ok": False, "msg": "Poucos candles para simular."}
    sess = server_date(rates[-1]["time"])
    day = rates[np.array([server_date(t) == sess for t in rates["time"]])]
    if STATE.get("market_live") and len(day) > 1:
        day = day[:-1]  # candle em formacao fica de fora
    n = len(day)
    if n < MIN_BARS + 2:
        return {"ok": False, "msg": f"Pregao com so {n} candles (minimo {MIN_BARS + 2})."}
    o, h, l, c = (day[k].astype(float) for k in ("open", "high", "low", "close"))
    vw = vwap_series(day)
    tick = si.trade_tick_size or si.point or 1.0
    pv = (si.trade_tick_value / tick) if si.trade_tick_value else 1.0  # dinheiro por ponto por lote
    lots = RUNTIME["lots"] or si.volume_min or 1.0
    hhmm = lambda i: datetime.fromtimestamp(int(day["time"][i]), tz=timezone.utc).strftime("%H:%M")
    rng = np.random.default_rng(int(day["time"][0]))  # reprodutivel para o mesmo dia
    trades, pos = [], None

    for i in range(MIN_BARS, n):
        if pos:
            hit = None
            if pos["side"] == "BUY":
                if l[i] <= pos["sl"]:
                    hit = ("STOP", pos["sl"])
                elif h[i] >= pos["tp"]:
                    hit = ("ALVO", pos["tp"])
            else:
                if h[i] >= pos["sl"]:
                    hit = ("STOP", pos["sl"])
                elif l[i] <= pos["tp"]:
                    hit = ("ALVO", pos["tp"])
            if hit is None and i == n - 1:
                hit = ("FIM DO DIA", c[i])
            if hit:
                pts = (hit[1] - pos["entry"]) if pos["side"] == "BUY" else (pos["entry"] - hit[1])
                trades.append({**{k: pos[k] for k in ("side", "entry", "sl", "tp", "entry_time", "rsi", "mc")},
                               "exit": float(hit[1]), "exit_time": hhmm(i), "reason": hit[0],
                               "points": round(float(pts), 5), "money": round(float(pts * pv * lots), 2), "bar": i})
                pos = None
            continue
        if i >= n - 1 or len(trades) >= MAX_TRADES_DAY:
            continue
        rsi = rsi_wilder(c[:i + 1])
        atr = atr_wilder(day[:i + 1])
        last, v = c[i], float(vw[i])
        if rsi is None or not atr or not ((last > v and 50 < rsi < 70) or (last < v and 30 < rsi < 50)):
            continue
        mc = monte_carlo(c[:i + 1], SL_ATR * atr, TP_ATR * atr, paths=paths, rng=rng)
        sig = signal_from(last, v, rsi, mc)
        if sig == "AGUARDAR":
            continue
        side = "BUY" if sig == "COMPRA" else "SELL"
        entry = o[i + 1]
        sl = round_tick(entry - SL_ATR * atr if side == "BUY" else entry + SL_ATR * atr, tick)
        tp = round_tick(entry + TP_ATR * atr if side == "BUY" else entry - TP_ATR * atr, tick)
        pos = {"side": side, "entry": float(entry), "sl": float(sl), "tp": float(tp), "entry_time": hhmm(i + 1),
               "rsi": round(rsi, 1), "mc": round(mc["long_win"] if side == "BUY" else mc["short_win"], 3)}

    eq, peak, dd = [], 0.0, 0.0
    for t in trades:
        eq.append(round((eq[-1] if eq else 0.0) + t["money"], 2))
        peak = max(peak, eq[-1])
        dd = min(dd, eq[-1] - peak)
    wins = sum(1 for t in trades if t["money"] > 0)
    res = {"ok": True, "symbol": sym, "trade_symbol": tsym, "date": str(sess), "bars": n,
           "first": hhmm(0), "last": hhmm(n - 1), "lots": lots, "point_value": pv, "paths": paths,
           "trades": trades, "wins": wins, "losses": len(trades) - wins,
           "pnl_points": round(sum(t["points"] for t in trades), 5), "pnl_money": round(sum(t["money"] for t in trades), 2),
           "max_dd": round(dd, 2), "equity": eq, "closes": [float(x) for x in c], "elapsed": round(time.time() - t0, 2)}
    log(f"[SIMULACAO] {sym} {sess}: {len(trades)} trades, {wins}W/{len(trades) - wins}L, "
        f"{res['pnl_money']:+.2f} ({res['pnl_points']:+g} pts) em {res['elapsed']}s - nenhuma ordem enviada")
    return res


def brain_loop():
    log("Sistema Grupo Bressan iniciado (Python 3.12).")
    while True:
        try:
            if RUNTIME["panic"]:
                RUNTIME["panic"] = False
                close_all("PANIC")
            cycle()
        except Exception as e:  # nunca derruba o servidor
            setstate(error=f"Erro no ciclo: {e!r}")
            log(f"[ERRO] {e!r}")
            time.sleep(3)
        time.sleep(LOOP_SECONDS)


# ----------------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, code=200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/state"):
            with STATE_LOCK:
                snap = json.loads(json.dumps(STATE, default=str))
            return self._json(snap)
        if self.path in ("/", "/index.html", "/war_room.html"):
            with open(HTML_FILE, "rb") as f:
                body = f.read()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        self._json({"error": "not found"}, 404)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            data = {}
        if self.path == "/api/toggle":
            want = not STATE["auto_trade"]
            acc = STATE.get("account") or {}
            if want and STATE["circuit_breaker"]:
                return self._json({"ok": False, "msg": "Circuit breaker ativo hoje."})
            if want and acc.get("mode") == "REAL" and not data.get("confirm_real"):
                return self._json({"ok": False, "need_confirm": True})
            setstate(auto_trade=want, real_confirmed=bool(want and acc.get("mode") == "REAL"))
            log(f"[COMANDO] AUTO-TRADE MT5: {'ON' if want else 'OFF'}" + (" (CONTA REAL CONFIRMADA)" if want and acc.get("mode") == "REAL" else ""))
            return self._json({"ok": True, "auto_trade": want})
        if self.path == "/api/backtest":
            try:
                return self._json(backtest_today())
            except Exception as e:
                log(f"[SIMULACAO] erro: {e!r}")
                return self._json({"ok": False, "msg": f"Erro na simulacao: {e!r}"})
        if self.path == "/api/panic":
            setstate(auto_trade=False, real_confirmed=False)
            RUNTIME["panic"] = True
            log("[PANICO] Auto-trade OFF. Zerando posicoes do robo...")
            return self._json({"ok": True})
        self._json({"error": "not found"}, 404)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser(description="Grupo Bressan MT5 Live Trader")
    ap.add_argument("--symbol", help="forcar ativo de dados (ex.: WIN$, WDO$N, EURUSD)")
    ap.add_argument("--lots", type=float, help="lote por ordem (padrao: volume minimo do ativo)")
    ap.add_argument("--no-browser", action="store_true")
    args = ap.parse_args()
    RUNTIME["forced_symbol"] = args.symbol
    RUNTIME["lots"] = args.lots
    threading.Thread(target=brain_loop, daemon=True).start()
    srv = ThreadingHTTPServer((HOST, PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Sala Grupo Bressan rodando em {url}  (Ctrl+C para parar)", flush=True)
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if HAS_MT5:
            mt5.shutdown()


if __name__ == "__main__":
    main()

---
name: quant-mt5-war-room
description: Sala isometrica pixel art ao vivo conectada ao MetaTrader 5 (VWAP, RSI, Monte Carlo e ordens com SL/TP). Use quando o usuario quiser abrir, ajustar ou entender a War Room / auto-trade MT5.
---
Arquivos: `scripts/mt5_live_trader.py` (motor + servidor HTTP na porta 8000) e `scripts/war_room.html` (escritorio isometrico).

Executar somente com Python 3.12: `py -3.12 scripts/mt5_live_trader.py` (opcoes: `--symbol WIN$`, `--lots 1`, `--no-browser`).
Dependencias: `py -3.12 -m pip install MetaTrader5 numpy`.

Endpoints: `GET /api/state`, `POST /api/toggle` (conta REAL exige `{"confirm_real": true}`), `POST /api/panic`.

Logica: candles M1 do pregao atual -> VWAP, RSI(14), ATR(14) -> Monte Carlo bootstrap 5000x30 dos retornos reais ->
COMPRA se preco > VWAP, 50 < RSI < 70 e P(alvo antes do stop) >= 40%; VENDA no espelho. Stop 1,5xATR e alvo 3xATR.
Ordens so com AUTO-TRADE ON, Algo Trading ligado no terminal, mercado com ticks novos e sem posicao aberta do robo.

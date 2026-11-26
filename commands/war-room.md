---
description: Abre a War Room isometrica (atalho de /sala-mt5) e, se pedido, simula o pregao de hoje sem enviar ordens.
---
Acione `quant-swarm-commander` com a skill `quant-mt5-war-room`.
1. Inicie com Python 3.12: `py -3.12 scripts/mt5_live_trader.py` (abre http://localhost:8000).
2. Se o usuario pedir o resultado do dia, chame `POST http://localhost:8000/api/backtest` (simulacao com candles reais, nenhuma ordem) e resuma trades, acerto, pontos e resultado.
3. Nunca ligue o AUTO-TRADE pelo usuario; o botao na tela e dele.

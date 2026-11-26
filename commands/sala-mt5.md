---
description: Inicia a War Room isometrica ao vivo (4 robos + MT5 real) em http://localhost:8000.
---
Acione `quant-swarm-commander` e `quant-execution-engineer` com a skill `quant-mt5-war-room`.
1. Confirme que o MetaTrader 5 esta aberto e logado. Se faltar dependencia: `py -3.12 -m pip install MetaTrader5 numpy`.
2. Inicie o servidor com Python 3.12: `py -3.12 scripts/mt5_live_trader.py` (abre http://localhost:8000 no navegador).
3. Leia `/api/state` e informe ao usuario conta (DEMO/REAL), ativo, VWAP, RSI, Monte Carlo e bloqueios ativos.
4. Nao ligue o AUTO-TRADE pelo usuario; o botao verde na tela e dele.

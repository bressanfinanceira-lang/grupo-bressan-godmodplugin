# Grupo Bressan - GodModPlugin v8.2 [War Room MT5 ao vivo]

Plugin para Claude Code com uma War Room isometrica em pixel art conectada ao MetaTrader 5,
mais skills, agentes e comandos de pesquisa quantitativa. Scripts rodam com **Python 3.12** (`py -3.12`).

## Instalacao

```
/plugin install grupo-bressan-godmodplugin --marketplace bressanfinanceira-lang/grupo-bressan-godmodplugin
```

Ou em duas etapas:

```
/plugin marketplace add bressanfinanceira-lang/grupo-bressan-godmodplugin
/plugin install grupo-bressan-godmodplugin@grupo-bressan
```

Dependencias da War Room (Windows com MetaTrader 5 aberto):

```
py -3.12 -m pip install MetaTrader5 numpy
```

## Comandos

| Comando | O que faz |
|---|---|
| `/war-room` | Abre a War Room e, se pedido, simula o pregao de hoje |
| `/sala-mt5` | Inicia a War Room ao vivo em http://localhost:8000 |
| `/sovereign` | Ciclo completo: pesquisa, auditoria, portfolio e War Room |
| `/mesa-quant` | Pesquisador + Auditor + Arquiteto montam um portfolio |
| `/pesquisar` | Descoberta autonoma de estrategias |
| `/auditar` | Auditoria de risco de um robo existente |
| `/deploy-testnet` | Estrutura de deploy em paper trading / testnet |

## Estrutura

- `.claude-plugin/` - `plugin.json`, `marketplace.json` e icone
- `skills/` - quant-hyper-matrix, quant-evolutionary-lab, quant-monte-carlo-redteam, quant-risk-shield, quant-hft-execution, quant-mt5-war-room
- `agents/` - alpha-researcher, risk-auditor, portfolio-architect, swarm-commander, execution-engineer
- `commands/` - os 7 comandos acima
- `hooks/` - SessionStart + PreToolUse (`guard_secrets.py` bloqueia chaves privadas gravadas no codigo)
- `.mcp.json` + `mcp/quant_mcp_server.py` - servidor MCP quant
- `scripts/` - `mt5_live_trader.py` (motor + servidor HTTP), `war_room.html` (escritorio isometrico), quant_engine, tear_sheet, exchange_router

## War Room

```
py -3.12 scripts/mt5_live_trader.py
```

- Candles M1 reais do pregao: VWAP, RSI(14), ATR(14) e Monte Carlo bootstrap (5000 caminhos).
- **Simular o dia de hoje:** roda a regra candle a candle sobre os candles reais e mostra trades, acerto e curva de capital. Nao envia ordens.
- **Auto-trade:** ordens reais (`mt5.order_send`, SL 1,5xATR / TP 3xATR) somente com o botao AUTO-TRADE MT5: ON. Conta REAL exige confirmacao extra; travas de 1 posicao, limite diario de trades, circuit breaker e PANIC STOP.

## Aviso Legal

Ferramenta de pesquisa e engenharia de software, sem garantia de lucro e sem recomendacao de investimento.
Operacoes financeiras envolvem alto risco de perda de capital. Valide sempre em conta DEMO.

## Licenca

MIT - veja [LICENSE](LICENSE).

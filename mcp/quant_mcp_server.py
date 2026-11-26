import sys
import json
import os
sys.path.append(os.path.join(os.path.dirname(__file__), "..", "scripts"))

def handle_request(req):
    method = req.get("method")
    req_id = req.get("id")
    if method == "initialize":
        return {"jsonrpc":"2.0","id":req_id,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"grupo-bressan-quant-mcp","version":"7.0.0"}}}
    elif method == "tools/list":
        return {"jsonrpc":"2.0","id":req_id,"result":{"tools":[
            {"name":"quant_status","description":"Status completo do laboratorio Grupo Bressan v7.0.","inputSchema":{"type":"object","properties":{}}},
            {"name":"market_config","description":"Retorna parametros de execucao para CRYPTO ou B3.","inputSchema":{"type":"object","properties":{"market":{"type":"string"}}}}
        ]}}
    elif method == "tools/call":
        name = req.get("params", {}).get("name")
        if name == "market_config":
            from exchange_router import get_market_adapter
            m = req.get("params", {}).get("arguments", {}).get("market", "CRYPTO")
            return {"jsonrpc":"2.0","id":req_id,"result":{"content":[{"type":"text","text":json.dumps(get_market_adapter(m))}]}}
        return {"jsonrpc":"2.0","id":req_id,"result":{"content":[{"type":"text","text":"Grupo Bressan v7.0 MCP Ativo [Crypto + B3 + TearSheet + MonteCarlo]."}]}}
    return None

if __name__ == "__main__":
    for line in sys.stdin:
        try:
            res = handle_request(json.loads(line))
            if res:
                print(json.dumps(res), flush=True)
        except Exception:
            pass

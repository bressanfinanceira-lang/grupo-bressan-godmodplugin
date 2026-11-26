"""Roteador Universal Grupo Bressan - Suporte a Cripto [CCXT] e B3/Forex [MetaTrader5]."""
import os

def get_market_adapter(market_type="CRYPTO"):
    if market_type.upper() == "CRYPTO":
        return {"engine": "ccxt.pro", "fees_maker": 0.0002, "fees_taker": 0.0005, "24_7": True}
    elif market_type.upper() == "B3":
        return {"engine": "MetaTrader5", "tick_size_win": 5.0, "tick_size_wdo": 0.5, "24_7": False}
    return {"engine": "generic_rest", "fees_taker": 0.001, "24_7": True}

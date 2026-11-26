"""Atalho legado: a War Room agora roda em scripts/mt5_live_trader.py (dados e ordens reais do MT5).

Use: py -3.12 scripts/isometric_war_room.py   (equivale a py -3.12 scripts/mt5_live_trader.py)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mt5_live_trader import main  # noqa: E402

if __name__ == "__main__":
    main()

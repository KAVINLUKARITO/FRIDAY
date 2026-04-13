# Trading System

This is a standalone algorithmic trading application.
It is NOT part of the root AI Worker (runner.py / aiworker/).

## Run independently

```bash
cd trading_system
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## Test independently

```bash
cd trading_system
pytest tests/ -v
```

## Why it lives here

This module is co-located for development convenience.
It shares no runtime code with the root aiworker/ package.
Do not import from trading_system/ in aiworker/ or vice versa.

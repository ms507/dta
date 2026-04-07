# Day Trading Agent

Python-basierter Krypto Day Trading Agent für Binance mit 5 klassischen Strategien, einer gewichteten lokalen AI-Entscheidungslogik und vollständigem Risikomanagement.

## Architektur

```
day_trading_agent/
├── main.py                     # Einstiegspunkt
├── agent.py                    # Haupt-Orchestrator
├── config.py                   # Konfiguration via .env
├── risk_manager.py             # Stop-Loss, Take-Profit, Positionsgröße
├── portfolio.py                # Verwaltung offener Positionen
├── broker/
│   ├── base.py                 # Abstrakte Broker-Schnittstelle
│   └── binance_broker.py       # Binance-Implementierung
├── strategies/
│   ├── base.py                 # Abstrakte Strategie + Signal-Enum
│   ├── rsi_strategy.py         # RSI Überverkauft/Überkauft
│   ├── macd_strategy.py        # MACD-Kreuzung
│   ├── ma_crossover.py         # EMA Golden/Death Cross
│   ├── bollinger_strategy.py   # Bollinger-Band Reversion
│   └── momentum_strategy.py    # ROC + Volumen-Spike
└── utils/
    └── logger.py               # Farbiges Console- & File-Logging
```

## Quick Start

### 1. Abhängigkeiten installieren
```bash
pip install -r requirements.txt
```

### 2. .env-Datei anlegen
```bash
copy .env.example .env
```
Trage deine Binance API-Keys in `.env` ein.

> **Testnet empfohlen** — Erstelle Testnet-Keys unter https://testnet.binance.vision

### 3. Agent starten
```bash
python main.py
```

## Webinterface

Ein lokales Dashboard zeigt den aktuellen Kontostand, Tages-PnL, investierte Assets und erlaubt das Bearbeiten der `.env`-Werte.

Bereits im Binance-Konto vorhandene Bestände der konfigurierten Handelspaare werden beim Start und vor jedem Zyklus ins Portfolio übernommen. Dadurch kann der Bot auch manuell oder früher gekaufte Assets per SELL-Signal sowie via Stop-Loss/Take-Profit verwalten.

### Starten
```bash
pip install -r requirements.txt
python webapp.py
```

Dann im Browser oeffnen:
- `http://localhost:8080` (Dashboard)
- `http://localhost:8080/settings` (.env-Einstellungen)

Hinweis: Nach Aenderungen in der Einstellungsseite den Bot neu starten, damit alle neuen Werte aktiv werden.

## Update Auf LXC Ohne Config-Verlust

Wenn du eine neue ZIP-Version deployen willst und `.env` plus `keys/` behalten moechtest:

1. Backup im LXC anlegen
```bash
cd /opt/day_trading_agent
cp .env /root/day_trading_agent.env.bak
cp -r keys /root/day_trading_agent.keys.bak
```

2. Neue ZIP in den Container kopieren (vom Proxmox-Host)
```bash
pct push 100 /root/day_trading_agent.zip /root/day_trading_agent.zip
```

3. Code sicher aktualisieren, Config wiederherstellen
```bash
pct exec 100 -- bash -lc "set -e; cd /opt; rm -rf /opt/day_trading_agent.new; mkdir -p /opt/day_trading_agent.new; unzip -o /root/day_trading_agent.zip -d /opt/day_trading_agent.new; cp /opt/day_trading_agent/.env /opt/day_trading_agent.new/.env || true; cp -r /opt/day_trading_agent/keys /opt/day_trading_agent.new/keys || true; rm -rf /opt/day_trading_agent; mv /opt/day_trading_agent.new /opt/day_trading_agent"
```

4. Abhaengigkeiten updaten und starten
```bash
pct exec 100 -- bash -lc "cd /opt/day_trading_agent && python3 -m venv .venv && . .venv/bin/activate && pip install --upgrade pip && pip install -r requirements.txt"
pct exec 100 -- bash -lc "cd /opt/day_trading_agent && . .venv/bin/activate && python3 webapp.py"
```

## Strategien

| Strategie | Signal-Logik |
|-----------|-------------|
| **RSI** | Kauf wenn RSI aus Überverkauft-Zone (<30) steigt; Verkauf aus Überkauft-Zone (>70) |
| **MACD** | Kauf bei bullischer MACD/Signal-Kreuzung; Verkauf bei bärischer |
| **MA Crossover** | EMA(9) kreuzt EMA(21) nach oben (Golden Cross) / unten (Death Cross) |
| **Bollinger** | Kauf bei Unterschreiten des unteren Bandes; Verkauf bei Überschreiten des oberen |
| **Momentum** | Rate of Change positiv/negativ + Volumen-Spike als Bestätigung |

Ein Trade wird nur ausgelöst, wenn **mindestens 3 von 5** Strategien übereinstimmen (konfigurierbar via `MIN_SIGNAL_CONSENSUS`).

Zusätzlich ist eine lokale AI-Entscheidungsstrategie aktiv. Sie bewertet RSI, MACD, EMA-Abstand, Trend, Bollinger-Lage und Momentum gewichtet und bringt 2 Stimmen in die Entscheidung ein. Damit kann der Bot auch in laufende Trends einsteigen, statt nur sehr seltene Einzelkerzen-Crossovers zu handeln.

## Risikomanagement

- **Positionsgröße**: max. 2% des Guthabens pro Trade
- **Stop-Loss**: 1,5% unterhalb des Einstiegspreises
- **Take-Profit**: 3,0% oberhalb des Einstiegspreises
- **Tagesverlust-Limit**: Keine neuen Trades wenn 5% des Tagesstartguthabens verloren
- **Max. offene Positionen**: 3 gleichzeitig

Alle Werte sind in `.env` anpassbar.

## Konfiguration

| Variable | Standard | Beschreibung |
|----------|---------|--------------|
| `BINANCE_TESTNET` | `true` | `true` = Testnet, `false` = Live |
| `TRADING_SYMBOLS` | `BTCUSDT,ETHUSDT` | Handelspaare |
| `TIMEFRAME` | `15m` | Kerzen-Zeitrahmen |
| `MIN_SIGNAL_CONSENSUS` | `3` | Mindestanzahl übereinstimmender Strategien |
| `CHECK_INTERVAL` | `60` | Prüfintervall in Sekunden |
| `MAX_POSITION_PCT` | `0.02` | Max. 2% pro Trade |
| `STOP_LOSS_PCT` | `0.015` | 1,5% Stop-Loss |
| `TAKE_PROFIT_PCT` | `0.03` | 3% Take-Profit |
| `MAX_DAILY_LOSS_PCT` | `0.05` | 5% Tagesverlust-Limit |
| `MAX_OPEN_POSITIONS` | `3` | Max. gleichzeitige Positionen |

## Haftungsausschluss

Dieser Agent dient ausschließlich zu Bildungszwecken.  
**Der Einsatz mit echtem Kapital erfolgt auf eigene Gefahr.**  
Vergangene Signale garantieren keine zukünftigen Gewinne.

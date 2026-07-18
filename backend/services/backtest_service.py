from datetime import datetime, timezone

from backend.models.schemas import BacktestRequest, BacktestResult
from backend.services.market_data import market_data_service
from backend.services.timeframes import aggregate_candles
from engine.market_structure import ema


def run_backtest(request: BacktestRequest) -> BacktestResult:
    candles = aggregate_candles(market_data_service.snapshot(limit=request.max_bars), request.timeframe)
    if len(candles) < 80:
        return BacktestResult(generated_at=datetime.now(timezone.utc), trades=0, wins=0, losses=0, expired=0, win_rate=0, average_r=0, profit_factor=0, net_r=0, equity_curve=[0], rows=[])
    closes = [c.close for c in candles]
    e9, e21, e55 = ema(closes, 9), ema(closes, 21), ema(closes, 55)
    rows, equity, total = [], [0.0], 0.0
    cooldown = 0
    for i in range(60, len(candles) - 30):
        if cooldown:
            cooldown -= 1; continue
        direction = "LONG" if e9[i] > e21[i] > e55[i] else "SHORT" if e9[i] < e21[i] < e55[i] else None
        if not direction:
            continue
        recent = candles[i-14:i+1]
        atr = sum(c.high-c.low for c in recent) / len(recent)
        if atr <= 0: continue
        entry = candles[i].close
        stop = entry - atr if direction == "LONG" else entry + atr
        target = entry + atr * request.target_r if direction == "LONG" else entry - atr * request.target_r
        result, exit_time = 0.0, candles[min(i+30, len(candles)-1)].time
        for future in candles[i+1:i+31]:
            stop_hit = future.low <= stop if direction == "LONG" else future.high >= stop
            target_hit = future.high >= target if direction == "LONG" else future.low <= target
            if stop_hit and target_hit:
                result = -1.0; exit_time = future.time; break
            if stop_hit:
                result = -1.0; exit_time = future.time; break
            if target_hit:
                result = request.target_r; exit_time = future.time; break
        total += result; equity.append(round(total, 2))
        rows.append({"time": candles[i].time, "exit_time": exit_time, "direction": direction, "entry": round(entry,2), "stop": round(stop,2), "target": round(target,2), "result_r": result})
        cooldown = 4
    wins = sum(1 for r in rows if r["result_r"] > 0); losses = sum(1 for r in rows if r["result_r"] < 0); expired = len(rows)-wins-losses
    results = [r["result_r"] for r in rows]
    gross_win = sum(r for r in results if r>0); gross_loss = abs(sum(r for r in results if r<0))
    return BacktestResult(
        generated_at=datetime.now(timezone.utc), trades=len(rows), wins=wins, losses=losses, expired=expired,
        win_rate=round(wins/len(rows)*100,1) if rows else 0,
        average_r=round(sum(results)/len(results),2) if results else 0,
        profit_factor=round(gross_win/gross_loss,2) if gross_loss else gross_win,
        net_r=round(sum(results),2), equity_curve=equity, rows=rows[-100:],
    )

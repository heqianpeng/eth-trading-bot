#!/usr/bin/env python3
"""
所有策略对比回测
"""
import asyncio
import yaml
import numpy as np
from datetime import datetime
from loguru import logger
import sys

from data_fetcher import DataFetcher
from indicators import TechnicalIndicators
from strategy_overnight import OvernightStrategy
from strategy_trend import TrendStrategy, SignalType
from strategy_breakout import BreakoutStrategy
from strategy_combo import ComboStrategy


async def backtest_strategy(strategy, strategy_name, df, indicators_calc, leverage=20, position_size=0.10):
    """回测单个策略"""
    trades = []
    position = None
    initial_capital = 10000
    capital = initial_capital
    
    for i in range(50, len(df)):
        current_bar = df.iloc[i]
        current_time = df.index[i]
        current_price = current_bar['close']
        
        historical = df.iloc[:i+1].copy()
        ind = indicators_calc.calculate_all(historical)
        
        if not ind:
            continue
        
        # 检查平仓
        if position:
            exit_reason = None
            exit_price = None
            
            if position['direction'] == 'long':
                if current_bar['low'] <= position['stop_loss']:
                    exit_price = position['stop_loss']
                    exit_reason = "止损"
                elif current_bar['high'] >= position['take_profit']:
                    exit_price = position['take_profit']
                    exit_reason = "止盈"
            else:
                if current_bar['high'] >= position['stop_loss']:
                    exit_price = position['stop_loss']
                    exit_reason = "止损"
                elif current_bar['low'] <= position['take_profit']:
                    exit_price = position['take_profit']
                    exit_reason = "止盈"
            
            if exit_reason:
                if position['direction'] == 'long':
                    pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
                else:
                    pnl_pct = (position['entry_price'] - exit_price) / position['entry_price']
                
                pnl_pct_leveraged = pnl_pct * leverage * position_size
                pnl = capital * pnl_pct_leveraged
                
                if pnl_pct * leverage <= -1:
                    pnl = -capital * position_size
                
                capital += pnl
                hold_hours = (current_time - position['entry_time']).total_seconds() / 3600
                
                trades.append({
                    'pnl_pct': pnl_pct_leveraged * 100,
                    'pnl': pnl,
                    'exit_reason': exit_reason,
                    'hold_hours': hold_hours
                })
                position = None
                
                if capital <= 0:
                    break
        
        # 开仓
        if not position and capital > 0:
            signal = strategy.analyze(ind, '1h')
            if signal and signal.signal_type != SignalType.NEUTRAL:
                direction = 'long' if signal.signal_type in [SignalType.BUY, SignalType.STRONG_BUY] else 'short'
                position = {
                    'entry_time': current_time,
                    'entry_price': current_price,
                    'direction': direction,
                    'stop_loss': signal.stop_loss,
                    'take_profit': signal.take_profit
                }
    
    # 计算统计
    if not trades:
        return None
    
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    
    total_return = (capital - initial_capital) / initial_capital * 100
    win_rate = len(wins) / len(trades) * 100 if trades else 0
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
    profit_factor = abs(sum(t['pnl_pct'] for t in wins) / sum(t['pnl_pct'] for t in losses)) if losses and sum(t['pnl_pct'] for t in losses) != 0 else float('inf')
    avg_hold = np.mean([t['hold_hours'] for t in trades])
    
    # 最大回撤
    equity = initial_capital
    peak = initial_capital
    max_dd = 0
    for t in trades:
        equity += t['pnl']
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        max_dd = min(max_dd, dd)
    
    # 夏普比率
    if len(trades) > 1:
        returns = [t['pnl_pct'] for t in trades]
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 / avg_hold * 24) if np.std(returns) > 0 else 0
    else:
        sharpe = 0
    
    return {
        'name': strategy_name,
        'total_return': total_return,
        'win_rate': win_rate,
        'profit_factor': profit_factor,
        'max_dd': max_dd * 100,
        'sharpe': sharpe,
        'trades': len(trades),
        'avg_hold': avg_hold
    }


async def main(days: int = 40):
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    fetcher = DataFetcher(config)
    await fetcher.init()
    
    limit = min(days * 24, 1000)
    df = await fetcher.fetch_ohlcv('1h', limit=limit)
    await fetcher.close()
    
    if df.empty or len(df) < 100:
        print("数据不足")
        return
    
    indicators_calc = TechnicalIndicators(config)
    
    # 所有策略
    strategies = [
        (OvernightStrategy(config), "均值回归"),
        (TrendStrategy(config), "趋势跟踪"),
        (BreakoutStrategy(config), "突破策略"),
        (ComboStrategy(config), "多策略组合"),
    ]
    
    print("\n" + "=" * 80)
    print(f"         策略对比回测（{days}天，20倍杠杆，10%仓位）")
    print("=" * 80)
    print(f"数据范围: {df.index[50]} ~ {df.index[-1]}\n")
    
    results = []
    for strategy, name in strategies:
        result = await backtest_strategy(strategy, name, df, indicators_calc)
        if result:
            results.append(result)
    
    # 打印对比表格
    print(f"{'策略':<12} {'收益':>8} {'胜率':>8} {'盈亏比':>8} {'回撤':>8} {'夏普':>8} {'交易数':>8}")
    print("-" * 80)
    
    for r in results:
        print(f"{r['name']:<12} {r['total_return']:>+7.2f}% {r['win_rate']:>7.1f}% "
              f"{r['profit_factor']:>8.2f} {r['max_dd']:>7.2f}% {r['sharpe']:>8.2f} {r['trades']:>8}")
    
    print("-" * 80)
    
    # 找出最佳策略
    if results:
        # 综合评分：收益*0.3 + 胜率*0.2 + 盈亏比*0.2 + (100-回撤)*0.15 + 夏普*0.15
        for r in results:
            r['score'] = (
                r['total_return'] * 0.3 +
                r['win_rate'] * 0.2 +
                r['profit_factor'] * 10 * 0.2 +
                (100 + r['max_dd']) * 0.15 +
                r['sharpe'] * 0.15
            )
        
        best = max(results, key=lambda x: x['score'])
        print(f"\n🏆 最佳策略: {best['name']}")
        print(f"   收益: {best['total_return']:+.2f}%")
        print(f"   胜率: {best['win_rate']:.1f}%")
        print(f"   盈亏比: {best['profit_factor']:.2f}")
        print(f"   最大回撤: {best['max_dd']:.2f}%")
    
    print("\n" + "=" * 80)


if __name__ == '__main__':
    logger.remove()
    logger.add(sys.stdout, level="WARNING")
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--days', type=int, default=40, help='回测天数')
    args = parser.parse_args()
    
    asyncio.run(main(args.days))

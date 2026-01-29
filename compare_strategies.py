#!/usr/bin/env python3
"""
策略对比 - 简化版
"""
import asyncio
import yaml
import numpy as np
from loguru import logger
import sys

from data_fetcher import DataFetcher
from indicators import TechnicalIndicators


def run_backtest(strategy_class, config, df, indicators_calc, leverage=20, position_size=0.10):
    """运行单个策略回测"""
    strategy = strategy_class(config)
    
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
                capital += pnl
                
                trades.append({'pnl_pct': pnl_pct_leveraged * 100, 'pnl': pnl})
                position = None
                
                if capital <= 0:
                    break
        
        # 开仓
        if not position and capital > 0:
            signal = strategy.analyze(ind, '1h')
            if signal and signal.signal_type.value in ['买入', '强烈买入', '卖出', '强烈卖出']:
                direction = 'long' if signal.signal_type.value in ['买入', '强烈买入'] else 'short'
                position = {
                    'entry_time': current_time,
                    'entry_price': current_price,
                    'direction': direction,
                    'stop_loss': signal.stop_loss,
                    'take_profit': signal.take_profit
                }
    
    if not trades:
        return None
    
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    
    total_return = (capital - initial_capital) / initial_capital * 100
    win_rate = len(wins) / len(trades) * 100
    profit_factor = abs(sum(t['pnl_pct'] for t in wins) / sum(t['pnl_pct'] for t in losses)) if losses and sum(t['pnl_pct'] for t in losses) != 0 else 999
    
    equity = initial_capital
    peak = initial_capital
    max_dd = 0
    for t in trades:
        equity += t['pnl']
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        max_dd = min(max_dd, dd)
    
    return {
        'total_return': total_return,
        'win_rate': win_rate,
        'profit_factor': min(profit_factor, 99),
        'max_dd': max_dd * 100,
        'trades': len(trades)
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
    
    # 导入策略
    from strategy_overnight import OvernightStrategy
    from strategy_trend import TrendStrategy
    from strategy_breakout import BreakoutStrategy
    from strategy_combo import ComboStrategy
    
    strategies = [
        (OvernightStrategy, "均值回归"),
        (TrendStrategy, "趋势跟踪"),
        (BreakoutStrategy, "突破策略"),
        (ComboStrategy, "多策略组合"),
    ]
    
    print("\n" + "=" * 75)
    print(f"         策略对比（{days}天，20倍杠杆，10%仓位）")
    print("=" * 75)
    
    print(f"\n{'策略':<12} {'收益':>10} {'胜率':>8} {'盈亏比':>8} {'回撤':>10} {'交易数':>8}")
    print("-" * 75)
    
    results = []
    for strategy_class, name in strategies:
        result = run_backtest(strategy_class, config, df, indicators_calc)
        if result:
            result['name'] = name
            results.append(result)
            print(f"{name:<12} {result['total_return']:>+9.2f}% {result['win_rate']:>7.1f}% "
                  f"{result['profit_factor']:>8.2f} {result['max_dd']:>9.2f}% {result['trades']:>8}")
    
    print("-" * 75)
    
    if results:
        best = max(results, key=lambda x: x['total_return'])
        print(f"\n🏆 最佳策略: {best['name']}")
        print(f"   收益: {best['total_return']:+.2f}%, 胜率: {best['win_rate']:.1f}%, 回撤: {best['max_dd']:.2f}%")
    
    print("=" * 75)


if __name__ == '__main__':
    logger.remove()
    logger.add(sys.stdout, level="WARNING")
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--days', type=int, default=40, help='回测天数')
    args = parser.parse_args()
    
    asyncio.run(main(args.days))

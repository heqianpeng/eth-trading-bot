#!/usr/bin/env python3
"""
均值回归策略参数优化（快速版）
"""
import itertools
import pandas as pd
import numpy as np
from datetime import datetime
from data_fetcher import DataFetcher
import asyncio
import yaml
import ta

# 加载配置
with open('config.yaml', 'r') as f:
    config = yaml.safe_load(f)

# 简化参数范围
PARAM_GRID = {
    'rsi_oversold': [20, 25, 30],
    'rsi_overbought': [70, 75],
    'sl_mult': [0.6, 0.8, 1.0],
    'tp_mult': [0.8, 1.0, 1.5],
    'signal_threshold': [45, 50, 55],
}


def backtest_params(df, params):
    """快速回测"""
    trades = []
    capital = 10000
    position_size = 0.1
    leverage = 20
    peak_capital = capital
    max_drawdown = 0
    
    rsi = df['rsi'].values
    bb_pband = df['bb_pband'].values
    stoch_k = df['stoch_k'].values
    atr = df['atr'].values
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    
    i = 50
    while i < len(df) - 48:
        # 计算信号
        score = 0
        
        if rsi[i] < params['rsi_oversold']:
            score += 45
        elif rsi[i] < params['rsi_oversold'] + 10:
            score += 30
        elif rsi[i] > params['rsi_overbought']:
            score -= 45
        elif rsi[i] > params['rsi_overbought'] - 10:
            score -= 30
        
        if bb_pband[i] < 0:
            score += 40
        elif bb_pband[i] < 0.15:
            score += 25
        elif bb_pband[i] > 1:
            score -= 40
        elif bb_pband[i] > 0.85:
            score -= 25
        
        if stoch_k[i] < 20:
            score += 30
        elif stoch_k[i] > 80:
            score -= 30
        
        total_score = score
        
        if abs(total_score) < params['signal_threshold']:
            i += 1
            continue
        
        # 开仓
        entry_price = close[i]
        direction = 'long' if total_score > 0 else 'short'
        sl_dist = atr[i] * params['sl_mult']
        tp_dist = atr[i] * params['tp_mult']
        
        if direction == 'long':
            stop_loss = entry_price - sl_dist
            take_profit = entry_price + tp_dist
        else:
            stop_loss = entry_price + sl_dist
            take_profit = entry_price - tp_dist
        
        # 模拟持仓
        exit_price = None
        for j in range(i + 1, min(i + 48, len(df))):
            if direction == 'long':
                if low[j] <= stop_loss:
                    exit_price = stop_loss
                    break
                elif high[j] >= take_profit:
                    exit_price = take_profit
                    break
            else:
                if high[j] >= stop_loss:
                    exit_price = stop_loss
                    break
                elif low[j] <= take_profit:
                    exit_price = take_profit
                    break
        
        if exit_price is None:
            exit_price = close[min(i + 47, len(df) - 1)]
        
        # 计算收益
        if direction == 'long':
            pnl_pct = (exit_price - entry_price) / entry_price
        else:
            pnl_pct = (entry_price - exit_price) / entry_price
        
        trade_return = pnl_pct * leverage * position_size
        capital *= (1 + trade_return)
        
        if capital > peak_capital:
            peak_capital = capital
        drawdown = (peak_capital - capital) / peak_capital
        max_drawdown = max(max_drawdown, drawdown)
        
        trades.append(trade_return)
        i += 10  # 跳过一段时间避免重复信号
    
    if not trades:
        return {'total_return': 0, 'win_rate': 0, 'trades': 0, 'profit_factor': 0, 'max_drawdown': 0}
    
    wins = [t for t in trades if t > 0]
    losses = [t for t in trades if t <= 0]
    
    total_return = (capital - 10000) / 10000 * 100
    win_rate = len(wins) / len(trades) * 100
    
    total_wins = sum(wins) if wins else 0
    total_losses = abs(sum(losses)) if losses else 0.001
    profit_factor = total_wins / total_losses
    
    return {
        'total_return': total_return,
        'win_rate': win_rate,
        'trades': len(trades),
        'profit_factor': profit_factor,
        'max_drawdown': max_drawdown * 100
    }


async def main():
    print("=" * 70)
    print("均值回归策略参数优化")
    print("=" * 70)
    
    fetcher = DataFetcher(config)
    await fetcher.init()
    
    print("获取历史数据...")
    df = await fetcher.fetch_ohlcv('15m', limit=1500)
    await fetcher.close()
    
    if df is None or len(df) < 100:
        print("数据不足")
        return
    
    # 计算指标
    df['rsi'] = ta.momentum.RSIIndicator(df['close'], window=14).rsi()
    bb = ta.volatility.BollingerBands(df['close'], window=20, window_dev=2)
    df['bb_pband'] = bb.bollinger_pband()
    stoch = ta.momentum.StochasticOscillator(df['high'], df['low'], df['close'], window=14, smooth_window=3)
    df['stoch_k'] = stoch.stoch()
    df['atr'] = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=14).average_true_range()
    
    df = df.dropna()
    
    print(f"数据条数: {len(df)}")
    print()
    
    # 生成参数组合
    param_names = list(PARAM_GRID.keys())
    param_values = list(PARAM_GRID.values())
    combinations = list(itertools.product(*param_values))
    
    print(f"参数组合数: {len(combinations)}")
    print("开始优化...")
    
    results = []
    for combo in combinations:
        params = dict(zip(param_names, combo))
        result = backtest_params(df, params)
        result['params'] = params
        results.append(result)
    
    # 按收益排序
    results.sort(key=lambda x: x['total_return'], reverse=True)
    
    print()
    print("=" * 70)
    print("TOP 10 参数组合（按收益排序）")
    print("=" * 70)
    
    for i, r in enumerate(results[:10]):
        print(f"\n#{i+1} 收益: {r['total_return']:+.2f}% | 胜率: {r['win_rate']:.1f}% | "
              f"盈亏比: {r['profit_factor']:.2f} | 回撤: {r['max_drawdown']:.2f}% | 交易: {r['trades']}次")
        print(f"   RSI: {r['params']['rsi_oversold']}/{r['params']['rsi_overbought']} | "
              f"止损: {r['params']['sl_mult']}ATR | 止盈: {r['params']['tp_mult']}ATR | "
              f"阈值: {r['params']['signal_threshold']}")
    
    # 最佳综合得分
    for r in results:
        r['score'] = r['total_return'] * 0.4 + r['win_rate'] * 0.3 + r['profit_factor'] * 10 * 0.2 - r['max_drawdown'] * 0.1
    
    results_score = sorted([r for r in results if r['trades'] >= 5], key=lambda x: x['score'], reverse=True)
    
    print()
    print("=" * 70)
    print("⭐ 最佳综合参数（推荐使用）")
    print("=" * 70)
    
    best = results_score[0] if results_score else results[0]
    print(f"\n收益: {best['total_return']:+.2f}%")
    print(f"胜率: {best['win_rate']:.1f}%")
    print(f"盈亏比: {best['profit_factor']:.2f}")
    print(f"最大回撤: {best['max_drawdown']:.2f}%")
    print(f"交易次数: {best['trades']}")
    print()
    print("最佳参数:")
    print(f"  RSI超卖阈值: {best['params']['rsi_oversold']}")
    print(f"  RSI超买阈值: {best['params']['rsi_overbought']}")
    print(f"  止损倍数: {best['params']['sl_mult']} ATR")
    print(f"  止盈倍数: {best['params']['tp_mult']} ATR")
    print(f"  信号阈值: {best['params']['signal_threshold']}")


if __name__ == '__main__':
    asyncio.run(main())

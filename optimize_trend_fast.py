#!/usr/bin/env python3
"""
趋势跟踪策略快速参数优化
预计算指标，大幅提升速度
"""
import asyncio
import yaml
import numpy as np
import pandas as pd
from loguru import logger
import sys
from itertools import product

from data_fetcher import DataFetcher
from strategy_trend import SignalType


def calculate_indicators_vectorized(df):
    """向量化计算所有指标"""
    close = df['close']
    high = df['high']
    low = df['low']
    
    # EMA
    df['ema_9'] = close.ewm(span=9).mean()
    df['ema_21'] = close.ewm(span=21).mean()
    
    # MA
    df['ma_20'] = close.rolling(20).mean()
    df['ma_50'] = close.rolling(50).mean()
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # ATR
    tr = pd.concat([
        high - low,
        (high - close.shift()).abs(),
        (low - close.shift()).abs()
    ], axis=1).max(axis=1)
    df['atr'] = tr.rolling(14).mean()
    
    # Bollinger Bands
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    df['bb_upper'] = bb_mid + 2 * bb_std
    df['bb_lower'] = bb_mid - 2 * bb_std
    df['bb_pband'] = (close - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])
    
    # Stochastic
    low_14 = low.rolling(14).min()
    high_14 = high.rolling(14).max()
    df['stoch_k'] = 100 * (close - low_14) / (high_14 - low_14)
    
    # MACD
    ema12 = close.ewm(span=12).mean()
    ema26 = close.ewm(span=26).mean()
    df['macd'] = ema12 - ema26
    df['macd_signal'] = df['macd'].ewm(span=9).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']
    
    # ADX
    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0)
    
    atr14 = tr.rolling(14).mean()
    df['di_plus'] = 100 * (plus_dm.rolling(14).mean() / atr14)
    df['di_minus'] = 100 * (minus_dm.rolling(14).mean() / atr14)
    dx = 100 * (df['di_plus'] - df['di_minus']).abs() / (df['di_plus'] + df['di_minus'])
    df['adx'] = dx.rolling(14).mean()
    
    return df


def get_trend(row, adx_threshold):
    """判断趋势"""
    if pd.isna(row['adx']) or row['adx'] < adx_threshold:
        return 'neutral'
    
    price = row['close']
    up_count = 0
    down_count = 0
    
    if price > row['ma_20']: up_count += 1
    else: down_count += 1
    if price > row['ma_50']: up_count += 1
    else: down_count += 1
    if row['ema_9'] > row['ema_21']: up_count += 1
    else: down_count += 1
    if row['ma_20'] > row['ma_50']: up_count += 1
    else: down_count += 1
    
    if up_count >= 3:
        return 'up'
    elif down_count >= 3:
        return 'down'
    return 'neutral'


def check_entry(row, trend, params):
    """检查入场条件"""
    score = 0
    rsi = row['rsi']
    bb_pband = row['bb_pband']
    k = row['stoch_k']
    price = row['close']
    ema21 = row['ema_21']
    
    rsi_low = params.get('rsi_pullback_low', 35)
    rsi_high = params.get('rsi_pullback_high', 50)
    
    if trend == 'up':
        if rsi_low <= rsi <= rsi_high:
            score += 30
        if 0.3 <= bb_pband <= 0.6:
            score += 25
        if abs(price - ema21) / ema21 < 0.01:
            score += 25
        if 30 <= k <= 50:
            score += 20
    else:
        if (100 - rsi_high) <= rsi <= (100 - rsi_low):
            score -= 30
        if 0.4 <= bb_pband <= 0.7:
            score -= 25
        if abs(price - ema21) / ema21 < 0.01:
            score -= 25
        if 50 <= k <= 70:
            score -= 20
    
    return score


def check_momentum(row, trend):
    """检查动量"""
    if trend == 'up':
        return row['macd_hist'] > 0 or row['di_plus'] > row['di_minus']
    else:
        return row['macd_hist'] < 0 or row['di_minus'] > row['di_plus']


def run_backtest_fast(df, params, leverage=20, position_size=0.10):
    """快速回测"""
    trades = []
    position = None
    initial_capital = 10000
    capital = initial_capital
    
    adx_threshold = params.get('adx_threshold', 20)
    entry_threshold = params.get('entry_threshold', 40)
    sl_mult = params.get('sl_mult', 1.0)
    tp_mult = params.get('tp_mult', 1.5)
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        price = row['close']
        atr = row['atr']
        
        if pd.isna(atr) or atr / price * 100 > 4 or atr / price * 100 < 0.2:
            continue
        
        # 检查平仓
        if position:
            exit_reason = None
            exit_price = None
            
            if position['direction'] == 'long':
                if row['low'] <= position['stop_loss']:
                    exit_price = position['stop_loss']
                    exit_reason = "止损"
                elif row['high'] >= position['take_profit']:
                    exit_price = position['take_profit']
                    exit_reason = "止盈"
            else:
                if row['high'] >= position['stop_loss']:
                    exit_price = position['stop_loss']
                    exit_reason = "止损"
                elif row['low'] <= position['take_profit']:
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
                trades.append({'pnl_pct': pnl_pct_leveraged * 100, 'pnl': pnl, 'exit_reason': exit_reason})
                position = None
                
                if capital <= 0:
                    break
        
        # 开仓
        if not position and capital > 0:
            trend = get_trend(row, adx_threshold)
            if trend == 'neutral':
                continue
            
            score = check_entry(row, trend, params)
            if abs(score) < entry_threshold:
                continue
            
            if not check_momentum(row, trend):
                continue
            
            direction = 'long' if score > 0 else 'short'
            if direction == 'long':
                stop_loss = price - atr * sl_mult
                take_profit = price + atr * tp_mult
            else:
                stop_loss = price + atr * sl_mult
                take_profit = price - atr * tp_mult
            
            position = {
                'entry_price': price,
                'direction': direction,
                'stop_loss': stop_loss,
                'take_profit': take_profit
            }
    
    if not trades or len(trades) < 5:
        return None
    
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    
    total_return = (capital - initial_capital) / initial_capital * 100
    win_rate = len(wins) / len(trades) * 100
    profit_factor = abs(sum(t['pnl_pct'] for t in wins) / sum(t['pnl_pct'] for t in losses)) if losses and sum(t['pnl_pct'] for t in losses) != 0 else 0
    
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
        'profit_factor': profit_factor,
        'max_drawdown': max_dd * 100,
        'trades': len(trades),
        'wins': len(wins)
    }


async def optimize():
    with open('config.yaml', 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f)
    
    fetcher = DataFetcher(config)
    await fetcher.init()
    df = await fetcher.fetch_ohlcv('1h', limit=1000)
    await fetcher.close()
    
    if df.empty or len(df) < 100:
        print("数据不足")
        return
    
    print("\n预计算指标...")
    df = calculate_indicators_vectorized(df)
    
    # 参数搜索空间（精细版）
    param_grid = {
        'sl_mult': [0.7, 0.8, 0.9],
        'tp_mult': [2.0, 2.2, 2.5],
        'adx_threshold': [26, 28],
        'entry_threshold': [30, 35],
        'rsi_pullback_low': [25, 28, 30],
        'rsi_pullback_high': [55, 58, 60],
    }
    
    total = np.prod([len(v) for v in param_grid.values()])
    print(f"\n" + "=" * 70)
    print(f"         趋势跟踪策略参数优化")
    print("=" * 70)
    print(f"数据范围: {df.index[50]} ~ {df.index[-1]}")
    print(f"参数组合数: {total}")
    print("\n正在优化...")
    
    results = []
    keys = list(param_grid.keys())
    count = 0
    
    for values in product(*param_grid.values()):
        params = dict(zip(keys, values))
        result = run_backtest_fast(df, params)
        if result:
            result['params'] = params
            results.append(result)
        count += 1
        if count % 500 == 0:
            print(f"  进度: {count}/{total}")
    
    if not results:
        print("无有效结果")
        return
    
    # 综合得分
    for r in results:
        if r['max_drawdown'] != 0:
            r['score'] = r['total_return'] / abs(r['max_drawdown']) + r['profit_factor'] * 2
        else:
            r['score'] = r['profit_factor'] * 2
    
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print("\n" + "=" * 70)
    print("                    TOP 10 参数组合")
    print("=" * 70)
    print(f"{'排名':<4} {'收益%':<9} {'胜率%':<8} {'盈亏比':<8} {'回撤%':<9} {'交易':<6}")
    print("-" * 70)
    
    for i, r in enumerate(results[:10], 1):
        print(f"{i:<4} {r['total_return']:>+7.2f}%  {r['win_rate']:>6.1f}%  {r['profit_factor']:>6.2f}   {r['max_drawdown']:>7.2f}%  {r['trades']:<6}")
    
    best = results[0]
    print("\n" + "=" * 70)
    print("                    🏆 最优参数")
    print("=" * 70)
    print(f"止损倍数 (sl_mult):        {best['params']['sl_mult']}")
    print(f"止盈倍数 (tp_mult):        {best['params']['tp_mult']}")
    print(f"ADX阈值 (adx_threshold):   {best['params']['adx_threshold']}")
    print(f"入场阈值 (entry_threshold): {best['params']['entry_threshold']}")
    print(f"RSI回调区间:               {best['params']['rsi_pullback_low']}-{best['params']['rsi_pullback_high']}")
    print(f"\n📊 预期表现:")
    print(f"   收益率:   {best['total_return']:+.2f}%")
    print(f"   胜率:     {best['win_rate']:.1f}%")
    print(f"   盈亏比:   {best['profit_factor']:.2f}")
    print(f"   最大回撤: {best['max_drawdown']:.2f}%")
    print(f"   交易次数: {best['trades']}")
    print("=" * 70)
    
    return best


if __name__ == '__main__':
    logger.remove()
    logger.add(sys.stdout, level="WARNING")
    asyncio.run(optimize())

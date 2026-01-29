#!/usr/bin/env python3
"""
突破策略参数优化
"""
import asyncio
import yaml
import numpy as np
import pandas as pd
from loguru import logger
import sys
from itertools import product

from data_fetcher import DataFetcher
from strategy_breakout import SignalType


def calculate_indicators_vectorized(df):
    """向量化计算所有指标"""
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
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
    
    # 20日高低点
    df['high_20'] = high.rolling(20).max()
    df['low_20'] = low.rolling(20).min()
    
    # 成交量比率
    df['volume_ma'] = volume.rolling(20).mean()
    df['volume_ratio'] = volume / df['volume_ma']
    
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
    
    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # EMA
    df['ema_9'] = close.ewm(span=9).mean()
    df['ema_21'] = close.ewm(span=21).mean()
    
    return df


def detect_breakout(row, params):
    """检测突破信号"""
    score = 0
    breakout_level = row['close']
    price = row['close']
    
    bb_pband = row['bb_pband']
    high_20 = row['high_20']
    low_20 = row['low_20']
    adx = row['adx']
    volume_ratio = row['volume_ratio']
    
    vol_threshold = params.get('vol_threshold', 1.2)
    adx_threshold = params.get('adx_threshold', 20)
    bb_breakout_threshold = params.get('bb_breakout', 1.0)
    
    # 成交量确认
    if volume_ratio < vol_threshold:
        return {'valid': False, 'score': 0, 'breakout_level': price}
    
    up_breakout = False
    down_breakout = False
    
    # 向上突破
    if bb_pband > bb_breakout_threshold:
        score += 40
        breakout_level = row['bb_upper']
        up_breakout = True
    
    if price > high_20 * 0.998:
        score += 35
        breakout_level = high_20
        up_breakout = True
    
    # 向下突破
    if bb_pband < (1 - bb_breakout_threshold):
        score -= 40
        breakout_level = row['bb_lower']
        down_breakout = True
    
    if price < low_20 * 1.002:
        score -= 35
        breakout_level = low_20
        down_breakout = True
    
    # ADX确认
    if adx > adx_threshold:
        if up_breakout:
            score += 20
        elif down_breakout:
            score -= 20
    
    return {
        'valid': up_breakout or down_breakout,
        'score': score,
        'breakout_level': breakout_level
    }


def run_backtest_fast(df, params, leverage=20, position_size=0.10):
    """快速回测"""
    trades = []
    position = None
    initial_capital = 10000
    capital = initial_capital
    
    entry_threshold = params.get('entry_threshold', 50)
    sl_mult = params.get('sl_mult', 0.5)
    tp_mult = params.get('tp_mult', 2.0)
    
    for i in range(50, len(df)):
        row = df.iloc[i]
        price = row['close']
        atr = row['atr']
        
        if pd.isna(atr) or atr / price * 100 > 4 or atr / price * 100 < 0.3:
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
            breakout = detect_breakout(row, params)
            if not breakout['valid']:
                continue
            
            score = breakout['score']
            if abs(score) < entry_threshold:
                continue
            
            direction = 'long' if score > 0 else 'short'
            bl = breakout['breakout_level']
            
            if direction == 'long':
                stop_loss = bl - atr * sl_mult
                take_profit = price + atr * tp_mult
            else:
                stop_loss = bl + atr * sl_mult
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
    
    # 参数搜索空间 - 增加趋势过滤
    param_grid = {
        'sl_mult': [0.5, 0.6, 0.8],
        'tp_mult': [2.0, 2.5, 3.0],
        'vol_threshold': [1.5, 2.0, 2.5],  # 更严格的成交量要求
        'adx_threshold': [25, 28, 30],      # 更强的趋势要求
        'entry_threshold': [50, 55, 60],    # 更高的入场门槛
        'bb_breakout': [1.0, 1.02],
    }
    
    total = np.prod([len(v) for v in param_grid.values()])
    print(f"\n" + "=" * 70)
    print(f"         突破策略参数优化")
    print("=" * 70)
    print(f"数据范围: {df.index[50]} ~ {df.index[-1]}")
    print(f"参数组合数: {total}")
    print("\n正在优化...")
    
    results = []
    keys = list(param_grid.keys())
    
    for values in product(*param_grid.values()):
        params = dict(zip(keys, values))
        result = run_backtest_fast(df, params)
        if result:
            result['params'] = params
            results.append(result)
    
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
    print(f"成交量阈值 (vol_threshold): {best['params']['vol_threshold']}")
    print(f"ADX阈值 (adx_threshold):   {best['params']['adx_threshold']}")
    print(f"入场阈值 (entry_threshold): {best['params']['entry_threshold']}")
    print(f"布林突破阈值 (bb_breakout): {best['params']['bb_breakout']}")
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

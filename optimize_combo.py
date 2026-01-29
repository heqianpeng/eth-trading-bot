#!/usr/bin/env python3
"""
多策略组合参数优化
核心思路：只在最有把握的时候交易，宁可错过也不做错
"""
import asyncio
import yaml
import numpy as np
import pandas as pd
from loguru import logger
import sys
from itertools import product

from data_fetcher import DataFetcher
from strategy_combo import SignalType


def calculate_indicators_vectorized(df):
    """向量化计算所有指标"""
    close = df['close']
    high = df['high']
    low = df['low']
    volume = df['volume']
    
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
    df['bb_width'] = (df['bb_upper'] - df['bb_lower']) / bb_mid
    
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
    
    # 成交量比率
    df['volume_ma'] = volume.rolling(20).mean()
    df['volume_ratio'] = volume / df['volume_ma']
    
    return df


def identify_market_state(row, params):
    """识别市场状态"""
    adx = row['adx']
    bb_width = row['bb_width']
    bb_pband = row['bb_pband']
    vol_ratio = row['volume_ratio']
    
    adx_trend = params.get('adx_trend', 25)
    adx_range = params.get('adx_range', 20)
    
    # 只在明确趋势时交易
    if adx > adx_trend:
        return 'trending'
    elif adx < adx_range:
        return 'ranging'
    return 'neutral'


def get_trend_signal(row, params):
    """趋势信号 - 只做顺势回调"""
    score = 0
    price = row['close']
    ma20 = row['ma_20']
    ma50 = row['ma_50']
    ema9 = row['ema_9']
    ema21 = row['ema_21']
    rsi = row['rsi']
    adx = row['adx']
    macd_hist = row['macd_hist']
    bb_pband = row['bb_pband']
    
    rsi_low = params.get('rsi_pullback_low', 35)
    rsi_high = params.get('rsi_pullback_high', 50)
    
    # 多头趋势
    if ema9 > ema21 and ma20 > ma50 and price > ma20:
        score += 30
        # 回调入场
        if rsi_low <= rsi <= rsi_high:
            score += 30
        if 0.3 <= bb_pband <= 0.6:
            score += 20
        if macd_hist > 0:
            score += 10
    
    # 空头趋势
    elif ema9 < ema21 and ma20 < ma50 and price < ma20:
        score -= 30
        if (100 - rsi_high) <= rsi <= (100 - rsi_low):
            score -= 30
        if 0.4 <= bb_pband <= 0.7:
            score -= 20
        if macd_hist < 0:
            score -= 10
    
    return score


def get_range_signal(row, params):
    """震荡信号 - 只做极端超买超卖"""
    score = 0
    rsi = row['rsi']
    bb_pband = row['bb_pband']
    k = row['stoch_k']
    
    rsi_oversold = params.get('rsi_oversold', 25)
    rsi_overbought = params.get('rsi_overbought', 75)
    
    # 超卖
    if rsi < rsi_oversold:
        score += 35
        if bb_pband < 0.1:
            score += 25
        if k < 20:
            score += 20
    
    # 超买
    elif rsi > rsi_overbought:
        score -= 35
        if bb_pband > 0.9:
            score -= 25
        if k > 80:
            score -= 20
    
    return score


def run_backtest_fast(df, params, leverage=20, position_size=0.10):
    """快速回测"""
    trades = []
    position = None
    initial_capital = 10000
    capital = initial_capital
    
    entry_threshold = params.get('entry_threshold', 50)
    
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
            market_state = identify_market_state(row, params)
            
            if market_state == 'neutral':
                continue
            
            if market_state == 'trending':
                score = get_trend_signal(row, params)
                sl_mult = params.get('trend_sl', 0.9)
                tp_mult = params.get('trend_tp', 2.0)
            else:  # ranging
                score = get_range_signal(row, params)
                sl_mult = params.get('range_sl', 0.8)
                tp_mult = params.get('range_tp', 1.2)
            
            if abs(score) < entry_threshold:
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
    
    # 参数搜索空间（精简版）
    param_grid = {
        'adx_trend': [25, 28],
        'adx_range': [18, 20],
        'entry_threshold': [50, 55],
        'trend_sl': [0.9, 1.0],
        'trend_tp': [1.8, 2.0],
        'range_sl': [0.8],
        'range_tp': [1.0, 1.2],
        'rsi_pullback_low': [35],
        'rsi_pullback_high': [50],
        'rsi_oversold': [25, 30],
        'rsi_overbought': [70, 75],
    }
    
    total = np.prod([len(v) for v in param_grid.values()])
    print(f"\n" + "=" * 70)
    print(f"         多策略组合参数优化")
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
    print(f"ADX趋势阈值:     {best['params']['adx_trend']}")
    print(f"ADX震荡阈值:     {best['params']['adx_range']}")
    print(f"入场阈值:        {best['params']['entry_threshold']}")
    print(f"趋势止损/止盈:   {best['params']['trend_sl']} / {best['params']['trend_tp']}")
    print(f"震荡止损/止盈:   {best['params']['range_sl']} / {best['params']['range_tp']}")
    print(f"RSI超卖/超买:    {best['params']['rsi_oversold']} / {best['params']['rsi_overbought']}")
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

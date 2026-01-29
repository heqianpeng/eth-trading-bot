#!/usr/bin/env python3
"""
趋势跟踪策略参数优化
测试不同参数组合，找出最优配置
"""
import asyncio
import yaml
import numpy as np
from datetime import datetime
from loguru import logger
import sys
from itertools import product

from data_fetcher import DataFetcher
from indicators import TechnicalIndicators
from strategy_trend import SignalType


class TrendStrategyOptimized:
    """可配置参数的趋势策略"""
    
    def __init__(self, config: dict, params: dict):
        self.config = config.get('strategy', {})
        self.params = params
        
    def analyze(self, indicators, timeframe: str):
        if not indicators or 'price' not in indicators:
            return None
        
        price = indicators['price']
        atr = indicators.get('atr', price * 0.01)
        atr_pct = atr / price * 100
        
        if atr_pct > 4 or atr_pct < 0.2:
            return None
        
        trend = self._get_main_trend(indicators)
        if trend == 'neutral':
            return None
        
        entry_signal = self._check_pullback_entry(indicators, trend)
        if not entry_signal['valid']:
            return None
        
        momentum_ok = self._check_momentum(indicators, trend)
        if not momentum_ok:
            return None
        
        total_score = entry_signal['score']
        threshold = self.params.get('entry_threshold', 40)
        
        if abs(total_score) < threshold:
            return None
        
        signal_type = self._get_signal_type(total_score)
        if signal_type == SignalType.NEUTRAL:
            return None
        
        # 使用参数化的止盈止损
        sl_mult = self.params.get('sl_mult', 1.0)
        tp_mult = self.params.get('tp_mult', 1.5)
        
        if total_score > 0:
            stop_loss = price - atr * sl_mult
            take_profit = price + atr * tp_mult
        else:
            stop_loss = price + atr * sl_mult
            take_profit = price - atr * tp_mult
        
        return {
            'signal_type': signal_type,
            'strength': min(100, abs(int(total_score))),
            'price': price,
            'stop_loss': round(stop_loss, 2),
            'take_profit': round(take_profit, 2)
        }
    
    def _get_main_trend(self, ind: dict) -> str:
        price = ind['price']
        ma20 = ind.get('ma_20', price)
        ma50 = ind.get('ma_50', price)
        ema9 = ind.get('ema_9', price)
        ema21 = ind.get('ema_21', price)
        adx = ind.get('adx', 20)
        
        adx_threshold = self.params.get('adx_threshold', 20)
        if adx < adx_threshold:
            return 'neutral'
        
        up_count = 0
        down_count = 0
        
        if price > ma20: up_count += 1
        else: down_count += 1
        if price > ma50: up_count += 1
        else: down_count += 1
        if ema9 > ema21: up_count += 1
        else: down_count += 1
        if ma20 > ma50: up_count += 1
        else: down_count += 1
        
        trend_confirm = self.params.get('trend_confirm', 3)
        if up_count >= trend_confirm:
            return 'up'
        elif down_count >= trend_confirm:
            return 'down'
        return 'neutral'
    
    def _check_pullback_entry(self, ind: dict, trend: str) -> dict:
        score = 0
        reasons = []
        
        price = ind['price']
        rsi = ind.get('rsi', 50)
        bb_pband = ind.get('bb_pband', 0.5)
        ema21 = ind.get('ema_21', price)
        k = ind.get('stoch_k', 50)
        
        rsi_low = self.params.get('rsi_pullback_low', 35)
        rsi_high = self.params.get('rsi_pullback_high', 50)
        
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
        
        return {'valid': abs(score) >= self.params.get('entry_threshold', 40), 'score': score, 'reasons': reasons}
    
    def _check_momentum(self, ind: dict, trend: str) -> bool:
        macd_hist = ind.get('macd_hist', 0)
        di_plus = ind.get('di_plus', 0)
        di_minus = ind.get('di_minus', 0)
        
        if trend == 'up':
            return macd_hist > 0 or di_plus > di_minus
        else:
            return macd_hist < 0 or di_minus > di_plus
    
    def _get_signal_type(self, score: float) -> SignalType:
        if score >= 60:
            return SignalType.STRONG_BUY
        elif score >= 40:
            return SignalType.BUY
        elif score <= -60:
            return SignalType.STRONG_SELL
        elif score <= -40:
            return SignalType.SELL
        return SignalType.NEUTRAL


async def run_backtest(df, indicators_calc, params, leverage=20, position_size=0.10):
    """运行单次回测"""
    strategy = TrendStrategyOptimized({}, params)
    
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
                trades.append({'pnl_pct': pnl_pct_leveraged * 100, 'pnl': pnl, 'exit_reason': exit_reason})
                position = None
                
                if capital <= 0:
                    break
        
        if not position and capital > 0:
            signal = strategy.analyze(ind, '1h')
            if signal and signal['signal_type'] != SignalType.NEUTRAL:
                direction = 'long' if signal['signal_type'] in [SignalType.BUY, SignalType.STRONG_BUY] else 'short'
                position = {
                    'entry_price': current_price,
                    'direction': direction,
                    'stop_loss': signal['stop_loss'],
                    'take_profit': signal['take_profit']
                }
    
    if not trades:
        return None
    
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    
    total_return = (capital - initial_capital) / initial_capital * 100
    win_rate = len(wins) / len(trades) * 100 if trades else 0
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
    
    indicators_calc = TechnicalIndicators(config)
    
    # 参数搜索空间（精简版）
    param_grid = {
        'sl_mult': [0.8, 1.0, 1.2],           # 止损倍数
        'tp_mult': [1.5, 1.8, 2.0, 2.5],      # 止盈倍数
        'adx_threshold': [18, 22, 25],        # ADX阈值
        'entry_threshold': [35, 40],          # 入场阈值
        'rsi_pullback_low': [35],             # RSI回调下限
        'rsi_pullback_high': [50],            # RSI回调上限
    }
    
    print("\n" + "=" * 70)
    print("         趋势跟踪策略参数优化")
    print("=" * 70)
    print(f"数据范围: {df.index[50]} ~ {df.index[-1]}")
    print(f"参数组合数: {np.prod([len(v) for v in param_grid.values()])}")
    print("\n正在优化...\n")
    
    results = []
    keys = list(param_grid.keys())
    
    for values in product(*param_grid.values()):
        params = dict(zip(keys, values))
        params['trend_confirm'] = 3
        
        result = await run_backtest(df, indicators_calc, params)
        if result and result['trades'] >= 10:
            result['params'] = params
            results.append(result)
    
    if not results:
        print("无有效结果")
        return
    
    # 按综合得分排序（收益/回撤比 + 盈亏比）
    for r in results:
        r['score'] = r['total_return'] / abs(r['max_drawdown']) if r['max_drawdown'] != 0 else 0
        r['score'] += r['profit_factor'] * 2
    
    results.sort(key=lambda x: x['score'], reverse=True)
    
    print("=" * 70)
    print("                    TOP 10 参数组合")
    print("=" * 70)
    print(f"{'排名':<4} {'收益%':<8} {'胜率%':<7} {'盈亏比':<7} {'回撤%':<8} {'交易数':<6} {'得分':<6}")
    print("-" * 70)
    
    for i, r in enumerate(results[:10], 1):
        print(f"{i:<4} {r['total_return']:>+6.2f}%  {r['win_rate']:>5.1f}%  {r['profit_factor']:>5.2f}   {r['max_drawdown']:>6.2f}%  {r['trades']:<6} {r['score']:.2f}")
    
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

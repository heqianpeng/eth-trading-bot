#!/usr/bin/env python3
"""
趋势跟踪策略回测
"""
import asyncio
import yaml
import numpy as np
from datetime import datetime
from loguru import logger
import sys

from data_fetcher import DataFetcher
from indicators import TechnicalIndicators
from strategy_trend import TrendStrategy, SignalType


async def backtest(days: int = 40):
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
    strategy = TrendStrategy(config)
    
    trades = []
    position = None
    initial_capital = 10000
    capital = initial_capital
    leverage = 20
    position_size = 0.10
    
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
                    'entry_time': position['entry_time'],
                    'exit_time': current_time,
                    'direction': position['direction'],
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
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
    
    # 强制平仓
    if position and capital > 0:
        exit_price = df.iloc[-1]['close']
        if position['direction'] == 'long':
            pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
        else:
            pnl_pct = (position['entry_price'] - exit_price) / position['entry_price']
        
        pnl_pct_leveraged = pnl_pct * leverage * position_size
        pnl = capital * pnl_pct_leveraged
        capital += pnl
        hold_hours = (df.index[-1] - position['entry_time']).total_seconds() / 3600
        trades.append({
            'entry_time': position['entry_time'],
            'exit_time': df.index[-1],
            'direction': position['direction'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'pnl_pct': pnl_pct_leveraged * 100,
            'pnl': pnl,
            'exit_reason': '回测结束',
            'hold_hours': hold_hours
        })
    
    # 打印报告
    print("\n" + "=" * 70)
    print(f"         趋势跟踪策略回测报告（{leverage}倍杠杆，{int(position_size*100)}%仓位）")
    print("=" * 70)
    print(f"数据范围: {df.index[50]} ~ {df.index[-1]}")
    print(f"回测天数: {days}天\n")
    
    if not trades:
        print("无交易")
        return
    
    wins = [t for t in trades if t['pnl_pct'] > 0]
    losses = [t for t in trades if t['pnl_pct'] <= 0]
    
    total_return = (capital - initial_capital) / initial_capital * 100
    win_rate = len(wins) / len(trades) * 100
    avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
    avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
    
    profit_factor = abs(sum(t['pnl_pct'] for t in wins) / sum(t['pnl_pct'] for t in losses)) if losses and sum(t['pnl_pct'] for t in losses) != 0 else float('inf')
    avg_hold = np.mean([t['hold_hours'] for t in trades])
    actual_days = (df.index[-1] - df.index[50]).days or 1
    trades_per_day = len(trades) / actual_days
    
    equity = initial_capital
    peak = initial_capital
    max_dd = 0
    for t in trades:
        equity += t['pnl']
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        max_dd = min(max_dd, dd)
    
    if len(trades) > 1:
        returns = [t['pnl_pct'] for t in trades]
        sharpe = np.mean(returns) / np.std(returns) * np.sqrt(252 / avg_hold * 24) if np.std(returns) > 0 else 0
    else:
        sharpe = 0
    
    print(f"📊 资金统计")
    print(f"   初始资金:     ${initial_capital:,.2f}")
    print(f"   最终资金:     ${capital:,.2f}")
    print(f"   总收益:       {total_return:+.2f}%")
    print(f"   最大回撤:     {max_dd*100:.2f}%")
    print(f"   夏普比率:     {sharpe:.2f}")
    
    print(f"\n📈 交易统计")
    print(f"   总交易次数:   {len(trades)}")
    print(f"   日均交易:     {trades_per_day:.1f}笔")
    print(f"   平均持仓:     {avg_hold:.1f}小时")
    print(f"   盈利次数:     {len(wins)}")
    print(f"   亏损次数:     {len(losses)}")
    print(f"   胜率:         {win_rate:.1f}%")
    
    print(f"\n💰 盈亏分析")
    print(f"   盈亏比:       {profit_factor:.2f}")
    print(f"   平均盈利:     {avg_win:+.2f}%")
    print(f"   平均亏损:     {avg_loss:.2f}%")
    
    print(f"\n📋 最近10笔交易")
    print("-" * 70)
    for t in trades[-10:]:
        direction = "🟢做多" if t['direction'] == 'long' else "🔴做空"
        pnl_emoji = "✅" if t['pnl_pct'] > 0 else "❌"
        print(f"   {direction} | 入场: ${t['entry_price']:.2f} | "
              f"出场: ${t['exit_price']:.2f} | "
              f"{pnl_emoji} {t['pnl_pct']:+.2f}% | {t['exit_reason']} | {t['hold_hours']:.1f}h")
    
    print("\n" + "=" * 70)


if __name__ == '__main__':
    logger.remove()
    logger.add(sys.stdout, level="WARNING")
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--days', type=int, default=40, help='回测天数')
    args = parser.parse_args()
    
    asyncio.run(backtest(args.days))

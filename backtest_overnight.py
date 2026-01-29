#!/usr/bin/env python3
"""
隔夜时段专用回测 - 只在北京时间0:00-8:00开仓
"""
import asyncio
import yaml
import pandas as pd
import numpy as np
from datetime import datetime
from loguru import logger
import sys

from data_fetcher import DataFetcher
from indicators import TechnicalIndicators
from strategy import TradingStrategy, SignalType


def is_overnight_session(utc_time) -> bool:
    """判断是否在北京时间凌晨时段 (0:00-8:00)，对应UTC 16:00-00:00"""
    beijing_hour = (utc_time.hour + 8) % 24
    return 0 <= beijing_hour < 8


async def backtest_overnight(days: int = 40):
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
    strategy = TradingStrategy(config)
    
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
        
        # 检查平仓（任何时间都可以平仓）
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
                
                pnl = capital * pnl_pct
                capital += pnl
                
                trades.append({
                    'entry_time': position['entry_time'],
                    'exit_time': current_time,
                    'direction': position['direction'],
                    'entry_price': position['entry_price'],
                    'exit_price': exit_price,
                    'pnl_pct': pnl_pct * 100,
                    'pnl': pnl,
                    'exit_reason': exit_reason
                })
                position = None
        
        # 只在隔夜时段开仓
        if not position and is_overnight_session(current_time):
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
    if position:
        exit_price = df.iloc[-1]['close']
        if position['direction'] == 'long':
            pnl_pct = (exit_price - position['entry_price']) / position['entry_price']
        else:
            pnl_pct = (position['entry_price'] - exit_price) / position['entry_price']
        
        pnl = capital * pnl_pct
        capital += pnl
        trades.append({
            'entry_time': position['entry_time'],
            'exit_time': df.index[-1],
            'direction': position['direction'],
            'entry_price': position['entry_price'],
            'exit_price': exit_price,
            'pnl_pct': pnl_pct * 100,
            'pnl': pnl,
            'exit_reason': '回测结束'
        })
    
    # 打印报告
    print("\n" + "=" * 70)
    print("         ETH/USDT 隔夜时段专用回测报告")
    print("         (仅在北京时间 0:00-8:00 开仓)")
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
    
    # 盈亏比
    profit_factor = abs(sum(t['pnl_pct'] for t in wins) / sum(t['pnl_pct'] for t in losses)) if losses else float('inf')
    
    # 最大回撤
    equity = initial_capital
    peak = initial_capital
    max_dd = 0
    for t in trades:
        equity += t['pnl']
        peak = max(peak, equity)
        dd = (equity - peak) / peak
        max_dd = min(max_dd, dd)
    
    print(f"📊 资金统计")
    print(f"   初始资金:     ${initial_capital:,.2f}")
    print(f"   最终资金:     ${capital:,.2f}")
    print(f"   总收益:       {total_return:+.2f}%")
    
    print(f"\n📈 交易统计")
    print(f"   总交易次数:   {len(trades)}")
    print(f"   盈利次数:     {len(wins)}")
    print(f"   亏损次数:     {len(losses)}")
    print(f"   胜率:         {win_rate:.1f}%")
    
    print(f"\n💰 盈亏分析")
    print(f"   盈亏比:       {profit_factor:.2f}")
    print(f"   平均盈利:     {avg_win:+.2f}%")
    print(f"   平均亏损:     {avg_loss:.2f}%")
    print(f"   最大回撤:     {max_dd*100:.2f}%")
    
    print(f"\n📋 最近10笔交易")
    print("-" * 70)
    for t in trades[-10:]:
        direction = "🟢做多" if t['direction'] == 'long' else "🔴做空"
        pnl_emoji = "✅" if t['pnl_pct'] > 0 else "❌"
        print(f"   {direction} | 入场: ${t['entry_price']:.2f} | "
              f"出场: ${t['exit_price']:.2f} | "
              f"{pnl_emoji} {t['pnl_pct']:+.2f}% | {t['exit_reason']}")
    
    print("\n" + "=" * 70)
    
    # 评估
    print("\n📝 隔夜策略评估:")
    if win_rate >= 60:
        print(f"   ✅ 胜率优秀 ({win_rate:.1f}%)")
    elif win_rate >= 50:
        print(f"   ⚠️ 胜率一般 ({win_rate:.1f}%)")
    else:
        print(f"   ❌ 胜率偏低 ({win_rate:.1f}%)")
    
    if profit_factor >= 1.5:
        print(f"   ✅ 盈亏比优秀 ({profit_factor:.2f})")
    elif profit_factor >= 1:
        print(f"   ⚠️ 盈亏比一般 ({profit_factor:.2f})")
    else:
        print(f"   ❌ 盈亏比不佳 ({profit_factor:.2f})")
    
    if total_return > 0:
        print(f"   ✅ 策略盈利 ({total_return:+.2f}%)")
    else:
        print(f"   ❌ 策略亏损 ({total_return:.2f}%)")


if __name__ == '__main__':
    logger.remove()
    logger.add(sys.stdout, level="WARNING")
    
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-d', '--days', type=int, default=40, help='回测天数')
    args = parser.parse_args()
    
    asyncio.run(backtest_overnight(args.days))

#!/usr/bin/env python3
"""
分析不同时段的交易表现
北京时间：
- 凌晨时段: 0:00-8:00 (对应美股收盘后)
- 白天时段: 8:00-16:00 (对应欧洲盘)
- 晚间时段: 16:00-24:00 (对应美股盘)
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


def get_session(hour: int) -> str:
    """根据北京时间小时判断时段"""
    if 0 <= hour < 8:
        return "凌晨(0-8点)"
    elif 8 <= hour < 16:
        return "白天(8-16点)"
    else:
        return "晚间(16-24点)"


async def analyze_sessions(days: int = 40):
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
    
    # 存储每个时段的交易
    session_trades = {
        "凌晨(0-8点)": [],
        "白天(8-16点)": [],
        "晚间(16-24点)": []
    }
    
    # 模拟交易
    position = None
    
    for i in range(50, len(df)):
        current_bar = df.iloc[i]
        current_time = df.index[i]
        current_price = current_bar['close']
        
        # 转换为北京时间 (UTC+8)
        beijing_hour = (current_time.hour + 8) % 24
        session = get_session(beijing_hour)
        
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
                    pnl_pct = (exit_price - position['entry_price']) / position['entry_price'] * 100
                else:
                    pnl_pct = (position['entry_price'] - exit_price) / position['entry_price'] * 100
                
                session_trades[position['session']].append({
                    'entry_time': position['entry_time'],
                    'exit_time': current_time,
                    'direction': position['direction'],
                    'pnl_pct': pnl_pct,
                    'exit_reason': exit_reason
                })
                position = None
        
        # 开新仓
        if not position:
            signal = strategy.analyze(ind, '1h')
            if signal and signal.signal_type != SignalType.NEUTRAL:
                direction = 'long' if signal.signal_type in [SignalType.BUY, SignalType.STRONG_BUY] else 'short'
                position = {
                    'entry_time': current_time,
                    'entry_price': current_price,
                    'direction': direction,
                    'stop_loss': signal.stop_loss,
                    'take_profit': signal.take_profit,
                    'session': session
                }
    
    # 打印分析结果
    print("\n" + "=" * 70)
    print("              ETH/USDT 时段交易分析报告")
    print("=" * 70)
    print(f"数据范围: {df.index[50]} ~ {df.index[-1]}")
    print(f"总天数: {days}天\n")
    
    all_trades = []
    for session_name, trades in session_trades.items():
        all_trades.extend(trades)
        
        if not trades:
            print(f"\n🕐 {session_name}: 无交易")
            continue
        
        wins = [t for t in trades if t['pnl_pct'] > 0]
        losses = [t for t in trades if t['pnl_pct'] <= 0]
        
        total_pnl = sum(t['pnl_pct'] for t in trades)
        win_rate = len(wins) / len(trades) * 100
        avg_win = np.mean([t['pnl_pct'] for t in wins]) if wins else 0
        avg_loss = np.mean([t['pnl_pct'] for t in losses]) if losses else 0
        
        print(f"\n🕐 {session_name}")
        print(f"   交易次数: {len(trades)}")
        print(f"   胜率:     {win_rate:.1f}%")
        print(f"   总收益:   {total_pnl:+.2f}%")
        print(f"   平均盈利: {avg_win:+.2f}%")
        print(f"   平均亏损: {avg_loss:.2f}%")
        
        # 盈亏比
        if avg_loss != 0:
            profit_factor = abs(avg_win / avg_loss) if avg_loss != 0 else 0
            print(f"   盈亏比:   {profit_factor:.2f}")
    
    # 总体对比
    print("\n" + "-" * 70)
    print("📊 时段对比总结:")
    
    best_session = None
    best_return = -999
    
    for session_name, trades in session_trades.items():
        if trades:
            total_return = sum(t['pnl_pct'] for t in trades)
            win_rate = len([t for t in trades if t['pnl_pct'] > 0]) / len(trades) * 100
            print(f"   {session_name}: {len(trades)}笔, 胜率{win_rate:.0f}%, 收益{total_return:+.1f}%")
            
            if total_return > best_return:
                best_return = total_return
                best_session = session_name
    
    if best_session:
        print(f"\n✅ 最佳时段: {best_session}")
    
    print("\n" + "=" * 70)


if __name__ == '__main__':
    logger.remove()
    logger.add(sys.stdout, level="WARNING")
    asyncio.run(analyze_sessions(40))

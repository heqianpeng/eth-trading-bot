#!/usr/bin/env python3
"""
策略回测模块
"""
import asyncio
import yaml
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from dataclasses import dataclass
from typing import List, Dict
from loguru import logger
import sys

from data_fetcher import DataFetcher
from indicators import TechnicalIndicators
from strategy import TradingStrategy, SignalType


@dataclass
class Trade:
    entry_time: datetime
    entry_price: float
    exit_time: datetime = None
    exit_price: float = None
    signal_type: SignalType = None
    stop_loss: float = 0
    take_profit: float = 0
    trailing_stop: float = 0
    trailing_activation: float = 0.008
    trailing_stop_pct: float = 0.015
    highest_price: float = 0
    lowest_price: float = 0
    pnl: float = 0
    pnl_pct: float = 0
    exit_reason: str = ""
    position_size: float = 1.0  # 仓位比例


class Backtester:
    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, 'r', encoding='utf-8') as f:
            self.config = yaml.safe_load(f)
        
        self.indicators = TechnicalIndicators(self.config)
        self.strategy = TradingStrategy(self.config)
        self.trades: List[Trade] = []
        self.initial_capital = 10000
        self.consecutive_losses = 0  # 连续亏损次数
        self.cooldown_bars = 0  # 冷却期剩余K线数  # 初始资金 $10000
        
    async def fetch_historical_data(self, days: int = 30) -> pd.DataFrame:
        """获取历史数据"""
        fetcher = DataFetcher(self.config)
        await fetcher.init()
        
        # 获取足够多的K线数据
        limit = min(days * 24, 1000)  # 1小时K线
        df = await fetcher.fetch_ohlcv('1h', limit=limit)
        await fetcher.close()
        
        logger.info(f"获取到 {len(df)} 根K线数据")
        return df
        
    def run_backtest(self, df: pd.DataFrame) -> Dict:
        """运行回测"""
        if len(df) < 100:
            logger.error("数据不足，至少需要100根K线")
            return {}
            
        logger.info(f"开始回测，数据范围: {df.index[0]} ~ {df.index[-1]}")
        
        position = None  # 当前持仓
        capital = self.initial_capital
        equity_curve = []
        
        # 预先计算所有指标
        all_indicators = []
        for i in range(len(df)):
            if i < 50:
                all_indicators.append(None)
                continue
            historical = df.iloc[:i+1].copy()
            indicators = self.indicators.calculate_all(historical)
            all_indicators.append(indicators)
        
        # 从第50根K线开始
        for i in range(50, len(df)):
            current_bar = df.iloc[i]
            current_time = df.index[i]
            current_price = current_bar['close']
            indicators = all_indicators[i]
            
            if not indicators:
                continue
                
            # 检查是否需要平仓
            if position:
                exit_reason = None
                exit_price = None
                
                # 检查止损止盈
                if position.signal_type in [SignalType.BUY, SignalType.STRONG_BUY]:
                    if current_bar['low'] <= position.stop_loss:
                        exit_price = position.stop_loss
                        exit_reason = "止损"
                    elif current_bar['high'] >= position.take_profit:
                        exit_price = position.take_profit
                        exit_reason = "止盈"
                else:  # 做空
                    if current_bar['high'] >= position.stop_loss:
                        exit_price = position.stop_loss
                        exit_reason = "止损"
                    elif current_bar['low'] <= position.take_profit:
                        exit_price = position.take_profit
                        exit_reason = "止盈"
                        
                if exit_reason:
                    position.exit_time = current_time
                    position.exit_price = exit_price
                    position.exit_reason = exit_reason
                    
                    if position.signal_type in [SignalType.BUY, SignalType.STRONG_BUY]:
                        position.pnl_pct = (exit_price - position.entry_price) / position.entry_price
                    else:
                        position.pnl_pct = (position.entry_price - exit_price) / position.entry_price
                        
                    position.pnl = capital * position.position_size * position.pnl_pct
                    capital += position.pnl
                    
                    # 更新连续亏损计数
                    if position.pnl < 0:
                        self.consecutive_losses += 1
                        if self.consecutive_losses >= 3:
                            self.cooldown_bars = 5  # 连续3次亏损后冷却5根K线
                    else:
                        self.consecutive_losses = 0
                    
                    self.trades.append(position)
                    position = None
            
            # 冷却期倒计时
            if self.cooldown_bars > 0:
                self.cooldown_bars -= 1
                    
            # 生成新信号
            if not position and self.cooldown_bars == 0:
                signal = self.strategy.analyze(indicators, '1h')
                
                if signal and signal.signal_type != SignalType.NEUTRAL:
                    # 动态仓位：根据信号强度和连续亏损调整
                    base_size = 1.0
                    if signal.strength >= 50:
                        base_size = 1.0
                    elif signal.strength >= 40:
                        base_size = 0.8
                    else:
                        base_size = 0.6
                    
                    # 连续亏损后减仓
                    if self.consecutive_losses >= 2:
                        base_size *= 0.5
                        
                    position = Trade(
                        entry_time=current_time,
                        entry_price=current_price,
                        signal_type=signal.signal_type,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        trailing_activation=getattr(signal, 'trailing_activation', 0.008),
                        trailing_stop_pct=getattr(signal, 'trailing_stop_pct', 0.015),
                        highest_price=current_price,
                        lowest_price=current_price,
                        position_size=base_size
                    )
                    
            # 记录权益曲线
            current_equity = capital
            if position:
                if position.signal_type in [SignalType.BUY, SignalType.STRONG_BUY]:
                    unrealized = capital * (current_price - position.entry_price) / position.entry_price
                else:
                    unrealized = capital * (position.entry_price - current_price) / position.entry_price
                current_equity += unrealized
                
            equity_curve.append({
                'time': current_time,
                'equity': current_equity,
                'price': current_price
            })
            
        # 强制平仓未完成的交易
        if position:
            position.exit_time = df.index[-1]
            position.exit_price = df.iloc[-1]['close']
            position.exit_reason = "回测结束"
            
            if position.signal_type in [SignalType.BUY, SignalType.STRONG_BUY]:
                position.pnl_pct = (position.exit_price - position.entry_price) / position.entry_price
            else:
                position.pnl_pct = (position.entry_price - position.exit_price) / position.entry_price
                
            position.pnl = capital * position.pnl_pct
            capital += position.pnl
            self.trades.append(position)
            
        return self._calculate_stats(capital, equity_curve, df)
        
    def _calculate_stats(self, final_capital: float, equity_curve: List, df: pd.DataFrame) -> Dict:
        """计算回测统计"""
        if not self.trades:
            return {'error': '没有产生任何交易'}
            
        # 基础统计
        total_trades = len(self.trades)
        winning_trades = [t for t in self.trades if t.pnl > 0]
        losing_trades = [t for t in self.trades if t.pnl < 0]
        
        win_rate = len(winning_trades) / total_trades * 100 if total_trades > 0 else 0
        
        total_profit = sum(t.pnl for t in winning_trades)
        total_loss = abs(sum(t.pnl for t in losing_trades))
        
        profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
        
        avg_win = np.mean([t.pnl_pct for t in winning_trades]) * 100 if winning_trades else 0
        avg_loss = np.mean([t.pnl_pct for t in losing_trades]) * 100 if losing_trades else 0
        
        # 最大回撤
        equity_df = pd.DataFrame(equity_curve)
        equity_df['peak'] = equity_df['equity'].cummax()
        equity_df['drawdown'] = (equity_df['equity'] - equity_df['peak']) / equity_df['peak']
        max_drawdown = equity_df['drawdown'].min() * 100
        
        # 收益率
        total_return = (final_capital - self.initial_capital) / self.initial_capital * 100
        
        # 买入持有收益
        buy_hold_return = (df.iloc[-1]['close'] - df.iloc[50]['close']) / df.iloc[50]['close'] * 100
        
        # 夏普比率
        if len(equity_curve) > 1:
            returns = equity_df['equity'].pct_change().dropna()
            sharpe = returns.mean() / returns.std() * np.sqrt(365 * 24) if returns.std() > 0 else 0
        else:
            sharpe = 0
        
        # 交易频率
        total_days = (df.index[-1] - df.index[50]).days
        trades_per_day = total_trades / total_days if total_days > 0 else 0
        
        # 持仓时间统计
        durations = []
        for t in self.trades:
            if t.exit_time and t.entry_time:
                duration = (t.exit_time - t.entry_time).total_seconds() / 3600
                durations.append(duration)
        
        avg_duration = np.mean(durations) if durations else 0
        min_duration = min(durations) if durations else 0
        max_duration = max(durations) if durations else 0
        
        # 持仓时间分布
        short_trades = len([d for d in durations if d < 6])
        medium_trades = len([d for d in durations if 6 <= d < 24])
        long_trades = len([d for d in durations if d >= 24])
        
        duration_dist = {
            'short': short_trades,
            'medium': medium_trades,
            'long': long_trades,
            'short_pct': short_trades / len(durations) * 100 if durations else 0,
            'medium_pct': medium_trades / len(durations) * 100 if durations else 0,
            'long_pct': long_trades / len(durations) * 100 if durations else 0
        }
            
        stats = {
            'initial_capital': self.initial_capital,
            'final_capital': round(final_capital, 2),
            'total_return': round(total_return, 2),
            'buy_hold_return': round(buy_hold_return, 2),
            'total_trades': total_trades,
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': round(win_rate, 2),
            'profit_factor': round(profit_factor, 2),
            'avg_win': round(avg_win, 2),
            'avg_loss': round(avg_loss, 2),
            'max_drawdown': round(max_drawdown, 2),
            'sharpe_ratio': round(sharpe, 2),
            'trades_per_day': round(trades_per_day, 2),
            'avg_duration': round(avg_duration, 1),
            'min_duration': round(min_duration, 1),
            'max_duration': round(max_duration, 1),
            'duration_dist': duration_dist,
            'trades': self.trades
        }
        
        return stats
        
    def print_report(self, stats: Dict):
        """打印回测报告"""
        if 'error' in stats:
            logger.error(stats['error'])
            return
            
        print("\n" + "=" * 60)
        print("               ETH/USDT 策略回测报告")
        print("=" * 60)
        
        print(f"\n📊 资金统计")
        print(f"   初始资金:     ${stats['initial_capital']:,.2f}")
        print(f"   最终资金:     ${stats['final_capital']:,.2f}")
        print(f"   策略收益:     {stats['total_return']:+.2f}%")
        print(f"   买入持有收益: {stats['buy_hold_return']:+.2f}%")
        
        print(f"\n📈 交易统计")
        print(f"   总交易次数:   {stats['total_trades']}")
        print(f"   盈利次数:     {stats['winning_trades']}")
        print(f"   亏损次数:     {stats['losing_trades']}")
        print(f"   胜率:         {stats['win_rate']:.1f}%")
        
        # 交易频率
        if 'trades_per_day' in stats:
            print(f"   日均交易:     {stats['trades_per_day']:.2f} 笔/天")
        
        print(f"\n💰 盈亏分析")
        print(f"   盈亏比:       {stats['profit_factor']:.2f}")
        print(f"   平均盈利:     {stats['avg_win']:+.2f}%")
        print(f"   平均亏损:     {stats['avg_loss']:.2f}%")
        print(f"   最大回撤:     {stats['max_drawdown']:.2f}%")
        print(f"   夏普比率:     {stats['sharpe_ratio']:.2f}")
        
        # 持仓时间
        if 'avg_duration' in stats:
            print(f"\n⏱️ 持仓时间")
            print(f"   平均持仓:     {stats['avg_duration']:.1f} 小时")
            print(f"   最短持仓:     {stats['min_duration']:.1f} 小时")
            print(f"   最长持仓:     {stats['max_duration']:.1f} 小时")
            if 'duration_dist' in stats:
                d = stats['duration_dist']
                print(f"   <6小时:       {d['short']} 笔 ({d['short_pct']:.0f}%)")
                print(f"   6-24小时:     {d['medium']} 笔 ({d['medium_pct']:.0f}%)")
                print(f"   >24小时:      {d['long']} 笔 ({d['long_pct']:.0f}%)")
        
        print(f"\n📋 最近10笔交易")
        print("-" * 60)
        
        for trade in stats['trades'][-10:]:
            direction = "🟢做多" if trade.signal_type in [SignalType.BUY, SignalType.STRONG_BUY] else "🔴做空"
            pnl_emoji = "✅" if trade.pnl > 0 else "❌"
            print(f"   {direction} | 入场: ${trade.entry_price:.2f} | "
                  f"出场: ${trade.exit_price:.2f} | "
                  f"{pnl_emoji} {trade.pnl_pct*100:+.2f}% | {trade.exit_reason}")
                  
        print("\n" + "=" * 60)
        
        # 评估
        print("\n📝 策略评估:")
        if stats['total_return'] > stats['buy_hold_return']:
            print("   ✅ 策略跑赢买入持有")
        else:
            print("   ⚠️ 策略未能跑赢买入持有")
            
        if stats['win_rate'] >= 50:
            print(f"   ✅ 胜率良好 ({stats['win_rate']:.1f}%)")
        else:
            print(f"   ⚠️ 胜率偏低 ({stats['win_rate']:.1f}%)")
            
        if stats['profit_factor'] >= 1.5:
            print(f"   ✅ 盈亏比优秀 ({stats['profit_factor']:.2f})")
        elif stats['profit_factor'] >= 1:
            print(f"   ⚠️ 盈亏比一般 ({stats['profit_factor']:.2f})")
        else:
            print(f"   ❌ 盈亏比不佳 ({stats['profit_factor']:.2f})")
            
        if stats['max_drawdown'] > -20:
            print(f"   ✅ 回撤可控 ({stats['max_drawdown']:.1f}%)")
        else:
            print(f"   ⚠️ 回撤较大 ({stats['max_drawdown']:.1f}%)")


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='ETH/USDT 策略回测')
    parser.add_argument('-c', '--config', default='config.yaml', help='配置文件')
    parser.add_argument('-d', '--days', type=int, default=30, help='回测天数')
    args = parser.parse_args()
    
    # 配置日志
    logger.remove()
    logger.add(sys.stdout, level="INFO", format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")
    
    logger.info(f"开始回测，周期: {args.days}天")
    
    backtester = Backtester(args.config)
    
    # 获取历史数据
    df = await backtester.fetch_historical_data(args.days)
    
    if df.empty:
        logger.error("无法获取历史数据")
        return
        
    # 运行回测
    stats = backtester.run_backtest(df)
    
    # 打印报告
    backtester.print_report(stats)


if __name__ == '__main__':
    asyncio.run(main())

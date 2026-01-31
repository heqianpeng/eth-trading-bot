#!/usr/bin/env python3
"""
ETH/USDT 多策略并行交易信号系统
同时运行多个策略，每个策略独立发送信号
"""
import asyncio
import yaml
import sys
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger

from data_fetcher import DataFetcher
from indicators import TechnicalIndicators
from strategy import SignalType
from strategy_trend import TrendStrategy
from strategy_combo import ComboStrategy
from strategy_overnight import OvernightStrategy
from notifier import Notifier


# 策略配置
STRATEGIES = {
    'trend': {
        'class': TrendStrategy,
        'name': '趋势跟踪V3',
        'emoji': '📈'
    }
}


class MultiStrategyBot:
    def __init__(self, config_path: str = "config.yaml", strategies: list = None):
        self.config = self._load_config(config_path)
        self._setup_logging()
        
        self.fetcher = DataFetcher(self.config)
        self.indicators = TechnicalIndicators(self.config)
        self.notifier = Notifier(self.config)
        
        # 初始化选中的策略
        self.strategies = {}
        strategy_list = strategies or ['trend', 'combo']
        
        for key in strategy_list:
            if key in STRATEGIES:
                info = STRATEGIES[key]
                self.strategies[key] = {
                    'instance': info['class'](self.config),
                    'name': info['name'],
                    'emoji': info['emoji'],
                    'last_signal_time': {}
                }
        
        self.running = False
        self.startup_delay = True  # 启动延迟标志，避免启动时发送大量邮件
        
    def _load_config(self, path: str) -> dict:
        config_file = Path(path)
        if not config_file.exists():
            logger.error(f"配置文件不存在: {path}")
            sys.exit(1)
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
            
    def _setup_logging(self):
        log_config = self.config.get('logging', {})
        logger.remove()
        logger.add(
            sys.stdout,
            level=log_config.get('level', 'INFO'),
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>"
        )
        log_file = log_config.get('file', 'logs/trading.log')
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        logger.add(
            log_file,
            level=log_config.get('level', 'INFO'),
            rotation=log_config.get('rotation', '1 day'),
            retention=log_config.get('retention', '7 days'),
            encoding='utf-8'
        )
        
    async def start(self):
        logger.info("=" * 60)
        logger.info("ETH/USDT 多策略并行交易信号系统启动")
        logger.info("=" * 60)
        
        for key, info in self.strategies.items():
            logger.info(f"  {info['emoji']} {info['name']}")
        
        logger.info("=" * 60)
        
        await self.fetcher.init()
        self.running = True
        
        interval = self.config['trading'].get('fetch_interval', 10)
        logger.info(f"数据刷新间隔: {interval}秒")
        logger.info(f"监控时间周期: {', '.join(self.config['trading']['timeframes'])}")
        
        try:
            while self.running:
                await self._analyze_cycle()
                # 第一次分析后关闭启动延迟
                if self.startup_delay:
                    self.startup_delay = False
                    logger.info("首次分析完成，后续将正常发送信号")
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            logger.info("收到停止信号")
        finally:
            await self.stop()
            
    async def stop(self):
        self.running = False
        await self.fetcher.close()
        logger.info("系统已停止")
        
    async def _analyze_cycle(self):
        try:
            ticker = await self.fetcher.fetch_ticker()
            if not ticker:
                return
                
            price = ticker['price']
            change = ticker.get('change_24h', 0)
            logger.info(f"ETH/USDT: ${price:.2f} ({change:+.2f}%)")
            
            all_data = await self.fetcher.fetch_all_timeframes()
            
            for timeframe, df in all_data.items():
                await self._analyze_timeframe(timeframe, df, ticker)
                
        except Exception as e:
            logger.error(f"分析周期异常: {e}")
            
    async def _analyze_timeframe(self, timeframe: str, df, ticker: dict):
        try:
            indicators = self.indicators.calculate_all(df)
            if not indicators:
                return
            
            # 对每个策略进行分析
            for strategy_key, strategy_info in self.strategies.items():
                await self._analyze_with_strategy(
                    strategy_key, strategy_info, 
                    indicators, timeframe, ticker
                )
                
        except Exception as e:
            logger.error(f"[{timeframe}] 分析异常: {e}")
    
    async def _analyze_with_strategy(self, strategy_key, strategy_info, 
                                      indicators, timeframe, ticker):
        try:
            strategy = strategy_info['instance']
            signal = strategy.analyze(indicators, timeframe)
            
            if signal and signal.signal_type != SignalType.NEUTRAL:
                if self._should_send_signal(strategy_info, timeframe):
                    strategy_name = strategy_info['name']
                    emoji = strategy_info['emoji']
                    
                    logger.info(f"[{timeframe}] {emoji} {strategy_name} 发现信号: {signal.signal_type.value}")
                    self._print_signal(signal, strategy_name)
                    
                    # 启动时只记录不发送，避免邮件轰炸
                    if self.startup_delay:
                        logger.info(f"[启动中] 跳过发送邮件，等待下一周期")
                    else:
                        await self._send_strategy_signal(signal, ticker, strategy_name, emoji)
                    
                    strategy_info['last_signal_time'][timeframe] = datetime.now()
                    
        except Exception as e:
            logger.error(f"[{timeframe}] {strategy_info['name']} 分析异常: {e}")
    
    def _should_send_signal(self, strategy_info, timeframe: str) -> bool:
        last_signal_time = strategy_info['last_signal_time']
        if timeframe not in last_signal_time:
            return True
        min_interval = self.config['strategy']['min_signal_interval']
        elapsed = datetime.now() - last_signal_time[timeframe]
        return elapsed > timedelta(minutes=min_interval)
    
    async def _send_strategy_signal(self, signal, ticker, strategy_name, emoji):
        """发送带策略名称的信号通知"""
        price = ticker['price']
        change = ticker.get('change_24h', 0)
        
        # 获取主机名前4个字符
        import socket
        hostname = socket.gethostname()[:4]
        
        # 构建邮件标题，包含策略名称和强度
        signal_type = signal.signal_type.value
        subject = f"{emoji}【{strategy_name}】ETH {signal_type} ${price:.0f} 强度{signal.strength}"
        
        # 构建邮件内容
        body = f"""
<html>
<body style="font-family: Arial, sans-serif; padding: 20px;">
<h2 style="color: {'#00C853' if '买' in signal_type else '#FF1744'};">
    {emoji} {strategy_name} - {signal_type}
</h2>

<div style="background: #f5f5f5; padding: 15px; border-radius: 8px; margin: 10px 0;">
    <h3>📊 行情信息</h3>
    <p><strong>当前价格:</strong> ${price:.2f}</p>
    <p><strong>24h涨跌:</strong> {change:+.2f}%</p>
    <p><strong>信号强度:</strong> {signal.strength}/100</p>
</div>

<div style="background: #e3f2fd; padding: 15px; border-radius: 8px; margin: 10px 0;">
    <h3>🎯 交易建议</h3>
    <p><strong>入场价格:</strong> ${signal.entry_price:.2f}</p>
    <p><strong>止损价位:</strong> ${signal.stop_loss:.2f}</p>
    <p><strong>止盈价位:</strong> ${signal.take_profit:.2f}</p>
    <p><strong>时间周期:</strong> {signal.timeframe}</p>
</div>

<div style="background: #fff3e0; padding: 15px; border-radius: 8px; margin: 10px 0;">
    <h3>📝 信号依据</h3>
    <ul>
        {''.join(f'<li>{r}</li>' for r in signal.reasons[:6])}
    </ul>
</div>

<p style="color: #666; font-size: 12px; margin-top: 20px;">
    策略: {strategy_name} | 时间: {signal.timestamp}
</p>
</body>
</html>
"""
        
        await self.notifier._send_email(subject, body)
        
    def _print_signal(self, signal, strategy_name):
        logger.info("-" * 50)
        logger.info(f"策略: {strategy_name}")
        logger.info(f"信号类型: {signal.signal_type.value}")
        logger.info(f"信号强度: {signal.strength}/100")
        logger.info(f"当前价格: ${signal.price:.2f}")
        logger.info(f"止损价位: ${signal.stop_loss:.2f}")
        logger.info(f"止盈价位: ${signal.take_profit:.2f}")
        logger.info("信号依据:")
        for reason in signal.reasons[:5]:
            logger.info(f"  • {reason}")
        logger.info("-" * 50)


async def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='ETH/USDT 多策略并行交易信号系统')
    parser.add_argument('-c', '--config', default='config.yaml', help='配置文件路径')
    parser.add_argument('-s', '--strategies', nargs='+', 
                        default=['trend', 'combo'],
                        choices=['trend', 'combo', 'overnight'],
                        help='要运行的策略列表')
    parser.add_argument('--test', action='store_true', help='发送测试通知')
    args = parser.parse_args()
    
    bot = MultiStrategyBot(args.config, strategies=args.strategies)
    
    if args.test:
        await bot.fetcher.init()
        await bot.notifier.send_test()
        await bot.fetcher.close()
    else:
        await bot.start()


if __name__ == '__main__':
    asyncio.run(main())

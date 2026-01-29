#!/usr/bin/env python3
"""
ETH/USDT 实时交易信号系统
"""
import asyncio
import yaml
import sys
from pathlib import Path
from datetime import datetime, timedelta
from loguru import logger

from data_fetcher import DataFetcher
from indicators import TechnicalIndicators
from strategy import TradingStrategy, SignalType
from strategy_overnight import OvernightStrategy
from notifier import Notifier


# 策略映射
STRATEGIES = {
    'v5': {
        'class': TradingStrategy,
        'name': '优化版V5策略',
        'desc': '全天候多维度技术分析，自适应趋势/震荡市场'
    },
    'overnight': {
        'class': OvernightStrategy,
        'name': '均值回归策略(20x杠杆优化)',
        'desc': '全天候运行，止损0.8倍ATR，止盈1倍ATR，建议10-20%仓位'
    }
}


class TradingBot:
    def __init__(self, config_path: str = "config.yaml", strategy_type: str = "v5"):
        self.config = self._load_config(config_path)
        self._setup_logging()
        
        self.fetcher = DataFetcher(self.config)
        self.indicators = TechnicalIndicators(self.config)
        
        # 根据策略类型选择策略
        self.strategy_type = strategy_type
        if strategy_type not in STRATEGIES:
            logger.warning(f"未知策略类型: {strategy_type}，使用默认V5策略")
            strategy_type = 'v5'
        
        strategy_info = STRATEGIES[strategy_type]
        self.strategy = strategy_info['class'](self.config)
        self.strategy_name = strategy_info['name']
        self.strategy_desc = strategy_info['desc']
        
        self.notifier = Notifier(self.config)
        
        self.last_signal_time = {}
        self.running = False
        
    def _load_config(self, path: str) -> dict:
        """加载配置文件"""
        config_file = Path(path)
        if not config_file.exists():
            logger.error(f"配置文件不存在: {path}")
            logger.info("请复制 config.example.yaml 为 config.yaml 并配置")
            sys.exit(1)
            
        with open(config_file, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
            
    def _setup_logging(self):
        """配置日志"""
        log_config = self.config.get('logging', {})
        
        # 移除默认handler
        logger.remove()
        
        # 控制台输出
        logger.add(
            sys.stdout,
            level=log_config.get('level', 'INFO'),
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{message}</cyan>"
        )
        
        # 文件输出
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
        """启动交易信号系统"""
        logger.info("=" * 50)
        logger.info("ETH/USDT 实时交易信号系统启动")
        logger.info(f"📌 当前策略: {self.strategy_name}")
        logger.info(f"📝 策略说明: {self.strategy_desc}")
        logger.info("=" * 50)
        
        await self.fetcher.init()
        self.running = True
        
        # 发送测试消息
        # await self.notifier.send_test()
        
        interval = self.config['trading']['fetch_interval']
        logger.info(f"数据刷新间隔: {interval}秒")
        logger.info(f"监控时间周期: {', '.join(self.config['trading']['timeframes'])}")
        
        try:
            while self.running:
                await self._analyze_cycle()
                await asyncio.sleep(interval)
        except KeyboardInterrupt:
            logger.info("收到停止信号")
        finally:
            await self.stop()
            
    async def stop(self):
        """停止系统"""
        self.running = False
        await self.fetcher.close()
        logger.info("系统已停止")
        
    async def _analyze_cycle(self):
        """单次分析周期"""
        try:
            # 获取实时行情
            ticker = await self.fetcher.fetch_ticker()
            if not ticker:
                return
                
            price = ticker['price']
            change = ticker.get('change_24h', 0)
            logger.info(f"ETH/USDT: ${price:.2f} ({change:+.2f}%)")
            
            # 获取所有时间周期数据
            all_data = await self.fetcher.fetch_all_timeframes()
            
            # 分析每个时间周期
            for timeframe, df in all_data.items():
                await self._analyze_timeframe(timeframe, df, ticker)
                
        except Exception as e:
            logger.error(f"分析周期异常: {e}")
            
    async def _analyze_timeframe(self, timeframe: str, df, ticker: dict):
        """分析单个时间周期"""
        try:
            # 计算技术指标
            indicators = self.indicators.calculate_all(df)
            if not indicators:
                return
                
            # 生成交易信号
            signal = self.strategy.analyze(indicators, timeframe)
            
            if signal and signal.signal_type != SignalType.NEUTRAL:
                # 检查信号间隔
                if self._should_send_signal(timeframe):
                    logger.info(f"[{timeframe}] 发现信号: {signal.signal_type.value} 强度:{signal.strength}")
                    
                    # 打印信号详情
                    self._print_signal(signal)
                    
                    # 发送通知
                    await self.notifier.send_signal(signal, ticker)
                    
                    self.last_signal_time[timeframe] = datetime.now()
                    
        except Exception as e:
            logger.error(f"[{timeframe}] 分析异常: {e}")
            
    def _should_send_signal(self, timeframe: str) -> bool:
        """检查是否应该发送信号（避免频繁发送）"""
        if timeframe not in self.last_signal_time:
            return True
            
        min_interval = self.config['strategy']['min_signal_interval']
        elapsed = datetime.now() - self.last_signal_time[timeframe]
        return elapsed > timedelta(minutes=min_interval)
        
    def _print_signal(self, signal):
        """打印信号详情到控制台"""
        logger.info("-" * 40)
        logger.info(f"信号类型: {signal.signal_type.value}")
        logger.info(f"信号强度: {signal.strength}/100")
        logger.info(f"当前价格: ${signal.price:.2f}")
        logger.info(f"止损价位: ${signal.stop_loss:.2f}")
        logger.info(f"止盈价位: ${signal.take_profit:.2f}")
        logger.info("信号依据:")
        for reason in signal.reasons[:5]:
            logger.info(f"  • {reason}")
        logger.info("-" * 40)


async def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='ETH/USDT 交易信号系统')
    parser.add_argument('-c', '--config', default='config.yaml', help='配置文件路径')
    parser.add_argument('-s', '--strategy', default='v5', choices=['v5', 'overnight'],
                        help='策略类型: v5=优化版V5策略, overnight=隔夜策略')
    parser.add_argument('--test', action='store_true', help='发送测试通知')
    args = parser.parse_args()
    
    bot = TradingBot(args.config, strategy_type=args.strategy)
    
    if args.test:
        await bot.fetcher.init()
        await bot.notifier.send_test()
        await bot.fetcher.close()
    else:
        await bot.start()


if __name__ == '__main__':
    asyncio.run(main())

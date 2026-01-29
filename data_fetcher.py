"""
数据获取模块 - 支持多交易所，国内服务器优化
"""
import asyncio
import ccxt.async_support as ccxt
import pandas as pd
from datetime import datetime
from loguru import logger
from typing import Dict, List, Optional


class DataFetcher:
    # 国内可用的交易所优先级（从高到低）
    FALLBACK_EXCHANGES = ['gateio', 'huobi', 'okx']
    
    def __init__(self, config: dict):
        self.config = config
        self.exchange = None
        self.symbol = config['trading']['symbol']
        self.timeframes = config['trading']['timeframes']
        self.data_cache: Dict[str, pd.DataFrame] = {}
        self.retry_count = 3
        self.retry_delay = 2
        
    async def init(self):
        """初始化交易所连接，支持自动切换备用交易所"""
        exchange_config = self.config['exchange']
        exchange_name = exchange_config.get('name', 'gateio')
        
        # 尝试连接主交易所
        if await self._try_connect(exchange_name, exchange_config):
            return
            
        # 主交易所失败，尝试备用交易所
        logger.warning(f"{exchange_name} 连接失败，尝试备用交易所...")
        for fallback in self.FALLBACK_EXCHANGES:
            if fallback != exchange_name:
                if await self._try_connect(fallback, exchange_config):
                    return
                    
        raise Exception("所有交易所连接失败，请检查网络或配置代理")
        
    async def _try_connect(self, exchange_name: str, exchange_config: dict) -> bool:
        """尝试连接指定交易所"""
        try:
            exchange_class = getattr(ccxt, exchange_name)
            self.exchange = exchange_class({
                'apiKey': exchange_config.get('api_key', ''),
                'secret': exchange_config.get('api_secret', ''),
                'enableRateLimit': True,
                'timeout': 30000,  # 30秒超时
                'options': {'defaultType': 'spot'}
            })
            
            # 测试连接
            await asyncio.wait_for(
                self.exchange.fetch_ticker(self.symbol),
                timeout=15
            )
            logger.info(f"交易所连接成功: {exchange_name}")
            return True
        except asyncio.TimeoutError:
            logger.warning(f"{exchange_name} 连接超时")
            if self.exchange:
                await self.exchange.close()
            return False
        except Exception as e:
            logger.warning(f"{exchange_name} 连接失败: {e}")
            if self.exchange:
                await self.exchange.close()
            return False
        
    async def close(self):
        """关闭连接"""
        if self.exchange:
            await self.exchange.close()
            
    async def fetch_ticker(self) -> dict:
        """获取实时行情（带重试）"""
        for attempt in range(self.retry_count):
            try:
                ticker = await asyncio.wait_for(
                    self.exchange.fetch_ticker(self.symbol),
                    timeout=10
                )
                return {
                    'symbol': ticker['symbol'],
                    'price': ticker['last'],
                    'bid': ticker['bid'],
                    'ask': ticker['ask'],
                    'high_24h': ticker['high'],
                    'low_24h': ticker['low'],
                    'volume_24h': ticker['baseVolume'],
                    'change_24h': ticker['percentage'],
                    'timestamp': datetime.now()
                }
            except asyncio.TimeoutError:
                logger.warning(f"获取行情超时，重试 {attempt + 1}/{self.retry_count}")
                await asyncio.sleep(self.retry_delay)
            except Exception as e:
                logger.error(f"获取行情失败: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(self.retry_delay)
        return {}
            
    async def fetch_ohlcv(self, timeframe: str, limit: int = 200) -> pd.DataFrame:
        """获取K线数据（带重试）"""
        for attempt in range(self.retry_count):
            try:
                ohlcv = await asyncio.wait_for(
                    self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=limit),
                    timeout=15
                )
                df = pd.DataFrame(
                    ohlcv, 
                    columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                )
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                self.data_cache[timeframe] = df
                return df
            except asyncio.TimeoutError:
                logger.warning(f"获取K线超时 [{timeframe}]，重试 {attempt + 1}/{self.retry_count}")
                await asyncio.sleep(self.retry_delay)
            except Exception as e:
                logger.error(f"获取K线数据失败 [{timeframe}]: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(self.retry_delay)
        return pd.DataFrame()
            
    async def fetch_all_timeframes(self) -> Dict[str, pd.DataFrame]:
        """获取所有时间周期的数据"""
        tasks = [self.fetch_ohlcv(tf) for tf in self.timeframes]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        data = {}
        for tf, result in zip(self.timeframes, results):
            if isinstance(result, pd.DataFrame) and not result.empty:
                data[tf] = result
            else:
                logger.warning(f"时间周期 {tf} 数据获取失败")
        return data
        
    async def fetch_orderbook(self, limit: int = 20) -> dict:
        """获取订单簿"""
        try:
            orderbook = await self.exchange.fetch_order_book(self.symbol, limit)
            return {
                'bids': orderbook['bids'][:limit],
                'asks': orderbook['asks'][:limit],
                'spread': orderbook['asks'][0][0] - orderbook['bids'][0][0] if orderbook['asks'] and orderbook['bids'] else 0
            }
        except Exception as e:
            logger.error(f"获取订单簿失败: {e}")
            return {}
            
    def get_cached_data(self, timeframe: str) -> Optional[pd.DataFrame]:
        """获取缓存的数据"""
        return self.data_cache.get(timeframe)

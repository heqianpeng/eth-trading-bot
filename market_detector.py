"""
市场异常检测模块
检测：单边趋势、瀑布流、插针
"""
import pandas as pd
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List


@dataclass
class MarketAlert:
    alert_type: str      # trend/waterfall/pin_bar
    direction: str       # up/down
    severity: str        # warning/danger
    message: str
    details: dict
    timestamp: str


class MarketDetector:
    """市场异常检测器"""
    
    def __init__(self, config: dict):
        self.config = config
        
    def detect_all(self, df: pd.DataFrame, timeframe: str) -> List[MarketAlert]:
        """检测所有异常"""
        if df is None or len(df) < 20:
            return []
        
        alerts = []
        
        # 检测单边趋势
        trend = self._detect_trend(df, timeframe)
        if trend:
            alerts.append(trend)
        
        # 检测瀑布流
        waterfall = self._detect_waterfall(df, timeframe)
        if waterfall:
            alerts.append(waterfall)
        
        # 检测插针
        pin = self._detect_pin_bar(df, timeframe)
        if pin:
            alerts.append(pin)
        
        return alerts
    
    def _detect_trend(self, df: pd.DataFrame, timeframe: str) -> Optional[MarketAlert]:
        """检测单边趋势"""
        periods = 10
        if len(df) < periods + 5:
            return None
        
        closes = df['close'].tail(periods).values
        
        # 连续上涨/下跌计数
        up_count = sum(1 for i in range(1, len(closes)) if closes[i] > closes[i-1])
        down_count = periods - 1 - up_count
        
        # 计算ADX
        high = df['high']
        low = df['low']
        close = df['close']
        
        # 简化ADX计算
        tr = pd.concat([
            high - low,
            abs(high - close.shift(1)),
            abs(low - close.shift(1))
        ], axis=1).max(axis=1)
        atr = tr.rolling(14).mean().iloc[-1]
        
        # 价格变化幅度
        price_change = (closes[-1] - closes[0]) / closes[0] * 100
        
        # MA20偏离度
        ma20 = df['close'].rolling(20).mean().iloc[-1]
        deviation = (df['close'].iloc[-1] - ma20) / ma20 * 100
        
        # 强势上涨趋势
        if up_count >= 7 and price_change > 3 and deviation > 2:
            return MarketAlert(
                alert_type='trend',
                direction='up',
                severity='warning',
                message=f'🚀 强势上涨趋势',
                details={
                    'timeframe': timeframe,
                    'up_count': up_count,
                    'price_change': f'{price_change:.2f}%',
                    'deviation': f'{deviation:.2f}%'
                },
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        
        # 强势下跌趋势
        if down_count >= 7 and price_change < -3 and deviation < -2:
            return MarketAlert(
                alert_type='trend',
                direction='down',
                severity='warning',
                message=f'📉 强势下跌趋势',
                details={
                    'timeframe': timeframe,
                    'down_count': down_count,
                    'price_change': f'{price_change:.2f}%',
                    'deviation': f'{deviation:.2f}%'
                },
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        
        return None
    
    def _detect_waterfall(self, df: pd.DataFrame, timeframe: str) -> Optional[MarketAlert]:
        """检测瀑布流下跌/拉升"""
        if len(df) < 10:
            return None
        
        # 最近5根K线的涨跌幅
        change_5 = (df['close'].iloc[-1] - df['close'].iloc[-5]) / df['close'].iloc[-5] * 100
        
        # 单根K线涨跌幅
        single_change = (df['close'].iloc[-1] - df['open'].iloc[-1]) / df['open'].iloc[-1] * 100
        
        # 成交量比率
        vol_ma = df['volume'].rolling(20).mean().iloc[-1]
        vol_ratio = df['volume'].iloc[-1] / vol_ma if vol_ma > 0 else 1
        
        # 瀑布流下跌
        if change_5 < -4 and vol_ratio > 1.5:
            return MarketAlert(
                alert_type='waterfall',
                direction='down',
                severity='danger',
                message=f'🌊 瀑布流下跌',
                details={
                    'timeframe': timeframe,
                    'change_5': f'{change_5:.2f}%',
                    'vol_ratio': f'{vol_ratio:.1f}x'
                },
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        
        # 急速拉升
        if change_5 > 4 and vol_ratio > 1.5:
            return MarketAlert(
                alert_type='waterfall',
                direction='up',
                severity='danger',
                message=f'🚀 急速拉升',
                details={
                    'timeframe': timeframe,
                    'change_5': f'{change_5:.2f}%',
                    'vol_ratio': f'{vol_ratio:.1f}x'
                },
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        
        # 单根大阴线
        if single_change < -2.5 and vol_ratio > 2:
            return MarketAlert(
                alert_type='waterfall',
                direction='down',
                severity='danger',
                message=f'💥 大阴线砸盘',
                details={
                    'timeframe': timeframe,
                    'single_change': f'{single_change:.2f}%',
                    'vol_ratio': f'{vol_ratio:.1f}x'
                },
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        
        # 单根大阳线
        if single_change > 2.5 and vol_ratio > 2:
            return MarketAlert(
                alert_type='waterfall',
                direction='up',
                severity='danger',
                message=f'💥 大阳线拉升',
                details={
                    'timeframe': timeframe,
                    'single_change': f'{single_change:.2f}%',
                    'vol_ratio': f'{vol_ratio:.1f}x'
                },
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        
        return None
    
    def _detect_pin_bar(self, df: pd.DataFrame, timeframe: str) -> Optional[MarketAlert]:
        """检测插针"""
        if len(df) < 5:
            return None
        
        row = df.iloc[-1]
        
        open_price = row['open']
        close_price = row['close']
        high_price = row['high']
        low_price = row['low']
        
        body = abs(close_price - open_price)
        upper_wick = high_price - max(close_price, open_price)
        lower_wick = min(close_price, open_price) - low_price
        total_range = high_price - low_price
        
        if total_range == 0 or body == 0:
            return None
        
        # 计算影线与实体的比例
        lower_ratio = lower_wick / body if body > 0 else 0
        upper_ratio = upper_wick / body if body > 0 else 0
        
        # 插针幅度（相对于价格）
        pin_pct = total_range / close_price * 100
        
        # 下插针（看涨）：下影线 > 实体2倍，上影线很短，且幅度够大
        if lower_ratio > 2 and upper_ratio < 0.5 and pin_pct > 1:
            return MarketAlert(
                alert_type='pin_bar',
                direction='up',
                severity='warning',
                message=f'📍 下插针（看涨）',
                details={
                    'timeframe': timeframe,
                    'lower_wick_ratio': f'{lower_ratio:.1f}x',
                    'pin_range': f'{pin_pct:.2f}%',
                    'low_price': f'${low_price:.2f}'
                },
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        
        # 上插针（看跌）：上影线 > 实体2倍，下影线很短，且幅度够大
        if upper_ratio > 2 and lower_ratio < 0.5 and pin_pct > 1:
            return MarketAlert(
                alert_type='pin_bar',
                direction='down',
                severity='warning',
                message=f'📍 上插针（看跌）',
                details={
                    'timeframe': timeframe,
                    'upper_wick_ratio': f'{upper_ratio:.1f}x',
                    'pin_range': f'{pin_pct:.2f}%',
                    'high_price': f'${high_price:.2f}'
                },
                timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            )
        
        return None

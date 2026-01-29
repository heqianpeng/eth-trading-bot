"""
技术指标计算模块
"""
import pandas as pd
import numpy as np
import ta
from typing import Dict, Any
from loguru import logger


class TechnicalIndicators:
    def __init__(self, config: dict):
        self.config = config['indicators']
        
    def calculate_all(self, df: pd.DataFrame) -> Dict[str, Any]:
        """计算所有技术指标"""
        if df.empty or len(df) < 50:
            return {}
            
        indicators = {}
        
        # 趋势指标
        indicators.update(self._calc_ma(df))
        indicators.update(self._calc_ema(df))
        indicators.update(self._calc_macd(df))
        indicators.update(self._calc_adx(df))
        
        # 动量指标
        indicators.update(self._calc_rsi(df))
        indicators.update(self._calc_stochastic(df))
        indicators.update(self._calc_cci(df))
        indicators.update(self._calc_williams_r(df))
        
        # 波动率指标
        indicators.update(self._calc_bollinger(df))
        indicators.update(self._calc_atr(df))
        indicators.update(self._calc_keltner(df))
        
        # 成交量指标
        indicators.update(self._calc_obv(df))
        indicators.update(self._calc_volume_ma(df))
        indicators.update(self._calc_vwap(df))
        
        # 支撑阻力
        indicators.update(self._calc_pivot_points(df))
        indicators.update(self._calc_fibonacci(df))
        
        # 当前价格和开盘价
        indicators['price'] = df['close'].iloc[-1]
        indicators['open'] = df['open'].iloc[-1]
        
        return indicators
        
    def _calc_ma(self, df: pd.DataFrame) -> dict:
        """移动平均线"""
        result = {}
        for period in self.config['ma_periods']:
            if len(df) >= period:
                ma = df['close'].rolling(window=period).mean()
                result[f'ma_{period}'] = ma.iloc[-1]
        return result
        
    def _calc_ema(self, df: pd.DataFrame) -> dict:
        """指数移动平均线"""
        result = {}
        for period in self.config['ema_periods']:
            if len(df) >= period:
                ema = df['close'].ewm(span=period, adjust=False).mean()
                result[f'ema_{period}'] = ema.iloc[-1]
        return result
        
    def _calc_macd(self, df: pd.DataFrame) -> dict:
        """MACD"""
        fast = self.config['macd_fast']
        slow = self.config['macd_slow']
        signal = self.config['macd_signal']
        
        macd = ta.trend.MACD(df['close'], window_slow=slow, window_fast=fast, window_sign=signal)
        macd_hist = macd.macd_diff()
        return {
            'macd': macd.macd().iloc[-1],
            'macd_signal': macd.macd_signal().iloc[-1],
            'macd_hist': macd_hist.iloc[-1],
            'macd_hist_prev': macd_hist.iloc[-2] if len(macd_hist) > 1 else macd_hist.iloc[-1]
        }
        
    def _calc_adx(self, df: pd.DataFrame) -> dict:
        """ADX"""
        period = self.config['adx_period']
        adx = ta.trend.ADXIndicator(df['high'], df['low'], df['close'], window=period)
        return {
            'adx': adx.adx().iloc[-1],
            'di_plus': adx.adx_pos().iloc[-1],
            'di_minus': adx.adx_neg().iloc[-1]
        }
        
    def _calc_rsi(self, df: pd.DataFrame) -> dict:
        """RSI"""
        period = self.config['rsi_period']
        rsi = ta.momentum.RSIIndicator(df['close'], window=period)
        rsi_values = rsi.rsi()
        return {
            'rsi': rsi_values.iloc[-1],
            'rsi_prev': rsi_values.iloc[-2] if len(rsi_values) > 1 else rsi_values.iloc[-1]
        }
        
    def _calc_stochastic(self, df: pd.DataFrame) -> dict:
        """随机指标"""
        k = self.config['stoch_k']
        d = self.config['stoch_d']
        smooth = self.config['stoch_smooth']
        
        stoch = ta.momentum.StochasticOscillator(
            df['high'], df['low'], df['close'],
            window=k, smooth_window=d
        )
        return {
            'stoch_k': stoch.stoch().iloc[-1],
            'stoch_d': stoch.stoch_signal().iloc[-1]
        }
        
    def _calc_cci(self, df: pd.DataFrame) -> dict:
        """CCI"""
        cci = ta.trend.CCIIndicator(df['high'], df['low'], df['close'], window=20)
        return {'cci': cci.cci().iloc[-1]}
        
    def _calc_williams_r(self, df: pd.DataFrame) -> dict:
        """Williams %R"""
        wr = ta.momentum.WilliamsRIndicator(df['high'], df['low'], df['close'], lbp=14)
        return {'williams_r': wr.williams_r().iloc[-1]}
        
    def _calc_bollinger(self, df: pd.DataFrame) -> dict:
        """布林带"""
        period = self.config['bb_period']
        std = self.config['bb_std']
        
        bb = ta.volatility.BollingerBands(df['close'], window=period, window_dev=std)
        return {
            'bb_upper': bb.bollinger_hband().iloc[-1],
            'bb_middle': bb.bollinger_mavg().iloc[-1],
            'bb_lower': bb.bollinger_lband().iloc[-1],
            'bb_width': bb.bollinger_wband().iloc[-1],
            'bb_pband': bb.bollinger_pband().iloc[-1]
        }
        
    def _calc_atr(self, df: pd.DataFrame) -> dict:
        """ATR"""
        period = self.config['atr_period']
        atr = ta.volatility.AverageTrueRange(df['high'], df['low'], df['close'], window=period)
        return {'atr': atr.average_true_range().iloc[-1]}
        
    def _calc_keltner(self, df: pd.DataFrame) -> dict:
        """Keltner Channel"""
        kc = ta.volatility.KeltnerChannel(df['high'], df['low'], df['close'], window=20)
        return {
            'kc_upper': kc.keltner_channel_hband().iloc[-1],
            'kc_middle': kc.keltner_channel_mband().iloc[-1],
            'kc_lower': kc.keltner_channel_lband().iloc[-1]
        }
        
    def _calc_obv(self, df: pd.DataFrame) -> dict:
        """OBV"""
        obv = ta.volume.OnBalanceVolumeIndicator(df['close'], df['volume'])
        obv_values = obv.on_balance_volume()
        return {
            'obv': obv_values.iloc[-1],
            'obv_change': obv_values.iloc[-1] - obv_values.iloc[-2] if len(obv_values) > 1 else 0
        }
        
    def _calc_volume_ma(self, df: pd.DataFrame) -> dict:
        """成交量均线"""
        vol_ma = df['volume'].rolling(window=20).mean()
        return {
            'volume': df['volume'].iloc[-1],
            'volume_ma': vol_ma.iloc[-1],
            'volume_ratio': df['volume'].iloc[-1] / vol_ma.iloc[-1] if vol_ma.iloc[-1] > 0 else 1
        }
        
    def _calc_vwap(self, df: pd.DataFrame) -> dict:
        """VWAP"""
        vwap = ta.volume.VolumeWeightedAveragePrice(
            df['high'], df['low'], df['close'], df['volume']
        )
        return {'vwap': vwap.volume_weighted_average_price().iloc[-1]}
        
    def _calc_pivot_points(self, df: pd.DataFrame) -> dict:
        """枢轴点"""
        high = df['high'].iloc[-1]
        low = df['low'].iloc[-1]
        close = df['close'].iloc[-1]
        
        pivot = (high + low + close) / 3
        r1 = 2 * pivot - low
        s1 = 2 * pivot - high
        r2 = pivot + (high - low)
        s2 = pivot - (high - low)
        r3 = high + 2 * (pivot - low)
        s3 = low - 2 * (high - pivot)
        
        return {
            'pivot': pivot,
            'r1': r1, 'r2': r2, 'r3': r3,
            's1': s1, 's2': s2, 's3': s3
        }
        
    def _calc_fibonacci(self, df: pd.DataFrame) -> dict:
        """斐波那契回撤"""
        # 使用最近50根K线的高低点
        recent = df.tail(50)
        high = recent['high'].max()
        low = recent['low'].min()
        diff = high - low
        
        return {
            'fib_0': low,
            'fib_236': low + diff * 0.236,
            'fib_382': low + diff * 0.382,
            'fib_500': low + diff * 0.5,
            'fib_618': low + diff * 0.618,
            'fib_786': low + diff * 0.786,
            'fib_100': high
        }

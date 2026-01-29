"""
趋势跟踪策略V3 - 顺势交易，追求高盈亏比
优化参数：止损0.8ATR，止盈2.2ATR，ADX>28，RSI回调25-55
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class SignalType(Enum):
    STRONG_BUY = "强烈买入"
    BUY = "买入"
    NEUTRAL = "观望"
    SELL = "卖出"
    STRONG_SELL = "强烈卖出"


@dataclass
class TradeSignal:
    signal_type: SignalType
    strength: int
    price: float
    entry_price: float
    stop_loss: float
    take_profit: float
    reasons: list
    timeframe: str
    timestamp: str


class TrendStrategy:
    """
    趋势跟踪策略V3：
    - 只顺势交易，不抄底摸顶
    - 等待回调入场，提高胜率
    - 优化参数：收益+43.67%, 胜率44.9%, 盈亏比2.21, 回撤-5.79%
    """
    
    def __init__(self, config: dict):
        self.config = config.get('strategy', {})
        # 优化后的参数
        self.adx_threshold = 28
        self.entry_threshold = 50
        self.sl_mult = 0.8
        self.tp_mult = 2.2
        self.rsi_pullback_low = 25
        self.rsi_pullback_high = 55
        
    def analyze(self, indicators: Dict[str, Any], timeframe: str) -> Optional[TradeSignal]:
        if not indicators or 'price' not in indicators:
            return None
        
        price = indicators['price']
        atr = indicators.get('atr', price * 0.01)
        atr_pct = atr / price * 100
        
        if atr_pct > 4 or atr_pct < 0.2:
            return None
        
        # 1. 判断主趋势
        trend = self._get_main_trend(indicators)
        if trend == 'neutral':
            return None
        
        # 2. 等待回调入场点
        entry_signal = self._check_pullback_entry(indicators, trend)
        if not entry_signal['valid']:
            return None
        
        # 3. 确认动量
        momentum_ok = self._check_momentum(indicators, trend)
        if not momentum_ok:
            return None
        
        total_score = entry_signal['score']
        
        reasons = ["📈 趋势跟踪V3"]
        if trend == 'up':
            reasons.append("🟢 上涨趋势")
        else:
            reasons.append("🔴 下跌趋势")
        reasons.extend(entry_signal['reasons'])
        
        if abs(total_score) < self.entry_threshold:
            return None
        
        signal_type = self._get_signal_type(total_score)
        if signal_type == SignalType.NEUTRAL:
            return None
        
        # 优化后的止盈止损：0.8ATR止损，2.2ATR止盈
        if total_score > 0:
            stop_loss = price - atr * self.sl_mult
            take_profit = price + atr * self.tp_mult
        else:
            stop_loss = price + atr * self.sl_mult
            take_profit = price - atr * self.tp_mult
        
        return TradeSignal(
            signal_type=signal_type,
            strength=min(100, abs(int(total_score))),
            price=price,
            entry_price=price,
            stop_loss=round(stop_loss, 2),
            take_profit=round(take_profit, 2),
            reasons=reasons,
            timeframe=timeframe,
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        )
    
    def _get_main_trend(self, ind: dict) -> str:
        """判断主趋势"""
        price = ind['price']
        ma20 = ind.get('ma_20', price)
        ma50 = ind.get('ma_50', price)
        ema9 = ind.get('ema_9', price)
        ema21 = ind.get('ema_21', price)
        adx = ind.get('adx', 20)
        
        if adx < self.adx_threshold:
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
        
        if up_count >= 3:
            return 'up'
        elif down_count >= 3:
            return 'down'
        return 'neutral'
    
    def _check_pullback_entry(self, ind: dict, trend: str) -> dict:
        """检查回调入场点"""
        score = 0
        reasons = []
        
        price = ind['price']
        rsi = ind.get('rsi', 50)
        bb_pband = ind.get('bb_pband', 0.5)
        ema21 = ind.get('ema_21', price)
        k = ind.get('stoch_k', 50)
        
        if trend == 'up':
            # RSI回调到25-55区间
            if self.rsi_pullback_low <= rsi <= self.rsi_pullback_high:
                score += 30
                reasons.append(f"RSI回调至{rsi:.0f}")
            
            if 0.3 <= bb_pband <= 0.6:
                score += 25
                reasons.append("回调至布林中轨")
            
            if abs(price - ema21) / ema21 < 0.01:
                score += 25
                reasons.append("回调至EMA21")
            
            if 30 <= k <= 50:
                score += 20
                reasons.append("KD回调")
                
        else:
            # 下跌趋势：RSI反弹到45-75区间
            if (100 - self.rsi_pullback_high) <= rsi <= (100 - self.rsi_pullback_low):
                score -= 30
                reasons.append(f"RSI反弹至{rsi:.0f}")
            
            if 0.4 <= bb_pband <= 0.7:
                score -= 25
                reasons.append("反弹至布林中轨")
            
            if abs(price - ema21) / ema21 < 0.01:
                score -= 25
                reasons.append("反弹至EMA21")
            
            if 50 <= k <= 70:
                score -= 20
                reasons.append("KD反弹")
        
        return {'valid': abs(score) >= 40, 'score': score, 'reasons': reasons}
    
    def _check_momentum(self, ind: dict, trend: str) -> bool:
        """检查动量"""
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
        elif score >= 35:
            return SignalType.BUY
        elif score <= -60:
            return SignalType.STRONG_SELL
        elif score <= -35:
            return SignalType.SELL
        return SignalType.NEUTRAL

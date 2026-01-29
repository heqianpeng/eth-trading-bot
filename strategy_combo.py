"""
多策略组合V2 - 根据市场状态自动切换策略
优化版：只在明确趋势或极端超买超卖时交易
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


class ComboStrategy:
    """
    多策略组合V2：
    - 趋势市场(ADX>28)：趋势跟踪策略，等待回调入场
    - 震荡市场(ADX<18)：均值回归策略，只做极端超买超卖
    - 中性市场：不交易
    """
    
    def __init__(self, config: dict):
        self.config = config.get('strategy', {})
        # 优化后的参数
        self.adx_trend = 28      # ADX趋势阈值
        self.adx_range = 18      # ADX震荡阈值
        self.entry_threshold = 50
        self.trend_sl = 0.9
        self.trend_tp = 2.0
        self.range_sl = 0.8
        self.range_tp = 1.0
        self.rsi_oversold = 25
        self.rsi_overbought = 75
        
    def analyze(self, indicators: Dict[str, Any], timeframe: str) -> Optional[TradeSignal]:
        if not indicators or 'price' not in indicators:
            return None
        
        price = indicators['price']
        atr = indicators.get('atr', price * 0.01)
        atr_pct = atr / price * 100
        
        if atr_pct > 4 or atr_pct < 0.2:
            return None
        
        # 1. 识别市场状态
        market_state = self._identify_market_state(indicators)
        
        # 中性市场不交易
        if market_state == 'neutral':
            return None
        
        # 2. 根据市场状态选择策略
        if market_state == 'trending':
            signal = self._trend_signal(indicators)
            strategy_name = "📈 趋势跟踪"
            sl_mult, tp_mult = self.trend_sl, self.trend_tp
        else:  # ranging
            signal = self._mean_reversion_signal(indicators)
            strategy_name = "📊 均值回归"
            sl_mult, tp_mult = self.range_sl, self.range_tp
        
        if not signal['valid']:
            return None
        
        total_score = signal['score']
        reasons = [f"🔄 多策略组合V2"]
        reasons.append(f"{strategy_name}")
        reasons.extend(signal['reasons'])
        
        if abs(total_score) < self.entry_threshold:
            return None
        
        signal_type = self._get_signal_type(total_score)
        if signal_type == SignalType.NEUTRAL:
            return None
        
        if total_score > 0:
            stop_loss = price - atr * sl_mult
            take_profit = price + atr * tp_mult
        else:
            stop_loss = price + atr * sl_mult
            take_profit = price - atr * tp_mult
        
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
    
    def _identify_market_state(self, ind: dict) -> str:
        """识别市场状态"""
        adx = ind.get('adx', 20)
        
        if adx > self.adx_trend:
            return 'trending'
        elif adx < self.adx_range:
            return 'ranging'
        return 'neutral'
    
    def _trend_signal(self, ind: dict) -> dict:
        """趋势跟踪信号 - 只做顺势回调"""
        score = 0
        reasons = []
        
        price = ind['price']
        ma20 = ind.get('ma_20', price)
        ma50 = ind.get('ma_50', price)
        ema9 = ind.get('ema_9', price)
        ema21 = ind.get('ema_21', price)
        rsi = ind.get('rsi', 50)
        macd_hist = ind.get('macd_hist', 0)
        bb_pband = ind.get('bb_pband', 0.5)
        
        # 多头趋势
        if ema9 > ema21 and ma20 > ma50 and price > ma20:
            score += 30
            reasons.append("🟢 多头趋势")
            # 回调入场
            if 35 <= rsi <= 50:
                score += 30
                reasons.append(f"RSI回调至{rsi:.0f}")
            if 0.3 <= bb_pband <= 0.6:
                score += 20
                reasons.append("回调至布林中轨")
            if macd_hist > 0:
                score += 10
        
        # 空头趋势
        elif ema9 < ema21 and ma20 < ma50 and price < ma20:
            score -= 30
            reasons.append("🔴 空头趋势")
            if 50 <= rsi <= 65:
                score -= 30
                reasons.append(f"RSI反弹至{rsi:.0f}")
            if 0.4 <= bb_pband <= 0.7:
                score -= 20
                reasons.append("反弹至布林中轨")
            if macd_hist < 0:
                score -= 10
        
        return {'valid': abs(score) >= 50, 'score': score, 'reasons': reasons}
    
    def _mean_reversion_signal(self, ind: dict) -> dict:
        """均值回归信号 - 只做极端超买超卖"""
        score = 0
        reasons = []
        
        rsi = ind.get('rsi', 50)
        bb_pband = ind.get('bb_pband', 0.5)
        k = ind.get('stoch_k', 50)
        
        # 超卖
        if rsi < self.rsi_oversold:
            score += 35
            reasons.append(f"RSI={rsi:.0f}极度超卖")
            if bb_pband < 0.1:
                score += 25
                reasons.append("触及布林下轨")
            if k < 20:
                score += 20
                reasons.append("KD超卖")
        
        # 超买
        elif rsi > self.rsi_overbought:
            score -= 35
            reasons.append(f"RSI={rsi:.0f}极度超买")
            if bb_pband > 0.9:
                score -= 25
                reasons.append("触及布林上轨")
            if k > 80:
                score -= 20
                reasons.append("KD超买")
        
        return {'valid': abs(score) >= 50, 'score': score, 'reasons': reasons}
    
    def _get_signal_type(self, score: float) -> SignalType:
        if score >= 60:
            return SignalType.STRONG_BUY
        elif score >= 50:
            return SignalType.BUY
        elif score <= -60:
            return SignalType.STRONG_SELL
        elif score <= -50:
            return SignalType.SELL
        return SignalType.NEUTRAL

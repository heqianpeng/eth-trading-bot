"""
突破策略 - 等待明确突破再入场
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


class BreakoutStrategy:
    """
    突破策略：
    - 等待价格突破关键位置
    - 布林带突破 + 成交量确认
    - 突破后回踩入场
    """
    
    def __init__(self, config: dict):
        self.config = config.get('strategy', {})
        
    def analyze(self, indicators: Dict[str, Any], timeframe: str) -> Optional[TradeSignal]:
        if not indicators or 'price' not in indicators:
            return None
        
        price = indicators['price']
        atr = indicators.get('atr', price * 0.01)
        atr_pct = atr / price * 100
        
        if atr_pct > 4 or atr_pct < 0.3:
            return None
        
        # 检测突破信号
        breakout = self._detect_breakout(indicators)
        if not breakout['valid']:
            return None
        
        # 成交量确认（优化参数：1.5倍放量）
        vol_ratio = indicators.get('volume_ratio', 1)
        if vol_ratio < 1.5:
            return None  # 突破需要放量确认
        
        total_score = breakout['score']
        reasons = ["🚀 突破策略"]
        reasons.extend(breakout['reasons'])
        reasons.append(f"放量{vol_ratio:.1f}x")
        
        threshold = 50  # 优化后的入场阈值
        if abs(total_score) < threshold:
            return None
        
        signal_type = self._get_signal_type(total_score)
        if signal_type == SignalType.NEUTRAL:
            return None
        
        # 突破策略：止损在突破位下方，止盈用ATR（优化参数）
        # 止损0.5倍ATR，止盈3.0倍ATR，盈亏比约2.0
        if total_score > 0:
            stop_loss = breakout.get('breakout_level', price) - atr * 0.5
            take_profit = price + atr * 3.0
        else:
            stop_loss = breakout.get('breakout_level', price) + atr * 0.5
            take_profit = price - atr * 3.0
        
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
    
    def _detect_breakout(self, ind: dict) -> dict:
        """检测突破信号"""
        score = 0
        reasons = []
        breakout_level = ind['price']
        
        price = ind['price']
        bb_upper = ind.get('bb_upper', price * 1.02)
        bb_lower = ind.get('bb_lower', price * 0.98)
        bb_pband = ind.get('bb_pband', 0.5)
        r1 = ind.get('r1', 0)
        s1 = ind.get('s1', 0)
        high_20 = ind.get('high_20', price)
        low_20 = ind.get('low_20', price)
        adx = ind.get('adx', 20)
        
        # 向上突破
        up_breakout = False
        
        # 突破布林带上轨
        if bb_pband > 1.0:
            score += 40
            reasons.append("突破布林带上轨")
            breakout_level = bb_upper
            up_breakout = True
        
        # 突破20日高点
        if price > high_20 * 0.998:
            score += 35
            reasons.append("突破20日高点")
            breakout_level = high_20
            up_breakout = True
        
        # 突破阻力位R1
        if r1 > 0 and price > r1:
            score += 30
            reasons.append(f"突破阻力位R1 ${r1:.2f}")
            breakout_level = r1
            up_breakout = True
        
        # 向下突破
        down_breakout = False
        
        # 跌破布林带下轨
        if bb_pband < 0:
            score -= 40
            reasons.append("跌破布林带下轨")
            breakout_level = bb_lower
            down_breakout = True
        
        # 跌破20日低点
        if price < low_20 * 1.002:
            score -= 35
            reasons.append("跌破20日低点")
            breakout_level = low_20
            down_breakout = True
        
        # 跌破支撑位S1
        if s1 > 0 and price < s1:
            score -= 30
            reasons.append(f"跌破支撑位S1 ${s1:.2f}")
            breakout_level = s1
            down_breakout = True
        
        # ADX确认趋势强度（优化参数：25）
        if adx > 25:
            if up_breakout:
                score += 20
            elif down_breakout:
                score -= 20
            reasons.append(f"ADX={adx:.0f}趋势强")
        
        return {
            'valid': up_breakout or down_breakout,
            'score': score,
            'reasons': reasons,
            'breakout_level': breakout_level
        }
    
    def _get_signal_type(self, score: float) -> SignalType:
        if score >= 70:
            return SignalType.STRONG_BUY
        elif score >= 50:
            return SignalType.BUY
        elif score <= -70:
            return SignalType.STRONG_SELL
        elif score <= -50:
            return SignalType.SELL
        return SignalType.NEUTRAL

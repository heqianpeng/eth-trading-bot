"""
趋势跟踪策略V4 - 防爆仓优化版
优化：放宽止损1.2ATR，增加波动率过滤，高波动不开仓
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
    趋势跟踪策略V4 - 防爆仓优化版：
    - 放宽止损：1.2ATR（原0.8ATR）
    - 波动率过滤：ATR>3%不开仓
    - 更严格的入场条件
    - 只做强趋势
    """
    
    def __init__(self, config: dict):
        self.config = config.get('strategy', {})
        # 防爆仓优化参数
        self.adx_threshold = 30      # 提高ADX阈值，只做强趋势
        self.entry_threshold = 60
        self.sl_mult = 1.2           # 放宽止损，从0.8改为1.2
        self.tp_mult = 2.0           # 止盈保持2倍
        self.rsi_pullback_low = 30   # RSI回调区间收窄
        self.rsi_pullback_high = 50
        self.max_atr_pct = 3.0       # 最大ATR波动率，超过不开仓
        
    def analyze(self, indicators: Dict[str, Any], timeframe: str) -> Optional[TradeSignal]:
        if not indicators or 'price' not in indicators:
            return None
        
        price = indicators['price']
        atr = indicators.get('atr', price * 0.01)
        atr_pct = atr / price * 100
        
        # 波动率过滤：太高或太低都不开仓
        if atr_pct > self.max_atr_pct:
            return None  # 高波动不开仓，容易被扫止损
        if atr_pct < 0.3:
            return None  # 波动太小没意义
        
        # 1. 判断主趋势（更严格）
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
        
        # 4. 检查是否处于支撑/阻力位附近（增加安全边际）
        safe_entry = self._check_safe_entry(indicators, trend)
        if not safe_entry:
            return None
        
        total_score = entry_signal['score']
        
        reasons = ["📈 趋势跟踪V4"]
        reasons.append(f"ATR={atr_pct:.1f}%")
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
        
        # 放宽止损：1.2ATR止损，2.0ATR止盈
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
        """判断主趋势 - 更严格"""
        price = ind['price']
        ma20 = ind.get('ma_20', price)
        ma50 = ind.get('ma_50', price)
        ema9 = ind.get('ema_9', price)
        ema21 = ind.get('ema_21', price)
        adx = ind.get('adx', 20)
        di_plus = ind.get('di_plus', 0)
        di_minus = ind.get('di_minus', 0)
        
        # ADX必须足够强
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
        
        # DI方向确认
        if di_plus > di_minus: up_count += 1
        else: down_count += 1
        
        # 需要4个以上确认（原来是3个）
        if up_count >= 4:
            return 'up'
        elif down_count >= 4:
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
            # RSI回调到30-50区间（收窄）
            if self.rsi_pullback_low <= rsi <= self.rsi_pullback_high:
                score += 30
                reasons.append(f"RSI回调至{rsi:.0f}")
            
            if 0.3 <= bb_pband <= 0.5:
                score += 25
                reasons.append("回调至布林中下轨")
            
            if abs(price - ema21) / ema21 < 0.008:
                score += 25
                reasons.append("回调至EMA21")
            
            if 25 <= k <= 45:
                score += 20
                reasons.append("KD回调")
                
        else:
            # 下跌趋势：RSI反弹到50-70区间
            if 50 <= rsi <= 70:
                score -= 30
                reasons.append(f"RSI反弹至{rsi:.0f}")
            
            if 0.5 <= bb_pband <= 0.7:
                score -= 25
                reasons.append("反弹至布林中上轨")
            
            if abs(price - ema21) / ema21 < 0.008:
                score -= 25
                reasons.append("反弹至EMA21")
            
            if 55 <= k <= 75:
                score -= 20
                reasons.append("KD反弹")
        
        return {'valid': abs(score) >= 45, 'score': score, 'reasons': reasons}
    
    def _check_momentum(self, ind: dict, trend: str) -> bool:
        """检查动量"""
        macd_hist = ind.get('macd_hist', 0)
        di_plus = ind.get('di_plus', 0)
        di_minus = ind.get('di_minus', 0)
        
        if trend == 'up':
            return macd_hist > 0 and di_plus > di_minus
        else:
            return macd_hist < 0 and di_minus > di_plus
    
    def _check_safe_entry(self, ind: dict, trend: str) -> bool:
        """检查是否有安全边际（靠近支撑/阻力）"""
        price = ind['price']
        s1 = ind.get('s1', 0)
        r1 = ind.get('r1', 0)
        bb_lower = ind.get('bb_lower', 0)
        bb_upper = ind.get('bb_upper', 0)
        
        if trend == 'up':
            # 做多时，价格应该靠近支撑位
            if s1 > 0:
                dist_to_support = (price - s1) / price * 100
                if dist_to_support < 1.5:  # 距离支撑1.5%以内
                    return True
            if bb_lower > 0:
                dist_to_bb = (price - bb_lower) / price * 100
                if dist_to_bb < 2:
                    return True
            # 如果没有明确支撑，但RSI够低也可以
            rsi = ind.get('rsi', 50)
            if rsi < 40:
                return True
        else:
            # 做空时，价格应该靠近阻力位
            if r1 > 0:
                dist_to_resist = (r1 - price) / price * 100
                if dist_to_resist < 1.5:
                    return True
            if bb_upper > 0:
                dist_to_bb = (bb_upper - price) / price * 100
                if dist_to_bb < 2:
                    return True
            rsi = ind.get('rsi', 50)
            if rsi > 60:
                return True
        
        return False
    
    def _get_signal_type(self, score: float) -> SignalType:
        if score >= 70:
            return SignalType.STRONG_BUY
        elif score >= 60:
            return SignalType.BUY
        elif score <= -70:
            return SignalType.STRONG_SELL
        elif score <= -60:
            return SignalType.SELL
        return SignalType.NEUTRAL

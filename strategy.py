"""
交易策略模块 - 优化版V5
最佳表现版本：高胜率 + 低回撤 + 稳定盈亏比
"""
from typing import Dict, Any, Optional
from dataclasses import dataclass
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


class TradingStrategy:
    def __init__(self, config: dict):
        self.config = config['strategy']
        self.ind_config = config['indicators']
        
    def analyze(self, indicators: Dict[str, Any], timeframe: str) -> Optional[TradeSignal]:
        if not indicators or 'price' not in indicators:
            return None
        
        price = indicators['price']
        atr = indicators.get('atr', price * 0.01)
        atr_pct = atr / price * 100
        
        if atr_pct > 5 or atr_pct < 0.3:
            return None
        
        market_state = self._get_market_state(indicators)
        
        mean_rev = self._mean_reversion_signal(indicators)
        trend = self._trend_signal(indicators)
        volume = self._volume_signal(indicators)
        structure = self._market_structure(indicators)
        
        reasons = []
        
        if market_state == 'trending':
            total_score = trend['score'] * 0.5 + structure['score'] * 0.25 + volume['score'] * 0.25
            reasons.append("📈 趋势市场")
        elif market_state == 'ranging':
            total_score = mean_rev['score'] * 0.5 + structure['score'] * 0.25 + volume['score'] * 0.25
            reasons.append("📊 震荡市场")
        else:
            total_score = (trend['score'] + mean_rev['score']) * 0.35 + structure['score'] * 0.15 + volume['score'] * 0.15
            reasons.append("⚖️ 混合市场")
        
        reasons.extend(trend['reasons'])
        reasons.extend(mean_rev['reasons'])
        reasons.extend(volume['reasons'])
        reasons.extend(structure['reasons'])
        
        # 大趋势过滤
        ma50 = indicators.get('ma_50', price)
        ma200 = indicators.get('ma_200', price)
        
        if ma200 > 0:
            if ma50 > ma200 * 1.02 and total_score < -20:
                return None
            elif ma50 < ma200 * 0.98 and total_score > 20:
                return None
        
        threshold = self.config.get('signal_threshold', 28)
        if abs(total_score) < threshold:
            return None
            
        signal_type = self._get_signal_type(total_score)
        if signal_type == SignalType.NEUTRAL:
            return None
        
        # 最佳参数：2.8倍ATR止损，1.6倍ATR止盈
        if total_score > 0:
            stop_loss = price - atr * 2.8
            take_profit = price + atr * 1.6
        else:
            stop_loss = price + atr * 2.8
            take_profit = price - atr * 1.6
            
        from datetime import datetime
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
    
    def _get_market_state(self, ind: dict) -> str:
        adx = ind.get('adx', 25)
        bb_width = ind.get('bb_width', 0.03)
        
        if adx > 30 and bb_width > 0.04:
            return 'trending'
        elif adx < 20 or bb_width < 0.02:
            return 'ranging'
        return 'mixed'
    
    def _mean_reversion_signal(self, ind: dict) -> dict:
        score = 0
        reasons = []
        
        rsi = ind.get('rsi', 50)
        if rsi < 20:
            score += 50
            reasons.append(f"RSI={rsi:.0f} 极度超卖")
        elif rsi < 30:
            score += 35
            reasons.append(f"RSI={rsi:.0f} 超卖")
        elif rsi < 40:
            score += 15
        elif rsi > 80:
            score -= 50
            reasons.append(f"RSI={rsi:.0f} 极度超买")
        elif rsi > 70:
            score -= 35
            reasons.append(f"RSI={rsi:.0f} 超买")
        elif rsi > 60:
            score -= 15
            
        bb_pband = ind.get('bb_pband', 0.5)
        if bb_pband < -0.05:
            score += 40
            reasons.append("突破布林带下轨")
        elif bb_pband < 0.1:
            score += 25
        elif bb_pband > 1.05:
            score -= 40
            reasons.append("突破布林带上轨")
        elif bb_pband > 0.9:
            score -= 25
            
        k = ind.get('stoch_k', 50)
        d = ind.get('stoch_d', 50)
        if k < 15 and d < 20 and k > d:
            score += 35
            reasons.append("随机指标超卖金叉")
        elif k > 85 and d > 80 and k < d:
            score -= 35
            reasons.append("随机指标超买死叉")
        elif k < 25 and k > d:
            score += 20
        elif k > 75 and k < d:
            score -= 20
                
        return {'score': max(-100, min(100, score)), 'reasons': reasons}
    
    def _trend_signal(self, ind: dict) -> dict:
        score = 0
        reasons = []
        price = ind['price']
        
        ma20 = ind.get('ma_20', price)
        ma50 = ind.get('ma_50', price)
        ema9 = ind.get('ema_9', price)
        ema21 = ind.get('ema_21', price)
        
        if ema9 > ema21 * 1.002:
            score += 20
            reasons.append("EMA9 > EMA21")
        elif ema9 < ema21 * 0.998:
            score -= 20
            
        if ma20 > ma50 * 1.005:
            score += 25
            reasons.append("MA20 > MA50 多头")
        elif ma20 < ma50 * 0.995:
            score -= 25
            reasons.append("MA20 < MA50 空头")
            
        above_count = sum([price > ma20, price > ma50, price > ema21])
        if above_count == 3:
            score += 20
        elif above_count == 0:
            score -= 20
            
        macd_hist = ind.get('macd_hist', 0)
        macd = ind.get('macd', 0)
        signal = ind.get('macd_signal', 0)
        
        if macd_hist > 0 and macd > signal:
            score += 25
            reasons.append("MACD金叉")
        elif macd_hist < 0 and macd < signal:
            score -= 25
            reasons.append("MACD死叉")
            
        adx = ind.get('adx', 20)
        di_plus = ind.get('di_plus', 0)
        di_minus = ind.get('di_minus', 0)
        
        if adx > 25:
            if di_plus > di_minus * 1.2:
                score += 20
                reasons.append(f"ADX={adx:.0f} 强多")
            elif di_minus > di_plus * 1.2:
                score -= 20
                reasons.append(f"ADX={adx:.0f} 强空")
                
        return {'score': max(-100, min(100, score)), 'reasons': reasons}
    
    def _volume_signal(self, ind: dict) -> dict:
        score = 0
        reasons = []
        
        vol_ratio = ind.get('volume_ratio', 1)
        obv_change = ind.get('obv_change', 0)
        
        if vol_ratio > 2.5:
            score += 30
            reasons.append(f"放量 {vol_ratio:.1f}x")
        elif vol_ratio > 1.8:
            score += 20
        elif vol_ratio > 1.3:
            score += 10
        elif vol_ratio < 0.5:
            score -= 15
            
        if obv_change > 0:
            score += 15
        else:
            score -= 15
            
        return {'score': max(-50, min(50, score)), 'reasons': reasons}
    
    def _market_structure(self, ind: dict) -> dict:
        score = 0
        reasons = []
        price = ind['price']
        
        s1 = ind.get('s1', 0)
        r1 = ind.get('r1', 0)
        
        if s1 > 0:
            dist_s1 = (price - s1) / s1 * 100
            if 0 < dist_s1 < 0.8:
                score += 25
                reasons.append("接近S1支撑")
            elif -0.3 < dist_s1 <= 0:
                score += 35
                reasons.append("触及S1支撑")
                
        if r1 > 0:
            dist_r1 = (price - r1) / r1 * 100
            if -0.8 < dist_r1 < 0:
                score -= 25
                reasons.append("接近R1阻力")
            elif 0 <= dist_r1 < 0.3:
                score -= 35
                reasons.append("触及R1阻力")
        
        fib_382 = ind.get('fib_382', 0)
        fib_618 = ind.get('fib_618', 0)
        
        if fib_382 > 0 and fib_618 > 0:
            if abs(price - fib_382) / fib_382 < 0.005:
                score += 20
                reasons.append("斐波那契38.2%")
            elif abs(price - fib_618) / fib_618 < 0.005:
                score += 25
                reasons.append("斐波那契61.8%")
                
        return {'score': max(-60, min(60, score)), 'reasons': reasons}
        
    def _get_signal_type(self, score: float) -> SignalType:
        if score >= 45:
            return SignalType.STRONG_BUY
        elif score >= 28:
            return SignalType.BUY
        elif score <= -45:
            return SignalType.STRONG_SELL
        elif score <= -28:
            return SignalType.SELL
        return SignalType.NEUTRAL

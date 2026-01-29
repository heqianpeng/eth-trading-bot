"""
隔夜交易策略模块
只在北京时间 0:00-8:00 开仓，任何时间可平仓
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


def is_overnight_session() -> bool:
    """判断当前是否在北京时间凌晨时段 (0:00-8:00)"""
    now = datetime.utcnow()
    beijing_hour = (now.hour + 8) % 24
    return 0 <= beijing_hour < 8


def get_beijing_hour() -> int:
    """获取当前北京时间小时"""
    now = datetime.utcnow()
    return (now.hour + 8) % 24


class OvernightStrategy:
    """
    隔夜策略：利用亚洲时段低波动特性
    - 只在北京时间 0:00-8:00 开仓
    - 使用均值回归 + 支撑阻力策略
    - 更宽松的止损，更保守的止盈
    """
    
    def __init__(self, config: dict):
        self.config = config.get('strategy', {})
        self.ind_config = config.get('indicators', {})
        
    def analyze(self, indicators: Dict[str, Any], timeframe: str) -> Optional[TradeSignal]:
        if not indicators or 'price' not in indicators:
            return None
        
        # 全天候运行（移除时段限制）
        # if not is_overnight_session():
        #     return None
        
        price = indicators['price']
        atr = indicators.get('atr', price * 0.01)
        atr_pct = atr / price * 100
        
        # 隔夜时段波动较小，过滤极端波动
        if atr_pct > 3 or atr_pct < 0.2:
            return None
        
        # 计算各维度信号
        mean_rev = self._mean_reversion_signal(indicators)
        structure = self._market_structure(indicators)
        momentum = self._momentum_signal(indicators)
        
        # 隔夜策略侧重均值回归
        total_score = mean_rev['score'] * 0.5 + structure['score'] * 0.3 + momentum['score'] * 0.2
        
        reasons = ["📊 均值回归策略"]
        reasons.extend(mean_rev['reasons'])
        reasons.extend(structure['reasons'])
        reasons.extend(momentum['reasons'])
        
        # 20倍杠杆：提高信号阈值到50，只做最高确定性交易
        threshold = self.config.get('signal_threshold', 50)
        if abs(total_score) < threshold:
            return None
            
        signal_type = self._get_signal_type(total_score)
        if signal_type == SignalType.NEUTRAL:
            return None
        
        # 20倍杠杆优化：更窄止损防爆仓
        # 止损0.8倍ATR（约0.8-1%），止盈1倍ATR
        if total_score > 0:
            stop_loss = price - atr * 0.8
            take_profit = price + atr * 1.0
        else:
            stop_loss = price + atr * 0.8
            take_profit = price - atr * 1.0
            
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
    
    def _mean_reversion_signal(self, ind: dict) -> dict:
        """均值回归信号 - 隔夜时段核心策略"""
        score = 0
        reasons = []
        
        # RSI
        rsi = ind.get('rsi', 50)
        if rsi < 25:
            score += 45
            reasons.append(f"RSI={rsi:.0f} 深度超卖")
        elif rsi < 35:
            score += 30
            reasons.append(f"RSI={rsi:.0f} 超卖")
        elif rsi > 75:
            score -= 45
            reasons.append(f"RSI={rsi:.0f} 深度超买")
        elif rsi > 65:
            score -= 30
            reasons.append(f"RSI={rsi:.0f} 超买")
            
        # 布林带
        bb_pband = ind.get('bb_pband', 0.5)
        if bb_pband < 0:
            score += 40
            reasons.append("跌破布林带下轨")
        elif bb_pband < 0.15:
            score += 25
            reasons.append("接近布林带下轨")
        elif bb_pband > 1:
            score -= 40
            reasons.append("突破布林带上轨")
        elif bb_pband > 0.85:
            score -= 25
            reasons.append("接近布林带上轨")
            
        # 随机指标
        k = ind.get('stoch_k', 50)
        d = ind.get('stoch_d', 50)
        if k < 20 and d < 25:
            score += 30
            if k > d:
                reasons.append("随机指标超卖金叉")
        elif k > 80 and d > 75:
            score -= 30
            if k < d:
                reasons.append("随机指标超买死叉")
                
        return {'score': max(-100, min(100, score)), 'reasons': reasons}
    
    def _market_structure(self, ind: dict) -> dict:
        """市场结构分析"""
        score = 0
        reasons = []
        price = ind['price']
        
        # 支撑阻力
        s1 = ind.get('s1', 0)
        r1 = ind.get('r1', 0)
        
        if s1 > 0:
            dist_s1 = (price - s1) / s1 * 100
            if 0 < dist_s1 < 1:
                score += 35
                reasons.append(f"接近支撑位S1 ${s1:.2f}")
            elif -0.5 < dist_s1 <= 0:
                score += 45
                reasons.append(f"触及支撑位S1 ${s1:.2f}")
                
        if r1 > 0:
            dist_r1 = (price - r1) / r1 * 100
            if -1 < dist_r1 < 0:
                score -= 35
                reasons.append(f"接近阻力位R1 ${r1:.2f}")
            elif 0 <= dist_r1 < 0.5:
                score -= 45
                reasons.append(f"触及阻力位R1 ${r1:.2f}")
        
        # 斐波那契
        fib_382 = ind.get('fib_382', 0)
        fib_618 = ind.get('fib_618', 0)
        
        if fib_618 > 0 and abs(price - fib_618) / fib_618 < 0.008:
            score += 25
            reasons.append("斐波那契61.8%回撤位")
        elif fib_382 > 0 and abs(price - fib_382) / fib_382 < 0.008:
            score += 20
            reasons.append("斐波那契38.2%回撤位")
                
        return {'score': max(-80, min(80, score)), 'reasons': reasons}
    
    def _momentum_signal(self, ind: dict) -> dict:
        """动量信号（辅助确认）"""
        score = 0
        reasons = []
        
        # MACD
        macd_hist = ind.get('macd_hist', 0)
        if macd_hist > 0:
            score += 15
        else:
            score -= 15
            
        # 成交量
        vol_ratio = ind.get('volume_ratio', 1)
        if vol_ratio > 1.5:
            score += 10
        elif vol_ratio < 0.6:
            score -= 10
            
        return {'score': max(-30, min(30, score)), 'reasons': reasons}
        
    def _get_signal_type(self, score: float) -> SignalType:
        if score >= 50:
            return SignalType.STRONG_BUY
        elif score >= 30:
            return SignalType.BUY
        elif score <= -50:
            return SignalType.STRONG_SELL
        elif score <= -30:
            return SignalType.SELL
        return SignalType.NEUTRAL

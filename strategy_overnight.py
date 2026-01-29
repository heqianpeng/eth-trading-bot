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
        # 优化后的参数
        self.rsi_oversold = 30
        self.rsi_overbought = 75
        self.sl_mult = 0.8
        self.tp_mult = 1.5
        
    def analyze(self, indicators: Dict[str, Any], timeframe: str) -> Optional[TradeSignal]:
        if not indicators or 'price' not in indicators:
            return None
        
        price = indicators['price']
        atr = indicators.get('atr', price * 0.01)
        atr_pct = atr / price * 100
        
        # 过滤极端波动
        if atr_pct > 3 or atr_pct < 0.2:
            return None
        
        # 计算各维度信号
        mean_rev = self._mean_reversion_signal(indicators)
        structure = self._market_structure(indicators)
        momentum = self._momentum_signal(indicators)
        
        total_score = mean_rev['score'] * 0.5 + structure['score'] * 0.3 + momentum['score'] * 0.2
        
        reasons = ["📊 均值回归策略"]
        reasons.extend(mean_rev['reasons'])
        reasons.extend(structure['reasons'])
        reasons.extend(momentum['reasons'])
        
        # 信号阈值50
        threshold = self.config.get('signal_threshold', 50)
        if abs(total_score) < threshold:
            return None
            
        signal_type = self._get_signal_type(total_score)
        if signal_type == SignalType.NEUTRAL:
            return None
        
        # 动态止盈止损：根据市场结构设置更精准的点位
        stop_loss, take_profit = self._calculate_dynamic_levels(indicators, total_score, price, atr)
            
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
        """均值回归信号 - 优化版"""
        score = 0
        reasons = []
        
        # RSI（优化参数：30/75）
        rsi = ind.get('rsi', 50)
        if rsi < self.rsi_oversold:
            score += 45
            reasons.append(f"RSI={rsi:.0f} 深度超卖")
        elif rsi < self.rsi_oversold + 10:
            score += 30
            reasons.append(f"RSI={rsi:.0f} 超卖")
        elif rsi > self.rsi_overbought:
            score -= 45
            reasons.append(f"RSI={rsi:.0f} 深度超买")
        elif rsi > self.rsi_overbought - 10:
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
    
    def _get_trend(self, ind: dict) -> str:
        """判断当前趋势"""
        price = ind['price']
        ma20 = ind.get('ma_20', price)
        ma50 = ind.get('ma_50', price)
        ema9 = ind.get('ema_9', price)
        ema21 = ind.get('ema_21', price)
        
        up_signals = 0
        down_signals = 0
        
        if price > ma20: up_signals += 1
        else: down_signals += 1
        
        if price > ma50: up_signals += 1
        else: down_signals += 1
        
        if ema9 > ema21: up_signals += 1
        else: down_signals += 1
        
        if ma20 > ma50: up_signals += 1
        else: down_signals += 1
        
        if up_signals >= 3:
            return 'up'
        elif down_signals >= 3:
            return 'down'
        return 'neutral'
    
    def _count_confirmations(self, ind: dict, score: float) -> int:
        """计算确认信号数量 - 更严格"""
        confirmations = 0
        
        rsi = ind.get('rsi', 50)
        bb_pband = ind.get('bb_pband', 0.5)
        k = ind.get('stoch_k', 50)
        d = ind.get('stoch_d', 50)
        macd_hist = ind.get('macd_hist', 0)
        
        if score > 0:  # 做多信号
            if rsi < 35: confirmations += 1  # RSI超卖
            if bb_pband < 0.2: confirmations += 1  # 接近布林下轨
            if k < 25 and k > d: confirmations += 1  # 随机指标超卖金叉
            if macd_hist > 0: confirmations += 1  # MACD多头
        else:  # 做空信号
            if rsi > 65: confirmations += 1  # RSI超买
            if bb_pband > 0.8: confirmations += 1  # 接近布林上轨
            if k > 75 and k < d: confirmations += 1  # 随机指标超买死叉
            if macd_hist < 0: confirmations += 1  # MACD空头
        
        return confirmations
        
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
    
    def _calculate_dynamic_levels(self, ind: dict, score: float, price: float, atr: float) -> tuple:
        """动态计算止盈止损点位，基于支撑阻力和波动率"""
        
        # 获取关键价位
        s1 = ind.get('s1', 0)
        s2 = ind.get('s2', 0)
        r1 = ind.get('r1', 0)
        r2 = ind.get('r2', 0)
        bb_lower = ind.get('bb_lower', price - atr * 2)
        bb_upper = ind.get('bb_upper', price + atr * 2)
        bb_middle = ind.get('bb_middle', price)
        
        # 默认止损止盈（优化参数：0.8ATR止损，1.5ATR止盈）
        default_sl_dist = atr * self.sl_mult
        default_tp_dist = atr * self.tp_mult
        
        if score > 0:  # 做多
            # 止损：取支撑位和ATR止损中更近的
            sl_candidates = [price - default_sl_dist]
            if s1 > 0 and s1 < price:
                sl_candidates.append(s1 - atr * 0.1)  # 支撑位下方一点
            if bb_lower > 0 and bb_lower < price:
                sl_candidates.append(bb_lower - atr * 0.1)
            
            # 选择最近的止损（但不能太近）
            valid_sls = [sl for sl in sl_candidates if price - sl >= atr * 0.5]
            stop_loss = max(valid_sls) if valid_sls else price - default_sl_dist
            
            # 止盈：取阻力位和ATR止盈中更近的
            tp_candidates = [price + default_tp_dist]
            if r1 > 0 and r1 > price:
                tp_candidates.append(r1 - atr * 0.05)  # 阻力位下方一点
            if bb_middle > price:
                tp_candidates.append(bb_middle)
            if bb_upper > price:
                tp_candidates.append(bb_upper - atr * 0.1)
            
            # 选择最近的止盈（但要保证盈亏比）
            min_tp = price + (price - stop_loss) * 1.0  # 至少1:1盈亏比
            valid_tps = [tp for tp in tp_candidates if tp >= min_tp]
            take_profit = min(valid_tps) if valid_tps else price + default_tp_dist
            
        else:  # 做空
            # 止损：取阻力位和ATR止损中更近的
            sl_candidates = [price + default_sl_dist]
            if r1 > 0 and r1 > price:
                sl_candidates.append(r1 + atr * 0.1)  # 阻力位上方一点
            if bb_upper > 0 and bb_upper > price:
                sl_candidates.append(bb_upper + atr * 0.1)
            
            valid_sls = [sl for sl in sl_candidates if sl - price >= atr * 0.5]
            stop_loss = min(valid_sls) if valid_sls else price + default_sl_dist
            
            # 止盈：取支撑位和ATR止盈中更近的
            tp_candidates = [price - default_tp_dist]
            if s1 > 0 and s1 < price:
                tp_candidates.append(s1 + atr * 0.05)  # 支撑位上方一点
            if bb_middle < price:
                tp_candidates.append(bb_middle)
            if bb_lower < price:
                tp_candidates.append(bb_lower + atr * 0.1)
            
            min_tp = price - (stop_loss - price) * 1.0  # 至少1:1盈亏比
            valid_tps = [tp for tp in tp_candidates if tp <= min_tp]
            take_profit = max(valid_tps) if valid_tps else price - default_tp_dist
        
        return round(stop_loss, 2), round(take_profit, 2)

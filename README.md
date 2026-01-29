# ETH/USDT 实时交易信号系统

## 功能特点

- 📊 实时获取 ETH/USDT 行情数据
- 📈 多维度技术指标分析
- 🎯 智能交易信号生成
- 📱 多渠道消息推送（Telegram/微信/邮件）
- 💰 自动计算止盈止损位

## 技术指标

### 趋势指标
- MA (移动平均线) - 5/10/20/50/200
- EMA (指数移动平均线)
- MACD (异同移动平均线)
- ADX (平均趋向指数)

### 动量指标
- RSI (相对强弱指数)
- Stochastic (随机指标)
- CCI (商品通道指数)
- Williams %R

### 波动率指标
- Bollinger Bands (布林带)
- ATR (真实波动幅度)
- Keltner Channel

### 成交量指标
- OBV (能量潮)
- Volume MA
- VWAP (成交量加权平均价)

### 支撑阻力
- Pivot Points
- Fibonacci Retracement
- 关键价格位

## 项目结构

```
eth-trading-bot/
├── main.py              # 主程序入口
├── data_fetcher.py      # 数据获取模块（Binance API）
├── indicators.py        # 技术指标计算
├── strategy.py          # 交易策略分析
├── notifier.py          # 消息推送（Telegram/微信/邮件）
├── config.example.yaml  # 配置模板
├── config.yaml          # 你的配置（需创建）
└── requirements.txt     # Python依赖
```

## 快速开始

```bash
cd eth-trading-bot

# 安装依赖
pip install -r requirements.txt

# 复制配置模板
cp config.example.yaml config.yaml

# 编辑配置文件，设置推送渠道
nano config.yaml

# 启动系统
python main.py

# 发送测试通知
python main.py --test
```

## 配置说明

### 推送渠道配置

#### Telegram
1. 找 @BotFather 创建机器人，获取 bot_token
2. 找 @userinfobot 获取你的 chat_id
3. 在 config.yaml 中填入

#### 微信（Server酱）
1. 访问 https://sct.ftqq.com/ 注册
2. 获取 SendKey
3. 在 config.yaml 中填入

#### 邮件
1. 使用Gmail需要开启"应用专用密码"
2. 在 config.yaml 中配置SMTP信息

### 策略参数

- `signal_threshold`: 信号强度阈值，越高越严格（默认60）
- `atr_stop_multiplier`: ATR止损倍数（默认2.0）
- `atr_profit_multiplier`: ATR止盈倍数（默认3.0）
- `min_signal_interval`: 同一周期最小信号间隔（分钟）

## 信号说明

系统会综合分析以下维度：
- 趋势（30%）：MA/EMA/MACD/ADX
- 动量（25%）：RSI/Stochastic/CCI/Williams%R
- 波动率（15%）：布林带/Keltner通道
- 成交量（15%）：OBV/VWAP/成交量比率
- 支撑阻力（15%）：枢轴点/斐波那契

信号类型：
- 🟢 强烈买入（得分≥60）
- 🟢 买入（得分≥30）
- ⚪ 观望（-30<得分<30）
- 🔴 卖出（得分≤-30）
- 🔴 强烈卖出（得分≤-60）

## 风险提示

⚠️ 本系统仅供学习参考，不构成投资建议。加密货币交易风险极高，请谨慎操作！

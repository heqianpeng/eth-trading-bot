"""
消息推送模块 - 支持Telegram/微信/邮件
"""
import asyncio
import aiohttp
from typing import Optional
from loguru import logger
from strategy import TradeSignal


class Notifier:
    def __init__(self, config: dict):
        self.config = config['notifications']
        
    async def send_signal(self, signal: TradeSignal, ticker: dict = None):
        """发送交易信号通知"""
        message = self._format_signal(signal, ticker)
        
        tasks = []
        if self.config['telegram']['enabled']:
            tasks.append(self._send_telegram(message))
        if self.config['wechat']['enabled']:
            tasks.append(self._send_wechat(signal, message))
        if self.config['email']['enabled']:
            tasks.append(self._send_email(signal, message))
            
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            logger.warning("没有启用任何通知渠道")
            
    def _format_signal(self, signal: TradeSignal, ticker: dict = None) -> str:
        """格式化信号消息"""
        emoji = "🟢" if "买" in signal.signal_type.value else "🔴"
        
        msg = f"""
{emoji} ETH/USDT 交易信号 {emoji}

📊 信号类型: {signal.signal_type.value}
💪 信号强度: {signal.strength}/100
⏰ 时间周期: {signal.timeframe}
🕐 时间: {signal.timestamp}

💰 当前价格: ${signal.price:.2f}
🎯 建议入场: ${signal.entry_price:.2f}
🛑 止损价位: ${signal.stop_loss:.2f}
✅ 止盈价位: ${signal.take_profit:.2f}

📈 盈亏比: {abs(signal.take_profit - signal.entry_price) / abs(signal.entry_price - signal.stop_loss):.2f}
"""
        
        if ticker:
            msg += f"""
📊 24H数据:
  • 最高: ${ticker.get('high_24h', 0):.2f}
  • 最低: ${ticker.get('low_24h', 0):.2f}
  • 涨跌: {ticker.get('change_24h', 0):.2f}%
  • 成交量: {ticker.get('volume_24h', 0):,.0f} ETH
"""
        
        msg += "\n📋 信号依据:\n"
        for i, reason in enumerate(signal.reasons[:10], 1):
            msg += f"  {i}. {reason}\n"
            
        msg += "\n⚠️ 风险提示: 此为系统自动分析，仅供参考，请谨慎操作！"
        
        return msg
        
    async def _send_telegram(self, message: str):
        """发送Telegram消息"""
        try:
            config = self.config['telegram']
            url = f"https://api.telegram.org/bot{config['bot_token']}/sendMessage"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json={
                    'chat_id': config['chat_id'],
                    'text': message,
                    'parse_mode': 'HTML'
                }) as resp:
                    if resp.status == 200:
                        logger.info("Telegram消息发送成功")
                    else:
                        logger.error(f"Telegram发送失败: {await resp.text()}")
        except Exception as e:
            logger.error(f"Telegram发送异常: {e}")
            
    async def _send_wechat(self, signal: TradeSignal, message: str):
        """发送微信消息（通过Server酱）"""
        try:
            config = self.config['wechat']
            url = f"https://sctapi.ftqq.com/{config['sendkey']}.send"
            
            title = f"ETH交易信号: {signal.signal_type.value}"
            
            async with aiohttp.ClientSession() as session:
                async with session.post(url, data={
                    'title': title,
                    'desp': message.replace('\n', '\n\n')  # Markdown格式
                }) as resp:
                    if resp.status == 200:
                        result = await resp.json()
                        if result.get('code') == 0:
                            logger.info("微信消息发送成功")
                        else:
                            logger.error(f"微信发送失败: {result}")
                    else:
                        logger.error(f"微信发送失败: {resp.status}")
        except Exception as e:
            logger.error(f"微信发送异常: {e}")
            
    async def _send_email(self, subject_or_signal, body_or_message: str = None):
        """发送邮件通知
        支持两种调用方式：
        1. _send_email(signal, message) - 传入信号对象
        2. _send_email(subject, body) - 直接传入标题和内容
        """
        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            from email.mime.multipart import MIMEMultipart
            
            config = self.config['email']
            
            import socket
            hostname = socket.gethostname()
            
            msg = MIMEMultipart()
            msg['From'] = config['username']
            msg['To'] = config['to_address']
            
            # 判断调用方式
            if hasattr(subject_or_signal, 'signal_type'):
                # 传入的是signal对象
                signal = subject_or_signal
                msg['Subject'] = f"[{hostname[:4]}] ETH交易信号: {signal.signal_type.value} 强度{signal.strength}"
                
                html = f"""
                <html>
                <body style="font-family: Arial, sans-serif;">
                <h2>{'🟢' if '买' in signal.signal_type.value else '🔴'} ETH/USDT 交易信号</h2>
                <table style="border-collapse: collapse; width: 100%;">
                    <tr><td style="padding: 8px; border: 1px solid #ddd;"><b>信号类型</b></td><td style="padding: 8px; border: 1px solid #ddd;">{signal.signal_type.value}</td></tr>
                    <tr><td style="padding: 8px; border: 1px solid #ddd;"><b>信号强度</b></td><td style="padding: 8px; border: 1px solid #ddd;">{signal.strength}/100</td></tr>
                    <tr><td style="padding: 8px; border: 1px solid #ddd;"><b>当前价格</b></td><td style="padding: 8px; border: 1px solid #ddd;">${signal.price:.2f}</td></tr>
                    <tr><td style="padding: 8px; border: 1px solid #ddd;"><b>止损价位</b></td><td style="padding: 8px; border: 1px solid #ddd;">${signal.stop_loss:.2f}</td></tr>
                    <tr><td style="padding: 8px; border: 1px solid #ddd;"><b>止盈价位</b></td><td style="padding: 8px; border: 1px solid #ddd;">${signal.take_profit:.2f}</td></tr>
                </table>
                <h3>信号依据:</h3>
                <ul>
                {''.join(f'<li>{r}</li>' for r in signal.reasons[:10])}
                </ul>
                <p style="color: red;"><b>⚠️ 风险提示: 此为系统自动分析，仅供参考！</b></p>
                </body>
                </html>
                """
            else:
                # 传入的是subject和body
                msg['Subject'] = f"[{hostname[:4]}] {subject_or_signal}"
                html = body_or_message
            
            msg.attach(MIMEText(html, 'html'))
            
            # QQ邮箱使用SSL端口465
            if config.get('use_ssl', False) or config['smtp_port'] == 465:
                await aiosmtplib.send(
                    msg,
                    hostname=config['smtp_server'],
                    port=config['smtp_port'],
                    username=config['username'],
                    password=config['password'],
                    use_tls=True  # SSL直连
                )
            else:
                await aiosmtplib.send(
                    msg,
                    hostname=config['smtp_server'],
                    port=config['smtp_port'],
                    username=config['username'],
                    password=config['password'],
                    start_tls=True  # STARTTLS
                )
            logger.info("邮件发送成功")
        except Exception as e:
            logger.error(f"邮件发送异常: {e}")
            
    async def send_test(self):
        """发送测试消息"""
        test_msg = "🔔 ETH交易信号系统测试消息\n\n系统已成功启动，通知功能正常！"
        
        tasks = []
        if self.config['telegram']['enabled']:
            tasks.append(self._send_telegram(test_msg))
        if self.config['wechat']['enabled']:
            async with aiohttp.ClientSession() as session:
                url = f"https://sctapi.ftqq.com/{self.config['wechat']['sendkey']}.send"
                tasks.append(session.post(url, data={'title': '系统测试', 'desp': test_msg}))
        if self.config['email']['enabled']:
            tasks.append(self._send_test_email())
                
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
            logger.info("测试消息已发送")
            
    async def _send_test_email(self):
        """发送测试邮件"""
        try:
            import aiosmtplib
            from email.mime.text import MIMEText
            
            config = self.config['email']
            
            import socket
            hostname = socket.gethostname()
            
            msg = MIMEText(f"🔔 ETH交易信号系统测试\n\n系统已成功启动，邮件通知功能正常！\n\n服务器: {hostname}\n\n当出现交易信号时，您将收到邮件通知。", 'plain', 'utf-8')
            msg['From'] = config['username']
            msg['To'] = config['to_address']
            msg['Subject'] = f"[{hostname[:4]}] ETH交易信号系统 - 测试邮件"
            
            # QQ邮箱使用SSL端口465
            if config.get('use_ssl', False) or config['smtp_port'] == 465:
                await aiosmtplib.send(
                    msg,
                    hostname=config['smtp_server'],
                    port=config['smtp_port'],
                    username=config['username'],
                    password=config['password'],
                    use_tls=True  # SSL直连
                )
            else:
                await aiosmtplib.send(
                    msg,
                    hostname=config['smtp_server'],
                    port=config['smtp_port'],
                    username=config['username'],
                    password=config['password'],
                    start_tls=True  # STARTTLS
                )
            logger.info("测试邮件发送成功")
        except Exception as e:
            logger.error(f"测试邮件发送异常: {e}")

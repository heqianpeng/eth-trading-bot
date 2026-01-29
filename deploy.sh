#!/bin/bash
# 阿里云一键部署脚本

echo "=========================================="
echo "  ETH/USDT 交易信号系统 - 阿里云部署"
echo "=========================================="

# 安装Python和pip
echo ">>> 安装依赖..."
sudo apt update
sudo apt install -y python3 python3-pip python3-venv

# 创建虚拟环境
echo ">>> 创建虚拟环境..."
python3 -m venv venv
source venv/bin/activate

# 安装Python依赖
echo ">>> 安装Python包..."
pip install -r requirements.txt

# 创建systemd服务
echo ">>> 配置系统服务..."
sudo tee /etc/systemd/system/eth-bot.service > /dev/null <<EOF
[Unit]
Description=ETH Trading Signal Bot
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$(pwd)
ExecStart=$(pwd)/venv/bin/python main.py -s overnight
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# 启动服务
sudo systemctl daemon-reload
sudo systemctl enable eth-bot
sudo systemctl start eth-bot

echo ""
echo "=========================================="
echo "  部署完成！"
echo "=========================================="
echo ""
echo "常用命令："
echo "  查看状态: sudo systemctl status eth-bot"
echo "  查看日志: sudo journalctl -u eth-bot -f"
echo "  重启服务: sudo systemctl restart eth-bot"
echo "  停止服务: sudo systemctl stop eth-bot"
echo ""

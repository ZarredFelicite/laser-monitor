#!/usr/bin/env bash

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}🔧 Installing Laser Monitor systemd services...${NC}"
echo -e "Project directory: ${PROJECT_DIR}"
echo

# Check if running as root
if [[ $EUID -eq 0 ]]; then
    echo -e "${RED}❌ Don't run this script as root. It will use sudo when needed.${NC}"
    exit 1
fi

# Check if systemd is available
if ! command -v systemctl &> /dev/null; then
    echo -e "${RED}❌ systemctl not found. This system doesn't appear to use systemd.${NC}"
    exit 1
fi

# Function to install a service file
install_service() {
    local service_file="$1"
    local service_name="$(basename "$service_file")"
    
    echo -e "${YELLOW}📋 Installing ${service_name}...${NC}"
    
    # Copy service file to systemd directory
    sudo cp "$service_file" "/etc/systemd/system/"
    
    # Set proper permissions
    sudo chmod 644 "/etc/systemd/system/$service_name"
    
    echo -e "${GREEN}✅ ${service_name} installed${NC}"
}

# Install service files
install_service "$SCRIPT_DIR/laser-monitor.service"
install_service "$SCRIPT_DIR/laser-monitor-server.service"
install_service "$SCRIPT_DIR/laser-monitor.target"

# Reload systemd daemon
echo -e "${YELLOW}🔄 Reloading systemd daemon...${NC}"
sudo systemctl daemon-reload

# Enable services
echo -e "${YELLOW}🚀 Enabling services...${NC}"
sudo systemctl enable laser-monitor.service
sudo systemctl enable laser-monitor-server.service
sudo systemctl enable laser-monitor.target

echo
echo -e "${GREEN}✅ Installation complete!${NC}"
echo
echo -e "${BLUE}📋 Available commands:${NC}"
echo -e "  ${YELLOW}Start both services:${NC}     sudo systemctl start laser-monitor.target"
echo -e "  ${YELLOW}Stop both services:${NC}      sudo systemctl stop laser-monitor.target"
echo -e "  ${YELLOW}Check status:${NC}            sudo systemctl status laser-monitor.target"
echo -e "  ${YELLOW}View logs (monitor):${NC}     sudo journalctl -u laser-monitor.service -f"
echo -e "  ${YELLOW}View logs (server):${NC}      sudo journalctl -u laser-monitor-server.service -f"
echo -e "  ${YELLOW}Restart services:${NC}        sudo systemctl restart laser-monitor.target"
echo
echo -e "${BLUE}🌐 Web dashboard will be available at:${NC} http://localhost:5000"
echo
echo -e "${YELLOW}⚠️  Note:${NC} Make sure the config file exists: ${PROJECT_DIR}/config/test.config.py"
echo -e "${YELLOW}⚠️  Note:${NC} Ensure camera permissions are set up correctly for user 'hilton'"
echo -e "${YELLOW}⚠️  Note:${NC} Verify uv is installed and available: $(which uv 2>/dev/null || echo 'uv not found')"
echo -e "${YELLOW}⚠️  Note:${NC} Services configured for: /home/hilton/git-repo"
echo

# Ask if user wants to start services now
read -p "Start the services now? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo -e "${YELLOW}🚀 Starting laser-monitor.target...${NC}"
    sudo systemctl start laser-monitor.target
    
    # Wait a moment and check status
    sleep 3
    echo
    echo -e "${BLUE}📊 Service status:${NC}"
    sudo systemctl status laser-monitor.target --no-pager -l
    
    echo
    echo -e "${GREEN}✅ Services started! Check the logs if there are any issues.${NC}"
else
    echo -e "${BLUE}ℹ️  Services installed but not started. Use 'sudo systemctl start laser-monitor.target' when ready.${NC}"
fi
#!/usr/bin/env bash

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to show usage
show_usage() {
    echo -e "${BLUE}🔧 Laser Monitor Service Manager${NC}"
    echo
    echo -e "${YELLOW}Usage:${NC} $0 <command>"
    echo
    echo -e "${YELLOW}Commands:${NC}"
    echo -e "  ${GREEN}start${NC}     - Start both laser monitor and web server"
    echo -e "  ${GREEN}stop${NC}      - Stop both services"
    echo -e "  ${GREEN}restart${NC}   - Restart both services"
    echo -e "  ${GREEN}status${NC}    - Show status of both services"
    echo -e "  ${GREEN}logs${NC}      - Show logs for both services"
    echo -e "  ${GREEN}logs-monitor${NC} - Show only laser monitor logs"
    echo -e "  ${GREEN}logs-server${NC}  - Show only web server logs"
    echo -e "  ${GREEN}enable${NC}    - Enable services to start on boot"
    echo -e "  ${GREEN}disable${NC}   - Disable services from starting on boot"
    echo
    echo -e "${BLUE}Examples:${NC}"
    echo -e "  $0 start"
    echo -e "  $0 logs-monitor"
    echo -e "  $0 status"
}

# Function to check if services are installed
check_services() {
    if ! systemctl list-unit-files | grep -q "laser-monitor.service"; then
        echo -e "${RED}❌ Services not installed. Run ./install-services.sh first.${NC}"
        exit 1
    fi
}

# Main command handling
case "${1:-}" in
    start)
        check_services
        echo -e "${YELLOW}🚀 Starting Laser Monitor services...${NC}"
        sudo systemctl start laser-monitor.target
        echo -e "${GREEN}✅ Services started${NC}"
        ;;
    
    stop)
        check_services
        echo -e "${YELLOW}🛑 Stopping Laser Monitor services...${NC}"
        sudo systemctl stop laser-monitor.target
        echo -e "${GREEN}✅ Services stopped${NC}"
        ;;
    
    restart)
        check_services
        echo -e "${YELLOW}🔄 Restarting Laser Monitor services...${NC}"
        sudo systemctl restart laser-monitor.target
        echo -e "${GREEN}✅ Services restarted${NC}"
        ;;
    
    status)
        check_services
        echo -e "${BLUE}📊 Laser Monitor Service Status:${NC}"
        echo
        sudo systemctl status laser-monitor.target --no-pager -l
        ;;
    
    logs)
        check_services
        echo -e "${BLUE}📋 Following logs for both services (Ctrl+C to exit):${NC}"
        sudo journalctl -u laser-monitor.service -u laser-monitor-server.service -f
        ;;
    
    logs-monitor)
        check_services
        echo -e "${BLUE}📋 Following laser monitor logs (Ctrl+C to exit):${NC}"
        sudo journalctl -u laser-monitor.service -f
        ;;
    
    logs-server)
        check_services
        echo -e "${BLUE}📋 Following web server logs (Ctrl+C to exit):${NC}"
        sudo journalctl -u laser-monitor-server.service -f
        ;;
    
    enable)
        check_services
        echo -e "${YELLOW}🔧 Enabling services to start on boot...${NC}"
        sudo systemctl enable laser-monitor.target
        echo -e "${GREEN}✅ Services enabled${NC}"
        ;;
    
    disable)
        check_services
        echo -e "${YELLOW}🔧 Disabling services from starting on boot...${NC}"
        sudo systemctl disable laser-monitor.target
        echo -e "${GREEN}✅ Services disabled${NC}"
        ;;
    
    *)
        show_usage
        exit 1
        ;;
esac
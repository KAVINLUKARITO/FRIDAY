#!/bin/bash
#
# AIWorker Monitor Script - Phase 3 Production Hardening
#
# Operational script for daily monitoring and maintenance.
#
# Functions:
#   status  - Quick health check
#   logs    - Tail with filtering
#   metrics - Export telemetry to CSV
#   cleanup - Purge old backups, vacuum SQLite, rotate logs
#   update  - Pull latest code, run tests, graceful restart
#   emergency-stop - Immediate halt with state preservation
#   verify  - Check all components
#
# Usage: ./monitor.sh [status|logs|metrics|cleanup|update|emergency-stop|verify]
#
# Cron integration:
#   0 */6 * * * root /opt/aiworker/deploy/monitor.sh cleanup
#   0 2 * * * root /opt/aiworker/deploy/monitor.sh update
#   */5 * * * * root /opt/aiworker/deploy/monitor.sh verify

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color
BOLD='\033[1m'

# Configuration
AIWORKER_BASE="/opt/aiworker"
AIWORKER_USER="aiworker"
LOG_DIR="${AIWORKER_BASE}/logs"
DATA_DIR="${AIWORKER_BASE}/data"
BACKUP_DIR="${AIWORKER_BASE}/backups"
VENV_PATH="${AIWORKER_BASE}/venv"

# Helper functions
print_header() {
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo -e "${BOLD}${CYAN}  $1${NC}"
    echo -e "${BOLD}${CYAN}═══════════════════════════════════════════════════════════════${NC}"
    echo
}

print_status() {
    local status=$1
    local message=$2
    if [ "$status" = "OK" ]; then
        echo -e "  ${GREEN}✓${NC} $message"
    elif [ "$status" = "WARN" ]; then
        echo -e "  ${YELLOW}⚠${NC} $message"
    elif [ "$status" = "FAIL" ]; then
        echo -e "  ${RED}✗${NC} $message"
    else
        echo -e "  $message"
    fi
}

print_metric() {
    local label=$1
    local value=$2
    local unit=${3:-}
    printf "  %-30s %10s %s\n" "$label:" "$value" "$unit"
}

# Get memory usage in GB
get_memory_gb() {
    awk '/MemTotal/{total=$2} /MemAvailable/{avail=$2} END{printf "%.1f", (total-avail)/1024/1024}' /proc/meminfo
}

get_memory_percent() {
    awk '/MemTotal/{total=$2} /MemAvailable/{avail=$2} END{printf "%.0f", ((total-avail)/total)*100}' /proc/meminfo
}

# Get disk usage
get_disk_usage() {
    df -h /opt/aiworker 2>/dev/null | awk 'NR==2 {print $5}' | tr -d '%'
}

# Check if service is running
check_service() {
    systemctl is-active --quiet "$1" 2>/dev/null
}

# Status command
cmd_status() {
    print_header "AIWorker Status Report"
    
    local timestamp
    timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    echo -e "  Report time: ${BLUE}$timestamp${NC}"
    echo
    
    # Service status
    echo -e "${BOLD}Service Status:${NC}"
    if check_service "aiworker"; then
        print_status "OK" "aiworker.service is running"
    else
        print_status "FAIL" "aiworker.service is NOT running"
    fi
    
    if check_service "aiworker-watchdog"; then
        print_status "OK" "aiworker-watchdog.service is running"
    else
        print_status "WARN" "aiworker-watchdog.service is NOT running"
    fi
    
    if check_service "ollama"; then
        print_status "OK" "ollama.service is running"
    else
        print_status "WARN" "ollama.service is NOT running"
    fi
    echo
    
    # Memory status
    echo -e "${BOLD}Memory Status:${NC}"
    local mem_gb mem_pct
    mem_gb=$(get_memory_gb)
    mem_pct=$(get_memory_percent)
    
    if [ "$mem_pct" -lt 70 ]; then
        print_status "OK" "Memory usage: ${mem_gb}GB (${mem_pct}%)"
    elif [ "$mem_pct" -lt 88 ]; then
        print_status "WARN" "Memory usage: ${mem_gb}GB (${mem_pct}%)"
    else
        print_status "FAIL" "Memory usage: ${mem_gb}GB (${mem_pct}%) - CRITICAL"
    fi
    echo
    
    # Disk status
    echo -e "${BOLD}Disk Status:${NC}"
    local disk_pct
    disk_pct=$(get_disk_usage)
    
    if [ "$disk_pct" -lt 70 ]; then
        print_status "OK" "Disk usage: ${disk_pct}%"
    elif [ "$disk_pct" -lt 90 ]; then
        print_status "WARN" "Disk usage: ${disk_pct}%"
    else
        print_status "FAIL" "Disk usage: ${disk_pct}% - CRITICAL"
    fi
    echo
    
    # Last iteration
    echo -e "${BOLD}Last Iteration:${NC}"
    if [ -f "${DATA_DIR}/checkpoints.db" ]; then
        local last_iter
        last_iter=$(sqlite3 "${DATA_DIR}/checkpoints.db" \
            "SELECT iteration_id FROM iterations ORDER BY started_at DESC LIMIT 1;" 2>/dev/null || echo "N/A")
        
        if [ "$last_iter" != "N/A" ] && [ -n "$last_iter" ]; then
            print_status "OK" "Last iteration: $last_iter"
        else
            print_status "WARN" "No iterations found"
        fi
    else
        print_status "WARN" "Checkpoint database not found"
    fi
    echo
    
    # Pending approvals
    echo -e "${BOLD}Pending Approvals:${NC}"
    if [ -f "${DATA_DIR}/safety.db" ]; then
        local pending
        pending=$(sqlite3 "${DATA_DIR}/safety.db" \
            "SELECT COUNT(*) FROM pending_patches;" 2>/dev/null || echo "0")
        
        if [ "$pending" -gt 0 ]; then
            print_status "WARN" "$pending patch(es) awaiting approval"
        else
            print_status "OK" "No pending approvals"
        fi
    else
        print_status "OK" "No pending approvals"
    fi
    echo
    
    # Recommendations
    echo -e "${BOLD}Recommendations:${NC}"
    if [ "$mem_pct" -gt 85 ]; then
        echo -e "  ${YELLOW}→ Consider running cleanup to free memory${NC}"
    fi
    if [ "$disk_pct" -gt 80 ]; then
        echo -e "  ${YELLOW}→ Consider running cleanup to free disk space${NC}"
    fi
    if ! check_service "aiworker"; then
        echo -e "  ${RED}→ Run: systemctl start aiworker${NC}"
    fi
    echo
}

# Logs command
cmd_logs() {
    local filter=${1:-"all"}
    local lines=${2:-50}
    
    print_header "AIWorker Logs"
    
    local log_file="${LOG_DIR}/aiworker.log"
    
    if [ ! -f "$log_file" ]; then
        echo -e "${RED}Log file not found: $log_file${NC}"
        return 1
    fi
    
    echo -e "${BOLD}Showing last $lines lines (filter: $filter):${NC}"
    echo
    
    case "$filter" in
        error)
            tail -n "$lines" "$log_file" | grep -i "error\|critical\|fatal" || echo "No errors found"
            ;;
        warning)
            tail -n "$lines" "$log_file" | grep -i "warning\|warn" || echo "No warnings found"
            ;;
        info)
            tail -n "$lines" "$log_file" | grep -i "info" || echo "No info messages found"
            ;;
        *)
            tail -n "$lines" "$log_file"
            ;;
    esac
    echo
}

# Metrics command
cmd_metrics() {
    print_header "AIWorker Metrics Export"
    
    local output_file="${AIWORKER_BASE}/metrics_$(date +%Y%m%d_%H%M%S).csv"
    
    echo -e "Exporting metrics to: ${BLUE}$output_file${NC}"
    echo
    
    if [ ! -f "${DATA_DIR}/telemetry.db" ]; then
        echo -e "${RED}Telemetry database not found${NC}"
        return 1
    fi
    
    # Export to CSV
    sqlite3 "${DATA_DIR}/telemetry.db" <<EOF > "$output_file"
    .mode csv
    .headers on
    SELECT 
        datetime(timestamp, 'unixepoch') as time,
        metric_type,
        value,
        unit
    FROM telemetry_samples 
    WHERE timestamp > strftime('%s', 'now', '-24 hours')
    ORDER BY timestamp DESC;
EOF
    
    local count
    count=$(wc -l < "$output_file")
    echo -e "${GREEN}Exported $count records to $output_file${NC}"
    echo
    
    # Summary
    echo -e "${BOLD}24-Hour Summary:${NC}"
    sqlite3 "${DATA_DIR}/telemetry.db" <<EOF | while read -r line; do echo "  $line"; done
    SELECT 
        metric_type,
        printf('%.2f', AVG(value)) as avg,
        printf('%.2f', MIN(value)) as min,
        printf('%.2f', MAX(value)) as max
    FROM telemetry_samples 
    WHERE timestamp > strftime('%s', 'now', '-24 hours')
    GROUP BY metric_type;
EOF
    echo
}

# Cleanup command
cmd_cleanup() {
    print_header "AIWorker Cleanup"
    
    echo -e "${BOLD}Running cleanup tasks...${NC}"
    echo
    
    # Purge old backups
    echo "  Purging old backups..."
    find "$BACKUP_DIR" -name "*.tar.gz" -mtime +7 -delete 2>/dev/null || true
    find "$BACKUP_DIR" -name "*.tar.zst" -mtime +7 -delete 2>/dev/null || true
    find "$BACKUP_DIR" -name "*.json" -mtime +7 -delete 2>/dev/null || true
    print_status "OK" "Old backups purged"
    
    # Vacuum SQLite databases
    echo "  Vacuuming SQLite databases..."
    for db in "$DATA_DIR"/*.db; do
        if [ -f "$db" ]; then
            sqlite3 "$db" "VACUUM;" 2>/dev/null || true
        fi
    done
    print_status "OK" "SQLite databases vacuumed"
    
    # Rotate logs
    echo "  Rotating logs..."
    if [ -f "${LOG_DIR}/aiworker.log" ]; then
        # Keep last 10MB
        tail -c 10485760 "${LOG_DIR}/aiworker.log" > "${LOG_DIR}/aiworker.log.tmp" 2>/dev/null || true
        mv "${LOG_DIR}/aiworker.log.tmp" "${LOG_DIR}/aiworker.log" 2>/dev/null || true
    fi
    print_status "OK" "Logs rotated"
    
    # Clear Python cache
    echo "  Clearing Python cache..."
    find "$AIWORKER_BASE" -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
    find "$AIWORKER_BASE" -name "*.pyc" -delete 2>/dev/null || true
    print_status "OK" "Python cache cleared"
    
    # Sync filesystem
    sync
    
    echo
    echo -e "${GREEN}Cleanup complete!${NC}"
    echo
}

# Update command
cmd_update() {
    print_header "AIWorker Update"
    
    echo -e "${BOLD}Updating AIWorker...${NC}"
    echo
    
    # Check if we're in a git repo
    if [ ! -d "${AIWORKER_BASE}/.git" ]; then
        echo -e "${RED}Not a git repository, cannot update${NC}"
        return 1
    fi
    
    # Create pre-update backup
    echo "  Creating pre-update backup..."
    "${VENV_PATH}/bin/python" -c "
from aiworker.backup.manager import create_backup_manager
bm = create_backup_manager()
bm.backup_sqlite('manual')
" 2>/dev/null || print_status "WARN" "Backup creation failed, continuing..."
    
    # Pull latest code
    echo "  Pulling latest code..."
    cd "$AIWORKER_BASE"
    if git pull origin main 2>/dev/null; then
        print_status "OK" "Code updated"
    else
        print_status "WARN" "Git pull failed or already up to date"
    fi
    
    # Update dependencies
    echo "  Updating dependencies..."
    if "${VENV_PATH}/bin/pip" install -r requirements.txt -q 2>/dev/null; then
        print_status "OK" "Dependencies updated"
    else
        print_status "WARN" "Dependency update failed or not needed"
    fi
    
    # Run tests
    echo "  Running tests..."
    if "${VENV_PATH}/bin/python" -m pytest tests/integration/test_full_cycle.py -v --tb=short 2>/dev/null; then
        print_status "OK" "Tests passed"
    else
        print_status "WARN" "Some tests failed, review output above"
    fi
    
    # Graceful restart
    echo
    echo -e "${BOLD}Restarting AIWorker...${NC}"
    if systemctl reload aiworker 2>/dev/null; then
        print_status "OK" "AIWorker reloaded gracefully"
    elif systemctl restart aiworker 2>/dev/null; then
        print_status "OK" "AIWorker restarted"
    else
        print_status "FAIL" "Failed to restart AIWorker"
        return 1
    fi
    
    echo
    echo -e "${GREEN}Update complete!${NC}"
    echo
}

# Emergency stop command
cmd_emergency_stop() {
    print_header "AIWorker Emergency Stop"
    
    echo -e "${RED}${BOLD}WARNING: This will immediately stop AIWorker!${NC}"
    echo
    read -p "Are you sure? Type 'STOP' to confirm: " confirm
    
    if [ "$confirm" != "STOP" ]; then
        echo "Cancelled."
        return 0
    fi
    
    echo
    echo -e "${BOLD}Creating emergency backup...${NC}"
    "${VENV_PATH}/bin/python" -c "
from aiworker.backup.manager import create_backup_manager
bm = create_backup_manager()
bm.pre_shutdown_backup()
" 2>/dev/null || true
    
    echo -e "${BOLD}Stopping services...${NC}"
    systemctl stop aiworker 2>/dev/null || true
    systemctl stop aiworker-watchdog 2>/dev/null || true
    
    # Kill any remaining processes
    pkill -f "aiworker" 2>/dev/null || true
    
    echo
    echo -e "${GREEN}AIWorker stopped. State preserved in backup.${NC}"
    echo -e "To restart: ${CYAN}systemctl start aiworker${NC}"
    echo
}

# Verify command
cmd_verify() {
    print_header "AIWorker Component Verification"
    
    local all_ok=true
    
    # Check Ollama
    echo -e "${BOLD}Checking Ollama...${NC}"
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        print_status "OK" "Ollama is responding"
    else
        print_status "FAIL" "Ollama is not responding"
        all_ok=false
    fi
    echo
    
    # Check disk space
    echo -e "${BOLD}Checking disk space...${NC}"
    local disk_pct
    disk_pct=$(get_disk_usage)
    if [ "$disk_pct" -lt 90 ]; then
        print_status "OK" "Disk usage: ${disk_pct}%"
    else
        print_status "FAIL" "Disk usage critical: ${disk_pct}%"
        all_ok=false
    fi
    echo
    
    # Check memory
    echo -e "${BOLD}Checking memory...${NC}"
    local mem_pct
    mem_pct=$(get_memory_percent)
    if [ "$mem_pct" -lt 90 ]; then
        print_status "OK" "Memory usage: ${mem_pct}%"
    else
        print_status "WARN" "Memory usage high: ${mem_pct}%"
    fi
    echo
    
    # Check databases
    echo -e "${BOLD}Checking databases...${NC}"
    for db in checkpoints safety telemetry; do
        if [ -f "${DATA_DIR}/${db}.db" ]; then
            if sqlite3 "${DATA_DIR}/${db}.db" "PRAGMA integrity_check;" 2>/dev/null | grep -q "ok"; then
                print_status "OK" "${db}.db integrity verified"
            else
                print_status "FAIL" "${db}.db integrity check failed"
                all_ok=false
            fi
        else
            print_status "WARN" "${db}.db not found"
        fi
    done
    echo
    
    # Check Python environment
    echo -e "${BOLD}Checking Python environment...${NC}"
    if "${VENV_PATH}/bin/python" -c "import aiworker" 2>/dev/null; then
        print_status "OK" "AIWorker module imports successfully"
    else
        print_status "FAIL" "AIWorker module import failed"
        all_ok=false
    fi
    echo
    
    # Summary
    echo -e "${BOLD}Verification Summary:${NC}"
    if $all_ok; then
        echo -e "  ${GREEN}All critical components verified successfully${NC}"
    else
        echo -e "  ${RED}Some components failed verification${NC}"
        echo -e "  ${YELLOW}Review failures above and take corrective action${NC}"
    fi
    echo
}

# Main
main() {
    local cmd=${1:-status}
    
    case "$cmd" in
        status)
            cmd_status
            ;;
        logs)
            cmd_logs "${2:-all}" "${3:-50}"
            ;;
        metrics)
            cmd_metrics
            ;;
        cleanup)
            cmd_cleanup
            ;;
        update)
            cmd_update
            ;;
        emergency-stop)
            cmd_emergency_stop
            ;;
        verify)
            cmd_verify
            ;;
        help|--help|-h)
            echo "AIWorker Monitor Script"
            echo
            echo "Usage: $0 [command] [options]"
            echo
            echo "Commands:"
            echo "  status         - Quick health check"
            echo "  logs [filter] [lines] - Tail logs (filter: error|warning|info|all)"
            echo "  metrics        - Export telemetry to CSV"
            echo "  cleanup        - Purge old data, vacuum DB, rotate logs"
            echo "  update         - Pull latest code, run tests, restart"
            echo "  emergency-stop - Immediate halt with state preservation"
            echo "  verify         - Check all components"
            echo "  help           - Show this help"
            echo
            echo "Examples:"
            echo "  $0 status"
            echo "  $0 logs error 100"
            echo "  $0 verify"
            ;;
        *)
            echo -e "${RED}Unknown command: $cmd${NC}"
            echo "Run '$0 help' for usage information"
            exit 1
            ;;
    esac
}

main "$@"

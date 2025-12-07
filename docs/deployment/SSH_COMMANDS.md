# SSH Commands Reference

This document lists common SSH commands that can be run on the Lightsail instance.

## Connection

```bash
# Basic connection
ssh lightsail

# Or use full alias
ssh lightsail-visa-bulletin
```

## Common Operations

### Check Server Status
```bash
ssh lightsail "uptime && df -h /"
ssh lightsail "docker ps"
ssh lightsail "systemctl status docker"
```

### Project Directory Operations
```bash
# Check git status
ssh lightsail "cd /opt/visa_bulletin && git status"

# Pull latest changes
ssh lightsail "cd /opt/visa_bulletin && git pull"

# View logs
ssh lightsail "cd /opt/visa_bulletin && docker-compose logs -f --tail=50"

# Check application status
ssh lightsail "cd /opt/visa_bulletin && docker-compose ps"
```

### Docker Operations
```bash
# Start services
ssh lightsail "cd /opt/visa_bulletin && docker-compose up -d"

# Stop services
ssh lightsail "cd /opt/visa_bulletin && docker-compose down"

# Restart services
ssh lightsail "cd /opt/visa_bulletin && docker-compose restart"

# Rebuild and start
ssh lightsail "cd /opt/visa_bulletin && docker-compose up -d --build"

# View running containers
ssh lightsail "docker ps -a"

# View container logs
ssh lightsail "cd /opt/visa_bulletin && docker-compose logs web"
```

### Database Operations
```bash
# Run migrations
ssh lightsail "cd /opt/visa_bulletin && docker-compose exec web python manage.py migrate"

# Refresh data
ssh lightsail "cd /opt/visa_bulletin && docker-compose exec web python refresh_data.py --save-to-db"

# Check database
ssh lightsail "cd /opt/visa_bulletin && docker-compose exec web sqlite3 visa_bulletin.db '.tables'"
```

### File Operations
```bash
# Copy file to server
scp file.txt lightsail:/opt/visa_bulletin/

# Copy file from server
scp lightsail:/opt/visa_bulletin/file.txt ./

# Edit file on server (opens in local editor via SSH)
ssh lightsail "cd /opt/visa_bulletin && nano file.txt"
```

### System Operations
```bash
# Check disk usage
ssh lightsail "df -h"

# Check memory
ssh lightsail "free -h"

# Check running processes
ssh lightsail "ps aux | head -20"

# View system logs
ssh lightsail "sudo journalctl -u docker --tail=50"
```

### Nginx Operations
```bash
# Check Nginx status
ssh lightsail "sudo systemctl status nginx"

# Test Nginx config
ssh lightsail "sudo nginx -t"

# Reload Nginx
ssh lightsail "sudo systemctl reload nginx"

# View Nginx logs
ssh lightsail "sudo tail -f /var/log/nginx/access.log"
ssh lightsail "sudo tail -f /var/log/nginx/error.log"
```

## Multi-line Commands

For complex operations, use heredoc:

```bash
ssh lightsail << 'ENDSSH'
cd /opt/visa_bulletin
git pull
docker-compose down
docker-compose up -d --build
docker-compose logs -f
ENDSSH
```

## Examples

### Full Deployment
```bash
ssh lightsail << 'ENDSSH'
cd /opt/visa_bulletin
git pull origin main
docker-compose down
docker-compose up -d --build
docker-compose exec web python manage.py migrate
ENDSSH
```

### Quick Status Check
```bash
ssh lightsail "cd /opt/visa_bulletin && echo '=== Git Status ===' && git status --short && echo '' && echo '=== Docker Status ===' && docker-compose ps && echo '' && echo '=== Disk Usage ===' && df -h /"
```

### View Application Logs
```bash
ssh lightsail "cd /opt/visa_bulletin && docker-compose logs --tail=100 -f"
```

## Notes

- All commands run as `ubuntu` user
- Docker commands may need `sudo` for system-level operations
- Use `docker-compose exec` to run commands inside containers
- The project directory is `/opt/visa_bulletin`
- SSH config alias: `lightsail` or `lightsail-visa-bulletin`


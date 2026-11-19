#!/bin/bash
# ---------------------------------------------------------------------------
# userdata.sh - runs ONCE, as root, the first time each new EC2 server boots.
# The Auto Scaling Group launches servers by itself, so this script is what
# turns a blank server into a working web server with no human help.
# Written for Amazon Linux 2023.
# ---------------------------------------------------------------------------

# ===== EDIT THESE 5 VALUES BEFORE PUTTING THE SCRIPT IN THE LAUNCH TEMPLATE =====
REPO_URL="https://github.com/YOUR-USERNAME/highlyavailable-webapp-autoscaling.git"
DB_HOST="YOUR-RDS-ENDPOINT.us-east-1.rds.amazonaws.com"
DB_USER="admin"
DB_PASSWORD="YOUR-DB-PASSWORD"
DB_NAME="guestbook"
# =================================================================================

# Stop on the first error, and save everything this script prints to a log
# file so you can read it later if something goes wrong.
set -e
exec > /var/log/userdata.log 2>&1

# 1. Install the tools we need (git to download code, python to run it).
dnf update -y
dnf install -y git python3 python3-pip

# 2. Download the project code from GitHub (goes out through the NAT gateway).
git clone "$REPO_URL" /opt/webapp-src
APP_DIR=/opt/webapp-src/application

# 3. Install the Python packages the app needs.
pip3 install -r "$APP_DIR/requirements.txt"

# 4. Save the database settings in a protected file only root can read.
cat > /etc/webapp.env <<EOF
DB_HOST=$DB_HOST
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_NAME=$DB_NAME
EOF
chmod 600 /etc/webapp.env

# 5. Create the database table (safe to run on every server: it only
#    creates the table if it is missing).
cd "$APP_DIR"
set -a; . /etc/webapp.env; set +a
python3 -c "import app; app.init_db()" || echo "init_db failed, check DB settings"

# 6. Make the app a systemd service so it starts now, starts again after a
#    reboot, and restarts itself if it crashes.
cat > /etc/systemd/system/webapp.service <<EOF
[Unit]
Description=Guestbook web app (gunicorn)
After=network.target

[Service]
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/webapp.env
ExecStart=/usr/local/bin/gunicorn --workers 2 --bind 0.0.0.0:5000 app:app
Restart=always

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable --now webapp

echo "userdata finished OK"

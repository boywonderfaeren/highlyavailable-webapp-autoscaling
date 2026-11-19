"""
Project 4: Highly Available Web App with Auto Scaling
A small Flask guestbook. Visitors leave a message, it is saved in the RDS
MySQL database, and every page shows WHICH web server answered, so you can
see the load balancer spreading visitors across servers and zones.
"""
import os
import time
import urllib.request

import pymysql
from flask import Flask, jsonify, redirect, render_template, request, url_for

app = Flask(__name__)

# Database settings come from environment variables (set by userdata.sh),
# so no passwords are written inside the code.
DB_HOST = os.environ.get("DB_HOST", "localhost")
DB_USER = os.environ.get("DB_USER", "admin")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "guestbook")


def get_connection():
    """Open a new connection to the database."""
    return pymysql.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        connect_timeout=5,
        cursorclass=pymysql.cursors.DictCursor,
    )


def init_db():
    """Create the messages table if it does not exist yet."""
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(80) NOT NULL,
                    message VARCHAR(500) NOT NULL,
                    served_by VARCHAR(40),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
        conn.commit()
    finally:
        conn.close()


def imds(path):
    """
    Ask the EC2 'instance metadata service' about this server.
    It is a special address (169.254.169.254) that only works from
    inside an EC2 instance. Version 2 needs a token first.
    """
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "300"},
        )
        token = urllib.request.urlopen(token_req, timeout=2).read().decode()
        req = urllib.request.Request(
            "http://169.254.169.254/latest/meta-data/" + path,
            headers={"X-aws-ec2-metadata-token": token},
        )
        return urllib.request.urlopen(req, timeout=2).read().decode()
    except Exception:
        return "unknown"


INSTANCE_ID = imds("instance-id")
AZ = imds("placement/availability-zone")


@app.route("/health")
def health():
    """
    Used by the load balancer's health check. It deliberately does NOT
    touch the database, so a short database failover does not make the
    load balancer think every web server is dead.
    """
    return jsonify(status="ok", instance=INSTANCE_ID, az=AZ), 200


@app.route("/", methods=["GET"])
def index():
    messages, db_ok, error = [], True, None
    try:
        conn = get_connection()
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT name, message, served_by, created_at "
                    "FROM messages ORDER BY id DESC LIMIT 20"
                )
                messages = cur.fetchall()
        finally:
            conn.close()
    except Exception as exc:  # database unreachable
        db_ok, error = False, str(exc)
    return render_template(
        "index.html",
        messages=messages,
        instance_id=INSTANCE_ID,
        az=AZ,
        db_ok=db_ok,
        error=error,
    )


@app.route("/post", methods=["POST"])
def post():
    name = request.form.get("name", "").strip()[:80]
    message = request.form.get("message", "").strip()[:500]
    if name and message:
        try:
            conn = get_connection()
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO messages (name, message, served_by) "
                        "VALUES (%s, %s, %s)",
                        (name, message, INSTANCE_ID),
                    )
                conn.commit()
            finally:
                conn.close()
        except Exception:
            pass  # the page will show the database warning on reload
    return redirect(url_for("index"))


@app.route("/load")
def load():
    """
    Burns CPU for a few seconds. Used ONLY for the auto scaling test:
    open /load many times and the group's average CPU rises, which makes
    the Auto Scaling Group launch more servers.
    """
    end = time.time() + 20
    while time.time() < end:
        sum(i * i for i in range(10000))
    return jsonify(status="done", instance=INSTANCE_ID)


if __name__ == "__main__":
    # Only for testing on your own computer. On AWS, gunicorn runs the app.
    try:
        init_db()
    except Exception as exc:
        print("Database not ready:", exc)
    app.run(host="0.0.0.0", port=5000)

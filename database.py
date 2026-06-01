# database.py - SQLite database for persistent storage
import sqlite3
from datetime import datetime
import os

DB_PATH = "distance_monitor.db"

def init_database():
    """Create tables if they don't exist"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create readings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            distance REAL NOT NULL,
            status TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            source TEXT DEFAULT 'distance_monitor'
        )
    ''')
    
    # Create alerts table for tracking notifications
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS alerts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            alert_type TEXT NOT NULL,
            distance REAL NOT NULL,
            message TEXT,
            timestamp TEXT NOT NULL,
            sent_to_phone BOOLEAN DEFAULT 0
        )
    ''')
    
    # Create daily_stats table for analytics
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS daily_stats (
            date TEXT PRIMARY KEY,
            total_readings INTEGER,
            danger_count INTEGER,
            warning_count INTEGER,
            avg_distance REAL,
            min_distance REAL,
            max_distance REAL
        )
    ''')
    
    conn.commit()
    conn.close()
    print("✅ Database initialized")

def save_reading(distance, status, source="distance_monitor"):
    """Save a single reading to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    timestamp = datetime.now().isoformat()
    
    cursor.execute('''
        INSERT INTO readings (distance, status, timestamp, source)
        VALUES (?, ?, ?, ?)
    ''', (distance, status, timestamp, source))
    
    conn.commit()
    reading_id = cursor.lastrowid
    conn.close()
    
    return reading_id

def save_alert(alert_type, distance, message, sent_to_phone=False):
    """Save alert to database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    timestamp = datetime.now().isoformat()
    
    cursor.execute('''
        INSERT INTO alerts (alert_type, distance, message, timestamp, sent_to_phone)
        VALUES (?, ?, ?, ?, ?)
    ''', (alert_type, distance, message, timestamp, sent_to_phone))
    
    conn.commit()
    conn.close()

def get_recent_readings(limit=100):
    """Get most recent readings"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT distance, status, timestamp FROM readings
        ORDER BY timestamp DESC LIMIT ?
    ''', (limit,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{"distance": r[0], "status": r[1], "timestamp": r[2]} for r in rows]

def get_readings_since(start_time):
    """Get readings after specific time"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT distance, status, timestamp FROM readings
        WHERE timestamp > ?
        ORDER BY timestamp ASC
    ''', (start_time,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{"distance": r[0], "status": r[1], "timestamp": r[2]} for r in rows]

def get_statistics_from_db():
    """Calculate statistics from database"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Get overall stats
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            MIN(distance) as min_dist,
            MAX(distance) as max_dist,
            AVG(distance) as avg_dist,
            SUM(CASE WHEN status = 'DANGER' THEN 1 ELSE 0 END) as danger_count,
            SUM(CASE WHEN status = 'WARNING' THEN 1 ELSE 0 END) as warning_count,
            SUM(CASE WHEN status = 'SAFE' THEN 1 ELSE 0 END) as safe_count
        FROM readings
    ''')
    
    stats = cursor.fetchone()
    
    # Get last 24 hours stats
    cursor.execute('''
        SELECT COUNT(*) FROM readings
        WHERE timestamp > datetime('now', '-1 day')
    ''')
    last_24h = cursor.fetchone()[0]
    
    conn.close()
    
    return {
        "total_readings": stats[0] or 0,
        "min_distance": round(stats[1], 2) if stats[1] else 0,
        "max_distance": round(stats[2], 2) if stats[2] else 0,
        "avg_distance": round(stats[3], 2) if stats[3] else 0,
        "danger_count": stats[4] or 0,
        "warning_count": stats[5] or 0,
        "safe_count": stats[6] or 0,
        "last_24h_readings": last_24h or 0
    }

def update_daily_stats():
    """Aggregate daily statistics"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    today = datetime.now().strftime("%Y-%m-%d")
    
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status = 'DANGER' THEN 1 ELSE 0 END) as danger,
            SUM(CASE WHEN status = 'WARNING' THEN 1 ELSE 0 END) as warning,
            AVG(distance) as avg_dist,
            MIN(distance) as min_dist,
            MAX(distance) as max_dist
        FROM readings
        WHERE date(timestamp) = date(?)
    ''', (today,))
    
    row = cursor.fetchone()
    
    if row[0] > 0:  # Only save if we have readings
        cursor.execute('''
            INSERT OR REPLACE INTO daily_stats (date, total_readings, danger_count, warning_count, avg_distance, min_distance, max_distance)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (today, row[0], row[1] or 0, row[2] or 0, round(row[3], 2) if row[3] else 0, round(row[4], 2) if row[4] else 0, round(row[5], 2) if row[5] else 0))
    
    conn.commit()
    conn.close()

def get_daily_stats(days=7):
    """Get last N days of statistics"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT date, total_readings, danger_count, warning_count, avg_distance
        FROM daily_stats
        ORDER BY date DESC LIMIT ?
    ''', (days,))
    
    rows = cursor.fetchall()
    conn.close()
    
    return [{"date": r[0], "readings": r[1], "danger": r[2], "warning": r[3], "avg_distance": r[4]} for r in rows]

def clear_old_data(days_to_keep=30):
    """Delete readings older than specified days"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        DELETE FROM readings
        WHERE timestamp < datetime('now', '-' || ? || ' days')
    ''', (days_to_keep,))
    
    deleted = cursor.rowcount
    conn.commit()
    conn.close()
    
    print(f"🗑️  Deleted {deleted} old readings")
    return deleted
    
    # ============================================
# DATA EXPORT FUNCTIONS (Add to database.py)
# ============================================

import csv
import json
from io import StringIO

def export_to_csv(days=7):
    """
    Export readings from last N days to CSV format.
    
    CSV (Comma-Separated Values) can be opened in Excel, Google Sheets, etc.
    
    Parameters:
    days: Number of days to export (default 7, max 30)
    
    Returns:
    String containing CSV data
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT distance, status, timestamp FROM readings
        WHERE timestamp > datetime('now', '-' || ? || ' days')
        ORDER BY timestamp DESC
    ''', (days,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Create CSV in memory (no file on disk)
    output = StringIO()
    writer = csv.writer(output)
    
    # Write header row
    writer.writerow(['Distance (cm)', 'Status', 'Timestamp'])
    
    # Write data rows
    writer.writerows(rows)
    
    return output.getvalue()


def export_to_json(days=7):
    """
    Export readings from last N days to JSON format.
    
    JSON is ideal for programming, APIs, and data processing.
    
    Parameters:
    days: Number of days to export (default 7, max 30)
    
    Returns:
    JSON string
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT distance, status, timestamp FROM readings
        WHERE timestamp > datetime('now', '-' || ? || ' days')
        ORDER BY timestamp DESC
    ''', (days,))
    
    rows = cursor.fetchall()
    conn.close()
    
    # Convert to list of dictionaries
    data = []
    for row in rows:
        data.append({
            "distance_cm": row[0],
            "status": row[1],
            "timestamp": row[2]
        })
    
    return json.dumps(data, indent=2)


def export_summary(days=7):
    """
    Export a summary report of readings.
    
    Returns a dictionary with statistics for the export period.
    """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT 
            COUNT(*) as total,
            MIN(distance) as min_dist,
            MAX(distance) as max_dist,
            AVG(distance) as avg_dist,
            SUM(CASE WHEN status = 'DANGER' THEN 1 ELSE 0 END) as danger_count,
            SUM(CASE WHEN status = 'WARNING' THEN 1 ELSE 0 END) as warning_count
        FROM readings
        WHERE timestamp > datetime('now', '-' || ? || ' days')
    ''', (days,))
    
    row = cursor.fetchone()
    conn.close()
    
    return {
        "period_days": days,
        "export_date": datetime.now().isoformat(),
        "total_readings": row[0] or 0,
        "min_distance_cm": round(row[1], 2) if row[1] else 0,
        "max_distance_cm": round(row[2], 2) if row[2] else 0,
        "avg_distance_cm": round(row[3], 2) if row[3] else 0,
        "danger_alerts": row[4] or 0,
        "warning_alerts": row[5] or 0
    }
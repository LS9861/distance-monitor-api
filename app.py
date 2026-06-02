# app.py - Complete Production Distance Monitor API
from flask import Flask, request, jsonify, Response
from flask_cors import CORS
from datetime import datetime
from openai import OpenAI
import os
import time
import json
import sqlite3

# ========== IMPORTS ==========
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from auth import require_api_key

# Import modules
from config import Config, create_env_template
from database import (
    init_database, save_reading, get_recent_readings, 
    get_statistics_from_db, save_alert, update_daily_stats,
    clear_old_data, get_daily_stats, export_to_csv, export_to_json, export_summary
)
from logger import setup_logger, log_reading, log_alert, log_api_request

# Create .env template if it doesn't exist
create_env_template()

# Load configuration
config = Config()

# Setup logger
logger = setup_logger('distance_api', config.LOG_FILE, config.LOG_LEVEL)

# Initialize Flask
app = Flask(__name__)

# Initialize rate limiter
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per hour", "20 per minute"],
    storage_uri="memory://"
)

CORS(app)

# Initialize DeepSeek client (if API key is set)
if config.DEEPSEEK_API_KEY:
    deepseek_client = OpenAI(
        api_key=config.DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1"
    )
    logger.info("DeepSeek AI client initialized")
else:
    deepseek_client = None
    logger.warning("DeepSeek API key not set - AI features disabled")

# Initialize database
init_database()
logger.info("Database initialized")

# ============================================
# API ENDPOINTS
# ============================================

@app.route('/health', methods=['GET'])
def health():
    """Check API status"""
    start_time = time.time()
    stats = get_statistics_from_db()
    
    response = {
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "database_size": stats['total_readings'],
        "ai_available": deepseek_client is not None,
        "version": "2.0.0"
    }
    
    duration_ms = (time.time() - start_time) * 1000
    log_api_request(logger, '/health', 'GET', 200, duration_ms)
    
    return jsonify(response)


@app.route('/distance', methods=['POST'])
@limiter.limit("60 per minute")
@require_api_key
def add_distance():
    """Receive distance data from Arduino"""
    start_time = time.time()
    
    data = request.json
    
    if 'distance' not in data:
        return jsonify({"error": "Missing 'distance' field"}), 400
    
    distance = data.get('distance')
    status = data.get('status', 'UNKNOWN')
    source = data.get('source', 'distance_monitor')
    
    reading_id = save_reading(distance, status, source)
    log_reading(logger, distance, status)
    update_daily_stats()
    
    stats = get_statistics_from_db()
    if stats['total_readings'] % 100 == 0:
        deleted = clear_old_data(config.DATA_RETENTION_DAYS)
        if deleted > 0:
            logger.info(f"Auto-cleanup: deleted {deleted} old readings")
    
    duration_ms = (time.time() - start_time) * 1000
    log_api_request(logger, '/distance', 'POST', 200, duration_ms)
    
    return jsonify({
        "status": "success",
        "reading_id": reading_id,
        "total": stats['total_readings'] + 1
    })


@app.route('/readings', methods=['GET'])
@require_api_key
def get_readings():
    """Get recent readings"""
    start_time = time.time()
    
    limit = request.args.get('limit', default=100, type=int)
    limit = min(limit, 1000)
    
    readings = get_recent_readings(limit)
    
    duration_ms = (time.time() - start_time) * 1000
    log_api_request(logger, '/readings', 'GET', 200, duration_ms)
    
    return jsonify({
        "count": len(readings),
        "readings": readings
    })


@app.route('/stats', methods=['GET'])
@require_api_key
def get_stats():
    """Get statistics"""
    start_time = time.time()
    
    stats = get_statistics_from_db()
    daily = get_daily_stats(7)
    
    duration_ms = (time.time() - start_time) * 1000
    log_api_request(logger, '/stats', 'GET', 200, duration_ms)
    
    return jsonify({
        **stats,
        "daily_summary": daily,
        "alerts_cooldown": config.ALERT_COOLDOWN_SECONDS,
        "danger_threshold": config.DANGER_THRESHOLD,
        "warning_threshold": config.WARNING_THRESHOLD
    })


@app.route('/alerts', methods=['GET'])
@require_api_key
def get_alerts():
    """Get alert history"""
    conn = sqlite3.connect(config.DB_PATH)
    cursor = conn.cursor()
    
    cursor.execute('''
        SELECT alert_type, distance, message, timestamp, sent_to_phone
        FROM alerts
        ORDER BY timestamp DESC
        LIMIT 50
    ''')
    
    rows = cursor.fetchall()
    conn.close()
    
    alerts = [{
        "type": r[0],
        "distance": r[1],
        "message": r[2],
        "timestamp": r[3],
        "sent_to_phone": r[4]
    } for r in rows]
    
    return jsonify({
        "count": len(alerts),
        "alerts": alerts
    })


@app.route('/analyze', methods=['GET'])
@limiter.limit("10 per minute")
@require_api_key
def get_ai_analysis():
    """Get AI analysis from DeepSeek"""
    start_time = time.time()
    
    if not deepseek_client:
        return jsonify({"error": "AI not configured - set DEEPSEEK_API_KEY"}), 503
    
    readings = get_recent_readings(50)
    
    if len(readings) < 3:
        return jsonify({
            "error": f"Need at least 3 readings. Currently have {len(readings)}",
            "message": "Move your hand near the sensor to collect data"
        })
    
    distances = [r['distance'] for r in readings]
    statuses = [r['status'] for r in readings]
    
    prompt = f"""
    Analyze these distance sensor readings (in cm):
    Last {len(distances)} distances: {distances}
    Statuses: {statuses}
    Danger threshold: {config.DANGER_THRESHOLD}cm
    Warning threshold: {config.WARNING_THRESHOLD}cm
    
    Answer these 3 questions concisely (one sentence each):
    1. Is something getting closer? (YES/NO/MAYBE)
    2. What is the risk level? (LOW/MEDIUM/HIGH)
    3. What is your recommendation?
    
    Keep response short and useful.
    """
    
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[
                {"role": "system", "content": "You are a safety monitoring AI. Be very concise."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.3
        )
        
        analysis = response.choices[0].message.content
        logger.info(f"AI analysis completed on {len(readings)} readings")
        
        duration_ms = (time.time() - start_time) * 1000
        
        return jsonify({
            "analysis": analysis,
            "readings_analyzed": len(readings),
            "danger_threshold": config.DANGER_THRESHOLD,
            "warning_threshold": config.WARNING_THRESHOLD,
            "analysis_time_ms": round(duration_ms, 2)
        })
        
    except Exception as e:
        logger.error(f"AI analysis failed: {e}")
        return jsonify({"error": str(e)}), 500


@app.route('/export/csv', methods=['GET'])
@require_api_key
def export_csv():
    """Export readings as CSV"""
    days = request.args.get('days', default=7, type=int)
    days = min(days, 30)
    
    csv_data = export_to_csv(days)
    
    return Response(
        csv_data,
        mimetype='text/csv',
        headers={
            'Content-Disposition': f'attachment; filename=distance_readings_{days}days.csv',
            'Content-Type': 'text/csv'
        }
    )


@app.route('/export/json', methods=['GET'])
@require_api_key
def export_json():
    """Export readings as JSON"""
    days = request.args.get('days', default=7, type=int)
    days = min(days, 30)
    
    json_data = export_to_json(days)
    
    return jsonify({
        "export_date": datetime.now().isoformat(),
        "days_exported": days,
        "data": json.loads(json_data)
    })


@app.route('/export/summary', methods=['GET'])
@require_api_key
def export_summary():
    """Get export summary"""
    days = request.args.get('days', default=7, type=int)
    days = min(days, 30)
    
    summary = export_summary(days)
    
    return jsonify(summary)


@app.route('/dashboard', methods=['GET'])
def dashboard():
    """Professional dashboard with waveform chart"""
    
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Distance Monitor - Pro Dashboard</title>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js"></script>
        <style>
            * { margin: 0; padding: 0; box-sizing: border-box; }
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
                min-height: 100vh;
                padding: 20px;
            }
            .container { max-width: 1400px; margin: 0 auto; }
            .header {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                border-radius: 20px;
                padding: 25px 30px;
                margin-bottom: 25px;
                color: white;
                box-shadow: 0 10px 30px rgba(0,0,0,0.3);
            }
            .header h1 { font-size: 28px; margin-bottom: 8px; }
            .header p { opacity: 0.9; font-size: 14px; }
            .status-badge {
                display: inline-block;
                padding: 5px 12px;
                border-radius: 20px;
                font-size: 12px;
                font-weight: bold;
                margin-top: 10px;
            }
            .status-online { background: #10b981; color: white; }
            .stats-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
                gap: 20px;
                margin-bottom: 25px;
            }
            .stat-card {
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                border-radius: 15px;
                padding: 20px;
                text-align: center;
                color: white;
                border: 1px solid rgba(255,255,255,0.2);
                transition: transform 0.3s;
            }
            .stat-card:hover { transform: translateY(-5px); }
            .stat-value { font-size: 32px; font-weight: bold; margin-bottom: 5px; }
            .stat-label { font-size: 14px; opacity: 0.8; }
            .danger { color: #ef4444; }
            .warning { color: #f59e0b; }
            .safe { color: #10b981; }
            .chart-container {
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                border-radius: 20px;
                padding: 20px;
                margin-bottom: 25px;
                border: 1px solid rgba(255,255,255,0.2);
            }
            .chart-title {
                color: white;
                font-size: 18px;
                margin-bottom: 15px;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            canvas { max-height: 400px; width: 100%; }
            .alerts-section {
                background: rgba(255,255,255,0.1);
                backdrop-filter: blur(10px);
                border-radius: 20px;
                padding: 20px;
                border: 1px solid rgba(255,255,255,0.2);
            }
            .alert-item {
                background: rgba(0,0,0,0.3);
                border-radius: 10px;
                padding: 12px;
                margin-bottom: 10px;
                display: flex;
                justify-content: space-between;
                align-items: center;
            }
            .alert-danger { border-left: 4px solid #ef4444; }
            .alert-warning { border-left: 4px solid #f59e0b; }
            .alert-time { font-size: 12px; color: #888; }
            .loading { text-align: center; color: white; padding: 40px; }
            @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
            .live-indicator {
                display: inline-block;
                width: 10px;
                height: 10px;
                background: #10b981;
                border-radius: 50%;
                animation: pulse 1.5s infinite;
                margin-left: 10px;
            }
            button {
                background: #667eea;
                border: none;
                padding: 8px 20px;
                border-radius: 20px;
                color: white;
                cursor: pointer;
                font-size: 14px;
            }
            button:hover { background: #5a67d8; }
            @media (max-width: 768px) {
                .stats-grid { grid-template-columns: repeat(2, 1fr); gap: 10px; }
                .stat-value { font-size: 24px; }
                .header h1 { font-size: 22px; }
            }
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>📡 Distance Monitor Pro <span class="live-indicator"></span></h1>
                <p>Real-time distance monitoring with waveform visualization | Cloud-powered by Render</p>
                <div class="status-badge status-online">🟢 LIVE</div>
            </div>
            
            <div class="stats-grid" id="stats">
                <div class="stat-card"><div class="stat-value" id="total">--</div><div class="stat-label">Total Readings</div></div>
                <div class="stat-card"><div class="stat-value danger" id="danger">--</div><div class="stat-label">Danger Alerts</div></div>
                <div class="stat-card"><div class="stat-value warning" id="warning">--</div><div class="stat-label">Warning Alerts</div></div>
                <div class="stat-card"><div class="stat-value" id="avg">--</div><div class="stat-label">Average Distance</div></div>
                <div class="stat-card"><div class="stat-value" id="min">--</div><div class="stat-label">Closest (cm)</div></div>
                <div class="stat-card"><div class="stat-value" id="last24">--</div><div class="stat-label">Last 24 Hours</div></div>
            </div>
            
            <div class="chart-container">
                <div class="chart-title">📈 Distance Waveform <span style="font-size:12px;">(Last 50 readings)</span></div>
                <canvas id="distanceChart"></canvas>
            </div>
            
            <div class="chart-container">
                <div class="chart-title">
                    🤖 AI Safety Analysis
                    <button onclick="runAIAnalysis()">Analyze Now</button>
                </div>
                <div id="ai-result" style="color:white; padding:15px; background:rgba(0,0,0,0.3); border-radius:10px;">
                    Click "Analyze Now" for AI insights
                </div>
            </div>
            
            <div class="alerts-section">
                <div class="chart-title">🔔 Recent Alerts</div>
                <div id="alerts-list"><div class="loading">Loading alerts...</div></div>
            </div>
        </div>
        
        <script>
            let chart;
            const API_KEY = 'KyaNdPknHcxKGQRosNoOObG0XBZBCMupv_60vlvxYSY';
            
            async function fetchData() {
                try {
                    const response = await fetch(`/stats?api_key=${API_KEY}`);
                    const data = await response.json();
                    document.getElementById('total').innerHTML = data.total_readings || 0;
                    document.getElementById('danger').innerHTML = data.danger_count || 0;
                    document.getElementById('warning').innerHTML = data.warning_count || 0;
                    document.getElementById('avg').innerHTML = (data.avg_distance || 0) + ' cm';
                    document.getElementById('min').innerHTML = (data.min_distance || 0) + ' cm';
                    document.getElementById('last24').innerHTML = data.last_24h_readings || 0;
                    return data;
                } catch(e) { console.error('Stats error:', e); return null; }
            }
            
            async function fetchReadings() {
                try {
                    const response = await fetch(`/readings?api_key=${API_KEY}&limit=50`);
                    const data = await response.json();
                    return data.readings || [];
                } catch(e) { console.error('Readings error:', e); return []; }
            }
            
            async function fetchAlerts() {
                try {
                    const response = await fetch(`/alerts?api_key=${API_KEY}`);
                    const data = await response.json();
                    return data.alerts || [];
                } catch(e) { console.error('Alerts error:', e); return []; }
            }
            
            function updateChart(readings) {
                if (!readings || readings.length === 0) return;
                const reversed = [...readings].reverse();
                const distances = reversed.map(r => r.distance);
                const timestamps = reversed.map(r => new Date(r.timestamp).toLocaleTimeString());
                const ctx = document.getElementById('distanceChart').getContext('2d');
                if (chart) chart.destroy();
                chart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: timestamps,
                        datasets: [
                            { label: 'Distance (cm)', data: distances, borderColor: '#667eea', backgroundColor: 'rgba(102,126,234,0.1)', borderWidth: 2, fill: true, tension: 0.3, pointRadius: 3 },
                            { label: 'Danger Zone (<20cm)', data: distances.map(d => d < 20 ? d : null), borderColor: '#ef4444', backgroundColor: 'rgba(239,68,68,0.2)', borderWidth: 2, pointRadius: 5, pointBackgroundColor: '#ef4444' },
                            { label: 'Warning Zone (<50cm)', data: distances.map(d => (d >= 20 && d < 50) ? d : null), borderColor: '#f59e0b', backgroundColor: 'rgba(245,158,11,0.2)', borderWidth: 2, pointRadius: 4 }
                        ]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: true,
                        plugins: { legend: { labels: { color: 'white' } }, tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ${ctx.raw} cm` } } },
                        scales: { y: { title: { display: true, text: 'Distance (cm)', color: 'white' }, grid: { color: 'rgba(255,255,255,0.1)' }, ticks: { color: 'white' } }, x: { title: { display: true, text: 'Time', color: 'white' }, grid: { color: 'rgba(255,255,255,0.1)' }, ticks: { color: 'white', maxRotation: 45 } } }
                    }
                });
            }
            
            function updateAlerts(alerts) {
                const container = document.getElementById('alerts-list');
                if (!alerts || alerts.length === 0) { container.innerHTML = '<div class="alert-item">✅ No recent alerts</div>'; return; }
                container.innerHTML = alerts.slice(0, 10).map(alert => `<div class="alert-item ${alert.type === 'DANGER' ? 'alert-danger' : 'alert-warning'}"><div><strong>${alert.type === 'DANGER' ? '🔴' : '🟡'} ${alert.type}</strong> <span style="margin-left:10px;">Distance: ${alert.distance} cm</span></div><div class="alert-time">${new Date(alert.timestamp).toLocaleTimeString()}</div></div>`).join('');
            }
            
            async function runAIAnalysis() {
                const aiDiv = document.getElementById('ai-result');
                aiDiv.innerHTML = '🤖 Analyzing distance patterns with DeepSeek AI...';
                try {
                    const response = await fetch(`/analyze?api_key=${API_KEY}`);
                    const data = await response.json();
                    if (data.error) aiDiv.innerHTML = `⚠️ ${data.error}`;
                    else aiDiv.innerHTML = `<div style="white-space: pre-wrap;">${data.analysis}</div><div style="margin-top:10px; font-size:12px; opacity:0.7;">📊 Analyzed ${data.readings_analyzed || 0} readings</div>`;
                } catch(e) { aiDiv.innerHTML = `❌ AI analysis failed: ${e.message}`; }
            }
            
            async function refreshAll() {
                await fetchData();
                const readings = await fetchReadings();
                const alerts = await fetchAlerts();
                if (readings.length > 0) updateChart(readings);
                updateAlerts(alerts);
            }
            
            refreshAll();
            setInterval(refreshAll, 10000);
        </script>
    </body>
    </html>
    '''


# ============================================
# RUN THE SERVER
# ============================================

if __name__ == '__main__':
    print("=" * 60)
    print("🚀 PRODUCTION DISTANCE MONITOR API")
    print("=" * 60)
    print(f"\n✅ Database: {config.DB_PATH}")
    print(f"✅ Log file: {config.LOG_FILE}")
    print(f"✅ AI Status: {'Enabled' if deepseek_client else 'Disabled'}")
    print(f"\n📋 Configuration:")
    print(f"   Danger threshold: {config.DANGER_THRESHOLD}cm")
    print(f"   Warning threshold: {config.WARNING_THRESHOLD}cm")
    print(f"   Alert cooldown: {config.ALERT_COOLDOWN_SECONDS}s")
    print(f"   Data retention: {config.DATA_RETENTION_DAYS} days")
    print(f"\n🌐 API running at: http://{config.API_HOST}:{config.API_PORT}")
    print(f"📊 Dashboard: http://{config.API_HOST}:{config.API_PORT}/dashboard")
    print("=" * 60)
    
    app.run(debug=config.DEBUG_MODE, host=config.API_HOST, port=config.API_PORT)
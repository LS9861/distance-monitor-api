# app.py - UPDATED with Database + Config + Logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
from openai import OpenAI
    # For production on Render
import os
# ========== SECTION 1: ADD THESE IMPORTS (at the top of app.py) ==========
# Add these lines with your other imports
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from auth import require_api_key
import time

# Import new modules
from config import Config, create_env_template
from database import (
    init_database, save_reading, get_recent_readings, 
    get_statistics_from_db, save_alert, update_daily_stats,
    clear_old_data, get_daily_stats
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
# ========== SECTION 2: ADD RATE LIMITER (after creating app) ==========
# Add this right after `app = Flask(__name__)`
# ========== SECTION 2: ADD RATE LIMITER (after creating app) ==========
# Initialize rate limiter with correct syntax for newer versions
limiter = Limiter(
    get_remote_address,  # First parameter is the key function
    app=app,             # Explicitly tell it which Flask app to use
    default_limits=["200 per hour", "20 per minute"],
    storage_uri="memory://"  # Store rate limits in memory (works on Windows)
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
# API ENDPOINTS (UPDATED)
# ============================================

@app.route('/health', methods=['GET'])
def health():
    """Check API status"""
    start_time = time.time()
    
    # Get database stats
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
@limiter.limit("60 per minute")  # ← ADD THIS LINE
@require_api_key                  # ← ADD THIS LINE
def add_distance():
    """Receive distance data with database storage"""
    start_time = time.time()
    
    data = request.json
    
    if 'distance' not in data:
        return jsonify({"error": "Missing 'distance' field"}), 400
    
    distance = data.get('distance')
    status = data.get('status', 'UNKNOWN')
    source = data.get('source', 'distance_monitor')
    
    # Save to database (not just memory!)
    reading_id = save_reading(distance, status, source)
    
    # Log the reading
    log_reading(logger, distance, status)
    
    # Update daily stats
    update_daily_stats()
    
    # Clean old data periodically (once every 100 readings)
    stats = get_statistics_from_db()
    if stats['total_readings'] % 100 == 0:
        deleted = clear_old_data(config.DATA_RETENTION_DAYS)
        if deleted > 0:
            logger.info(f"Auto-cleanup: deleted {deleted} old readings")
    
    duration_ms = (time.time() - start_time) * 1000
    log_api_request(logger, '/distance', 'POST', 200, duration_ms)
    
    return jsonify({
        "status": "success",
        "message": "Reading saved to database",
        "reading_id": reading_id,
        "total": stats['total_readings'] + 1
    })

@app.route('/readings', methods=['GET'])
@require_api_key                  # ← ADD THIS LINE
def get_readings():
    """Get recent readings from database"""
    start_time = time.time()
    
    limit = request.args.get('limit', default=100, type=int)
    limit = min(limit, 1000)  # Cap at 1000
    
    readings = get_recent_readings(limit)
    
    duration_ms = (time.time() - start_time) * 1000
    log_api_request(logger, '/readings', 'GET', 200, duration_ms)
    
    return jsonify({
        "count": len(readings),
        "readings": readings
    })

@app.route('/stats', methods=['GET'])
@require_api_key                  # ← ADD THIS LINE
def get_stats():
    """Get statistics from database"""
    start_time = time.time()
    
    stats = get_statistics_from_db()
    
    # Get daily stats for last 7 days
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
@require_api_key                  # ← ADD THIS LINE
def get_alerts():
    """Get alert history"""
    import sqlite3
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
@limiter.limit("10 per minute")   # ← ADD THIS LINE (AI costs money!)
@require_api_key                  # ← ADD THIS LINE
def get_ai_analysis():
    """Get AI analysis from database data"""
    start_time = time.time()
    
    if not deepseek_client:
        return jsonify({"error": "AI not configured - set DEEPSEEK_API_KEY"}), 503
    
    # Get recent readings from database
    readings = get_recent_readings(50)
    
    if len(readings) < 3:
        return jsonify({
            "error": f"Need at least 3 readings. Currently have {len(readings)}",
            "message": "Move your hand near the sensor to collect data"
        })
    
    distances = [r['distance'] for r in readings]
    statuses = [r['status'] for r in readings]
    
    # Create prompt for AI
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
        
        # Save that AI was used
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

@app.route('/logs', methods=['GET'])
@require_api_key                  # ← ADD THIS LINE
def get_logs():
    """Get recent logs (admin only - no auth yet)"""
    from logger import get_log_summary
    
    lines = request.args.get('lines', default=50, type=int)
    lines = min(lines, 200)
    
    logs = get_log_summary(config.LOG_FILE, lines)
    
    return jsonify({
        "log_file": config.LOG_FILE,
        "lines": len(logs),
        "logs": logs
    })

@app.route('/dashboard', methods=['GET'])
def dashboard():
    """Enhanced dashboard with database stats"""
    stats = get_statistics_from_db()
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Distance Monitor - Production System</title>
        <style>
            body {{ font-family: Arial; margin: 20px; background: #f0f2f5; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .card {{ background: white; border-radius: 10px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 5px rgba(0,0,0,0.1); }}
            .stats-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }}
            .stat {{ background: #e9ecef; padding: 15px; border-radius: 8px; text-align: center; }}
            .stat-number {{ font-size: 28px; font-weight: bold; }}
            .danger {{ color: #dc3545; }}
            .warning {{ color: #ffc107; }}
            .safe {{ color: #28a745; }}
            button {{ background: #007bff; color: white; border: none; padding: 10px 20px; border-radius: 5px; cursor: pointer; margin: 5px; }}
            pre {{ background: #f8f9fa; padding: 15px; border-radius: 5px; overflow-x: auto; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="card">
                <h1>📡 Distance Monitor - Production System</h1>
                <p>Version 2.0 | Database: {stats['total_readings']} total readings</p>
                <p>⚙️ Config: Danger &lt; {config.DANGER_THRESHOLD}cm | Warning &lt; {config.WARNING_THRESHOLD}cm</p>
            </div>
            
            <div class="card">
                <h2>📊 Live Statistics</h2>
                <div class="stats-grid" id="stats"></div>
            </div>
            
            <div class="card">
                <h2>🤖 AI Analysis</h2>
                <button onclick="getAI()">Get AI Insights</button>
                <div id="ai-result"><pre>Click button to analyze</pre></div>
            </div>
        </div>
        
        <script>
            async function getStats() {{
                const response = await fetch('/stats?api_key=KyaNdPknHcxKGQRosNoOObG0XBZBCMupv_60vlvxYSY');
                const data = await response.json();
                document.getElementById('stats').innerHTML = `
                    <div class="stat"><div class="stat-number">${{data.total_readings}}</div><div>Total Readings</div></div>
                    <div class="stat"><div class="stat-number ${{data.danger_count > 0 ? 'danger' : ''}}">${{data.danger_count}}</div><div>Danger Alerts</div></div>
                    <div class="stat"><div class="stat-number ${{data.warning_count > 0 ? 'warning' : ''}}">${{data.warning_count}}</div><div>Warning Alerts</div></div>
                    <div class="stat"><div class="stat-number">${{data.avg_distance}} cm</div><div>Average Distance</div></div>
                    <div class="stat"><div class="stat-number">${{data.last_24h_readings}}</div><div>Last 24 Hours</div></div>
                `;
            }}
            
            async function getAI() {{
                document.getElementById('ai-result').innerHTML = '<pre>🤖 Analyzing...</pre>';
                const response = await fetch('/analyze?api_key=KyaNdPknHcxKGQRosNoOObG0XBZBCMupv_60vlvxYSY');
                const data = await response.json();
                document.getElementById('ai-result').innerHTML = `<pre>${{JSON.stringify(data, null, 2)}}</pre>`;
            }}
            
            getStats();
            setInterval(getStats, 5000);
        </script>
    </body>
    </html>
    '''

# ============================================
# RUN THE SERVER
# ============================================

# ============================================
# DATA EXPORT ENDPOINTS (Add to app.py)
# ============================================

@app.route('/export/csv', methods=['GET'])
@require_api_key
def export_csv():
    """
    Download readings as CSV file.
    
    Usage: GET /export/csv?days=7
    Query parameter 'days' = number of days to export (default 7, max 30)
    """
    from database import export_to_csv
    
    # Get days parameter (default 7, max 30)
    days = request.args.get('days', default=7, type=int)
    days = min(days, 30)  # Limit to 30 days max
    
    # Get the CSV data
    csv_data = export_to_csv(days)
    
    # Send as downloadable file
    from flask import Response
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
    """
    Download readings as JSON file.
    
    Usage: GET /export/json?days=7
    Query parameter 'days' = number of days to export (default 7, max 30)
    """
    from database import export_to_json
    
    # Get days parameter
    days = request.args.get('days', default=7, type=int)
    days = min(days, 30)
    
    # Get the JSON data
    json_data = export_to_json(days)
    
    return jsonify({
        "export_date": datetime.now().isoformat(),
        "days_exported": days,
        "data": json.loads(json_data)
    })


@app.route('/export/summary', methods=['GET'])
@require_api_key
def export_summary():
    """
    Get a summary report of readings.
    
    Usage: GET /export/summary?days=7
    Returns statistics without downloading full data.
    """
    from database import export_summary
    
    days = request.args.get('days', default=7, type=int)
    days = min(days, 30)
    
    summary = export_summary(days)
    
    return jsonify(summary)
    
    

# Get port from environment variable (Render sets this automatically)
port = int(os.environ.get('PORT', 5000))

# Then change the last line from:
# app.run(debug=config.DEBUG_MODE, host=config.API_HOST, port=config.API_PORT)
# To:
app.run(debug=False, host='0.0.0.0', port=port)

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

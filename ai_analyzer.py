# ai_analyzer.py - AI analysis functions using DeepSeek API
import os
from openai import OpenAI
from datetime import datetime
from dotenv import load_dotenv
# ============================================
# LOAD CONFIGURATION FROM .env
# ============================================

# Load environment variables
load_dotenv()

# Get DeepSeek API Key from .env (NOT hardcoded!)
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')

# Check if key is present
if not DEEPSEEK_API_KEY:
    print("⚠️ WARNING: DEEPSEEK_API_KEY not found in .env file")
    print("   AI features will not work!")
else:
    print(f"✅ Loaded DeepSeek API key (length: {len(DEEPSEEK_API_KEY)})")

# Initialize DeepSeek client (only if key exists)
if DEEPSEEK_API_KEY:
    deepseek_client = OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url="https://api.deepseek.com/v1"
    )
else:
    deepseek_client = None

# ============================================
# AI ANALYSIS FUNCTIONS
# ============================================

def analyze_distance_patterns(readings):
    """
    Analyze distance readings using DeepSeek AI
    
    Parameters:
    readings: List of reading dictionaries with 'distance' and 'status' keys
    
    Returns:
    String containing AI analysis
    """
    
    if not readings:
        return "No data to analyze. Move something near the sensor!"
    
    if len(readings) < 3:
        return f"Need more data. Only have {len(readings)} readings. Move your hand near the sensor a few times."
    
    # Get last 20 readings
    recent = readings[-20:]
    distances = [r['distance'] for r in recent]
    statuses = [r['status'] for r in recent]
    
    # Count alerts
    danger_count = statuses.count("DANGER")
    warning_count = statuses.count("WARNING")
    
    # Calculate trend
    if len(distances) >= 5:
        recent_avg = sum(distances[-5:]) / 5
        older_avg = sum(distances[:5]) / 5
        trend = recent_avg - older_avg
        trend_direction = "getting closer" if trend < 0 else "moving away" if trend > 0 else "stable"
    else:
        trend = 0
        trend_direction = "insufficient data"
    
    # Create prompt for AI
    prompt = f"""
    Analyze these distance sensor readings (in cm):
    Last 20 distances: {distances}
    Statuses: {statuses}
    Trend: {trend_direction} (change of {trend:.1f}cm)
    Alerts: {danger_count} danger, {warning_count} warning
    
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
                {"role": "system", "content": "You are a safety monitoring AI. Be very concise. Answer in 3 short sentences."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.3
        )
        
        analysis = response.choices[0].message.content
        
        # Add simple statistics to the analysis
        full_response = f"""
📊 DATA SUMMARY:
- Readings analyzed: {len(recent)}
- Average distance: {sum(distances)/len(distances):.1f}cm
- Trend: {trend_direction} ({trend:+.1f}cm change)
- Danger alerts: {danger_count}
- Warning alerts: {warning_count}

🤖 AI ANALYSIS:
{analysis}
"""
        return full_response
        
    except Exception as e:
        return f"❌ AI Error: {str(e)}\n\nCheck your DeepSeek API key and internet connection."


def get_simple_trend(readings):
    """
    Calculate simple trend without AI (faster fallback)
    
    Returns:
    Dictionary with trend information
    """
    
    if len(readings) < 3:
        return {
            "trend": "insufficient_data",
            "change_cm": 0,
            "risk": "unknown"
        }
    
    distances = [r['distance'] for r in readings[-10:]]
    
    if len(distances) >= 5:
        recent_avg = sum(distances[-3:]) / 3
        older_avg = sum(distances[:3]) / 3
        change = recent_avg - older_avg
    else:
        change = distances[-1] - distances[0]
    
    # Determine risk based on trend
    if change < -10:  # Getting closer rapidly
        risk = "HIGH"
        trend = "getting closer quickly"
    elif change < -3:  # Getting closer slowly
        risk = "MEDIUM"
        trend = "getting closer"
    elif change > 10:  # Moving away rapidly
        risk = "LOW"
        trend = "moving away quickly"
    elif change > 3:   # Moving away slowly
        risk = "LOW"
        trend = "moving away"
    else:
        risk = "LOW"
        trend = "stable"
    
    return {
        "trend": trend,
        "change_cm": round(change, 2),
        "risk": risk,
        "current_distance": distances[-1] if distances else 0
    }


def check_health():
    """Check if DeepSeek API is accessible"""
    try:
        response = deepseek_client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "Say OK"}],
            max_tokens=5
        )
        return {"status": "healthy", "message": "DeepSeek API is working"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
# config.py - Centralized configuration management
import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    """Application configuration"""
    
    # API Configuration
    API_HOST = os.getenv('API_HOST', '0.0.0.0')
    API_PORT = int(os.getenv('API_PORT', 5000))
    DEBUG_MODE = os.getenv('DEBUG_MODE', 'False').lower() == 'true'
    
    # DeepSeek AI Configuration
    DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY', '')
    DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
    
    # Pushbullet Configuration
    PUSHBULLET_API_KEY = os.getenv('PUSHBULLET_API_KEY', '')
    
    # Alert Configuration
    DANGER_THRESHOLD = float(os.getenv('DANGER_THRESHOLD', 20))
    WARNING_THRESHOLD = float(os.getenv('WARNING_THRESHOLD', 50))
    ALERT_COOLDOWN_SECONDS = int(os.getenv('ALERT_COOLDOWN_SECONDS', 10))
    
    # Database Configuration
    DB_PATH = os.getenv('DB_PATH', 'distance_monitor.db')
    DATA_RETENTION_DAYS = int(os.getenv('DATA_RETENTION_DAYS', 30))
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE = int(os.getenv('RATE_LIMIT_PER_MINUTE', 60))
    
    # Logging
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FILE = os.getenv('LOG_FILE', 'app.log')
    
        # ========== NEW: API AUTHENTICATION SETTINGS ==========
    # API_KEYS: Comma-separated list of valid API keys
    # Example: "key123,key456,key789"
    API_KEYS = os.getenv('API_KEYS', '').split(',')
    
    # REQUIRE_AUTH: Master switch for authentication
    # True = require API key for all protected endpoints
    # False = allow anyone (for testing)
    REQUIRE_AUTH = os.getenv('REQUIRE_AUTH', 'True').lower() == 'true'
    
    @classmethod
    def is_valid_api_key(cls, api_key):
        """Check if an API key is valid"""
        if not cls.REQUIRE_AUTH:
            return True  # Auth disabled, always valid
        return api_key in cls.API_KEYS
    
    @classmethod
    def validate(cls):
        """Check if critical configuration is present"""
        issues = []
        if not cls.DEEPSEEK_API_KEY:
            issues.append("DEEPSEEK_API_KEY not set")
        if not cls.PUSHBULLET_API_KEY:
            issues.append("PUSHBULLET_API_KEY not set")
        return issues

# Create .env template
def create_env_template():
    """Create example .env file if it doesn't exist"""
    if not os.path.exists('.env'):
        with open('.env', 'w') as f:
            f.write("""
# API Configuration
API_HOST=0.0.0.0
API_PORT=5000
DEBUG_MODE=False

# DeepSeek AI API Key (get from platform.deepseek.com)
DEEPSEEK_API_KEY=your_deepseek_key_here

# Pushbullet API Key (get from pushbullet.com/account)
PUSHBULLET_API_KEY=your_pushbullet_key_here

# Alert Thresholds (in centimeters)
DANGER_THRESHOLD=20
WARNING_THRESHOLD=50
ALERT_COOLDOWN_SECONDS=10

# Database
DB_PATH=distance_monitor.db
DATA_RETENTION_DAYS=30

# Rate Limiting
RATE_LIMIT_PER_MINUTE=60

# Logging
LOG_LEVEL=INFO
LOG_FILE=app.log
""")
        print("✅ Created .env template file")
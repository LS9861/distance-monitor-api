# logger.py - Professional logging setup
import logging
import os
from datetime import datetime

def setup_logger(name, log_file='app.log', log_level=logging.INFO):
    """Configure logging with file and console output"""
    
    # Create logger
    logger = logging.getLogger(name)
    logger.setLevel(log_level)
    
    # Clear existing handlers
    logger.handlers.clear()
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    # File handler (append mode)
    file_handler = logging.FileHandler(log_file)
    file_handler.setLevel(log_level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

def log_reading(logger, distance, status):
    """Log a reading event"""
    logger.info(f"Reading - Distance: {distance:.2f}cm, Status: {status}")

def log_alert(logger, alert_type, distance, message, sent=False):
    """Log an alert event"""
    sent_str = " (sent to phone)" if sent else ""
    logger.warning(f"ALERT - Type: {alert_type}, Distance: {distance:.2f}cm, Message: {message}{sent_str}")

def log_api_request(logger, endpoint, method, status_code, duration_ms):
    """Log API request"""
    logger.debug(f"API Request - {method} {endpoint} - Status: {status_code} - Duration: {duration_ms}ms")

def get_log_summary(log_file='app.log', lines=50):
    """Get recent log entries"""
    if not os.path.exists(log_file):
        return []
    
    with open(log_file, 'r') as f:
        all_lines = f.readlines()
        return all_lines[-lines:]
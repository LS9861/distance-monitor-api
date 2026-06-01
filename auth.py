# auth.py - API Authentication System
# This file handles all authentication for your API

from functools import wraps
from flask import request, jsonify
from config import Config

def require_api_key(f):
    """
    DECORATOR: Wraps around API endpoints to check for valid API key.
    
    HOW IT WORKS:
    1. User calls an endpoint (like /stats)
    2. This function runs FIRST
    3. It looks for API key in HTTP header or URL
    4. If key is valid, the original endpoint runs
    5. If key is invalid, it returns error immediately
    
    WHERE THE API KEY CAN BE:
    - HTTP Header: X-API-Key: your-key-here (RECOMMENDED)
    - URL Parameter: ?api_key=your-key-here (for testing)
    """
    
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Step 1: Check if authentication is enabled
        if not Config.REQUIRE_AUTH:
            # Auth disabled - let everyone through (for testing)
            return f(*args, **kwargs)
        
        # Step 2: Try to get API key from HTTP header (preferred method)
        api_key = request.headers.get('X-API-Key')
        
        # Step 3: If not in header, try URL parameter (for browser testing)
        if not api_key:
            api_key = request.args.get('api_key')
        
        # Step 4: Validate the key
        if not Config.is_valid_api_key(api_key):
            # Invalid or missing key - return error
            return jsonify({
                "error": "Invalid or missing API key",
                "message": "Please provide X-API-Key header or api_key parameter",
                "hint": "For testing, set REQUIRE_AUTH=False in .env"
            }), 401  # 401 = Unauthorized
        
        # Step 5: Key is valid - proceed to original function
        return f(*args, **kwargs)
    
    return decorated_function


def generate_api_key():
    """
    Utility function to generate a new random API key.
    
    Use this to create new keys for new devices/users.
    Run this function separately to get a new key.
    
    EXAMPLE USAGE:
        python -c "from auth import generate_api_key; print(generate_api_key())"
    """
    import secrets
    # secrets.token_urlsafe(32) creates a cryptographically secure random string
    # 32 = length of the key in bytes (produces ~43 characters)
    return secrets.token_urlsafe(32)


# Simple test when run directly
if __name__ == "__main__":
    print("=" * 50)
    print("API Key Generator")
    print("=" * 50)
    print(f"\nNew API Key: {generate_api_key()}")
    print("\nAdd this to your .env file:")
    print(f"API_KEYS=...,{generate_api_key()}")
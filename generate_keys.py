# generate_keys.py
import secrets

print("=" * 50)
print("GENERATE YOUR API KEYS")
print("=" * 50)

# Generate your API Authentication Keys
your_api_key_1 = secrets.token_urlsafe(32)
your_api_key_2 = secrets.token_urlsafe(32)

print("\n📌 YOUR API AUTHENTICATION KEYS (for .env):")
print(f"   API_KEYS={your_api_key_1},{your_api_key_2}")

print("\n📌 YOUR PUSHBULLET KEY (already have):")
print("   Get from: https://www.pushbullet.com/account")

print("\n📌 YOUR DEEPSEEK KEY (already have):")
print("   Get from: https://platform.deepseek.com/")

print("\n" + "=" * 50)
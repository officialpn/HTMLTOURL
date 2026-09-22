import sys
import os

# Root folder ko path mein add karo
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app

# Vercel ko handler chahiye
handler = app

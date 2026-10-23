import os
from pathlib import Path

class Config:
    # Location settings
    PLACE = "Ha Dong District, Hanoi, Vietnam"
    DEFAULT_CENTER = (20.959, 105.77)
    DEFAULT_ZOOM = 13

    # Path settings
    BASE_DIR = Path(__file__).parent.parent
    DATA_DIR = BASE_DIR / "data"
    MAP_FILE = DATA_DIR / "hadong_drive.graphml"
    
    # Network settings
    NETWORK_TYPE = "all_private"
    
    # Flask settings
    SECRET_KEY = os.environ.get('SECRET_KEY', "super-secret-123")  # Better to use environment variable
    
    # Validate paths exist
    @classmethod
    def validate(cls):
        if not cls.DATA_DIR.exists():
            raise RuntimeError(f"Data directory not found: {cls.DATA_DIR}")
        if not cls.MAP_FILE.exists():
            raise RuntimeError(f"Map file not found: {cls.MAP_FILE}")


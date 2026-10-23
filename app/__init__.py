from flask import Flask
from .routing import bp

def create_app():
    app = Flask(__name__, 
                static_url_path='/app_static')  # Prevent static route conflict
    app.secret_key = "super-secret-123"
    
    # Register blueprint
    app.register_blueprint(bp)
    
    # Print registered routes for debugging
    print('Registered routes:')
    for rule in app.url_map.iter_rules():
        print(f"{rule.endpoint}: {rule.rule}")
    
    return app


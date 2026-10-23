from flask import Blueprint

# Remove url_prefix to handle root path
bp = Blueprint('routing', __name__,
               template_folder='../templates',
               static_folder='../static',
               static_url_path='/static')  # Specify static URL to avoid conflicts

from . import controllers

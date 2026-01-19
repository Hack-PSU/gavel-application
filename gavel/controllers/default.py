from gavel import app
from flask import send_from_directory, jsonify
import os

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(
        os.path.join(app.root_path, 'static'),
        'favicon.ico',
        mimetype='image/vnd.microsoft.icon'
    )

@app.route('/health')
def health():
    """Lightweight health check endpoint for container orchestration."""
    return jsonify({"status": "ok"}), 200

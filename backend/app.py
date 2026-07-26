from flask import Flask
from flask_cors import CORS

from region import region_bp
from routes.pages import pages_bp
from routes.browse import browse_bp
from routes.discover import discover_bp
from routes.game import game_bp

app = Flask(__name__)
CORS(app)

app.register_blueprint(region_bp)
app.register_blueprint(pages_bp)
app.register_blueprint(browse_bp)
app.register_blueprint(discover_bp)
app.register_blueprint(game_bp)


if __name__ == "__main__":
    app.run(debug=True)
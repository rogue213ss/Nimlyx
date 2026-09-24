from flask import Blueprint, jsonify, request, session, render_template

rig_bp = Blueprint("rig", __name__)

@rig_bp.route("/rig")
def rig_page():
    return render_template("rig.html")

@rig_bp.route("/api/rig", methods=["GET", "PUT", "DELETE"])
def manage_rig():
    if request.method == "GET":
        rig = session.get("rig")
        if not rig:
            return jsonify({"status": "not_configured"}), 404
        return jsonify(rig)
        
    elif request.method == "PUT":
        data = request.get_json(silent=True) or {}
        # Validate input safely
        cpu = data.get("cpu_external_id")
        gpu = data.get("gpu_external_id")
        ram = data.get("ram_gb")
        
        # Must handle malformed gracefully
        try:
            ram = int(ram) if ram is not None else None
        except (ValueError, TypeError):
            ram = None
            
        if not isinstance(cpu, str): cpu = None
        if not isinstance(gpu, str): gpu = None

        rig_data = {
            "cpu_external_id": cpu,
            "gpu_external_id": gpu,
            "ram_gb": ram
        }
        
        session["rig"] = rig_data
        session.modified = True
        return jsonify({"status": "saved", "rig": rig_data})
        
    elif request.method == "DELETE":
        session.pop("rig", None)
        session.modified = True
        return jsonify({"status": "cleared"})

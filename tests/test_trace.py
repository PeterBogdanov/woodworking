import os
import json
import subprocess

def test_trace_sample():
    # Run the trace script on the provided sample image
    cmd = [".venv/bin/python", "-m", "boardcam.trace", "woodworking/board_v3/samples/sketch.jpg",
           "--size", "200x200", "--thickness", "22", "--pocket-depth", "12", "--rotate", "90", "--out", "out_test", "--debug"]
    result = subprocess.run(cmd, cwd=os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), capture_output=True, text=True)
    assert result.returncode == 0, f"Trace script failed: {result.stderr}\n{result.stdout}"
    # Verify output files exist
    out_dir = os.path.join(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")), "out_test")
    assert os.path.isfile(os.path.join(out_dir, "board.scad"))
    assert os.path.isfile(os.path.join(out_dir, "trace.json"))
    # Load trace.json and check basic metrics
    with open(os.path.join(out_dir, "trace.json"), "r") as f:
        data = json.load(f)
    assert data.get("outline_pts"), "No outline points"
    # Expect a warning about min wall (since sample may be thin)
    warnings = data.get("warnings", [])
    assert any("min_wall" in w.lower() for w in warnings), "Expected min wall warning not found"

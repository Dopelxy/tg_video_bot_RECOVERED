"""Reproducible screenshot matrix. Always uses demo + offline guards."""
import offline_support
import argparse
import json
from pathlib import Path
import struct
import subprocess
import sys

sys.path.insert(0, str(offline_support.ROOT))
from app.paths import PROJECT_DIR
from app.services.process_tree import popen_owned, stop_owned


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--native", action="store_true", help="Three GPU previews instead of the software state matrix")
    parser.add_argument("--lite", action="store_true", help="Verify the lightweight path on the native renderer")
    args = parser.parse_args()
    states = ("running",) if args.native else ("running", "stopped", "disconnected", "busy", "error")
    results = []
    for scale, tag in ((1.0, "100"), (1.25, "125"), (1.5, "150")):
        for state in states:
            prefix = "glass_native_lite" if args.native and args.lite else "glass_native" if args.native else "glass_" + state
            base = "artifacts/" + prefix + "_" + tag
            arguments = ["--demo", "--demo-state", state, "--preview-scale", str(scale),
                         "--preview-size", "1366x768", "--screenshot", base + ".png",
                         "--preview-report", base + ".json", "--quit-after", "1700"]
            arguments += ["--long-username"] if args.native else ["--offscreen"]
            if args.lite:
                arguments.append("--lite")
            code = ("import sys;sys.stdin.readline();sys.path.insert(0,'tests');"
                    "import offline_support;import gui_qml;sys.exit(gui_qml.main())")
            process, job = popen_owned([sys.executable, "-X", "utf8", "-B", "-c", code, *arguments],
                                       cwd=PROJECT_DIR, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            process.stdin = None
            try:
                output, _ = process.communicate(timeout=40)
                if process.returncode:
                    raise AssertionError(output.decode("utf-8", errors="replace"))
                assert not output.strip(), output.decode("utf-8", errors="replace")
            finally:
                stop_owned(process, job, timeout=5)
            data = json.loads((PROJECT_DIR / (base + ".json")).read_text(encoding="utf-8"))
            assert data["scenario"] == state
            assert abs(data["dpr"] - scale) < 0.01
            assert abs(data["width"] * scale - 1366) <= 1
            assert abs(data["height"] * scale - 768) <= 1
            if not args.native or args.lite:
                assert data["blur"] is False
            else:
                assert data["blur"] is True
                assert len(data["glass_sources"]) == 2
                assert all(s == {"source": "ambientBackground", "recursive": False, "live": False}
                           for s in data["glass_sources"])
            assert data["manual_busy"] == (state == "busy")
            for name in ("startButton", "stopButton", "refreshButton", "exitButton"):
                button = data["items"][name]
                assert button["scene_x"] >= 0
                assert button["scene_x"] + button["width"] <= data["width"] + 1
                assert button["scene_y"] + button["height"] <= data["height"] + 1
            image_header = (PROJECT_DIR / (base + ".png")).read_bytes()[:24]
            width, height = struct.unpack(">II", image_header[16:24])
            assert abs(width - 1366) <= 1 and abs(height - 768) <= 1
            results.append({"state": state, "scale": scale, "dpr": data["dpr"], "blur": data["blur"],
                            "renderer": data["renderer"], "screenshot": base + ".png"})
            print(state, tag, "OK", flush=True)
    name = "glass_native_lite_matrix.json" if args.native and args.lite else "glass_native_matrix.json" if args.native else "glass_state_matrix.json"
    (PROJECT_DIR / "artifacts" / name).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

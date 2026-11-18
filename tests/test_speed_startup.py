import subprocess
import sys

from utils.lazy import LazyModule


def test_lazy_module_defers_and_reports_missing():
    m = LazyModule("json")
    assert m.dumps({"a": 1}) == '{"a": 1}'
    missing = LazyModule("definitely_not_installed_pkg_xyz")
    assert not missing
    assert not missing.available()


def test_heavy_libs_not_imported_at_startup():
    code = (
        "import sys, core.orchestrator;"
        "bad=[m for m in ('pygame','pyautogui','pytesseract','playwright','openai','groq','chromadb') if m in sys.modules];"
        "print(','.join(bad))"
    )
    lines = subprocess.run([sys.executable, "-I", "-c", "import sys;sys.path.insert(0,'.');" + code],
                         capture_output=True, text=True, timeout=120).stdout.strip().splitlines()
    out = lines[-1] if lines else ""
    assert out == "", f"imported eagerly: {out}"


def test_vector_store_init_is_background_but_reads_wait(monkeypatch, tmp_path):
    import time

    from core.vector_store import VectorStore

    def slow_init(self):
        time.sleep(0.3)
        self.collection = "ready"
    monkeypatch.setattr(VectorStore, "_init_chroma", slow_init)
    t = time.perf_counter()
    vs = VectorStore(str(tmp_path / "v"))
    assert time.perf_counter() - t < 0.2          # constructor returns immediately
    assert vs.collection == "ready"               # first use waits for the background init

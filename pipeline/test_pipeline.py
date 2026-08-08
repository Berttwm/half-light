import json, os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipeline import build

def test_scan_sources():
    with tempfile.TemporaryDirectory() as d:
        for name in ["DSCF0001.JPG", "DSCF0002.RAF", "DSCF0001.RAF", "notes.txt", "DSCF0003.jpg"]:
            open(os.path.join(d, name), "wb").close()
        out = build.scan_sources(d)
        assert [e["stem"] for e in out] == ["DSCF0001", "DSCF0002", "DSCF0003"], out
        assert out[0]["ext"] == ".RAF"          # RAF preferred over same-stem JPG
        assert out[2]["ext"] == ".JPG"          # lowercase .jpg normalized
    print("ok test_scan_sources")

def test_load_config():
    cfg = build.load_config()
    assert cfg["title"] == "Half-Light"
    assert cfg["exposure"]["target_median"] == 0.42
    assert cfg["reel_size"] == 14
    print("ok test_load_config")

def main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
    print("ALL TESTS PASSED")

if __name__ == "__main__":
    main()

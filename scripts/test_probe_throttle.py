"""probe.py の editor_throttle 判定を、偽の unreal モジュールで検証する回帰テスト。

実機を必要とせず、埋め込み Python スクリプトを実際に exec して確認する。
    python3 scripts/test_probe_throttle.py   (リポジトリのルートから)
"""

import io, json, os, sys, tempfile, types, contextlib, importlib.util, pathlib

spec = importlib.util.spec_from_file_location("probe", os.path.join(os.path.dirname(os.path.abspath(__file__)), "probe.py"))
probe = importlib.util.module_from_spec(spec); sys.modules["probe"] = probe; spec.loader.exec_module(probe)

def make_unreal(project_dir, saved_dir):
    u = types.ModuleType("unreal")
    class P:
        @staticmethod
        def get_project_file_path(): return os.path.join(project_dir, "Dummy.uproject")
        @staticmethod
        def project_dir(): return project_dir + os.sep
        @staticmethod
        def project_saved_dir(): return saved_dir + os.sep
    class S:
        @staticmethod
        def get_engine_version(): return "5.5.4-test"
    u.Paths = P; u.SystemLibrary = S
    u.PythonScriptLibrary = object; u.EditorAssetLibrary = object
    return u

def run_case(name, first_body, second_body, expect_throttling, expect_source_prefix):
    with tempfile.TemporaryDirectory() as root:
        pd = os.path.join(root, "Proj"); sd = os.path.join(pd, "Saved")
        os.makedirs(os.path.join(pd, "Config"))
        os.makedirs(os.path.join(sd, "Config", "WindowsEditor"))
        if first_body is not None:
            pathlib.Path(pd, "Config", "DefaultEditorSettings.ini").write_text(first_body, encoding="utf-8")
        if second_body is not None:
            pathlib.Path(sd, "Config", "WindowsEditor", "EditorPerProjectUserSettings.ini").write_text(second_body, encoding="utf-8")
        sys.modules["unreal"] = make_unreal(pd, sd)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(probe.environment_command(), {"__name__": "__main__"})
        out = buf.getvalue()
        payload = json.loads(out[out.index(probe.ENV_MARKER) + len(probe.ENV_MARKER):].strip())
        et = payload["editor_throttle"]
        ok = et["throttling"] is expect_throttling and et["source"].startswith(expect_source_prefix)
        leftovers = [f for f in os.listdir(sd) if f.startswith(".ue_remote_probe_")]
        print(f"[{'PASS' if ok and not leftovers else 'FAIL'}] {name}")
        print(f"        -> {json.dumps(et, ensure_ascii=False)}")
        if leftovers: print(f"        !! 残留ファイル: {leftovers}")
        return ok and not leftovers

SEC = "[/Script/UnrealEd.EditorPerformanceSettings]\n"
results = [
  run_case("1番目にキーあり(False) -> 1番目を採用",
           SEC + "bThrottleCPUWhenNotForeground=False\n", None, False, "ini"),
  run_case("★1番目は存在するがキー無し・2番目にキーあり -> 2番目を採用",
           SEC + "SomethingElse=1\n", SEC + "bThrottleCPUWhenNotForeground=False\n", False, "ini"),
  run_case("どこにもキー無し -> 既定値 True",
           "[/Script/Other]\nFoo=1\n", "[/Script/Other]\nFoo=1\n", True, "default"),
  run_case("ファイルが1つも無い -> 既定値 True", None, None, True, "default"),
  run_case("別セクション内の同名キーは無視 -> 既定値 True",
           "[/Script/UnrealEd.SomethingElse]\nbThrottleCPUWhenNotForeground=False\n", None, True, "default"),
]
print("\n" + ("すべて PASS" if all(results) else "FAIL あり"))
sys.exit(0 if all(results) else 1)

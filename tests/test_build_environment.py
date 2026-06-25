"""Tests for the build-environment logic that feeds the Windows/Mac/Linux executables.

These tests cover the *source-side* inputs to the PyInstaller build.
The compiled executables themselves are not testable in Python unit tests
(they need PyInstaller + the 3 OS runners); that part lives in the CI
``build-executable`` matrix job.  What IS testable:

Section 1 – Runtime hook contracts (modules/hooks/*.py)
    Each hook injects one env var at binary start-up.  A typo in that value
    (e.g. "Linux" instead of "linux") would cause get_running_os() to
    silently report the wrong OS for update links.

Section 2 – get_running_os() — 9-path detection matrix
    Docker override → frozen-Windows/macOS/Linux/Unknown →
    local-Windows/macOS/Linux/Unknown.

Section 3 – get_branch() — update-channel detection
    In a frozen binary GitPython fails (no .git dir in the extraction temp),
    so BRANCH_NAME (set by the runtime hook) is the only way to communicate
    which update channel the user is on.

Section 4 – get_version() — VERSION + BUILDNUM file reading
    Covers master (bare) and non-master (version-buildN) formatting, missing
    files, and whitespace stripping.

Section 5 – get_pyfiglet_fonts() frozen path routing
    The function switches between sys._MEIPASS and os.path.abspath(".")
    depending on sys.frozen.  Both paths must still return the three
    predefined fonts first.

Section 6 – quickstart.spec structural integrity
    All datas source paths must exist in the repo; the explicit hiddenimports
    must all be importable; the entry-point (quickstart.py) must be declared.

Section 7 – VERSION and BUILDNUM file format
    The CI workflow embeds these verbatim in the binary filename, so a
    malformed value silently produces a weird filename rather than failing.
"""

import ast
import importlib
import importlib.util
import os
import platform
import sys

import pytest

import modules.helpers as helpers

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _load_hook(hook_rel_path: str):
    """Execute a hook file in a fresh module object and return it.

    This lets each test verify the hook's side-effects on os.environ without
    polluting the test process permanently (monkeypatch cleans up after each
    test).
    """
    full_path = os.path.join(REPO_ROOT, hook_rel_path)
    spec = importlib.util.spec_from_file_location("_hook_under_test", full_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ============================================================================
# Section 1 – Runtime hook contracts
# ============================================================================


class TestRuntimeHooks:
    """The five runtime hooks are each 2 lines long but carry a critical
    contract: they must set exactly the right env var to exactly the right
    value, because that is the *only* mechanism by which a frozen binary can
    know its build OS and update channel.
    """

    @pytest.mark.parametrize(
        "hook_file,env_var,expected",
        [
            ("modules/hooks/windows.py", "BUILD_OS", "windows"),
            ("modules/hooks/linux.py", "BUILD_OS", "linux"),
            ("modules/hooks/macos.py", "BUILD_OS", "macos"),
            ("modules/hooks/develop.py", "BRANCH_NAME", "develop"),
            ("modules/hooks/pull.py", "BRANCH_NAME", "pull"),
        ],
    )
    def test_hook_sets_correct_env_var(self, monkeypatch, hook_file, env_var, expected):
        """Running the hook module must set env_var to the expected value."""
        # Remove the variable first so we're certain the hook is the one that sets it.
        monkeypatch.delenv(env_var, raising=False)
        _load_hook(hook_file)
        assert os.environ.get(env_var) == expected, (
            f"{hook_file} must set {env_var}={expected!r}; "
            f"got {os.environ.get(env_var)!r}"
        )

    def test_all_hook_files_exist_on_disk(self):
        """All five hook files referenced in quickstart.spec must be present."""
        for hook in (
            "modules/hooks/windows.py",
            "modules/hooks/linux.py",
            "modules/hooks/macos.py",
            "modules/hooks/develop.py",
            "modules/hooks/pull.py",
        ):
            full = os.path.join(REPO_ROOT, hook)
            assert os.path.isfile(full), f"Missing runtime hook: {hook}"

    def test_hooks_are_valid_python(self):
        """Each hook must parse as valid Python (guards against accidental syntax errors)."""
        for hook in (
            "modules/hooks/windows.py",
            "modules/hooks/linux.py",
            "modules/hooks/macos.py",
            "modules/hooks/develop.py",
            "modules/hooks/pull.py",
        ):
            full = os.path.join(REPO_ROOT, hook)
            src = open(full, encoding="utf-8").read()
            ast.parse(src)  # raises SyntaxError if broken


# ============================================================================
# Section 2 – get_running_os()
# ============================================================================


class TestGetRunningOs:
    """get_running_os() controls which download URL is shown in the update
    notification (Windows needs a .exe, macOS and Linux don't).

    Priority order (first match wins):
      1. QUICKSTART_DOCKER env var is truthy  →  "Docker"
      2. sys.frozen is truthy                 →  "Frozen-<platform>"
      3. plain Python                         →  "Local-<platform>"
    """

    # --- Docker override ------------------------------------------------------

    @pytest.mark.parametrize("docker_val", ["true", "True", "1"])
    def test_docker_env_returns_docker_regardless_of_platform(
        self, monkeypatch, docker_val
    ):
        monkeypatch.setenv("QUICKSTART_DOCKER", docker_val)
        name, ext = helpers.get_running_os()
        assert name == "Docker"
        assert ext == ""

    def test_docker_env_false_does_not_short_circuit(self, monkeypatch):
        """A falsy QUICKSTART_DOCKER must NOT produce "Docker"."""
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.delattr(sys, "frozen", raising=False)
        name, _ = helpers.get_running_os()
        assert name != "Docker"

    # --- Frozen-build matrix --------------------------------------------------

    @pytest.mark.parametrize(
        "plat_system,expected_name,expected_ext",
        [
            ("Windows", "Frozen-Windows", ".exe"),
            ("Darwin", "Frozen-macOS", ""),
            ("Linux", "Frozen-Linux", ""),
        ],
    )
    def test_frozen_mode_known_platform(
        self, monkeypatch, plat_system, expected_name, expected_ext
    ):
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(platform, "system", lambda: plat_system)
        name, ext = helpers.get_running_os()
        assert name == expected_name
        assert ext == expected_ext

    def test_frozen_unknown_platform(self, monkeypatch):
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(platform, "system", lambda: "FreeBSD")
        name, ext = helpers.get_running_os()
        assert name == "Frozen-Unknown"
        assert ext == ""

    # --- Local (non-frozen) matrix --------------------------------------------

    @pytest.mark.parametrize(
        "plat_system,expected_name",
        [
            ("Windows", "Local-Windows"),
            ("Darwin", "Local-macOS"),
            ("Linux", "Local-Linux"),
        ],
    )
    def test_local_mode_known_platform(self, monkeypatch, plat_system, expected_name):
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.setattr(platform, "system", lambda: plat_system)
        name, _ = helpers.get_running_os()
        assert name == expected_name

    def test_local_unknown_platform(self, monkeypatch):
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.delattr(sys, "frozen", raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Haiku")
        name, _ = helpers.get_running_os()
        assert name == "Local-Unknown"

    # --- Extension correctness ------------------------------------------------

    def test_windows_extension_is_exe(self, monkeypatch):
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(platform, "system", lambda: "Windows")
        _, ext = helpers.get_running_os()
        assert ext == ".exe"

    @pytest.mark.parametrize("plat_system", ["Darwin", "Linux"])
    def test_non_windows_extension_is_empty(self, monkeypatch, plat_system):
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(platform, "system", lambda: plat_system)
        _, ext = helpers.get_running_os()
        assert ext == ""


# ============================================================================
# Section 3 – get_branch()
# ============================================================================


class TestGetBranch:
    """In a frozen binary:
      • GitPython fails (no .git dir in the PyInstaller extraction temp dir)
      • The runtime hook has set BRANCH_NAME to "develop" or "pull"
      • get_branch() must return that env var value

    Tests use a fake Repo class to simulate a frozen environment (no git repo)
    without actually needing sys.frozen.
    """

    class _RepoOk:
        """Fake Repo that reports a specific branch name."""

        def __init__(self, branch_name):
            self._branch = branch_name

        def __call__(self, *args, **kwargs):
            ref = type("Ref", (), {"name": self._branch})()
            head = type("Head", (), {"ref": ref})()
            repo = type("Repo", (), {"head": head})()
            return repo

    class _RepoBroken:
        """Fake Repo that always raises (simulates no .git dir)."""

        def __init__(self, *args, **kwargs):
            raise Exception("no git repo here")

    # --- Docker path (highest priority) ---------------------------------------

    @pytest.mark.parametrize("branch", ["master", "develop", "pull"])
    def test_docker_mode_reads_branch_name_env(self, monkeypatch, branch):
        monkeypatch.setenv("QUICKSTART_DOCKER", "true")
        monkeypatch.setenv("BRANCH_NAME", branch)
        assert helpers.get_branch() == branch

    def test_docker_mode_defaults_to_master_when_branch_name_absent(self, monkeypatch):
        monkeypatch.setenv("QUICKSTART_DOCKER", "true")
        monkeypatch.delenv("BRANCH_NAME", raising=False)
        assert helpers.get_branch() == "master"

    # --- GitPython path -------------------------------------------------------

    def test_gitpython_result_wins_over_branch_name_env(self, monkeypatch):
        """When GitPython succeeds it takes priority over BRANCH_NAME."""
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.setenv("BRANCH_NAME", "something-else")
        monkeypatch.setattr(
            helpers, "Repo", self._RepoOk("my-feature"), raising=False
        )
        assert helpers.get_branch() == "my-feature"

    # --- BRANCH_NAME env fallback (frozen-binary simulation) ------------------

    def test_branch_name_env_used_when_git_fails(self, monkeypatch):
        """Simulate frozen binary: GitPython raises → BRANCH_NAME env wins."""
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.setenv("BRANCH_NAME", "develop")
        monkeypatch.setattr(helpers, "Repo", self._RepoBroken, raising=False)
        assert helpers.get_branch() == "develop"

    def test_falls_back_to_master_when_git_fails_and_env_absent(self, monkeypatch):
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.delenv("BRANCH_NAME", raising=False)
        monkeypatch.setattr(helpers, "Repo", self._RepoBroken, raising=False)
        assert helpers.get_branch() == "master"

    def test_none_repo_skips_git_and_uses_env(self, monkeypatch):
        """When Repo is None (GitPython not installed) env-var path is used."""
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.setenv("BRANCH_NAME", "pull")
        monkeypatch.setattr(helpers, "Repo", None, raising=False)
        assert helpers.get_branch() == "pull"

    # --- BRANCH_NAME set by develop hook -------------------------------------

    def test_develop_hook_value_round_trips_through_get_branch(self, monkeypatch):
        """The value the develop hook injects must be what get_branch() returns."""
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.delenv("BRANCH_NAME", raising=False)
        monkeypatch.setattr(helpers, "Repo", None, raising=False)

        # Simulate the hook running
        _load_hook("modules/hooks/develop.py")
        assert helpers.get_branch() == "develop"

    def test_pull_hook_value_round_trips_through_get_branch(self, monkeypatch):
        monkeypatch.setenv("QUICKSTART_DOCKER", "false")
        monkeypatch.delenv("BRANCH_NAME", raising=False)
        monkeypatch.setattr(helpers, "Repo", None, raising=False)

        _load_hook("modules/hooks/pull.py")
        assert helpers.get_branch() == "pull"


# ============================================================================
# Section 4 – get_version()
# ============================================================================


class TestGetVersion:
    """get_version() reads VERSION (and for non-master branches also BUILDNUM)
    and formats the string that ends up in update notifications and binary
    filenames produced by the CI workflow.
    """

    def test_master_branch_returns_bare_version(self, tmp_path, monkeypatch):
        (tmp_path / "VERSION").write_text("1.2.3", encoding="utf-8")
        monkeypatch.setattr(helpers, "VERSION_FILE", str(tmp_path / "VERSION"))
        assert helpers.get_version("master") == "1.2.3"

    def test_develop_branch_appends_buildnum(self, tmp_path, monkeypatch):
        (tmp_path / "VERSION").write_text("1.2.3", encoding="utf-8")
        (tmp_path / "BUILDNUM").write_text("42", encoding="utf-8")
        monkeypatch.setattr(helpers, "VERSION_FILE", str(tmp_path / "VERSION"))
        monkeypatch.setattr(helpers, "BUILDNUM_FILE", str(tmp_path / "BUILDNUM"))
        assert helpers.get_version("develop") == "1.2.3-build42"

    def test_pull_branch_appends_buildnum(self, tmp_path, monkeypatch):
        (tmp_path / "VERSION").write_text("0.9.0", encoding="utf-8")
        (tmp_path / "BUILDNUM").write_text("7", encoding="utf-8")
        monkeypatch.setattr(helpers, "VERSION_FILE", str(tmp_path / "VERSION"))
        monkeypatch.setattr(helpers, "BUILDNUM_FILE", str(tmp_path / "BUILDNUM"))
        assert helpers.get_version("pull") == "0.9.0-build7"

    def test_missing_buildnum_file_defaults_to_zero(self, tmp_path, monkeypatch):
        """If BUILDNUM is absent the function must default to 0, not crash."""
        (tmp_path / "VERSION").write_text("1.0.0", encoding="utf-8")
        monkeypatch.setattr(helpers, "VERSION_FILE", str(tmp_path / "VERSION"))
        monkeypatch.setattr(helpers, "BUILDNUM_FILE", str(tmp_path / "no_such_file"))
        assert helpers.get_version("develop") == "1.0.0-build0"

    def test_missing_version_file_returns_unknown(self, tmp_path, monkeypatch):
        monkeypatch.setattr(helpers, "VERSION_FILE", str(tmp_path / "no_VERSION"))
        assert helpers.get_version("master") == "unknown"

    def test_version_strips_trailing_newline(self, tmp_path, monkeypatch):
        """PyInstaller embeds the raw file content; trailing whitespace would corrupt filenames."""
        (tmp_path / "VERSION").write_text("2.0.1\n", encoding="utf-8")
        monkeypatch.setattr(helpers, "VERSION_FILE", str(tmp_path / "VERSION"))
        result = helpers.get_version("master")
        assert result == "2.0.1"
        assert "\n" not in result

    def test_buildnum_strips_trailing_newline(self, tmp_path, monkeypatch):
        (tmp_path / "VERSION").write_text("1.0.0", encoding="utf-8")
        (tmp_path / "BUILDNUM").write_text("5\n", encoding="utf-8")
        monkeypatch.setattr(helpers, "VERSION_FILE", str(tmp_path / "VERSION"))
        monkeypatch.setattr(helpers, "BUILDNUM_FILE", str(tmp_path / "BUILDNUM"))
        result = helpers.get_version("develop")
        assert result == "1.0.0-build5"
        assert "\n" not in result


# ============================================================================
# Section 5 – get_pyfiglet_fonts() frozen path routing
# ============================================================================


class TestGetPyfigletFonts:
    """In frozen mode fonts must come from sys._MEIPASS/static/fonts/.
    In normal mode they come from static/fonts/ relative to the CWD.
    Either way the three predefined fonts must appear first.
    """

    def test_predefined_fonts_are_always_first(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        fonts = helpers.get_pyfiglet_fonts()
        assert fonts[:3] == ["none", "single line", "standard"]

    def test_return_value_is_a_list(self, monkeypatch):
        monkeypatch.delattr(sys, "frozen", raising=False)
        assert isinstance(helpers.get_pyfiglet_fonts(), list)

    def test_frozen_mode_reads_fonts_from_meipass(self, monkeypatch, tmp_path):
        """Simulate the PyInstaller extraction layout: _MEIPASS/static/fonts/."""
        meipass = tmp_path / "meipass"
        fonts_dir = meipass / "static" / "fonts"
        fonts_dir.mkdir(parents=True)
        (fonts_dir / "cool-font.flf").write_text("dummy", encoding="utf-8")
        (fonts_dir / "another-font.flf").write_text("dummy", encoding="utf-8")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

        fonts = helpers.get_pyfiglet_fonts()
        assert "cool-font" in fonts
        assert "another-font" in fonts
        assert fonts[:3] == ["none", "single line", "standard"]

    def test_frozen_mode_empty_font_dir_returns_only_predefined(
        self, monkeypatch, tmp_path
    ):
        meipass = tmp_path / "meipass"
        (meipass / "static" / "fonts").mkdir(parents=True)

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

        assert helpers.get_pyfiglet_fonts() == ["none", "single line", "standard"]

    def test_frozen_mode_missing_font_dir_does_not_crash(self, monkeypatch, tmp_path):
        """If the fonts dir doesn't exist at all the function must not crash."""
        meipass = tmp_path / "empty_meipass"
        meipass.mkdir()  # no static/fonts/ subdirectory

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

        fonts = helpers.get_pyfiglet_fonts()
        assert fonts == ["none", "single line", "standard"]

    def test_flf_extension_is_stripped_from_font_names(self, monkeypatch, tmp_path):
        meipass = tmp_path / "meipass"
        fonts_dir = meipass / "static" / "fonts"
        fonts_dir.mkdir(parents=True)
        (fonts_dir / "big.flf").write_text("x", encoding="utf-8")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

        fonts = helpers.get_pyfiglet_fonts()
        assert "big" in fonts
        assert "big.flf" not in fonts

    def test_non_flf_files_are_ignored(self, monkeypatch, tmp_path):
        """Only .flf files should be listed; .ttf, .otf, etc. must be ignored."""
        meipass = tmp_path / "meipass"
        fonts_dir = meipass / "static" / "fonts"
        fonts_dir.mkdir(parents=True)
        (fonts_dir / "MyFont.ttf").write_text("x", encoding="utf-8")
        (fonts_dir / "Other.otf").write_text("x", encoding="utf-8")
        (fonts_dir / "valid.flf").write_text("x", encoding="utf-8")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

        fonts = helpers.get_pyfiglet_fonts()
        assert "valid" in fonts
        assert "MyFont" not in fonts
        assert "Other" not in fonts

    def test_no_duplicate_predefined_fonts(self, monkeypatch, tmp_path):
        """A .flf named 'standard' in the dir must not create a duplicate."""
        meipass = tmp_path / "meipass"
        fonts_dir = meipass / "static" / "fonts"
        fonts_dir.mkdir(parents=True)
        (fonts_dir / "standard.flf").write_text("x", encoding="utf-8")

        monkeypatch.setattr(sys, "frozen", True, raising=False)
        monkeypatch.setattr(sys, "_MEIPASS", str(meipass), raising=False)

        fonts = helpers.get_pyfiglet_fonts()
        assert fonts.count("standard") == 1


# ============================================================================
# Section 6 – quickstart.spec structural integrity
# ============================================================================


# ---------------------------------------------------------------------------
# Module-level fixtures shared by TestSpecFile
# (class-scoped instance-method fixtures are deprecated in pytest >= 9)
# ---------------------------------------------------------------------------


@pytest.fixture()
def spec_ast():
    """Return (ast.Module, raw_src) for quickstart.spec."""
    spec_path = os.path.join(REPO_ROOT, "quickstart.spec")
    with open(spec_path, encoding="utf-8") as fh:
        src = fh.read()
    return ast.parse(src), src


@pytest.fixture()
def spec_datas(spec_ast):
    """List of (src_path, dst_path) tuples from the Analysis() datas argument."""
    tree, _ = spec_ast
    datas = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Analysis"
        ):
            for kw in node.keywords:
                if kw.arg == "datas" and isinstance(kw.value, ast.List):
                    for elt in kw.value.elts:
                        if isinstance(elt, ast.Tuple) and len(elt.elts) >= 2:
                            try:
                                src_path = ast.literal_eval(elt.elts[0])
                                dst_path = ast.literal_eval(elt.elts[1])
                                datas.append((src_path, dst_path))
                            except (ValueError, TypeError):
                                pass
    return datas


@pytest.fixture()
def spec_explicit_hiddenimports(spec_ast):
    """Literal strings from ``hiddenimports = [...]`` (before += collect_submodules())."""
    tree, _ = spec_ast
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "hiddenimports"
            and isinstance(node.value, ast.List)
        ):
            return [
                elt.value
                for elt in node.value.elts
                if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
            ]
    return []


class TestSpecFile:
    """Parse quickstart.spec (which is valid Python) and verify its declared
    inputs are present so a broken spec is caught before CI attempts to build.
    """

    # --- Basic structural checks ----------------------------------------------

    def test_spec_file_exists(self):
        assert os.path.isfile(os.path.join(REPO_ROOT, "quickstart.spec"))

    def test_spec_is_valid_python(self, spec_ast):
        # Fixture already parsed it; if we got here the parse succeeded.
        tree, _ = spec_ast
        assert tree is not None

    def test_spec_contains_analysis_call(self, spec_ast):
        tree, _ = spec_ast
        found = any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "Analysis"
            for node in ast.walk(tree)
        )
        assert found, "No Analysis() call found in quickstart.spec"

    def test_spec_entry_point_is_quickstart_py(self, spec_ast):
        tree, _ = spec_ast
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "Analysis"
                and node.args
                and isinstance(node.args[0], ast.List)
            ):
                scripts = [
                    ast.literal_eval(e)
                    for e in node.args[0].elts
                    if isinstance(e, ast.Constant)
                ]
                assert "quickstart.py" in scripts, (
                    f"quickstart.py must be the Analysis entry-point; got {scripts}"
                )
                assert os.path.isfile(os.path.join(REPO_ROOT, "quickstart.py"))
                return
        pytest.fail("Could not locate the Analysis() scripts list in quickstart.spec")

    # --- Datas ----------------------------------------------------------------

    def test_spec_datas_were_parsed(self, spec_datas):
        assert spec_datas, (
            "No datas entries extracted from quickstart.spec — the parser may be broken"
        )

    def test_spec_datas_source_paths_exist(self, spec_datas):
        missing = [
            src
            for src, _dst in spec_datas
            if not os.path.exists(os.path.join(REPO_ROOT, src))
        ]
        assert not missing, (
            "These datas source paths declared in quickstart.spec do not exist in the "
            f"repo: {missing}"
        )

    @pytest.mark.parametrize(
        "required_source",
        ["VERSION", "BUILDNUM", "static", "templates", "modules", ".env.example"],
    )
    def test_spec_includes_required_datas_source(self, spec_datas, required_source):
        sources = {src for src, _ in spec_datas}
        assert required_source in sources, (
            f"Expected {required_source!r} in spec datas; found: {sorted(sources)}"
        )

    # --- Hiddenimports --------------------------------------------------------

    def test_spec_explicit_hiddenimports_were_parsed(self, spec_explicit_hiddenimports):
        assert spec_explicit_hiddenimports, (
            "No explicit hiddenimports found in quickstart.spec — the parser may be broken"
        )

    def test_spec_explicit_hiddenimports_are_importable(
        self, spec_explicit_hiddenimports
    ):
        """Every module explicitly listed in hiddenimports = [...] must be importable.

        This catches a requirements.txt gap before CI spends minutes building a
        binary that crashes at start-up with ModuleNotFoundError.
        """
        failed = []
        for mod in spec_explicit_hiddenimports:
            try:
                importlib.import_module(mod)
            except ImportError as exc:
                failed.append(f"{mod}: {exc}")
        assert not failed, (
            "These hiddenimports in quickstart.spec cannot be imported:\n"
            + "\n".join(f"  {e}" for e in failed)
        )

    # --- Platform hook references ---------------------------------------------

    @pytest.mark.parametrize(
        "hook_path",
        [
            "modules/hooks/windows.py",
            "modules/hooks/linux.py",
            "modules/hooks/macos.py",
        ],
    )
    def test_spec_references_platform_hook(self, spec_ast, hook_path):
        _, src = spec_ast
        assert hook_path in src, (
            f"Platform hook {hook_path!r} is not referenced in quickstart.spec"
        )

    def test_spec_references_develop_and_pull_hooks(self, spec_ast):
        _, src = spec_ast
        assert "modules/hooks/develop.py" in src
        assert "modules/hooks/pull.py" in src


# ============================================================================
# Section 7 – VERSION and BUILDNUM file format
# ============================================================================


class TestVersionFiles:
    """The CI build workflow (validate-pull.yml) reads VERSION and BUILDNUM
    with bare ``cat`` and embeds them directly in the binary filename:

        filename="Quickstart-v$(cat VERSION)-build$(cat BUILDNUM)..."

    A malformed value silently produces a weird filename rather than failing
    loudly, so we validate format here.
    """

    def test_version_file_exists(self):
        assert os.path.isfile(os.path.join(REPO_ROOT, "VERSION")), (
            "VERSION file is missing — the CI build will fail"
        )

    def test_buildnum_file_exists(self):
        assert os.path.isfile(os.path.join(REPO_ROOT, "BUILDNUM")), (
            "BUILDNUM file is missing — the CI build will fail"
        )

    def test_version_is_valid_semver(self):
        version = open(
            os.path.join(REPO_ROOT, "VERSION"), encoding="utf-8"
        ).read().strip()
        parts = version.split(".")
        assert len(parts) == 3, f"VERSION must be X.Y.Z semver, got {version!r}"
        for part in parts:
            assert part.isdigit(), (
                f"Every VERSION segment must be an integer; got {version!r}"
            )

    def test_version_has_no_spurious_whitespace(self):
        raw = open(os.path.join(REPO_ROOT, "VERSION"), encoding="utf-8").read()
        stripped = raw.strip()
        assert raw in (stripped, stripped + "\n"), (
            "VERSION must contain only the semver string (optionally followed by a "
            f"single newline); got {raw!r}"
        )

    def test_buildnum_is_a_non_negative_integer(self):
        buildnum = open(
            os.path.join(REPO_ROOT, "BUILDNUM"), encoding="utf-8"
        ).read().strip()
        assert buildnum.isdigit(), (
            f"BUILDNUM must be a non-negative integer; got {buildnum!r}"
        )
        assert int(buildnum) >= 0

    def test_buildnum_has_no_spurious_whitespace(self):
        raw = open(os.path.join(REPO_ROOT, "BUILDNUM"), encoding="utf-8").read()
        stripped = raw.strip()
        assert raw in (stripped, stripped + "\n"), (
            "BUILDNUM must contain only the integer (optionally followed by a single "
            f"newline); got {raw!r}"
        )

    def test_version_file_matches_get_version_master(self):
        """The VERSION file content and get_version('master') must agree."""
        expected = open(
            os.path.join(REPO_ROOT, "VERSION"), encoding="utf-8"
        ).read().strip()
        assert helpers.get_version("master") == expected

    def test_get_version_develop_contains_version_and_buildnum(self):
        """Sanity-check the composite format used for non-master binaries."""
        version = open(
            os.path.join(REPO_ROOT, "VERSION"), encoding="utf-8"
        ).read().strip()
        buildnum = open(
            os.path.join(REPO_ROOT, "BUILDNUM"), encoding="utf-8"
        ).read().strip()
        result = helpers.get_version("develop")
        assert version in result
        assert buildnum in result
        assert result == f"{version}-build{buildnum}"

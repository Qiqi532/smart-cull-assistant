from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_light_build_uses_isolated_environment_and_output():
    script = _text("build_dist_lightweight.bat")
    assert ".venv-light\\Scripts\\python.exe" in script
    assert "--distpath dist_light" in script
    assert "--workpath build_light" in script
    assert "installer_lightweight.iss" in script


def test_light_installer_is_separate():
    standard = _text("installer.iss")
    light = _text("installer_lightweight.iss")
    assert '#define MySourceDir "dist\\光影选片助手"' in standard
    assert '#define MySourceDir "dist_light\\光影选片助手"' in light
    assert "AppId=LuminaSelect.Standard" in standard
    assert "AppId=LuminaSelect.Lightweight" in light
    assert "SetupMutexAppId" not in standard + light
    assert "DirExistsWarning=no" in standard
    assert "DirExistsWarning=no" in light
    assert "DirsExistsWarning" not in standard + light
    assert "ArchitecturesAllowed=x64compatible" in standard
    assert "ArchitecturesAllowed=x64compatible" in light
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in standard
    assert "ArchitecturesInstallIn64BitMode=x64compatible" in light
    assert "光影选片助手轻量版" in light


def test_light_spec_does_not_collect_entire_packages():
    spec = _text("光影选片助手_dist_lightweight.spec")
    assert "collect_submodules" not in spec
    assert "modules/face_landmark/**" in spec
    assert "modules/face_detection/**" in spec
    assert "'torch'" in spec
    assert "excludes=" in spec


def test_standard_spec_collects_only_required_model_families():
    spec = _text("光影选片助手_dist.spec")
    assert "collect_submodules" not in spec
    assert "transformers.models.clip.modeling_clip" in spec
    assert "transformers.models.vit.modeling_vit" in spec
    assert "pyiqa.archs.musiq_arch" in spec
    assert "pyiqa.archs.dbcnn_arch" in spec
    assert "pyiqa.archs.brisque_arch" in spec
    assert "modules/face_landmark/**" in spec


def test_pytest_config_is_cp936_readable():
    (ROOT / "pytest.ini").read_text(encoding="cp936")


def test_light_requirements_pin_numpy_compatibility():
    req = _text("requirements-lightweight.txt")
    assert "numpy>=1.26,<2" in req
    assert "opencv-contrib-python" in req
    assert "mediapipe==0.10.21" in req


def test_standard_requirements_use_compatible_mediapipe():
    assert "mediapipe==0.10.21" in _text("requirements.txt")

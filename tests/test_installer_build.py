from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_installer_variants_follow_the_authoritative_lock():
    from scripts.installer_dependencies import requirements
    from scripts.export_installer_lock import check
    check(PROJECT_ROOT)
    for mode, channel in [('cpu', 'cpu'), ('gpu', 'cu128')]:
        entry = PROJECT_ROOT / 'installer' / f'requirements-{mode}.txt'
        assert f'-r locks/{channel}.txt' in entry.read_text()
        locked = {r.name: r for r, _ in requirements(
            PROJECT_ROOT / 'installer/locks' / f'{channel}.txt')}
        assert str(locked['torch'].specifier) == f'==2.10.0+{channel}'
        assert str(locked['torchvision'].specifier) == f'==0.25.0+{channel}'


def test_manual_installer_build_does_not_publish_release_by_default():
    workflow = (
        PROJECT_ROOT / ".github" / "workflows" / "build-installer.yml"
    ).read_text(encoding="utf-8")

    assert "publish_release:" in workflow
    assert "type: boolean" in workflow
    assert "default: false" in workflow
    assert "if: github.event_name == 'push' || inputs.publish_release" in workflow

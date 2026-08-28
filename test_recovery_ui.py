from pathlib import Path


def test_fragments_recovery_keeps_capture_compact_and_5m_only():
    base = Path('app/templates/base.html').read_text()
    index = Path('app/templates/index.html').read_text()
    css = Path('app/static/fragments-recovery.css').read_text()

    assert '5 Million Minutes' in base
    assert 'control.hope-johnstone.com' in base
    assert 'recipes.bloodydaves.com' not in base
    assert 'Quiet Timer' not in base
    assert 'width: 72px' in css
    assert 'height: 72px' in css
    assert 'Tap once, speak, tap again.' in index
    assert 'What is on your mind?' in index


def test_auth_failure_is_an_infrastructure_state_not_owner_configuration():
    login = Path('app/templates/login.html').read_text()
    assert 'infrastructure fault' in login
    assert 'FRAGMENTS_AUTH_PASSPHRASE' not in login
    assert 'Return to Control' in login

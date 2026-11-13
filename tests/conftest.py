def pytest_configure(config):
    # Feature scenarios are tagged with the requirement they verify
    # (docs/requirements.md), e.g. `pytest -m FR-34`.
    for number in range(1, 100):
        config.addinivalue_line("markers", f"FR-{number:02d}: verifies requirement FR-{number:02d}")

"""The unimplemented phase commands must fail loudly, not exit 0."""

import pytest
from click.testing import CliRunner

from tishift_heatwave.cli import main


@pytest.mark.parametrize(
    ("command", "guide"),
    [
        ("check", "docs/check-guide.md"),
        ("sync", "docs/sync-guide.md"),
    ],
)
def test_stub_commands_exit_nonzero_and_point_to_guide(command, guide):
    runner = CliRunner()
    result = runner.invoke(main, [command])

    assert result.exit_code == 2
    assert "not implemented yet" in result.output
    assert guide in result.output


def test_load_is_intentionally_disabled():
    runner = CliRunner()
    result = runner.invoke(main, ["load"])

    assert result.exit_code == 2
    assert "intentionally disabled" in result.output
    assert "docs/load-guide.md" in result.output

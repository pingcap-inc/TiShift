"""The unimplemented phase commands must fail loudly, not exit 0."""

import pytest
from click.testing import CliRunner

from tishift_heatwave.cli import main


@pytest.mark.parametrize(
    ("command", "guide"),
    [
        ("load", "docs/load-guide.md"),
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

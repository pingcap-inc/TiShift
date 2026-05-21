"""Tests for mongodump_loader's security properties.

The critical property is that the Mongo URI (which embeds the password) is
NEVER passed as a `--uri=...` argv element. mongodump must read it from a
chmod-0600 config file instead.
"""

from __future__ import annotations

import stat

from tishift_mongodb.core.load.mongodump_loader import _mongodump_config_file


SECRET_URI = "mongodb://user:SUPER_SECRET_PASSWORD@host:27017/db?authSource=admin"


def test_config_file_is_mode_600():
    """The temp config file must be readable only by the owner."""
    with _mongodump_config_file(SECRET_URI) as config_path:
        mode = config_path.stat().st_mode & 0o777
        assert mode == stat.S_IRUSR | stat.S_IWUSR


def test_config_file_contains_uri():
    """The URI is what mongodump reads."""
    with _mongodump_config_file(SECRET_URI) as config_path:
        content = config_path.read_text()
        assert SECRET_URI in content


def test_config_file_deleted_on_exit():
    """No temp file remains after the context manager exits."""
    with _mongodump_config_file(SECRET_URI) as config_path:
        path_str = str(config_path)
        assert config_path.exists()
    # After exit:
    from pathlib import Path
    assert not Path(path_str).exists()


def test_config_file_deleted_on_exception():
    """Even if the wrapped code raises, the temp file is cleaned up."""
    from pathlib import Path

    leaked_path: str | None = None
    try:
        with _mongodump_config_file(SECRET_URI) as config_path:
            leaked_path = str(config_path)
            raise RuntimeError("simulated failure inside mongodump")
    except RuntimeError:
        pass
    assert leaked_path is not None
    assert not Path(leaked_path).exists()


def test_uri_with_special_chars_quoted():
    """A URI with quotes/backslashes can't escape the YAML key value."""
    weird_uri = 'mongodb://u:p@host/db?opt="value\\"injection"'
    with _mongodump_config_file(weird_uri) as config_path:
        content = config_path.read_text()
        # The whole URI lands inside the JSON-quoted YAML string value.
        # No matter what the URI contains, the YAML parser will reconstruct
        # the original URI without splitting on the embedded quote.
        import yaml
        parsed = yaml.safe_load(content)
        assert parsed["uri"] == weird_uri

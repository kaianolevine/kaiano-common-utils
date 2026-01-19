import os


def test_safe_filename_component_normalizes_unicode_and_strips_chars():
    from kaiano.mp3.rename.io.rename_fs import safe_filename_component, safe_str

    assert safe_str(None) == ""
    assert safe_str("None") == ""
    assert safe_filename_component("Beyoncé Knowles") == "beyonceknowles"
    assert safe_filename_component(" A/B ") == "a_b"
    assert safe_filename_component("!!!") == ""


def test_rename_facade_propose_and_apply(tmp_path):
    from kaiano.mp3.rename.io.rename_fs import RenameFacade

    f = tmp_path / "My Song.mp3"
    f.write_text("x")

    facade = RenameFacade()
    proposal = facade.propose(str(f), title="My Song", artist="The Artist")
    assert proposal.dest_name.endswith(".mp3")
    # Fallback sanitizer preserves case and replaces spaces with underscores.
    assert "My_Song" in proposal.dest_name
    assert "The_Artist" in proposal.dest_name

    dest = facade.apply(str(f), title="My Song", artist="The Artist")
    assert os.path.exists(dest)
    assert not os.path.exists(str(f))


def test_mp3_renamer_uses_metadata_and_reports_renamed(tmp_path):
    from kaiano.mp3.rename.renamer import Mp3Renamer

    f = tmp_path / "orig.mp3"
    f.write_text("x")

    r = Mp3Renamer()
    result = r.apply(str(f), metadata={"title": "T", "artist": "A"})
    assert result.renamed is True
    assert os.path.exists(result.dest_path)

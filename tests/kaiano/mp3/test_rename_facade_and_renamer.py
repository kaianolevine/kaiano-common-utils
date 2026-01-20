import os


def test_safe_filename_component_normalizes_unicode_and_strips_chars():
    from kaiano.mp3.rename.io.rename_fs import safe_filename_component, safe_str

    assert safe_str(None) == ""
    assert safe_str("None") == ""
    assert safe_filename_component("Beyoncé Knowles") == "beyonceknowles"
    assert safe_filename_component(" A/B ") == "a_b"
    assert safe_filename_component("!!!") == ""


def test_mp3_renamer_rename_uses_metadata_and_reports_renamed(tmp_path):
    from kaiano.mp3.rename.renamer import Mp3Renamer

    f = tmp_path / "orig.mp3"
    f.write_text("x")

    r = Mp3Renamer()
    result = r.rename(str(f), metadata={"title": "T", "artist": "A"})
    assert result.renamed is True
    assert os.path.exists(result.dest_path)


def test_mp3_renamer_sanitize_string_collapses_whitespace_and_strips_special_chars():
    from kaiano.mp3.rename.renamer import Mp3Renamer

    s = Mp3Renamer.sanitize_string

    assert s(None) == ""
    assert s("") == ""
    assert s("   ") == ""
    assert s("Alice   Leader") == "Alice_Leader"
    assert s("\tAlice\nLeader\r") == "Alice_Leader"
    assert s(" A/B ") == "AB"  # slash removed
    assert s("Beyoncé Knowles") == "Beyonc_Knowles"  # non-ascii stripped
    assert s("!!!") == ""
    assert s("__a__") == "a"  # strip leading/trailing underscores


def test_mp3_renamer_build_routine_filename_uses_strict_sanitization():
    from kaiano.mp3.rename.renamer import Mp3Renamer

    out = Mp3Renamer.build_routine_filename(
        leader="Alice   Leader",
        follower="Bob/Follower",
        division="Novice",
        routine="My Routine!!!",
        descriptor="  Finals  ",
        season_year="2026",
    )

    assert out.startswith("Alice_Leader_BobFollower_Novice_")
    assert out.endswith("2026_My_Routine_Finals")


def test_mp3_renamer_build_routine_filename_omits_empty_optional_tail_parts():
    from kaiano.mp3.rename.renamer import Mp3Renamer

    out = Mp3Renamer.build_routine_filename(
        leader="Alice",
        follower="Bob",
        division="Novice",
        routine="",  # omitted
        descriptor=None,  # omitted
        season_year="2026",
    )

    assert out == "Alice_Bob_Novice_2026"

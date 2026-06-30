from src.quarantine.assets import is_global_asset


def test_global_nfos_preserved():
    assert is_global_asset(r"\\h\Movies\X (2012)\movie.nfo")
    assert is_global_asset(r"\\h\TV\X (1999)\tvshow.nfo")
    assert is_global_asset(r"\\h\TV\X (1999)\Season 01\season.nfo")


def test_global_artwork_preserved():
    for name in ["poster.jpg", "fanart.jpg", "folder.jpg", "banner.jpg",
                 "backdrop.jpg", "logo.png", "disc.png", "clearart.png",
                 "season01-poster.jpg", "season-specials-poster.jpg"]:
        assert is_global_asset(r"\\h\X\\" + name), name


def test_per_file_sidecars_not_global():
    assert not is_global_asset(r"\\h\X\Dilbert - S01E01 - The Name.nfo")
    assert not is_global_asset(r"\\h\X\Dilbert - S01E01 - The Name-thumb.jpg")
    assert not is_global_asset(r"\\h\X\Movie (2012).mp4")

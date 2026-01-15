from __future__ import annotations

from .retagger_types import TagSnapshot, TrackMetadata


class MergeFacade:
    """Build TrackMetadata updates from existing tags + fetched metadata.

    This is the centralized place for all conflict rules.
    """

    def normalize_year(self, v: object) -> str:
        s = "" if v is None else str(v).strip()
        if len(s) >= 4 and s[:4].isdigit():
            return s[:4]
        return ""

    def passthrough(self, snapshot: TagSnapshot) -> TrackMetadata:
        t = snapshot.tags or {}
        title = str(t.get("tracktitle", "") or "").strip()
        artist = str(t.get("artist", "") or "").strip()
        album = str(t.get("album", "") or "").strip()
        album_artist = str(t.get("albumartist", "") or "").strip()
        genre = str(t.get("genre", "") or "").strip()
        bpm = str(t.get("bpm", "") or "").strip()
        comment = str(t.get("comment", "") or "").strip()
        year = self.normalize_year(t.get("year") or t.get("date"))
        track_number = str(t.get("tracknumber", "") or "").strip()
        disc_number = str(t.get("discnumber", "") or "").strip()

        return TrackMetadata(
            title=title or None,
            artist=artist or None,
            album=album or None,
            album_artist=album_artist or None,
            year=year or None,
            genre=genre or None,
            bpm=bpm or None,
            comment=comment or None,
            isrc=None,
            track_number=track_number or None,
            disc_number=disc_number or None,
            raw=getattr(snapshot, "raw", None),
        )

    def build_updates(
        self, existing: TagSnapshot, new_meta: TrackMetadata
    ) -> TrackMetadata:
        """Merge policy:

        - Title/artist: overwrite if new value provided
        - Genre: fill-only (do not overwrite existing genre)
        - Comment: preserve existing comment but add <KAT_v1> marker
        - Year: normalized to YYYY if possible
        """

        tags = existing.tags or {}

        existing_genre = str(tags.get("genre", "") or "").strip()
        new_genre = str(new_meta.genre or "").strip()
        genre_to_write = new_genre if (not existing_genre and new_genre) else None

        existing_comment = str(tags.get("comment", "") or "").strip()
        if existing_comment == "":
            comment_to_write = "<KAT_v1>"
        elif existing_comment.startswith("<KAT_v1>"):
            comment_to_write = existing_comment
        else:
            comment_to_write = "<KAT_v1> " + existing_comment

        year_norm = self.normalize_year(new_meta.year)

        return TrackMetadata(
            title=new_meta.title,
            artist=new_meta.artist,
            album=new_meta.album,
            album_artist=new_meta.album_artist,
            year=year_norm or None,
            genre=genre_to_write,
            bpm=new_meta.bpm,
            comment=comment_to_write,
            isrc=new_meta.isrc,
            track_number=new_meta.track_number,
            disc_number=new_meta.disc_number,
            raw=new_meta.raw,
        )

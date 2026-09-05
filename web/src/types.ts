export interface Library {
  folder: string;
  artists: Artist[];
  error?: string;
}

export interface Aggregate {
  album_count: number;
  track_count: number;
  pass_count: number;
  total_checks: number;
  grade_pct: number | null;
  audit_summary: "REAL" | "FAKE" | "Mix" | null;
}

export interface AlbumMeta {
  ALBUM?: string | null;
  ALBUMARTIST?: string | null;
  ARTIST?: string | null;
  DATE?: string | null;
  MUSICBRAINZ_ALBUMID?: string | null;
  MUSICBRAINZ_ALBUMARTISTID?: string | null;
  MUSICBRAINZ_RELEASEGROUPID?: string | null;
  RATEYOURMUSIC_ALBUM?: string | null;
}

export interface Tech {
  length?: number;
  bitrate?: number;
  sample_rate?: number;
  bits_per_sample?: number;
  channels?: number;
}

export interface TrackTags {
  TITLE?: string | null;
  ARTIST?: string | null;
  ALBUM?: string | null;
  DATE?: string | null;
  GENRE?: string | null;
  ITUNESADVISORY?: string | null;
  INSTRUMENTAL?: string | null;
  MEDIA?: string | null;
  SOURCE?: string | null;
  TRACKNUMBER?: string | null;
  DISCNUMBER?: string | null;
  MUSICBRAINZ_ALBUMID?: string | null;
  MUSICBRAINZ_ALBUMARTISTID?: string | null;
  MUSICBRAINZ_ARTISTID?: string | null;
  MUSICBRAINZ_TRACKID?: string | null;
  MUSICBRAINZ_RELEASEGROUPID?: string | null;
  RATEYOURMUSIC_ALBUM?: string | null;
  RATEYOURMUSIC_TRACK?: string | null;
  RATEYOURMUSIC_ARTIST?: string | null;
}

export interface Track {
  file: string;
  path: string;
  tracknumber?: number | null;
  discnumber?: number | null;
  issues: string[];
  values: Record<string, string | null>;
  audit: string | null;
  log_grade: string | null;
  accuraterip_status?: string;
  checksum_status?: string;
  lyrics_embedded: boolean;
  lyrics_lrc: boolean;
  unreadable: boolean;
  tech: Tech;
  tags: TrackTags;
  grade_pass: boolean;
  lyrics_present: boolean;
  cover_file?: string | null;
  sidecar_cover?: boolean;
  sidecar_cover_file?: string | null;
}

export interface Album {
  path: string;
  error?: string;
  meta?: AlbumMeta;
  album_artist?: string | null;
  album_values?: Record<string, string>;
  grade_pct: number | null;
  pass: boolean;
  pass_count: number;
  total_checks: number;
  track_count: number;
  audit_summary: "REAL" | "FAKE" | "Mix" | null;
  cover_file: string | null;
  has_log: boolean;
  has_cue: boolean;
  checksum_status: string;
  accuraterip_status: string;
  lyrics_present: number;
  lyrics_expected: number;
  instrumental_count: number;
  media: string;
  source_summary: string | null;
  tracks: Track[];
}

export interface Artist {
  path: string;
  name: string;
  display_name?: string | null;
  albums: Album[];
  aggregate: Aggregate;
}

export interface CoverResult {
  source: string;
  small: string | null;
  big: string | null;
  title: string | null;
  artist: string | null;
  tracks: number | null;
  url: string | null;
}

export interface Playlist {
  id: number;
  name: string;
  kind: "manual" | "smart";
  filter: { conditions: FilterCondition[]; match: "all" | "any" } | null;
  track_count: number;
  tracks?: string[];
  created?: number;
  updated?: number;
}

export interface FilterCondition {
  field: string;
  op: string;
  value?: string | number | boolean;
}

export interface Progress {
  done: number;
  total: number;
  desc: string;
}

export interface GradeResult {
  path: string;
  pass_count: number;
  total_checks: number;
  grade_pct: number | null;
  pass: boolean;
  audit_summary: string | null;
  tracks: Track[];
  issues?: Record<string, string[]>;
}

export interface MBPerson {
  name: string;
  mbid?: string;
}

export interface MBTrack {
  position: number;
  disc: number;
  title: string;
  length: number | null;
  recording_mbid: string | null;
  artist_mbids: string[];
  artist_credit: string;
  genres: string[];
}

export interface MBRelease {
  id: string;
  title: string;
  date: string;
  release_group_id: string | null;
  release_type?: string;
  barcode?: string;
  country?: string;
  catalog_number?: string;
  artists: MBPerson[];
  genres: string[];
  media: MBTrack[];
  medium_count: number;
  medium_formats?: string[];
}

export interface MatchSuggestion {
  local: string;
  file: string;
  matched: boolean;
  confidence: number;
  release_track: MBTrack | null;
}

export interface GenreCascade {
  per_track: { position: number; disc: number; title: string; genres: string[]; source: string | null }[];
  levels: { track: boolean; release: boolean; release_group: boolean; artist: boolean };
}
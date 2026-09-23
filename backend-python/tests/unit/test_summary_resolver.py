from __future__ import annotations

from reactor_backend.domain.summary_resolver import resolve


def test_summary_text_keeps_raw_including_delimiter() -> None:
    # "summary_text = raw" — must NOT strip the $$$ section
    raw = "answer text$$$key-a、key-b"
    resolved = resolve(raw)
    assert resolved.summary_text == raw


def test_artifact_keys_split_after_first_delimiter() -> None:
    resolved = resolve("text$$$a、b,c\nd\ne")
    assert resolved.artifact_keys == ["a", "b", "c", "d", "e"]


def test_artifact_keys_only_after_first_delimiter() -> None:
    resolved = resolve("text$$$a$$$b")
    # split(raw, "$$$", 1) → ["text", "a$$$b"]; the second $$$ is inside the section
    assert resolved.artifact_keys == ["a$$$b"]


def test_no_delimiter_means_no_keys() -> None:
    resolved = resolve("plain text")
    assert resolved.artifact_keys == []
    assert resolved.summary_text == "plain text"


def test_blank_section_means_no_keys() -> None:
    resolved = resolve("text")
    assert resolved.artifact_keys == []
    resolved = resolve("text   ")
    assert resolved.artifact_keys == []


def test_blank_items_are_trimmed_out() -> None:
    resolved = resolve("text$$$  a  、  、b  ")
    assert resolved.artifact_keys == ["a", "b"]


def test_file_list_and_artifact_refs_always_empty() -> None:
    resolved = resolve("anything")
    assert resolved.file_list == []
    assert resolved.artifact_refs == []


def test_none_raw_becomes_empty_string() -> None:
    resolved = resolve(None)
    assert resolved.summary_text == ""
    assert resolved.artifact_keys == []
